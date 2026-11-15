from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from clientes.models import Cliente
from core.models import Caja, SesionCaja, Sucursal, Usuario
from productos.models import Producto, StockSucursal, ajustar_stock
from ventas.models import Venta

from .models import OrdenItem, OrdenTrabajo, Tecnico, Turno, Vehiculo

E = OrdenTrabajo.Estado


class Base(TestCase):
    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.otra = Sucursal.objects.create(nombre="Norte")
        self.gerente = self.usuario("gerente", "gerente")
        self.adm = self.usuario("adm", "administracion", sucursal=self.suc)
        self.mec_user = self.usuario("mec", "mecanico")
        self.tecnico = Tecnico.objects.create(nombre="Mecánico Uno", usuario=self.mec_user)

        self.cliente = Cliente.objects.create(nombre="Piloto Uno")
        self.auto = Vehiculo.objects.create(cliente=self.cliente, patente="AB123CD", marca="Ford", modelo="Fiesta")

        self.filtro = Producto.objects.create(nombre="Filtro", precio_base=Decimal("1210"))
        ajustar_stock(sucursal=self.suc, producto=self.filtro, delta=5, tipo="COMPRA")
        StockSucursal.objects.filter(producto=self.filtro).update(costo_promedio=Decimal("500"))
        self.mano_obra = Producto.objects.create(nombre="Mano de obra", tipo="SERVICIO", precio_base=Decimal("10000"))

        caja = Caja.objects.create(sucursal=self.suc, numero=1)
        self.sesion = SesionCaja.objects.create(caja=caja, abierta_el=timezone.now(), abierta_por=self.gerente)

    def usuario(self, nombre, grupo, **kw):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=True, **kw)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def orden(self, **kw):
        datos = dict(sucursal=self.suc, vehiculo=self.auto, tecnico=self.tecnico, creada_por=self.adm)
        datos.update(kw)
        return OrdenTrabajo.objects.create(**datos)

    def item(self, orden, producto, cantidad=1, **kw):
        return OrdenItem.objects.create(orden=orden, producto=producto, cantidad=Decimal(cantidad), **kw)

    def orden_terminada(self):
        o = self.orden()
        self.item(o, self.filtro, 2)
        self.item(o, self.mano_obra)
        o.cambiar_estado(E.APROBADA, user=self.adm)
        o.cambiar_estado(E.EN_PROCESO, user=self.mec_user)
        o.cambiar_estado(E.TERMINADA, user=self.mec_user)
        return o


