from datetime import date

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
import shutil
import tempfile

from core.models import Usuario

from . import servicios
from . import servicios_contenido as sc
from .models import Asociacion, Membresia, PerfilPiloto, RegistroModeracion
from .models_contenido import Archivo

PRIVADO = tempfile.mkdtemp(prefix="privado_moderacion_test_")
M = Membresia


@override_settings(ALLOWED_HOSTS=["testserver"], PRIVATE_MEDIA_ROOT=PRIVADO)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVADO, ignore_errors=True)

    def setUp(self):
        self.gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="gerente"))
        self.asoc = Asociacion.objects.create(nombre="Pista Norte")
        self.otra = Asociacion.objects.create(nombre="Karting Sur")
        self.mod = self.portal("mod")
        servicios.aprobar_membresia(M.objects.create(usuario=self.mod, asociacion=self.asoc, rol=M.Rol.MODERADOR), self.gerente)
        self.client.force_login(self.mod)

    def portal(self, nombre, **kw):
        return Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL, **kw)

    def piloto(self, nombre, asociacion=None, aprobar=True, **kw):
        u = self.portal(nombre, dni=f"3{abs(hash(nombre)) % 10**7:07d}")
        m = M.objects.create(usuario=u, asociacion=asociacion or self.asoc)
        if aprobar:
            servicios.aprobar_membresia(m, self.gerente)
        return PerfilPiloto.objects.create(usuario=u, nombre_publico=nombre.title(), **kw)


class CuentasTests(Base):
    def test_aprobar_rechazar_y_spam(self):
        a, b, c = (self.piloto(n, aprobar=False) for n in ("ana", "beto", "carla"))
        r = self.client.get("/portal/moderacion/")
        self.assertContains(r, "Ana")
        self.assertContains(r, a.usuario.dni)  # el moderador ve el DNI para verificar
        ma, mb, mc = (p.usuario.membresias.get() for p in (a, b, c))
        self.client.post(f"/portal/moderacion/membresias/{ma.pk}/", {"accion": "aprobar"})
        self.client.post(f"/portal/moderacion/membresias/{mb.pk}/", {"accion": "rechazar", "motivo": "No corre acá"})
        self.client.post(f"/portal/moderacion/membresias/{mc.pk}/", {"accion": "spam"})
        for m in (ma, mb, mc):
            m.refresh_from_db()
        self.assertEqual((ma.estado, mb.estado, mc.estado), (M.Estado.APROBADA, M.Estado.RECHAZADA, M.Estado.RECHAZADA))
        c.usuario.refresh_from_db()
        self.assertFalse(c.usuario.is_active)
        self.assertEqual(RegistroModeracion.objects.filter(asociacion=self.asoc, actor=self.mod).count(), 3)

    def test_rechazo_sin_motivo(self):
        m = self.piloto("ana", aprobar=False).usuario.membresias.get()
        r = self.client.post(f"/portal/moderacion/membresias/{m.pk}/", {"accion": "rechazar"}, follow=True)
        self.assertContains(r, "Indicá el motivo")

    def test_no_ve_ni_toca_otra_asociacion(self):
        m = self.piloto("sur", self.otra, aprobar=False).usuario.membresias.get()
        self.assertNotContains(self.client.get("/portal/moderacion/"), "Sur")
        self.assertEqual(self.client.post(f"/portal/moderacion/membresias/{m.pk}/", {"accion": "aprobar"}).status_code, 404)

    def test_solo_moderadores(self):
        p = self.piloto("ana")
        self.client.force_login(p.usuario)
        self.assertEqual(self.client.get("/portal/moderacion/").status_code, 403)
        self.assertNotContains(self.client.get("/portal/"), "/portal/moderacion/")
        self.client.force_login(self.mod)
        self.assertContains(self.client.get("/portal/"), "/portal/moderacion/")


