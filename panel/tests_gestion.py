import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from clientes.models import Cliente, CuentaCorriente, MovimientoCuentaCorriente
from compras.models import Compra, Proveedor
from core.models import Caja, CajaMovimiento, SesionCaja, Sucursal, Usuario
from productos.models import ListaPrecio, Producto, StockSucursal, ajustar_stock

PRIVADO = tempfile.mkdtemp(prefix="privado_gestion_test_")


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
        self.jefe = self.personal("jefe", "jefe", sucursal=self.suc)
        self.adm = self.personal("adm", "administracion", sucursal=self.suc)
        self.mec = self.personal("mec", "mecanico")
        self.filtro = Producto.objects.create(nombre="Filtro", precio_base=Decimal("1000"))

    def personal(self, nombre, grupo, **kw):
        u = Usuario.objects.create_user(nombre, password="x", **kw)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def stock(self, sucursal=None):
        return StockSucursal.disponible(sucursal or self.suc, self.filtro)


class ProductosTests(Base):
    def test_jefe_crea_producto_sin_tocar_precio(self):
        self.client.force_login(self.jefe)
        r = self.client.get("/panel/productos/nuevo/")
        self.assertNotContains(r, 'name="precio_base"')
        self.client.post("/panel/productos/nuevo/", {
            "tipo": "PRODUCTO", "nombre": "Pastillas de freno", "controla_stock": "on", "unidad_medida": "UN",
            "cantidad_unidad": "1", "iva_tasa": "21", "precio_base": "99999", "vendible": "on", "activo": "on",
        })
        p = Producto.objects.get(nombre="Pastillas de freno")
        self.assertEqual(p.precio_base, Decimal("0.00"))  # el jefe no fija precios

    def test_administracion_solo_ve(self):
        self.client.force_login(self.adm)
        self.assertContains(self.client.get("/panel/productos/"), "Filtro")
        self.assertEqual(self.client.get("/panel/productos/nuevo/").status_code, 403)
        self.assertNotContains(self.client.get("/panel/productos/"), "Costo prom.")

    def test_ajuste_de_stock_y_minimo(self):
        self.client.force_login(self.jefe)
        self.client.post(f"/panel/productos/{self.filtro.pk}/stock/", {"operacion": "SUMAR", "cantidad": "10", "motivo": "Inventario"})
        self.client.post(f"/panel/productos/{self.filtro.pk}/stock/", {"operacion": "RESTAR", "cantidad": "2", "motivo": "Rotura"})
        self.assertEqual(self.stock(), Decimal("8.000"))
        r = self.client.post(f"/panel/productos/{self.filtro.pk}/stock/", {"operacion": "RESTAR", "cantidad": "50", "motivo": "x"})
        self.assertContains(r, "quedaría negativo")
        self.client.post(f"/panel/productos/{self.filtro.pk}/stock/", {"min-stock_minimo": "10"})
        self.assertContains(self.client.get("/panel/productos/stock/?bajo=1"), "Filtro")

    def test_precios_solo_gerente(self):
        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get("/panel/productos/precios/").status_code, 403)
        self.client.force_login(self.gerente)
        lista = ListaPrecio.objects.create(nombre="General", es_default=True)
        self.client.post("/panel/productos/precios/nuevo/", {
            "lista": lista.pk, "producto": self.filtro.pk, "tipo": "NORMAL", "precio": "1500",
            "desde": timezone.localtime().strftime("%Y-%m-%dT00:00"),
        })
        self.filtro.refresh_from_db()
        self.assertEqual(self.filtro.precio_vigente, Decimal("1500.00"))

    def test_mecanico_ve_productos_sin_costos(self):
        self.client.force_login(self.mec)
        self.assertEqual(self.client.get("/panel/productos/").status_code, 200)
        self.assertEqual(self.client.get("/panel/productos/stock/").status_code, 200)


