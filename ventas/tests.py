from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from clientes.models import Cliente
from core.models import Caja, SesionCaja, Sucursal, Usuario
from productos.models import MovimientoStock, Producto, StockSucursal, ajustar_stock

from .models import Venta, VentaDetalle


class Base(TestCase):
    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.caja = Caja.objects.create(sucursal=self.suc, numero=1)
        self.gerente = self.usuario("gerente", "gerente")
        self.adm = self.usuario("adm", "administracion", sucursal=self.suc)
        self.sesion = SesionCaja.objects.create(
            caja=self.caja, abierta_el=timezone.now(), abierta_por=self.gerente,
            saldo_inicial=Decimal("0"), saldo_estimado=Decimal("0"),
        )
        self.repuesto = Producto.objects.create(nombre="Filtro", precio_base=Decimal("1210"))
        ajustar_stock(sucursal=self.suc, producto=self.repuesto, delta=5, tipo="COMPRA")
        StockSucursal.objects.filter(producto=self.repuesto).update(costo_promedio=Decimal("500"))
        self.mano_obra = Producto.objects.create(nombre="Mano de obra", tipo="SERVICIO", precio_base=Decimal("10000"))

    def usuario(self, nombre, grupo, **kw):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=True, **kw)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def venta(self, cliente=None):
        return Venta.objects.create(
            sucursal=self.suc, caja=self.caja, sesion=self.sesion, cliente=cliente, creada_por=self.adm
        )

    def item(self, venta, producto, cantidad=1):
        return VentaDetalle.objects.create(venta=venta, producto=producto, cantidad=Decimal(cantidad))

    def stock(self):
        return StockSucursal.disponible(self.suc, self.repuesto)

    def saldo_caja(self):
        self.sesion.refresh_from_db()
        return self.sesion.saldo_estimado


class DetalleTests(Base):
    def test_precio_iva_y_costo_automaticos(self):
        v = self.venta()
        d = self.item(v, self.repuesto, 2)
        self.assertEqual(d.precio_unitario, Decimal("1210.00"))
        self.assertEqual(d.importe, Decimal("2420.00"))
        self.assertEqual(d.importe_neto, Decimal("2000.00"))
        self.assertEqual(d.costo_total, Decimal("1000.00"))  # 2 x costo promedio 500
        v.refresh_from_db()
        self.assertEqual((v.total, v.utilidad_bruta), (Decimal("2420.00"), Decimal("1000.00")))

    def test_servicio_no_exige_stock(self):
        self.item(self.venta(), self.mano_obra, 3)  # no hay stock de un servicio: igual se vende

    def test_stock_insuficiente(self):
        with self.assertRaises(ValidationError):
            self.item(self.venta(), self.repuesto, 6)


class FinalizarTests(Base):
    def test_finaliza_descuenta_stock_y_suma_efectivo(self):
        v = self.venta()
        self.item(v, self.repuesto, 2)
        self.item(v, self.mano_obra)
        v.finalizar(user=self.adm)  # sin medios de pago: todo efectivo
        self.assertEqual(v.estado, Venta.Estado.FINALIZADA)
        self.assertEqual(v.monto_efectivo, Decimal("12420.00"))
        self.assertEqual(self.stock(), Decimal("3.000"))
        self.assertEqual(self.saldo_caja(), Decimal("12420.00"))
        self.assertFalse(MovimientoStock.objects.filter(producto=self.mano_obra).exists())

    def test_medios_de_pago_deben_sumar_el_total(self):
        v = self.venta()
        self.item(v, self.repuesto)
        with self.assertRaises(ValidationError):
            v.finalizar(user=self.adm, efectivo=1000, tarjeta=100)
        v.refresh_from_db()
        self.assertEqual(v.estado, Venta.Estado.ABIERTA)
        self.assertEqual(self.stock(), Decimal("5.000"))  # no quedó nada a medias

    def test_pago_mixto(self):
        v = self.venta()
        self.item(v, self.repuesto)
        v.finalizar(user=self.adm, efectivo=210, tarjeta=1000)
        self.assertEqual(self.saldo_caja(), Decimal("210.00"))

    def test_items_bloqueados_al_finalizar(self):
        v = self.venta()
        d = self.item(v, self.repuesto)
        v.finalizar(user=self.adm)
        with self.assertRaises(ValidationError):
            self.item(v, self.repuesto)
        with self.assertRaises(ValidationError):
            d.delete()

    def test_mecanico_no_finaliza(self):
        v = self.venta()
        self.item(v, self.repuesto)
        with self.assertRaises(PermissionDenied):
            v.finalizar(user=self.usuario("mec", "mecanico"))


