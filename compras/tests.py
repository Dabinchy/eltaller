import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import Sucursal, Usuario
from productos.models import MovimientoStock, Producto, StockSucursal, ajustar_stock

from .models import Compra, CompraDetalle, Proveedor

PRIVADO = tempfile.mkdtemp(prefix="privado_test_")


@override_settings(PRIVATE_MEDIA_ROOT=PRIVADO, ALLOWED_HOSTS=["testserver"])
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVADO, ignore_errors=True)

    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.gerente = self.usuario("gerente", "gerente")
        self.jefe = self.usuario("jefe", "jefe", sucursal=self.suc)
        self.prov = Proveedor.objects.create(nombre="Repuestos SA", documento="30-12345678-9")
        self.filtro = Producto.objects.create(nombre="Filtro")
        self.rectificacion = Producto.objects.create(nombre="Rectificación", tipo="SERVICIO")

    def usuario(self, nombre, grupo, **kw):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=True, **kw)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def compra(self, *items, sucursal=None):
        c = Compra.objects.create(proveedor=self.prov, sucursal=sucursal or self.suc, creada_por=self.jefe)
        for producto, cantidad, costo in items:
            CompraDetalle.objects.create(
                compra=c, producto=producto, cantidad=Decimal(cantidad), costo_unitario=Decimal(costo)
            )
        c.refresh_from_db()
        return c

    def stock(self):
        return StockSucursal.objects.filter(producto=self.filtro, sucursal=self.suc).first()


class ProveedorTests(Base):
    def test_documento_normalizado_y_unico(self):
        self.assertEqual(self.prov.documento, "30123456789")
        with self.assertRaises(ValidationError):
            Proveedor.objects.create(nombre="Otro", documento="30.12345678.9")


class CompraTests(Base):
    def test_totales(self):
        c = self.compra((self.filtro, "2", "100"), (self.rectificacion, "1", "50"))
        self.assertEqual((c.subtotal, c.iva_total, c.total), (Decimal("250.00"), Decimal("52.50"), Decimal("302.50")))

    def test_confirmar_suma_stock_y_costo(self):
        ajustar_stock(sucursal=self.suc, producto=self.filtro, delta=2, tipo="INV_INICIAL")
        StockSucursal.objects.filter(producto=self.filtro).update(costo_promedio=Decimal("100"))
        c = self.compra((self.filtro, "2", "200"), (self.rectificacion, "1", "50"))
        c.confirmar(user=self.jefe)

        self.assertEqual(c.estado, Compra.Estado.CONFIRMADA)
        self.assertEqual(c.confirmada_por, self.jefe)
        st = self.stock()
        self.assertEqual((st.stock, st.costo_promedio), (Decimal("4.000"), Decimal("150.0000")))
        mov = MovimientoStock.objects.get(tipo="COMPRA")
        self.assertEqual(mov.creado_por, self.jefe)
        self.assertFalse(StockSucursal.objects.filter(producto=self.rectificacion).exists())

    def test_confirmada_no_se_edita(self):
        c = self.compra((self.filtro, "1", "100"))
        c.confirmar(user=self.jefe)
        with self.assertRaises(ValidationError):
            CompraDetalle.objects.create(compra=c, producto=self.filtro, cantidad=1, costo_unitario=1)
        with self.assertRaises(ValidationError):
            c.detalles.first().delete()
        c.observaciones = "cambio"
        with self.assertRaises(ValidationError):
            c.save()

    def test_no_confirma_sin_items_ni_dos_veces(self):
        c = self.compra()
        with self.assertRaises(ValidationError):
            c.confirmar(user=self.jefe)
        CompraDetalle.objects.create(compra=c, producto=self.filtro, cantidad=1, costo_unitario=1)
        c.confirmar(user=self.jefe)
        with self.assertRaises(ValidationError):
            c.confirmar(user=self.jefe)
        self.assertEqual(self.stock().stock, Decimal("1.000"))

    def test_anular_devuelve_stock(self):
        c = self.compra((self.filtro, "3", "100"))
        c.confirmar(user=self.jefe)
        c.anular(user=self.gerente)
        self.assertEqual(c.estado, Compra.Estado.ANULADA)
        self.assertEqual(self.stock().stock, Decimal("0.000"))

    def test_no_anula_si_el_stock_ya_se_uso(self):
        c = self.compra((self.filtro, "3", "100"))
        c.confirmar(user=self.jefe)
        ajustar_stock(sucursal=self.suc, producto=self.filtro, delta=-2, tipo="VENTA")
        with self.assertRaises(ValidationError):
            c.anular(user=self.gerente)
        c.refresh_from_db()
        self.assertEqual(c.estado, Compra.Estado.CONFIRMADA)
        self.assertEqual(self.stock().stock, Decimal("1.000"))

    def test_permisos(self):
        c = self.compra((self.filtro, "1", "100"))
        with self.assertRaises(PermissionDenied):
            c.confirmar(user=self.usuario("adm", "administracion"))
        c.confirmar(user=self.jefe)
        with self.assertRaises(PermissionDenied):
            c.anular(user=self.jefe)  # sólo el gerente anula


