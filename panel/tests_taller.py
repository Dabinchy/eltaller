import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from clientes.models import Cliente
from core.models import Caja, SesionCaja, Sucursal, Usuario
from productos.models import Producto, StockSucursal, ajustar_stock
from taller.models import OrdenTrabajo, Tecnico, Turno, Vehiculo

PRIVADO = tempfile.mkdtemp(prefix="privado_panel_test_")
E = OrdenTrabajo.Estado


@override_settings(ALLOWED_HOSTS=["testserver"], PRIVATE_MEDIA_ROOT=PRIVADO)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVADO, ignore_errors=True)

    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.otra = Sucursal.objects.create(nombre="Norte")
        self.gerente = self.personal("gerente", "gerente")
        self.adm = self.personal("adm", "administracion", sucursal=self.suc)
        self.mec = self.personal("mec", "mecanico")
        self.tecnico = Tecnico.objects.create(nombre="Mecánico Uno", usuario=self.mec)
        self.cliente = Cliente.objects.create(nombre="Juan Pérez")
        self.auto = Vehiculo.objects.create(cliente=self.cliente, patente="AB123CD", marca="Ford", modelo="Falcon")
        self.filtro = Producto.objects.create(nombre="Filtro de aceite", precio_base=Decimal("1210"))
        ajustar_stock(sucursal=self.suc, producto=self.filtro, delta=5, tipo="COMPRA")
        StockSucursal.objects.filter(producto=self.filtro).update(costo_promedio=Decimal("500"))
        self.mano = Producto.objects.create(nombre="Mano de obra", tipo="SERVICIO", precio_base=Decimal("10000"))

    def personal(self, nombre, grupo, **kw):
        u = Usuario.objects.create_user(nombre, password="x", **kw)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def como(self, u):
        self.client.force_login(u)

    def crear_orden(self, **datos):
        self.como(self.adm)
        base = {"sucursal": self.suc.pk, "vehiculo": self.auto.pk, "tecnico": self.tecnico.pk,
                "km_ingreso": "15000", "motivo_cliente": "Service"}
        base.update(datos)
        self.client.post("/panel/taller/ordenes/nueva/", base)
        return OrdenTrabajo.objects.latest("numero")

    def item(self, orden, producto, cantidad="1", **extra):
        self.client.post(f"/panel/taller/ordenes/{orden.pk}/items/",
                         {"producto": producto.pk, "cantidad": cantidad, **extra})

    def estado(self, orden, nuevo):
        return self.client.post(f"/panel/taller/ordenes/{orden.pk}/estado/", {"estado": nuevo}, follow=True)


class FlujoOrdenTests(Base):
    def test_flujo_completo_hasta_la_entrega(self):
        o = self.crear_orden()
        self.assertEqual((o.cliente, o.estado), (self.cliente, E.PRESUPUESTO))
        self.item(o, self.filtro, "2")
        self.item(o, self.mano)
        r = self.estado(o, E.APROBADA)
        self.assertContains(r, "Aprobada")
        o.refresh_from_db()
        self.assertEqual(o.total, Decimal("12420.00"))

        self.como(self.mec)
        self.estado(o, E.EN_PROCESO)
        self.item(o, self.filtro, "1")  # repuesto extra: queda pendiente
        self.estado(o, E.TERMINADA)
        o.refresh_from_db()
        self.assertEqual((o.estado, o.total), (E.TERMINADA, Decimal("12420.00")))

        self.como(self.adm)
        r = self.client.get(f"/panel/taller/ordenes/{o.pk}/")
        self.assertContains(r, "No hay ninguna caja abierta")
        caja = Caja.objects.create(sucursal=self.suc, numero=1)
        sesion = SesionCaja.objects.create(caja=caja, abierta_el=timezone.now(), abierta_por=self.adm)
        r = self.client.post(f"/panel/taller/ordenes/{o.pk}/entregar/", {"sesion": sesion.pk}, follow=True)
        self.assertContains(r, "lista para cobrar")
        o.refresh_from_db()
        self.assertEqual(o.estado, E.ENTREGADA)
        self.assertEqual(o.venta.detalles.count(), 2)  # el extra pendiente no se cobra

    def test_aprobar_items_pendientes(self):
        o = self.crear_orden()
        self.item(o, self.mano)
        self.estado(o, E.APROBADA)
        self.item(o, self.filtro)
        self.client.post(f"/panel/taller/ordenes/{o.pk}/aprobar-items/")
        o.refresh_from_db()
        self.assertEqual(o.total, Decimal("11210.00"))

    def test_precio_cero_es_sin_cargo(self):
        o = self.crear_orden()
        self.item(o, self.filtro, precio_unitario="0")
        self.assertContains(self.client.get(f"/panel/taller/ordenes/{o.pk}/"), "Sin cargo")

    def test_aviso_de_falta_de_stock(self):
        o = self.crear_orden()
        self.client.post(f"/panel/taller/ordenes/{o.pk}/items/", {"producto": self.filtro.pk, "cantidad": "9"})
        r = self.client.get(f"/panel/taller/ordenes/{o.pk}/")
        self.assertContains(r, "sin stock suficiente")

    def test_comentarios_y_fotos(self):
        o = self.crear_orden()
        self.client.post(f"/panel/taller/ordenes/{o.pk}/comentar/", {"texto": "Pedir repuesto"})
        self.client.post(f"/panel/taller/ordenes/{o.pk}/comentar/", {"texto": "Listo el jueves", "visible_piloto": "on"})
        salida = BytesIO()
        Image.new("RGB", (200, 100), "red").save(salida, format="JPEG")
        self.client.post(f"/panel/taller/ordenes/{o.pk}/archivos/", {
            "archivo": SimpleUploadedFile("dano.jpg", salida.getvalue()), "titulo": "Daño",
            "tipo": "FOTO", "visibilidad": "INTERNO",
        })
        r = self.client.get(f"/panel/taller/ordenes/{o.pk}/")
        self.assertContains(r, "Pedir repuesto")
        self.assertContains(r, "visible para el cliente")
        self.assertContains(r, "Daño")
        self.assertEqual(o.comentarios.count(), 2)