class CuentaCorrienteTests(Base):
    def cliente(self, limite):
        with self.captureOnCommitCallbacks(execute=True):
            return Cliente.objects.create(nombre="Piloto", limite_credito=Decimal(limite))

    def test_ctacte_debita_al_cliente(self):
        c = self.cliente("5000")
        v = self.venta(cliente=c)
        self.item(v, self.repuesto)
        v.finalizar(user=self.adm, efectivo=210, ctacte=1000)
        c.cuenta_corriente.refresh_from_db()
        self.assertEqual(c.cuenta_corriente.saldo, Decimal("1000.00"))

    def test_ctacte_respeta_limite(self):
        c = self.cliente("500")
        v = self.venta(cliente=c)
        self.item(v, self.repuesto)
        with self.assertRaises(ValidationError):
            v.finalizar(user=self.adm, ctacte=1210)
        self.assertEqual(self.stock(), Decimal("5.000"))

    def test_ctacte_exige_cliente(self):
        v = self.venta()
        self.item(v, self.repuesto)
        with self.assertRaises(ValidationError):
            v.finalizar(user=self.adm, ctacte=1210)

    def test_anular_revierte_todo(self):
        c = self.cliente("5000")
        v = self.venta(cliente=c)
        self.item(v, self.repuesto)
        v.finalizar(user=self.adm, efectivo=210, ctacte=1000)
        v.anular(user=self.gerente)
        c.cuenta_corriente.refresh_from_db()
        self.assertEqual(v.estado, Venta.Estado.ANULADA)
        self.assertEqual(self.stock(), Decimal("5.000"))
        self.assertEqual(self.saldo_caja(), Decimal("0.00"))
        self.assertEqual(c.cuenta_corriente.saldo, Decimal("0.00"))

    def test_no_anula_si_el_cliente_ya_pago_parte(self):
        from clientes.models import MovimientoCuentaCorriente

        c = self.cliente("5000")
        v = self.venta(cliente=c)
        self.item(v, self.repuesto)
        v.finalizar(user=self.adm, efectivo=210, ctacte=1000)
        MovimientoCuentaCorriente.objects.create(
            cuenta=c.cuenta_corriente, tipo="CREDITO", monto=Decimal("600"), creado_por=self.adm
        )
        with self.assertRaises(ValidationError):
            v.anular(user=self.gerente)
        v.refresh_from_db()
        self.assertEqual(v.estado, Venta.Estado.FINALIZADA)
        self.assertEqual(self.stock(), Decimal("4.000"))

    def test_solo_gerente_anula(self):
        v = self.venta()
        self.item(v, self.repuesto)
        v.finalizar(user=self.adm)
        with self.assertRaises(PermissionDenied):
            v.anular(user=self.adm)


@override_settings(ALLOWED_HOSTS=["testserver"])
class AdminTests(Base):
    def test_admin_por_rol(self):
        v = self.venta()
        self.item(v, self.repuesto)
        v.finalizar(user=self.adm)
        url = f"/admin/ventas/venta/{v.pk}/change/"

        self.client.force_login(self.adm)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Utilidad bruta")  # administración no ve costos
        self.assertNotContains(self.client.get("/admin/ventas/venta/"), "anular_ventas")

        self.client.force_login(self.gerente)
        self.assertContains(self.client.get(url), "Utilidad bruta")
        self.assertContains(self.client.get("/admin/ventas/venta/"), "anular_ventas")

        otra = Sucursal.objects.create(nombre="Otra")
        self.client.force_login(self.usuario("adm2", "administracion", sucursal=otra))
        self.assertEqual(self.client.get(url).status_code, 302)  # otra sucursal: no la encuentra

        self.client.force_login(self.usuario("mec", "mecanico"))
        self.assertEqual(self.client.get("/admin/ventas/venta/").status_code, 403)

    def test_anular_desde_admin(self):
        v = self.venta()
        self.item(v, self.repuesto)
        v.finalizar(user=self.adm)
        self.client.force_login(self.gerente)
        self.client.post("/admin/ventas/venta/", {"action": "anular_ventas", "_selected_action": [v.pk]})
        v.refresh_from_db()
        self.assertEqual(v.estado, Venta.Estado.ANULADA)