class AdjuntoYAdminTests(Base):
    def test_adjunto_privado(self):
        c = self.compra((self.filtro, "1", "100"))
        c.documento_adjunto = SimpleUploadedFile("factura.pdf", b"%PDF-1.4 prueba", content_type="application/pdf")
        c.save()
        self.assertTrue((Path(PRIVADO) / c.documento_adjunto.name).exists())
        with self.assertRaises(ValueError):
            c.documento_adjunto.url  # sin URL pública

        c.confirmar(user=self.jefe)
        self.client.force_login(self.jefe)
        r = self.client.get(f"/admin/compras/compra/{c.pk}/change/")
        self.assertContains(r, "factura.pdf (privado)")

    def test_extension_no_permitida(self):
        c = self.compra()
        c.documento_adjunto = SimpleUploadedFile("virus.exe", b"MZ")
        with self.assertRaises(ValidationError):
            c.save()

    def test_admin_por_rol(self):
        otra = Sucursal.objects.create(nombre="Otra")
        mia = self.compra((self.filtro, "1", "100"))
        ajena = self.compra((self.filtro, "1", "100"), sucursal=otra)

        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get(f"/admin/compras/compra/{mia.pk}/change/").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/compras/compra/{ajena.pk}/change/").status_code, 302)
        lista = self.client.get("/admin/compras/compra/")
        self.assertContains(lista, "confirmar_compras")
        self.assertNotContains(lista, "anular_compras")

        for grupo in ("administracion", "mecanico"):
            self.client.force_login(self.usuario(f"u_{grupo}", grupo))
            self.assertEqual(self.client.get("/admin/compras/compra/").status_code, 403)

    def test_cargar_y_confirmar_desde_admin(self):
        self.client.force_login(self.jefe)
        r = self.client.post("/admin/compras/compra/add/", {
            "proveedor": self.prov.pk, "sucursal": self.suc.pk,
            "fecha_0": "15/11/2026", "fecha_1": "10:00:00", "observaciones": "",
            "detalles-TOTAL_FORMS": "1", "detalles-INITIAL_FORMS": "0",
            "detalles-MIN_NUM_FORMS": "0", "detalles-MAX_NUM_FORMS": "1000",
            "detalles-0-producto": self.filtro.pk, "detalles-0-cantidad": "4",
            "detalles-0-costo_unitario": "250", "detalles-0-iva_tasa": "21",
        })
        self.assertEqual(r.status_code, 302)
        c = Compra.objects.get()
        self.assertEqual((c.total, c.creada_por), (Decimal("1210.00"), self.jefe))

        self.client.post("/admin/compras/compra/", {"action": "confirmar_compras", "_selected_action": [c.pk]})
        c.refresh_from_db()
        self.assertEqual(c.estado, Compra.Estado.CONFIRMADA)
        self.assertEqual(self.stock().stock, Decimal("4.000"))