class OrdenTests(Base):
    def test_numero_correlativo_y_cliente_del_vehiculo(self):
        o1, o2 = self.orden(), self.orden()
        self.assertEqual((o1.numero, o2.numero), (1, 2))
        self.assertEqual(o1.cliente, self.cliente)
        self.assertEqual(o1.historial.get().estado_nuevo, E.PRESUPUESTO)

    def test_km_ingreso_actualiza_vehiculo(self):
        self.orden(km_ingreso=42000)
        self.auto.refresh_from_db()
        self.assertEqual(self.auto.km_actual, 42000)

    def test_desde_turno(self):
        turno = Turno.objects.create(sucursal=self.suc, cliente=self.cliente, vehiculo=self.auto, inicio=timezone.now())
        self.orden(turno=turno)
        turno.refresh_from_db()
        self.assertEqual(turno.estado, Turno.Estado.EN_TALLER)

    def test_turno_de_otro_vehiculo_rechazado(self):
        otro = Vehiculo.objects.create(cliente=self.cliente, patente="ZZ999ZZ", marca="X", modelo="Y")
        turno = Turno.objects.create(sucursal=self.suc, cliente=self.cliente, vehiculo=otro, inicio=timezone.now())
        with self.assertRaises(ValidationError):
            self.orden(turno=turno)

    def test_item_toma_precio_y_costo(self):
        o = self.orden()
        it = self.item(o, self.filtro, 2)
        self.assertEqual((it.precio_unitario, it.costo_unitario, it.importe), (Decimal("1210.00"), Decimal("500"), Decimal("2420.00")))
        mo = self.item(o, self.mano_obra)
        self.assertEqual(mo.costo_unitario, 0)
        self.assertEqual(o.total_presupuestado, Decimal("12420.00"))

    def test_aprobar_presupuesto_aprueba_items_y_calcula_totales(self):
        o = self.orden()
        self.item(o, self.filtro, 2)
        self.item(o, self.mano_obra)
        o.cambiar_estado(E.APROBADA, user=self.adm)
        self.assertEqual((o.total_repuestos, o.total_mano_obra, o.total),
                         (Decimal("2420.00"), Decimal("10000.00"), Decimal("12420.00")))
        self.assertFalse(o.items.filter(aprobado=False).exists())

    def test_items_nuevos_quedan_pendientes(self):
        o = self.orden()
        self.item(o, self.filtro)
        o.cambiar_estado(E.APROBADA, user=self.adm)
        extra = self.item(o, self.filtro, 1)
        o.refresh_from_db()
        self.assertFalse(extra.aprobado)
        self.assertEqual(o.total, Decimal("1210.00"))  # el extra no suma hasta aprobarlo
        o.aprobar_items(user=self.adm)
        o.refresh_from_db()
        self.assertEqual(o.total, Decimal("2420.00"))

    def test_cambiar_item_aprobado_lo_vuelve_pendiente(self):
        o = self.orden()
        it = self.item(o, self.filtro)
        o.cambiar_estado(E.APROBADA, user=self.adm)
        it.refresh_from_db()
        it.cantidad = Decimal("3")
        it.save()
        self.assertFalse(it.aprobado)

    def test_no_aprueba_presupuesto_vacio(self):
        with self.assertRaises(ValidationError):
            self.orden().cambiar_estado(E.APROBADA, user=self.adm)

    def test_transicion_invalida(self):
        o = self.orden()
        self.item(o, self.filtro)
        with self.assertRaises(ValidationError):
            o.cambiar_estado(E.TERMINADA, user=self.adm)
        with self.assertRaises(ValidationError):
            o.cambiar_estado(E.ENTREGADA, user=self.adm)

    def test_terminada_puede_reabrirse(self):
        o = self.orden_terminada()
        o.cambiar_estado(E.EN_PROCESO, user=self.adm)
        self.assertEqual(o.estado, E.EN_PROCESO)

    def test_items_bloqueados_desde_terminada(self):
        o = self.orden_terminada()
        with self.assertRaises(ValidationError):
            self.item(o, self.filtro)

    def test_historial_registra_cada_paso(self):
        o = self.orden_terminada()
        pasos = list(o.historial.values_list("estado_nuevo", "usuario__username"))
        self.assertEqual(pasos, [
            (E.PRESUPUESTO, "adm"), (E.APROBADA, "adm"), (E.EN_PROCESO, "mec"), (E.TERMINADA, "mec"),
        ])


class PermisosTests(Base):
    def test_mecanico_solo_empieza_y_termina(self):
        o = self.orden()
        self.item(o, self.filtro)
        with self.assertRaises(PermissionDenied):
            o.cambiar_estado(E.APROBADA, user=self.mec_user)
        o.cambiar_estado(E.APROBADA, user=self.adm)
        o.cambiar_estado(E.EN_PROCESO, user=self.mec_user)
        with self.assertRaises(PermissionDenied):
            o.cambiar_estado(E.CANCELADA, user=self.mec_user)
        with self.assertRaises(PermissionDenied):
            o.aprobar_items(user=self.mec_user)

    def test_mecanico_no_toca_ordenes_ajenas(self):
        otro = Tecnico.objects.create(nombre="Otro")
        o = self.orden(tecnico=otro)
        self.item(o, self.filtro)
        o.cambiar_estado(E.APROBADA, user=self.adm)
        with self.assertRaises(PermissionDenied):
            o.cambiar_estado(E.EN_PROCESO, user=self.mec_user)

    def test_administracion_solo_su_sucursal(self):
        o = self.orden(sucursal=self.otra)
        self.item(o, self.filtro)
        with self.assertRaises(PermissionDenied):
            o.cambiar_estado(E.APROBADA, user=self.adm)
        o.cambiar_estado(E.APROBADA, user=self.gerente)  # el gerente opera todas


