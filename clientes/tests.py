from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from core.models import Usuario

from .models import Cliente, CuentaCorriente, MovimientoCuentaCorriente


def crear_cliente(test, **kw):
    """Crea un cliente ejecutando los on_commit (alta de la cuenta corriente)."""
    with test.captureOnCommitCallbacks(execute=True):
        return Cliente.objects.create(**{"nombre": "Juan Pérez", **kw})


class ClienteTests(TestCase):
    def test_crea_cuenta_corriente_al_dar_de_alta(self):
        c = crear_cliente(self)
        self.assertTrue(CuentaCorriente.objects.filter(cliente=c).exists())
        self.assertEqual(c.saldo_cc, Decimal("0.00"))

    def test_normaliza_cuit_a_digitos(self):
        c = crear_cliente(self, doc_tipo="cuit", doc_numero=" 20-12345678-9 ")
        self.assertEqual((c.doc_tipo, c.doc_numero), ("CUIT", "20123456789"))

    def test_documento_duplicado_rechazado(self):
        crear_cliente(self, doc_tipo="DNI", doc_numero="12.345.678")
        with self.assertRaises(ValidationError):
            crear_cliente(self, nombre="Otro", doc_tipo="DNI", doc_numero="12345678")

    def test_varios_sin_documento(self):
        crear_cliente(self)
        crear_cliente(self, nombre="Otro")
        self.assertEqual(Cliente.objects.count(), 2)

    def test_numero_sin_tipo_rechazado(self):
        with self.assertRaises(ValidationError):
            crear_cliente(self, doc_numero="123")


class CuentaCorrienteTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user("caja", password="x")
        self.cc = crear_cliente(self).cuenta_corriente

    def mov(self, tipo, monto, user=None):
        return MovimientoCuentaCorriente.objects.create(
            cuenta=self.cc, tipo=tipo, monto=Decimal(monto), creado_por=user or self.user
        )

    def test_debito_y_pago(self):
        self.mov("DEBITO", "1000")
        self.mov("CREDITO", "400")
        self.cc.refresh_from_db()
        self.assertEqual(self.cc.saldo, Decimal("600.00"))

    def test_pago_mayor_que_deuda_rechazado_sin_dejar_rastro(self):
        self.mov("DEBITO", "100")
        with self.assertRaises(ValidationError):
            self.mov("CREDITO", "150")
        self.cc.refresh_from_db()
        self.assertEqual(self.cc.saldo, Decimal("100.00"))
        self.assertEqual(self.cc.movimientos.count(), 1)

    def test_movimiento_no_se_edita(self):
        m = self.mov("DEBITO", "100")
        m.monto = Decimal("1")
        with self.assertRaises(ValidationError):
            m.save()

    def test_piloto_no_registra_movimientos(self):
        piloto = Usuario.objects.create_user("piloto", password="x", tipo=Usuario.Tipo.PILOTO)
        with self.assertRaises(ValidationError):
            self.mov("DEBITO", "100", user=piloto)


@override_settings(ALLOWED_HOSTS=["testserver"])
class AdminPorRolTests(TestCase):
    URLS = [
        "/admin/clientes/cliente/",
        "/admin/clientes/cliente/add/",
        "/admin/clientes/cuentacorriente/",
        "/admin/clientes/movimientocuentacorriente/add/",
    ]

    def usuario(self, nombre, grupo):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=True)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def codigos(self, user):
        self.client.force_login(user)
        return [self.client.get(u).status_code for u in self.URLS]

    def test_administracion_atiende_y_cobra(self):
        self.assertEqual(self.codigos(self.usuario("adm", "administracion")), [200, 200, 200, 200])

    def test_mecanico_sin_acceso(self):
        self.assertEqual(self.codigos(self.usuario("mec", "mecanico")), [403, 403, 403, 403])

    def test_registrar_pago_desde_admin(self):
        adm = self.usuario("adm", "administracion")
        cc = crear_cliente(self).cuenta_corriente
        MovimientoCuentaCorriente.objects.create(cuenta=cc, tipo="DEBITO", monto=500, creado_por=adm)
        self.client.force_login(adm)

        url = "/admin/clientes/movimientocuentacorriente/add/"
        base = {"cuenta": cc.pk, "fecha_0": "15/11/2026", "fecha_1": "10:00:00", "descripcion": "Pago"}
        r = self.client.post(url, {**base, "tipo": "CREDITO", "monto": "800"})
        self.assertEqual(r.status_code, 200)  # vuelve al formulario con el error
        r = self.client.post(url, {**base, "tipo": "CREDITO", "monto": "200"})
        self.assertEqual(r.status_code, 302)

        cc.refresh_from_db()
        self.assertEqual(cc.saldo, Decimal("300.00"))
        self.assertEqual(cc.movimientos.first().creado_por, adm)
