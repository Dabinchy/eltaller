import shutil
import tempfile
from datetime import date
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from core.models import Usuario

from . import servicios
from .models import Asociacion, Membresia, PerfilPiloto, RegistroModeracion

PRIVADO = tempfile.mkdtemp(prefix="privado_portal_test_")
M = Membresia


def jpg_con_metadatos(ancho=3000, alto=1500) -> SimpleUploadedFile:
    img = Image.new("RGB", (ancho, alto), "red")
    exif = Image.Exif()
    exif[0x010F] = "MarcaDelCelular"   # Make
    exif[0x0110] = "ModeloSecreto"     # Model
    salida = BytesIO()
    img.save(salida, format="JPEG", exif=exif)
    return SimpleUploadedFile("foto.jpg", salida.getvalue(), content_type="image/jpeg")


@override_settings(PRIVATE_MEDIA_ROOT=PRIVADO)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVADO, ignore_errors=True)

    def setUp(self):
        self.asoc_a = Asociacion.objects.create(nombre="Asociación Pista Norte")
        self.asoc_b = Asociacion.objects.create(nombre="Karting Sur", cuota_mb=800)
        self.gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="gerente"))
        self.mod_a = self.moderador("mod_a", self.asoc_a)
        self.piloto = self.usuario_portal("piloto", dni="30.111.222")

    def usuario_portal(self, nombre, **kw):
        return Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL, **kw)

    def moderador(self, nombre, asociacion):
        u = self.usuario_portal(nombre)
        m = Membresia.objects.create(usuario=u, asociacion=asociacion, rol=M.Rol.MODERADOR)
        servicios.aprobar_membresia(m, self.gerente)
        return u

    def membresia_piloto(self, usuario, asociacion):
        return Membresia.objects.create(usuario=usuario, asociacion=asociacion, rol=M.Rol.PILOTO)

    def perfil(self, usuario, **kw):
        return PerfilPiloto.objects.create(usuario=usuario, nombre_publico=kw.pop("nombre", "Juan Pérez"), **kw)


class UsuarioDniTests(Base):
    def test_dni_normalizado_y_unico(self):
        self.assertEqual(self.piloto.dni, "30111222")
        with self.assertRaises(ValidationError):
            u = Usuario(username="otro", dni="30 111 222", tipo=Usuario.Tipo.PORTAL)
            u.full_clean()


class MembresiaTests(Base):
    def test_moderador_aprueba_pilotos_de_su_asociacion(self):
        m = self.membresia_piloto(self.piloto, self.asoc_a)
        servicios.aprobar_membresia(m, self.mod_a)
        self.assertEqual(m.estado, M.Estado.APROBADA)
        self.assertEqual(m.resuelta_por, self.mod_a)

    def test_moderador_no_toca_otra_asociacion(self):
        m = self.membresia_piloto(self.piloto, self.asoc_b)
        with self.assertRaises(PermissionDenied):
            servicios.aprobar_membresia(m, self.mod_a)

    def test_nadie_se_aprueba_a_si_mismo(self):
        m = self.membresia_piloto(self.mod_a, self.asoc_a)  # el moderador también corre
        with self.assertRaises(PermissionDenied):
            servicios.aprobar_membresia(m, self.mod_a)
        otro_mod = self.moderador("mod_a2", self.asoc_a)
        servicios.aprobar_membresia(m, otro_mod)

    def test_solo_el_gerente_nombra_moderadores(self):
        candidato = self.usuario_portal("candidato")
        m = Membresia.objects.create(usuario=candidato, asociacion=self.asoc_a, rol=M.Rol.MODERADOR)
        with self.assertRaises(PermissionDenied):
            servicios.aprobar_membresia(m, self.mod_a)
        servicios.aprobar_membresia(m, self.gerente)

    def test_gerente_modera_todas(self):
        m = self.membresia_piloto(self.piloto, self.asoc_b)
        servicios.aprobar_membresia(m, self.gerente)

    def test_rechazo_exige_motivo(self):
        m = self.membresia_piloto(self.piloto, self.asoc_a)
        with self.assertRaises(ValidationError):
            servicios.rechazar_membresia(m, self.mod_a, "  ")
        servicios.rechazar_membresia(m, self.mod_a, "No corre en la asociación")
        self.assertEqual(m.estado, M.Estado.RECHAZADA)

    def test_suspender_y_reactivar(self):
        m = self.membresia_piloto(self.piloto, self.asoc_a)
        servicios.aprobar_membresia(m, self.mod_a)
        servicios.suspender_membresia(m, self.mod_a, "Conducta")
        servicios.aprobar_membresia(m, self.mod_a)
        acciones = list(RegistroModeracion.objects.filter(object_id=m.pk).values_list("accion", flat=True))
        self.assertEqual(sorted(acciones), sorted(["APROBAR", "SUSPENDER", "REACTIVAR"]))

    def test_spam_desactiva_cuenta_sin_otros_vinculos(self):
        m = self.membresia_piloto(self.piloto, self.asoc_a)
        self.assertTrue(servicios.marcar_spam(m, self.mod_a))
        self.piloto.refresh_from_db()
        self.assertFalse(self.piloto.is_active)

    def test_spam_no_desactiva_si_tiene_otro_vinculo(self):
        aprobada = self.membresia_piloto(self.piloto, self.asoc_b)
        servicios.aprobar_membresia(aprobada, self.gerente)
        m = self.membresia_piloto(self.piloto, self.asoc_a)
        self.assertFalse(servicios.marcar_spam(m, self.mod_a))
        self.piloto.refresh_from_db()
        self.assertTrue(self.piloto.is_active)

    def test_staff_no_puede_ser_miembro(self):
        with self.assertRaises(ValidationError):
            self.membresia_piloto(self.gerente, self.asoc_a)