class ClientesTests(Base):
    def setUp(self):
        super().setUp()
        self.cliente = Cliente.objects.create(nombre="Juan Pérez", limite_credito=Decimal("5000"))
        cuenta, _ = CuentaCorriente.objects.get_or_create(cliente=self.cliente)
        MovimientoCuentaCorriente.objects.create(cuenta=cuenta, tipo="DEBITO", monto=Decimal("3000"), creado_por=self.adm)
        self.caja = Caja.objects.create(sucursal=self.suc, numero=1)
        self.sesion = SesionCaja.objects.create(caja=self.caja, abierta_el=timezone.now(), abierta_por=self.adm)

    def test_alta_y_busqueda(self):
        self.client.force_login(self.adm)
        self.client.post("/panel/clientes/nuevo/", {"nombre": "Ana Gómez", "doc_tipo": "DNI", "doc_numero": "30.111.222",
                                                    "limite_credito": "0", "activo": "on"})
        self.assertEqual(Cliente.objects.get(nombre="Ana Gómez").doc_numero, "30111222")
        self.assertContains(self.client.get("/panel/clientes/?deudores=1"), "Juan Pérez")
        self.assertNotContains(self.client.get("/panel/clientes/?deudores=1"), "Ana Gómez")

    def test_pago_en_efectivo_entra_a_la_caja(self):
        self.client.force_login(self.adm)
        self.client.post(f"/panel/clientes/{self.cliente.pk}/pago/",
                         {"monto": "1.000", "medio": "EFECTIVO", "sesion": self.sesion.pk})
        self.cliente.cuenta_corriente.refresh_from_db()
        self.sesion.refresh_from_db()
        self.assertEqual(self.cliente.cuenta_corriente.saldo, Decimal("2000.00"))
        self.assertEqual(self.sesion.saldo_estimado, Decimal("1000.00"))
        self.assertTrue(CajaMovimiento.objects.filter(sesion=self.sesion, tipo="ingreso").exists())

    def test_pago_con_tarjeta_no_toca_la_caja(self):
        self.client.force_login(self.adm)
        self.client.post(f"/panel/clientes/{self.cliente.pk}/pago/", {"monto": "500", "medio": "TARJETA"})
        self.sesion.refresh_from_db()
        self.assertEqual(self.sesion.saldo_estimado, Decimal("0.00"))
        self.cliente.cuenta_corriente.refresh_from_db()
        self.assertEqual(self.cliente.cuenta_corriente.saldo, Decimal("2500.00"))

    def test_pago_mayor_que_la_deuda(self):
        self.client.force_login(self.adm)
        r = self.client.post(f"/panel/clientes/{self.cliente.pk}/pago/",
                             {"monto": "9000", "medio": "EFECTIVO", "sesion": self.sesion.pk}, follow=True)
        self.assertContains(r, "supera la deuda")
        self.sesion.refresh_from_db()
        self.assertEqual(self.sesion.saldo_estimado, Decimal("0.00"))  # no quedó nada a medias

    def test_mecanico_sin_acceso(self):
        self.client.force_login(self.mec)
        self.assertEqual(self.client.get("/panel/clientes/").status_code, 403)


class ComprasTests(Base):
    def setUp(self):
        super().setUp()
        self.prov = Proveedor.objects.create(nombre="Repuestos SA")

    def test_cargar_confirmar_y_factura_privada(self):
        self.client.force_login(self.jefe)
        self.client.post("/panel/compras/nueva/", {
            "proveedor": self.prov.pk, "sucursal": self.suc.pk, "fecha": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
            "documento_adjunto": SimpleUploadedFile("factura.pdf", b"%PDF-1.4"),
        })
        c = Compra.objects.get()
        self.client.post(f"/panel/compras/{c.pk}/items/", {"producto": self.filtro.pk, "cantidad": "4",
                                                           "costo_unitario": "500", "iva_tasa": "21"})
        c.refresh_from_db()
        self.assertEqual(c.total, Decimal("2420.00"))
        self.client.post(f"/panel/compras/{c.pk}/confirmar/")
        c.refresh_from_db()
        self.assertEqual(c.estado, Compra.Estado.CONFIRMADA)
        self.assertEqual(self.stock(), Decimal("4.000"))
        r = self.client.get(f"/panel/compras/{c.pk}/factura/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))
        self.assertNotContains(self.client.get(f"/panel/compras/{c.pk}/"), 'name="producto"')  # ya no se edita

    def test_solo_gerente_anula(self):
        c = Compra.objects.create(proveedor=self.prov, sucursal=self.suc, creada_por=self.jefe)
        self.client.force_login(self.jefe)
        self.assertNotContains(self.client.get(f"/panel/compras/{c.pk}/"), "Anular")
        self.client.force_login(self.gerente)
        self.client.post(f"/panel/compras/{c.pk}/anular/")
        c.refresh_from_db()
        self.assertEqual(c.estado, Compra.Estado.ANULADA)

    def test_alcance_y_roles(self):
        c = Compra.objects.create(proveedor=self.prov, sucursal=self.otra, creada_por=self.gerente)
        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get(f"/panel/compras/{c.pk}/").status_code, 404)
        self.client.force_login(self.adm)
        self.assertEqual(self.client.get("/panel/compras/").status_code, 403)  # las compras muestran costos

    def test_proveedores(self):
        self.client.force_login(self.jefe)
        self.client.post("/panel/compras/proveedores/nuevo/", {"nombre": "Lubricantes SRL", "documento": "30-11111111-1",
                                                               "activo": "on"})
        self.assertEqual(Proveedor.objects.get(nombre="Lubricantes SRL").documento, "30111111111")


class MenuTests(Base):
    def test_menu_por_rol(self):
        self.client.force_login(self.jefe)
        r = self.client.get("/panel/")
        for texto in ("Productos y servicios", "Stock", "Compras", "Clientes"):
            self.assertContains(r, texto)
        self.assertNotContains(r, 'href="/panel/productos/precios/"')
        self.client.force_login(self.gerente)
        self.assertContains(self.client.get("/panel/"), 'href="/panel/productos/precios/"')