class PermisosTests(Base):
    def test_mecanico_ve_solo_lo_suyo_y_sin_precios(self):
        mia = self.crear_orden()
        ajena = self.crear_orden(tecnico="")
        self.como(self.mec)
        r = self.client.get("/panel/taller/mis-ordenes/")
        self.assertContains(r, f"#{mia.numero}")
        self.assertNotContains(r, f"#{ajena.numero}<")
        self.assertEqual(self.client.get(f"/panel/taller/ordenes/{ajena.pk}/").status_code, 404)
        r = self.client.get(f"/panel/taller/ordenes/{mia.pk}/")
        self.assertNotContains(r, 'name="precio_unitario"')
        self.assertNotContains(r, "Aprobar presupuesto")
        self.assertContains(r, "Escribir diagnóstico")

    def test_mecanico_no_carga_precio_aunque_lo_mande(self):
        o = self.crear_orden()
        self.como(self.mec)
        self.item(o, self.filtro, precio_unitario="1")
        self.assertEqual(o.items.get().precio_unitario, Decimal("1210.00"))

    def test_administracion_no_ve_costos_ni_otra_sucursal(self):
        o = self.crear_orden()
        self.item(o, self.filtro)
        self.assertNotContains(self.client.get(f"/panel/taller/ordenes/{o.pk}/"), "Costo")
        self.como(self.gerente)
        otra = self.client.post("/panel/taller/ordenes/nueva/", {"sucursal": self.otra.pk, "vehiculo": self.auto.pk})
        o2 = OrdenTrabajo.objects.latest("numero")
        self.como(self.adm)
        self.assertEqual(self.client.get(f"/panel/taller/ordenes/{o2.pk}/").status_code, 404)

    def test_mecanico_no_crea_ordenes_ni_turnos(self):
        self.como(self.mec)
        self.assertEqual(self.client.get("/panel/taller/ordenes/nueva/").status_code, 403)
        self.assertEqual(self.client.get("/panel/taller/turnos/").status_code, 403)


class TurnosYVehiculosTests(Base):
    def test_turno_y_abrir_orden_desde_el_turno(self):
        self.como(self.adm)
        manana = timezone.localtime() + timedelta(days=1)
        self.client.post("/panel/taller/turnos/nuevo/", {
            "sucursal": self.suc.pk, "vehiculo": self.auto.pk, "inicio": manana.strftime("%Y-%m-%dT10:00"),
            "duracion_min": "60", "motivo": "Frenos",
        })
        t = Turno.objects.get()
        self.assertEqual(t.cliente, self.cliente)
        r = self.client.get(f"/panel/taller/turnos/?dia={manana.date().isoformat()}")
        self.assertContains(r, "Frenos")
        self.client.post(f"/panel/taller/turnos/{t.pk}/estado/", {"estado": "CONFIRMADO"})
        t.refresh_from_db()
        self.assertEqual(t.estado, Turno.Estado.CONFIRMADO)
        o = self.crear_orden(turno="")
        self.client.post(f"/panel/taller/ordenes/nueva/?turno={t.pk}", {
            "sucursal": self.suc.pk, "vehiculo": self.auto.pk, "motivo_cliente": "Frenos",
        })
        t.refresh_from_db()
        self.assertEqual(t.estado, Turno.Estado.EN_TALLER)

    def test_cupo_lleno_avisa_en_el_formulario(self):
        self.suc.cupo_turnos = 1
        self.suc.save()
        self.como(self.adm)
        manana = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT10:00")
        datos = {"sucursal": self.suc.pk, "vehiculo": self.auto.pk, "inicio": manana, "duracion_min": "60"}
        self.client.post("/panel/taller/turnos/nuevo/", datos)
        r = self.client.post("/panel/taller/turnos/nuevo/", datos)
        self.assertContains(r, "cupo 1")

    def test_vehiculo_alta_busqueda_y_detalle(self):
        self.como(self.adm)
        r = self.client.post("/panel/taller/vehiculos/nuevo/", {
            "cliente": self.cliente.pk, "vin": "ch-99", "marca": "Tango", "modelo": "TC",
            "combustible": "NAFTA", "km_actual": "0", "activo": "on",
        })
        v = Vehiculo.objects.get(vin="CH99")
        self.assertRedirects(r, f"/panel/taller/vehiculos/{v.pk}/")
        self.assertContains(self.client.get("/panel/taller/vehiculos/?q=tango"), "VIN CH99")
        self.assertContains(self.client.get("/panel/taller/vehiculos/?q=juan"), "AB123CD")


class MenuTests(Base):
    def test_menu_del_taller_por_rol(self):
        self.como(self.adm)
        r = self.client.get("/panel/")
        for texto in ("Órdenes de trabajo", "Turnos", "Vehículos"):
            self.assertContains(r, texto)
        self.assertNotContains(r, "Mis órdenes")
        self.como(self.mec)
        r = self.client.get("/panel/")
        self.assertContains(r, "Mis órdenes")
        self.assertNotContains(r, 'href="/panel/taller/turnos/"')
