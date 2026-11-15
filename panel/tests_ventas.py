from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone

from clientes.models import Cliente
from core.models import Caja, SesionCaja, Sucursal, Usuario
from productos.models import Producto, StockSucursal, ajustar_stock
from taller.models import OrdenItem, OrdenTrabajo, Vehiculo
from ventas.models import Venta

EV = Venta.Estado


@override_settings(ALLOWED_HOSTS=["testserver"])
class Base(TestCase):
    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.otra = Sucursal.objects.create(nombre="Norte")
        self.gerente = self.personal("gerente", "gerente", pin="1111")
        self.adm = self.personal("adm", "administracion", sucursal=self.suc)
        self.mec = self.personal("mec", "mecanico")
        self.caja = Caja.objects.create(sucursal=self.suc, numero=1)
        self.sesion = SesionCaja.objects.create(caja=self.caja, abierta_el=timezone.now(), abierta_por=self.adm)
        self.filtro = Producto.objects.create(nombre="Filtro", precio_base=Decimal("1000"))
        ajustar_stock(sucursal=self.suc, producto=self.filtro, delta=10, tipo="COMPRA")
        self.mano = Producto.objects.create(nombre="Mano de obra", tipo="SERVICIO", precio_base=Decimal("5000"))
        self.cliente = Cliente.objects.create(nombre="Juan", limite_credito=Decimal("10000"))
        from clientes.models import CuentaCorriente
        CuentaCorriente.objects.get_or_create(cliente=self.cliente)

    def personal(self, nombre, grupo, pin=None, **kw):
        u = Usuario.objects.create_user(nombre, password="x", **kw)
        u.groups.add(Group.objects.get(name=grupo))
        if pin:
            u.set_action_pin(pin)
            u.save()
        return u

    def venta_de_orden(self):
        """Orden entregada: genera una venta abierta (como desde el taller)."""
        auto = Vehiculo.objects.create(cliente=self.cliente, patente="AA111AA", marca="Ford", modelo="Fiesta")
        o = OrdenTrabajo.objects.create(sucursal=self.suc, vehiculo=auto, creada_por=self.adm)
        OrdenItem.objects.create(orden=o, producto=self.filtro, cantidad=2)
        OrdenItem.objects.create(orden=o, producto=self.mano)
        for e in (OrdenTrabajo.Estado.APROBADA, OrdenTrabajo.Estado.EN_PROCESO, OrdenTrabajo.Estado.TERMINADA):
            o.cambiar_estado(e, user=self.gerente)
        return o.entregar(user=self.adm, sesion=self.sesion)

    def stock(self):
        return StockSucursal.disponible(self.suc, self.filtro)


class CobroTests(Base):
    def test_cobrar_venta_de_orden_con_pago_mixto_y_ctacte(self):
        v = self.venta_de_orden()
        self.client.force_login(self.adm)
        self.assertContains(self.client.get("/panel/ventas/por-cobrar/"), f"#{v.pk}")
        r = self.client.get(f"/panel/ventas/{v.pk}/")
        self.assertContains(r, "disponible")
        self.assertNotContains(r, "Descartar")  # una venta de orden no se descarta
        r = self.client.post(f"/panel/ventas/{v.pk}/cobrar/", {
            "monto_efectivo": "2.000", "monto_tarjeta": "3.000,00", "monto_ctacte": "2000",
        })
        self.assertRedirects(r, f"/panel/ventas/{v.pk}/comprobante/")
        v.refresh_from_db()
        self.assertEqual(v.estado, EV.FINALIZADA)
        self.assertEqual(self.stock(), Decimal("8.000"))
        self.cliente.cuenta_corriente.refresh_from_db()
        self.assertEqual(self.cliente.cuenta_corriente.saldo, Decimal("2000.00"))
        self.sesion.refresh_from_db()
        self.assertEqual(self.sesion.saldo_estimado, Decimal("2000.00"))
        self.assertContains(self.client.get(f"/panel/ventas/{v.pk}/comprobante/"), "Documento no válido como factura")

    def test_medios_que_no_suman_el_total(self):
        v = self.venta_de_orden()
        self.client.force_login(self.adm)
        r = self.client.post(f"/panel/ventas/{v.pk}/cobrar/", {"monto_tarjeta": "100"}, follow=True)
        self.assertContains(r, "no coinciden con el total")
        v.refresh_from_db()
        self.assertEqual(v.estado, EV.ABIERTA)

    def test_sin_medios_es_todo_efectivo(self):
        v = self.venta_de_orden()
        self.client.force_login(self.adm)
        self.client.post(f"/panel/ventas/{v.pk}/cobrar/", {})
        v.refresh_from_db()
        self.assertEqual((v.estado, v.monto_efectivo), (EV.FINALIZADA, Decimal("7000.00")))


