from datetime import date

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from clientes.models import Cliente
from core.models import Usuario

from . import servicios
from .models import AccesoCliente, Asociacion, Membresia, PerfilPiloto

CLAVE = "UnaClave-Segura-2026"


def datos(**kw):
    base = dict(
        username="juanp", email="Juan@Example.com", password=CLAVE, nombre="Juan", apellido="Pérez",
        dni="30.111.222", fecha_nacimiento=date(1995, 5, 10),
    )
    base.update(kw)
    return base


class RegistroTests(TestCase):
    def setUp(self):
        self.asoc = Asociacion.objects.create(nombre="Pista Norte")

    def test_registro_como_piloto(self):
        u = servicios.registrar_cuenta(**datos(asociacion=self.asoc, licencia="LIC-1"))
        self.assertEqual((u.tipo, u.dni, u.email, u.is_staff), (Usuario.Tipo.PORTAL, "30111222", "juan@example.com", False))
        self.assertTrue(u.check_password(CLAVE))
        m = u.membresias.get()
        self.assertEqual((m.rol, m.estado), (Membresia.Rol.PILOTO, Membresia.Estado.PENDIENTE))
        p = u.perfil_piloto
        self.assertEqual((p.nombre_publico, p.licencia, p.perfil_publico, p.aprobado), ("Juan Pérez", "LIC-1", False, False))
        self.assertFalse(AccesoCliente.objects.exists())

    def test_registro_como_cliente_y_piloto(self):
        u = servicios.registrar_cuenta(**datos(asociacion=self.asoc, es_cliente=True, nota_cliente="Traje el Fiesta"))
        acceso = u.accesos_cliente.get()
        self.assertEqual((acceso.estado, acceso.doc_declarado, acceso.cliente), (AccesoCliente.Estado.PENDIENTE, "30111222", None))
        estado = servicios.estado_de_cuenta(u)
        self.assertFalse(estado["es_piloto"] or estado["es_cliente"])
        self.assertEqual(len(estado["pendientes"]), 2)

    def test_cliente_sin_asociacion_no_necesita_nacimiento(self):
        u = servicios.registrar_cuenta(**datos(es_cliente=True, fecha_nacimiento=None))
        self.assertFalse(PerfilPiloto.objects.filter(usuario=u).exists())

    def test_tiene_que_elegir_algo(self):
        with self.assertRaises(ValidationError):
            servicios.registrar_cuenta(**datos())

    def test_validaciones(self):
        servicios.registrar_cuenta(**datos(asociacion=self.asoc))
        with self.assertRaises(ValidationError) as ctx:
            servicios.registrar_cuenta(**datos(
                username="otro", email="JUAN@example.com", dni="30111222", password="123",
                asociacion=self.asoc, fecha_nacimiento=None,
            ))
        errores = ctx.exception.message_dict
        for campo in ("email", "dni", "password", "fecha_nacimiento"):
            self.assertIn(campo, errores)
        self.assertEqual(Usuario.objects.count(), 1)  # no quedó nada a medias

    def test_asociacion_inactiva(self):
        self.asoc.activa = False
        self.asoc.save()
        with self.assertRaises(ValidationError):
            servicios.registrar_cuenta(**datos(asociacion=self.asoc))


@override_settings(ALLOWED_HOSTS=["testserver"])
class AccesoClienteTests(TestCase):
    def setUp(self):
        self.adm = Usuario.objects.create_user("adm", password="x", is_staff=True)
        self.adm.groups.add(Group.objects.get(name="administracion"))
        self.cliente = Cliente.objects.create(nombre="Juan Pérez", doc_tipo="DNI", doc_numero="30111222")
        self.usuario = servicios.registrar_cuenta(**datos(es_cliente=True))
        self.acceso = self.usuario.accesos_cliente.get()

    def test_aprobar_exige_cliente(self):
        with self.assertRaises(ValidationError):
            servicios.aprobar_acceso(self.acceso, self.adm)
        servicios.aprobar_acceso(self.acceso, self.adm, cliente=self.cliente, rol=AccesoCliente.Rol.TITULAR)
        self.assertEqual((self.acceso.estado, self.acceso.cliente, self.acceso.resuelto_por),
                         (AccesoCliente.Estado.APROBADO, self.cliente, self.adm))
        self.assertTrue(servicios.estado_de_cuenta(self.usuario)["es_cliente"])

    def test_solo_el_personal_aprueba(self):
        moderador = Usuario.objects.create_user("mod", password="x", tipo=Usuario.Tipo.PORTAL)
        mecanico = Usuario.objects.create_user("mec", password="x", is_staff=True)
        mecanico.groups.add(Group.objects.get(name="mecanico"))
        for actor in (moderador, mecanico):
            with self.assertRaises(PermissionDenied):
                servicios.aprobar_acceso(self.acceso, actor, cliente=self.cliente)

    def test_revocar(self):
        servicios.aprobar_acceso(self.acceso, self.adm, cliente=self.cliente)
        with self.assertRaises(ValidationError):
            servicios.revocar_acceso(self.acceso, self.adm, "")
        servicios.revocar_acceso(self.acceso, self.adm, "Ya no es cliente")
        self.assertEqual(self.acceso.estado, AccesoCliente.Estado.REVOCADO)

    def test_spam_no_desactiva_a_un_cliente_aprobado(self):
        servicios.aprobar_acceso(self.acceso, self.adm, cliente=self.cliente)
        asoc = Asociacion.objects.create(nombre="Karting Sur")
        gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        gerente.groups.add(Group.objects.get(name="gerente"))
        m = Membresia.objects.create(usuario=self.usuario, asociacion=asoc)
        self.assertFalse(servicios.marcar_spam(m, gerente))

    def test_aprobar_desde_el_admin(self):
        self.client.force_login(self.adm)
        url = f"/admin/portal/accesocliente/{self.acceso.pk}/change/"
        r = self.client.get(url)
        self.assertContains(r, "30111222")  # el personal ve el documento declarado
        self.acceso.cliente = self.cliente
        self.acceso.save()
        self.client.post("/admin/portal/accesocliente/", {
            "action": "aprobar_acceso", "_selected_action": [self.acceso.pk],
        })
        self.acceso.refresh_from_db()
        self.assertEqual(self.acceso.estado, AccesoCliente.Estado.APROBADO)