class PerfilTests(Base):
    def aprobado(self, **kw):
        servicios.aprobar_membresia(self.membresia_piloto(self.piloto, self.asoc_a), self.mod_a)
        p = self.perfil(self.piloto, perfil_publico=True, **kw)
        servicios.aprobar_perfil(p, self.mod_a)
        return p

    def test_slug_e_instagram(self):
        p = self.perfil(self.piloto, instagram="https://www.instagram.com/juan.perez/")
        otro = self.perfil(self.usuario_portal("otro"))
        self.assertEqual((p.slug, otro.slug), ("juan-perez", "juan-perez-2"))
        self.assertEqual(p.instagram, "juan.perez")

    def test_visible_solo_con_todo_en_regla(self):
        p = self.perfil(self.piloto, perfil_publico=True)
        self.assertFalse(p.visible_en_web)
        with self.assertRaises(ValidationError):
            servicios.aprobar_perfil(p, self.mod_a)  # todavía sin membresía aprobada
        servicios.aprobar_membresia(self.membresia_piloto(self.piloto, self.asoc_a), self.mod_a)
        servicios.aprobar_perfil(p, self.mod_a)
        self.assertTrue(p.visible_en_web)
        p.perfil_publico = False  # el piloto decide ocultarlo
        self.assertFalse(p.visible_en_web)

    def test_cambio_tras_aprobacion(self):
        p = self.aprobado()
        p.bio = "Nueva biografía"
        p.save()
        self.assertTrue(p.cambio_tras_aprobacion)
        servicios.marcar_perfil_revisado(p, self.mod_a)
        self.assertFalse(p.cambio_tras_aprobacion)
        p.telefono = "123"  # dato privado: no marca
        p.save()
        self.assertFalse(p.cambio_tras_aprobacion)

    def test_menor_necesita_consentimiento(self):
        servicios.aprobar_membresia(self.membresia_piloto(self.piloto, self.asoc_a), self.mod_a)
        hoy = date.today()
        p = self.perfil(self.piloto, perfil_publico=True, fecha_nacimiento=date(hoy.year - 12, 1, 1))
        self.assertTrue(p.es_menor)
        with self.assertRaises(ValidationError):
            servicios.aprobar_perfil(p, self.mod_a)
        servicios.registrar_consentimiento_tutor(p, self.mod_a)
        servicios.aprobar_perfil(p, self.mod_a)
        self.assertTrue(p.visible_en_web)

    def test_moderador_de_otra_asociacion_no_aprueba(self):
        servicios.aprobar_membresia(self.membresia_piloto(self.piloto, self.asoc_b), self.gerente)
        p = self.perfil(self.piloto)
        with self.assertRaises(PermissionDenied):
            servicios.aprobar_perfil(p, self.mod_a)

    def test_cuota(self):
        p = self.perfil(self.piloto)
        self.assertEqual(p.cuota_efectiva_mb, 500)  # valor general
        servicios.aprobar_membresia(self.membresia_piloto(self.piloto, self.asoc_b), self.gerente)
        self.assertEqual(p.cuota_efectiva_mb, 800)  # la de su asociación
        servicios.cambiar_cuota(p, self.gerente, 2000)
        self.assertEqual(p.cuota_efectiva_mb, 2000)  # la propia

    def test_foto_sin_metadatos_y_achicada(self):
        p = self.perfil(self.piloto, foto=jpg_con_metadatos())
        with p.foto.open("rb") as f:
            img = Image.open(f)
            self.assertEqual(max(img.size), 2000)
            self.assertEqual(len(img.getexif()), 0)
        with p.foto_miniatura.open("rb") as f:
            self.assertEqual(max(Image.open(f).size), 400)

    def test_archivo_falso_rechazado(self):
        falso = SimpleUploadedFile("foto.jpg", b"esto no es una imagen", content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            self.perfil(self.piloto, foto=falso)
