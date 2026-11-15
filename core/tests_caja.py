from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from core import caja as servicio
from core.models import Caja, SesionCaja, Sucursal, TipoMovCaja, Usuario


@override_settings(ALLOWED_HOSTS=["testserver"])
class Base(TestCase):
    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.otra = Sucursal.objects.create(nombre="Norte")
        self.caja = Caja.objects.create(sucursal=self.suc, numero=1)
        self.caja_otra = Caja.objects.create(sucursal=self.otra, numero=1)
        self.gerente = self.personal("gerente", "gerente", pin="1111")
        self.jefe = self.personal("jefe", "jefe", pin="2222", sucursal=self.suc)
        self.adm = self.personal("adm", "administracion", pin="3333", sucursal=self.suc)
        self.mec = self.personal("mec", "mecanico")

    def personal(self, nombre, grupo, pin=None, **kw):
        u = Usuario.objects.create_user(nombre, password="x", **kw)
        u.groups.add(Group.objects.get(name=grupo))
        if pin:
            u.set_action_pin(pin)
            u.save()
        return Usuario.objects.get(pk=u.pk)  # recarga permisos

    def abrir(self, usuario=None, pin="3333", saldo="1.000,00"):
        self.client.force_login(usuario or self.adm)
        return self.client.post(f"/panel/caja/{self.caja.pk}/abrir/", {"saldo_inicial": saldo, "pin": pin})

    def sesion(self):
        return SesionCaja.objects.get(caja=self.caja, estado=SesionCaja.Estado.ABIERTA)


class AbrirTests(Base):
    def test_administracion_abre_con_pin(self):
        r = self.abrir()
        s = self.sesion()
        self.assertRedirects(r, f"/panel/caja/sesion/{s.pk}/")
        self.assertEqual((s.saldo_inicial, s.saldo_estimado), (Decimal("1000.00"), Decimal("1000.00")))

    def test_pin_incorrecto(self):
        r = self.abrir(pin="9999")
        self.assertContains(r, "PIN inválido")
        self.assertFalse(SesionCaja.objects.exists())

    def test_sin_pin_configurado(self):
        sin_pin = self.personal("adm2", "administracion", sucursal=self.suc)
        self.client.force_login(sin_pin)
        self.assertContains(self.client.get(f"/panel/caja/{self.caja.pk}/abrir/"), "Configuralo acá")

    def test_caja_de_otra_sucursal_no_existe_para_el(self):
        self.client.force_login(self.adm)
        self.assertEqual(self.client.get(f"/panel/caja/{self.caja_otra.pk}/abrir/").status_code, 404)

    def test_mecanico_sin_acceso(self):
        self.client.force_login(self.mec)
        self.assertEqual(self.client.get("/panel/caja/").status_code, 403)
        self.assertNotContains(self.client.get("/panel/"), 'href="/panel/caja/"')


class MovimientoTests(Base):
    def test_ingreso_y_egreso_actualizan_el_estimado(self):
        self.abrir()
        url = f"/panel/caja/{self.caja.pk}/movimiento/"
        self.client.post(url, {"tipo": TipoMovCaja.INGRESO, "monto": "500", "motivo": "Cambio", "pin": "3333"})
        self.client.post(url, {"tipo": TipoMovCaja.EGRESO, "monto": "200,50", "motivo": "Pago flete", "pin": "3333"})
        self.assertEqual(self.sesion().saldo_estimado, Decimal("1299.50"))

    def test_egreso_no_deja_la_caja_en_negativo(self):
        self.abrir()
        with self.assertRaises(ValidationError):
            servicio.registrar_movimiento(self.caja, self.adm, tipo=TipoMovCaja.EGRESO, monto=Decimal("5000"),
                                          motivo="Retiro", pin="3333")
        self.assertEqual(self.sesion().saldo_estimado, Decimal("1000.00"))

    def test_requiere_motivo_pin_y_caja_abierta(self):
        with self.assertRaises(ValidationError):
            servicio.registrar_movimiento(self.caja, self.adm, tipo=TipoMovCaja.INGRESO, monto=1, motivo="x", pin="3333")
        self.abrir()
        with self.assertRaises(ValidationError):
            servicio.registrar_movimiento(self.caja, self.adm, tipo=TipoMovCaja.INGRESO, monto=1, motivo=" ", pin="3333")
        with self.assertRaises(PermissionDenied):
            servicio.registrar_movimiento(self.caja, self.adm, tipo=TipoMovCaja.INGRESO, monto=1, motivo="x", pin="0000")

    def test_no_se_mueve_caja_de_otra_sucursal(self):
        with self.assertRaises(PermissionDenied):
            servicio.registrar_movimiento(self.caja_otra, self.adm, tipo=TipoMovCaja.INGRESO, monto=1, motivo="x",
                                          pin="3333")


class CerrarTests(Base):
    def test_administracion_no_cierra(self):
        self.abrir()
        s = self.sesion()
        self.assertEqual(self.client.get(f"/panel/caja/sesion/{s.pk}/cerrar/").status_code, 403)
        self.assertNotContains(self.client.get(f"/panel/caja/sesion/{s.pk}/"), "Cerrar caja")

    def test_jefe_cierra_y_queda_la_diferencia(self):
        self.abrir()
        s = self.sesion()
        self.client.force_login(self.jefe)
        r = self.client.post(f"/panel/caja/sesion/{s.pk}/cerrar/",
                             {"total_contado": "950", "observacion": "Faltante", "pin": "2222"}, follow=True)
        s.refresh_from_db()
        self.assertEqual((s.estado, s.diferencia, s.cerrada_por), (SesionCaja.Estado.CERRADA, Decimal("-50.00"), self.jefe))
        self.assertContains(r, "Diferencia: -50.00")

    def test_no_cierra_con_ventas_abiertas(self):
        from ventas.models import Venta

        self.abrir()
        s = self.sesion()
        Venta.objects.create(sucursal=self.suc, caja=self.caja, sesion=s, creada_por=self.adm)
        with self.assertRaises(ValidationError):
            servicio.cerrar_sesion(s, self.jefe, pin="2222", total_contado=Decimal("1000"))

    def test_pin_del_que_cierra(self):
        self.abrir()
        with self.assertRaises(PermissionDenied):
            servicio.cerrar_sesion(self.sesion(), self.jefe, pin="3333", total_contado=Decimal("1000"))


class PinTests(Base):
    def test_primera_vez_y_cambio(self):
        nuevo = self.personal("nuevo", "administracion", sucursal=self.suc)
        self.client.force_login(nuevo)
        self.client.post("/panel/mi-pin/", {"nuevo_pin": "4545", "repetir_pin": "4545"})
        nuevo.refresh_from_db()
        self.assertTrue(nuevo.check_action_pin("4545"))
        r = self.client.post("/panel/mi-pin/", {"nuevo_pin": "5656", "repetir_pin": "5656"})
        self.assertContains(r, "Ingresá tu PIN actual")
        self.client.post("/panel/mi-pin/", {"pin_actual": "4545", "nuevo_pin": "5656", "repetir_pin": "5656"})
        nuevo.refresh_from_db()
        self.assertTrue(nuevo.check_action_pin("5656"))

    def test_pin_repetido_entre_usuarios(self):
        with self.assertRaises(ValidationError):
            servicio.configurar_pin(self.mec, nuevo="1111", repetido="1111")  # es el del gerente

    def test_formato(self):
        with self.assertRaises(ValidationError):
            servicio.configurar_pin(self.mec, nuevo="12a4", repetido="12a4")