class MostradorTests(Base):
    def test_venta_de_mostrador(self):
        self.client.force_login(self.adm)
        r = self.client.get("/panel/ventas/mostrador/")  # una sola caja abierta: crea la venta directo
        v = Venta.objects.get()
        self.assertRedirects(r, f"/panel/ventas/{v.pk}/")
        self.client.post(f"/panel/ventas/{v.pk}/items/", {"producto": self.filtro.pk, "cantidad": "3",
                                                          "precio_unitario": "1"})  # sin permiso de precios: se ignora
        self.client.post(f"/panel/ventas/{v.pk}/cliente/", {"cliente": self.cliente.pk})
        v.refresh_from_db()
        self.assertEqual((v.total, v.cliente), (Decimal("3000.00"), self.cliente))
        self.client.post(f"/panel/ventas/{v.pk}/cobrar/", {})
        self.assertEqual(self.stock(), Decimal("7.000"))

    def test_stock_insuficiente(self):
        self.client.force_login(self.adm)
        self.client.get("/panel/ventas/mostrador/")
        v = Venta.objects.get()
        r = self.client.post(f"/panel/ventas/{v.pk}/items/", {"producto": self.filtro.pk, "cantidad": "50"}, follow=True)
        self.assertContains(r, "Stock insuficiente")

    def test_descartar(self):
        self.client.force_login(self.adm)
        self.client.get("/panel/ventas/mostrador/")
        v = Venta.objects.get()
        self.client.post(f"/panel/ventas/{v.pk}/items/", {"producto": self.mano.pk, "cantidad": "1"})
        self.client.post(f"/panel/ventas/{v.pk}/descartar/")
        self.assertFalse(Venta.objects.exists())

    def test_sin_caja_abierta(self):
        self.client.force_login(self.personal("adm2", "administracion", sucursal=self.otra))  # Norte: sin caja
        self.assertContains(self.client.get("/panel/ventas/mostrador/"), "No hay ninguna caja abierta")


class AnulacionYPermisosTests(Base):
    def test_gerente_anula_con_pin(self):
        v = self.venta_de_orden()
        v.finalizar(user=self.adm)
        self.client.force_login(self.gerente)
        r = self.client.post(f"/panel/ventas/{v.pk}/anular/", {"pin": "9999"}, follow=True)
        self.assertContains(r, "PIN inválido")
        self.client.post(f"/panel/ventas/{v.pk}/anular/", {"pin": "1111"})
        v.refresh_from_db()
        self.assertEqual(v.estado, EV.ANULADA)
        self.assertEqual(self.stock(), Decimal("10.000"))

    def test_administracion_no_anula(self):
        v = self.venta_de_orden()
        v.finalizar(user=self.adm)
        self.client.force_login(self.adm)
        self.assertNotContains(self.client.get(f"/panel/ventas/{v.pk}/"), "Anular venta")
        self.assertEqual(self.client.post(f"/panel/ventas/{v.pk}/anular/", {"pin": "1111"}).status_code, 403)

    def test_alcance_y_mecanico(self):
        v = self.venta_de_orden()
        otra_adm = self.personal("adm2", "administracion", sucursal=self.otra)
        self.client.force_login(otra_adm)
        self.assertEqual(self.client.get(f"/panel/ventas/{v.pk}/").status_code, 404)
        self.client.force_login(self.mec)
        self.assertEqual(self.client.get("/panel/ventas/por-cobrar/").status_code, 403)

    def test_listado_y_costos(self):
        v = self.venta_de_orden()
        v.finalizar(user=self.adm)
        self.client.force_login(self.adm)
        r = self.client.get("/panel/ventas/")
        self.assertContains(r, f"#{v.pk}")
        self.assertNotContains(self.client.get(f"/panel/ventas/{v.pk}/"), "Costo")
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(f"/panel/ventas/{v.pk}/"), "Costo")
