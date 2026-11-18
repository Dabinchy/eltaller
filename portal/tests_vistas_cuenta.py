import shutil
import tempfile
from datetime import date

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from core.models import Usuario

from . import servicios
from .models import Asociacion, Membresia, PerfilPiloto
from .models_contenido import Palmares

PRIVADO = tempfile.mkdtemp(prefix="privado_cuenta_test_")
CLAVE = "UnaClave-Segura-2026"


def datos_registro(**kw):
    base = {
        "nombre": "Ana", "apellido": "Gómez", "dni": "40.111.222", "email": "ana@ejemplo.com",
        "username": "anag", "password": CLAVE, "password2": CLAVE,
        "soy_piloto": "on", "fecha_nacimiento": "2000-05-10", "licencia": "",
    }
    base.update(kw)
    return base


@override_settings(ALLOWED_HOSTS=["testserver"], PRIVATE_MEDIA_ROOT=PRIVADO)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVADO, ignore_errors=True)

    def setUp(self):
        self.asoc = Asociacion.objects.create(nombre="Pista Norte")
        self.gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="gerente"))

    def piloto_aprobado(self, nombre="juan", **kw):
        u = Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL)
        servicios.aprobar_membresia(Membresia.objects.create(usuario=u, asociacion=self.asoc), self.gerente)
        return PerfilPiloto.objects.create(usuario=u, nombre_publico=nombre.title(), **kw)


class RegistroTests(Base):
    def test_registro_de_piloto(self):
        r = self.client.post("/portal/registro/", datos_registro(asociacion=self.asoc.pk), follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/portal/")
        self.assertContains(r, "En revisión")
        u = Usuario.objects.get(username="anag")
        self.assertEqual((u.tipo, u.dni), (Usuario.Tipo.PORTAL, "40111222"))
        self.assertTrue(u.membresias.filter(estado=Membresia.Estado.PENDIENTE).exists())

    def test_registro_de_cliente_sin_asociacion(self):
        self.client.post("/portal/registro/", datos_registro(soy_piloto="", soy_cliente="on", nota_cliente="El Fiesta rojo"))
        u = Usuario.objects.get(username="anag")
        self.assertTrue(u.accesos_cliente.exists())
        self.assertFalse(PerfilPiloto.objects.filter(usuario=u).exists())

    def test_errores_en_el_formulario(self):
        r = self.client.post("/portal/registro/", datos_registro(password2="otra", asociacion=self.asoc.pk))
        self.assertContains(r, "Las contraseñas no coinciden")
        r = self.client.post("/portal/registro/", datos_registro(soy_piloto=""))
        self.assertContains(r, "Marcá si sos piloto")
        self.assertFalse(Usuario.objects.filter(username="anag").exists())

    def test_documento_repetido(self):
        self.client.post("/portal/registro/", datos_registro(asociacion=self.asoc.pk))
        self.client.post("/salir/")
        r = self.client.post("/portal/registro/", datos_registro(username="otra", email="otra@x.com", asociacion=self.asoc.pk))
        self.assertContains(r, "Ya existe una cuenta con este documento")

    def test_campo_trampa(self):
        self.client.post("/portal/registro/", datos_registro(asociacion=self.asoc.pk, web="http://spam"))
        self.assertFalse(Usuario.objects.filter(username="anag").exists())

    @override_settings(PORTAL_REGISTROS_POR_IP_HORA=1)
    def test_limite_por_ip(self):
        self.client.post("/portal/registro/", datos_registro(asociacion=self.asoc.pk))
        self.client.post("/salir/")
        r = self.client.post("/portal/registro/", datos_registro(username="otra", email="o@x.com", dni="40999888",
                                                                 asociacion=self.asoc.pk))
        self.assertContains(r, "demasiados registros")
        self.assertFalse(Usuario.objects.filter(username="otra").exists())

    def test_link_desde_el_ingreso(self):
        self.assertContains(self.client.get("/ingresar/"), "/portal/registro/")


class PerfilTests(Base):
    def test_pendiente_no_entra(self):
        u = Usuario.objects.create_user("nuevo", password="x", tipo=Usuario.Tipo.PORTAL)
        Membresia.objects.create(usuario=u, asociacion=self.asoc)
        PerfilPiloto.objects.create(usuario=u, nombre_publico="Nuevo")
        self.client.force_login(u)
        r = self.client.get("/portal/perfil/", follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/portal/")
        self.assertContains(r, "se habilita cuando tu asociación")

    def test_editar_sin_tocar_la_aprobacion(self):
        p = self.piloto_aprobado()
        self.client.force_login(p.usuario)
        self.assertContains(self.client.get("/portal/"), "Mi perfil")  # aparece en el menú
        self.client.post("/portal/perfil/", {
            "perfil-nombre_publico": "Juan Pérez", "perfil-bio": "Corro desde 2010", "perfil-instagram": "@juanp",
            "perfil-perfil_publico": "on", "perfil-aprobado": "on", "perfil-cuota_mb": "99999",
        })
        p.refresh_from_db()
        self.assertEqual((p.nombre_publico, p.instagram, p.perfil_publico), ("Juan Pérez", "juanp", True))
        self.assertFalse(p.aprobado)          # el piloto no se aprueba solo
        self.assertIsNone(p.cuota_mb)         # ni se sube la cuota

    def test_aviso_de_menor(self):
        hoy = date.today()
        p = self.piloto_aprobado(fecha_nacimiento=date(hoy.year - 12, 1, 1))
        self.client.force_login(p.usuario)
        self.assertContains(self.client.get("/portal/perfil/"), "Sos menor de edad")

    def test_palmares(self):
        p = self.piloto_aprobado()
        otro = self.piloto_aprobado("pedro")
        ajeno = Palmares.objects.create(piloto=otro, anio=2024, campeonato="X", resultado="1°")
        self.client.force_login(p.usuario)
        self.client.post("/portal/perfil/palmares/", {"anio": "2025", "campeonato": "TC Pista", "resultado": "Campeón"})
        self.assertEqual(p.palmares.count(), 1)
        self.assertEqual(self.client.post(f"/portal/perfil/palmares/{ajeno.pk}/borrar/").status_code, 404)
        self.client.post(f"/portal/perfil/palmares/{p.palmares.get().pk}/borrar/")
        self.assertEqual(p.palmares.count(), 0)


class ClaveTests(Base):
    def test_cambio_de_clave_portal_y_panel(self):
        p = self.piloto_aprobado()
        self.client.force_login(p.usuario)
        r = self.client.post("/portal/clave/", {"old_password": "x", "new_password1": CLAVE, "new_password2": CLAVE})
        self.assertRedirects(r, "/portal/")
        p.usuario.refresh_from_db()
        self.assertTrue(p.usuario.check_password(CLAVE))
        self.client.force_login(self.gerente)
        r = self.client.post("/panel/clave/", {"old_password": "x", "new_password1": CLAVE, "new_password2": CLAVE})
        self.assertRedirects(r, "/panel/")