class EntregaTests(Base):
    def test_entregar_genera_venta_abierta(self):
        o = self.orden_terminada()
        venta = o.entregar(user=self.adm, sesion=self.sesion)

        self.assertEqual(o.estado, E.ENTREGADA)
        self.assertEqual(o.venta, venta)
        self.assertIsNotNone(o.fecha_egreso)
        self.assertEqual(venta.estado, Venta.Estado.ABIERTA)
        self.assertEqual(venta.cliente, self.cliente)
        self.assertEqual(venta.total, Decimal("12420.00"))
        self.assertEqual(venta.costo_total, Decimal("1000.00"))
        # El stock se descuenta recién al cobrar
        self.assertEqual(StockSucursal.disponible(self.suc, self.filtro), Decimal("5.000"))
        venta.finalizar(user=self.adm)
        self.assertEqual(StockSucursal.disponible(self.suc, self.filtro), Decimal("3.000"))

    def test_solo_items_aprobados_van_a_la_venta(self):
        o = self.orden()
        self.item(o, self.filtro)
        o.cambiar_estado(E.APROBADA, user=self.adm)
        self.item(o, self.mano_obra)  # pendiente, nunca aprobado
        o.cambiar_estado(E.EN_PROCESO, user=self.mec_user)
        o.cambiar_estado(E.TERMINADA, user=self.mec_user)
        venta = o.entregar(user=self.adm, sesion=self.sesion)
        self.assertEqual(list(venta.detalles.values_list("producto__nombre", flat=True)), ["Filtro"])

    def test_item_sin_cargo_se_respeta(self):
        o = self.orden()
        self.item(o, self.filtro, precio_unitario=Decimal("0"))  # garantía
        o.cambiar_estado(E.APROBADA, user=self.adm)
        o.cambiar_estado(E.EN_PROCESO, user=self.mec_user)
        o.cambiar_estado(E.TERMINADA, user=self.mec_user)
        venta = o.entregar(user=self.adm, sesion=self.sesion)
        self.assertEqual(venta.detalles.get().precio_unitario, Decimal("0.00"))

    def test_entregar_requisitos(self):
        o = self.orden()
        self.item(o, self.filtro)
        with self.assertRaises(ValidationError):
            o.entregar(user=self.adm, sesion=self.sesion)  # no está terminada
        o = self.orden_terminada()
        with self.assertRaises(PermissionDenied):
            o.entregar(user=self.mec_user, sesion=self.sesion)
        caja_norte = Caja.objects.create(sucursal=self.otra, numero=1)
        sesion_norte = SesionCaja.objects.create(caja=caja_norte, abierta_el=timezone.now(), abierta_por=self.gerente)
        with self.assertRaises(ValidationError):
            o.entregar(user=self.gerente, sesion=sesion_norte)  # caja de otra sucursal

    def test_stock_insuficiente_no_entrega(self):
        o = self.orden_terminada()
        ajustar_stock(sucursal=self.suc, producto=self.filtro, delta=-4, tipo="AJUSTE_NEG")
        with self.assertRaises(ValidationError):
            o.entregar(user=self.adm, sesion=self.sesion)
        o.refresh_from_db()
        self.assertEqual(o.estado, E.TERMINADA)
        self.assertFalse(Venta.objects.exists())

    def test_entregada_no_se_modifica(self):
        o = self.orden_terminada()
        o.entregar(user=self.adm, sesion=self.sesion)
        o.diagnostico = "cambio"
        with self.assertRaises(ValidationError):
            o.save()


@override_settings(ALLOWED_HOSTS=["testserver"])
class AdminTests(Base):
    def test_mecanico_ve_solo_sus_ordenes_sin_costos(self):
        mia = self.orden()
        self.item(mia, self.filtro)
        ajena = self.orden(tecnico=Tecnico.objects.create(nombre="Otro"))
        self.client.force_login(self.mec_user)

        r = self.client.get(f"/admin/taller/ordentrabajo/{mia.pk}/change/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "costo_unitario")
        self.assertContains(r, 'name="diagnostico"')
        self.assertNotContains(r, 'name="km_ingreso"')
        self.assertEqual(self.client.get(f"/admin/taller/ordentrabajo/{ajena.pk}/change/").status_code, 302)
        lista = self.client.get("/admin/taller/ordentrabajo/")
        self.assertContains(lista, "pasar_a_terminada")
        self.assertNotContains(lista, "entregar_ordenes")

    def test_flujo_por_acciones_y_entrega(self):
        o = self.orden()
        self.item(o, self.filtro)
        self.client.force_login(self.adm)
        url = "/admin/taller/ordentrabajo/"
        self.client.post(url, {"action": "pasar_a_aprobada", "_selected_action": [o.pk]})
        self.client.force_login(self.mec_user)
        self.client.post(url, {"action": "pasar_a_en_proceso", "_selected_action": [o.pk]})
        self.client.post(url, {"action": "pasar_a_terminada", "_selected_action": [o.pk]})
        self.client.force_login(self.adm)
        self.client.post(url, {"action": "entregar_ordenes", "_selected_action": [o.pk]})
        o.refresh_from_db()
        self.assertEqual(o.estado, E.ENTREGADA)
        self.assertIsNotNone(o.venta)
        self.assertEqual(self.client.get(f"{url}{o.pk}/change/").status_code, 200)  # sólo lectura