class ContenidoTests(Base):
    def test_perfil_y_cambios(self):
        p = self.piloto("ana", perfil_publico=True)
        self.assertContains(self.client.get("/portal/moderacion/"), "primera aprobación")
        self.client.post(f"/portal/moderacion/perfiles/{p.pk}/", {"accion": "aprobar"})
        p.refresh_from_db()
        self.assertTrue(p.visible_en_web)
        p.bio = "Nueva bio"
        p.save()
        self.assertContains(self.client.get("/portal/moderacion/"), "cambió después de aprobado")
        self.client.post(f"/portal/moderacion/perfiles/{p.pk}/", {"accion": "retirar", "motivo": "Foto inapropiada"})
        p.refresh_from_db()
        self.assertFalse(p.aprobado)

    def test_menor_y_consentimiento(self):
        hoy = date.today()
        p = self.piloto("nene", perfil_publico=True, fecha_nacimiento=date(hoy.year - 12, 1, 1))
        self.assertContains(self.client.get("/portal/moderacion/"), "Menores sin consentimiento")
        r = self.client.post(f"/portal/moderacion/perfiles/{p.pk}/", {"accion": "aprobar"}, follow=True)
        self.assertContains(r, "consentimiento del tutor")
        self.client.post(f"/portal/moderacion/perfiles/{p.pk}/", {"accion": "consentimiento"})
        self.client.post(f"/portal/moderacion/perfiles/{p.pk}/", {"accion": "aprobar"})
        p.refresh_from_db()
        self.assertTrue(p.aprobado)

    def test_auto_y_archivo(self):
        p = self.piloto("ana")
        a = sc.crear_auto(p, marca="Ford", modelo="Falcon")
        sc.publicar_auto(a, p, True)
        x = sc.subir_archivo_piloto(p, tipo="SETUP", titulo="Setup público", visibilidad="PUBLICO", auto=a,
                                    archivo=SimpleUploadedFile("s.pdf", b"%PDF"))
        r = self.client.get("/portal/moderacion/")
        self.assertContains(r, "Ford Falcon")
        self.assertContains(r, "Setup público")
        self.client.post(f"/portal/moderacion/autos/{a.pk}/", {"accion": "aprobar"})
        self.client.post(f"/portal/moderacion/archivos/{x.pk}/", {"accion": "aprobar"})
        a.refresh_from_db()
        x.refresh_from_db()
        self.assertTrue(a.aprobado and x.aprobado)

    def test_nada_propio_en_la_cola(self):
        servicios.aprobar_membresia(M.objects.create(usuario=self.mod, asociacion=self.asoc), self.gerente)
        mio = PerfilPiloto.objects.create(usuario=self.mod, nombre_publico="Moderador Corredor", perfil_publico=True)
        self.assertNotContains(self.client.get("/portal/moderacion/"), "Moderador Corredor")
        r = self.client.post(f"/portal/moderacion/perfiles/{mio.pk}/", {"accion": "aprobar"}, follow=True)
        self.assertContains(r, "No podés moderar lo tuyo")


class MiembrosTests(Base):
    def test_suspender_reactivar_y_cuota(self):
        p = self.piloto("ana")
        m = p.usuario.membresias.get()
        self.assertContains(self.client.get("/portal/moderacion/pilotos/"), "Ana")
        self.client.post(f"/portal/moderacion/membresias/{m.pk}/", {"accion": "suspender", "motivo": "Conducta"})
        m.refresh_from_db()
        self.assertEqual(m.estado, M.Estado.SUSPENDIDA)
        self.client.post(f"/portal/moderacion/pilotos/{m.pk}/reactivar/")
        m.refresh_from_db()
        self.assertEqual(m.estado, M.Estado.APROBADA)
        self.client.post(f"/portal/moderacion/perfiles/{p.pk}/", {"accion": "cuota", "cuota_mb": "2000"})
        p.refresh_from_db()
        self.assertEqual(p.cuota_efectiva_mb, 2000)
        self.assertContains(self.client.get("/portal/moderacion/historial/"), "Cambiar cuota")

    def test_volver_solo_a_moderacion(self):
        m = self.piloto("ana", aprobar=False).usuario.membresias.get()
        r = self.client.post(f"/portal/moderacion/membresias/{m.pk}/", {"accion": "aprobar", "volver": "https://malo.com"})
        self.assertRedirects(r, "/portal/moderacion/")
