"""Contenido editable del sitio (Parte 1 del frontend): modelos, fotos, permisos y admin."""
import atexit
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from core.models import Empresa, Usuario

from .models import Consulta, FotoTrabajo, Portada, Publicacion, Servicio, Testimonio, Trabajo

MEDIA = tempfile.mkdtemp(prefix="media_sitio_test_")
# Se borra al terminar la corrida (no al terminar cada clase: en paralelo la comparten).
atexit.register(shutil.rmtree, MEDIA, ignore_errors=True)
VIDEO_OK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def jpg_con_metadatos(ancho=3000, alto=1500) -> SimpleUploadedFile:
    img = Image.new("RGB", (ancho, alto), "blue")
    exif = Image.Exif()
    exif[0x010F] = "MarcaDelCelular"   # Make
    salida = BytesIO()
    img.save(salida, format="JPEG", exif=exif)
    return SimpleUploadedFile("foto.jpg", salida.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA, ALLOWED_HOSTS=["testserver"])
class Base(TestCase):
    def trabajo(self, **kw):
        datos = {"titulo": "Falcon Sprint", "resumen": "Restauración completa."}
        datos.update(kw)
        return Trabajo.objects.create(**datos)


class PublicadosTests(Base):
    def test_solo_lo_publicado(self):
        visible = self.trabajo(publicado=True)
        self.trabajo(titulo="Borrador")
        self.assertEqual(list(Trabajo.objects.publicados()), [visible])

        Servicio.objects.create(titulo="Frenos", resumen="x", publicado=True)
        Servicio.objects.create(titulo="Oculto", resumen="x")
        self.assertEqual([s.titulo for s in Servicio.objects.publicados()], ["Frenos"])

        Testimonio.objects.create(nombre="Ana", texto="Excelente", publicado=True)
        Testimonio.objects.create(nombre="Beto", texto="Sin permiso todavía")
        self.assertEqual([t.nombre for t in Testimonio.objects.publicados()], ["Ana"])

    def test_novedad_con_fecha_futura_espera(self):
        ahora = timezone.now()
        hoy = Publicacion.objects.create(titulo="Hoy", resumen="x", publicada=True, fecha=ahora)
        Publicacion.objects.create(titulo="Mañana", resumen="x", publicada=True, fecha=ahora + timedelta(days=1))
        Publicacion.objects.create(titulo="Borrador", resumen="x", fecha=ahora)
        self.assertEqual(list(Publicacion.objects.publicadas()), [hoy])


class FotosTests(Base):
    def test_portada_del_trabajo_limpia_y_achicada(self):
        t = self.trabajo(portada=jpg_con_metadatos())
        with t.portada.open("rb") as f:
            img = Image.open(f)
            self.assertEqual(max(img.size), 2000)
            self.assertEqual(len(img.getexif()), 0)
        with t.portada_miniatura.open("rb") as f:
            self.assertEqual(max(Image.open(f).size), 400)

    def test_fotos_de_la_galeria(self):
        foto = FotoTrabajo.objects.create(trabajo=self.trabajo(), imagen=jpg_con_metadatos(), etapa="antes")
        with foto.imagen.open("rb") as f:
            self.assertEqual(len(Image.open(f).getexif()), 0)
        self.assertTrue(foto.miniatura)

    def test_portada_de_parte_sin_miniatura(self):
        p = Portada.objects.create(parte="taller", titulo="Mecánica de confianza", imagen=jpg_con_metadatos())
        with p.imagen.open("rb") as f:
            self.assertEqual(max(Image.open(f).size), 2000)

    def test_archivo_que_no_es_imagen(self):
        falso = SimpleUploadedFile("foto.jpg", b"no soy una imagen", content_type="image/jpeg")
        with self.assertRaises(ValidationError):
            self.trabajo(portada=falso)


class ReglasTests(Base):
    def test_video_solo_youtube_o_vimeo(self):
        for modelo in (
            Trabajo(titulo="x", resumen="x", video_url="https://example.com/video.mp4"),
            Portada(parte="prepa", titulo="x", video_url="https://example.com/v"),
            Publicacion(titulo="x", resumen="x", video_url="https://example.com/v"),
        ):
            with self.assertRaises(ValidationError) as e:
                modelo.full_clean()
            self.assertIn("video_url", e.exception.message_dict)
        t = Trabajo(titulo="x", resumen="x", video_url=VIDEO_OK)
        t.full_clean(exclude=["slug"])
        self.assertEqual(t.video_embed_url, "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")

    def test_direccion_automatica_y_sin_repetir(self):
        a = self.trabajo()
        b = self.trabajo()
        self.assertEqual((a.slug, b.slug), ("falcon-sprint", "falcon-sprint-2"))
        a.titulo = "Otro nombre"
        a.save()
        self.assertEqual(a.slug, "falcon-sprint")  # el link no cambia si se renombra
        n = Publicacion.objects.create(titulo="¡Llegó el dinamómetro!", resumen="x")
        self.assertEqual(n.slug, "llego-el-dinamometro")

    def test_parte_segun_el_tipo(self):
        self.assertEqual(self.trabajo().parte, "taller")
        self.assertEqual(self.trabajo(tipo=Trabajo.Tipo.CLASICO).parte, "prepa")

    def test_una_portada_por_parte(self):
        Portada.objects.create(parte="taller", titulo="A")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Portada.objects.create(parte="taller", titulo="B")

    def test_seccion_solo_en_el_prepa(self):
        with self.assertRaises(ValidationError):
            Servicio(parte="prepa", titulo="x", resumen="x").full_clean()
        with self.assertRaises(ValidationError):
            Servicio(parte="taller", seccion="clasicos", titulo="x", resumen="x").full_clean()
        Servicio(parte="prepa", seccion="clasicos", titulo="x", resumen="x").full_clean()


class ConsultaTests(Base):
    def test_necesita_telefono_o_email(self):
        with self.assertRaises(ValidationError):
            Consulta(tipo="contacto", nombre="Ana", mensaje="Hola").full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Consulta.objects.create(tipo="contacto", nombre="Ana", mensaje="Hola")
        Consulta(tipo="contacto", nombre="Ana", mensaje="Hola", email="ana@example.com").full_clean()

    def test_marcar_respondida_guarda_quien_y_cuando(self):
        jefe = Usuario.objects.create_user("jefe", password="x")
        c = Consulta.objects.create(tipo="presupuesto", nombre="Ana", mensaje="Service", telefono="123")
        self.assertEqual(c.estado, Consulta.Estado.NUEVA)
        c.marcar(Consulta.Estado.RESPONDIDA, jefe)
        c.refresh_from_db()
        self.assertEqual((c.estado, c.respondida_por), (Consulta.Estado.RESPONDIDA, jefe))
        self.assertIsNotNone(c.respondida_el)


class EmpresaRedesTests(Base):
    def empresa(self, **kw):
        return Empresa(nombre="El Taller", **kw)

    def test_instagram_se_guarda_como_usuario(self):
        e = self.empresa(instagram="https://www.instagram.com/el.taller/")
        e.full_clean()
        self.assertEqual(e.instagram, "el.taller")

    def test_links_de_cada_red(self):
        self.empresa(facebook="https://www.facebook.com/eltaller", youtube="https://youtube.com/@eltaller",
                     mapa_url="https://maps.app.goo.gl/abc123").full_clean()
        for campo, valor in (("facebook", "https://example.com/x"), ("youtube", "https://vimeo.com/1"),
                             ("mapa_url", "https://example.com/mapa")):
            with self.assertRaises(ValidationError) as e:
                self.empresa(**{campo: valor}).full_clean()
            self.assertIn(campo, e.exception.message_dict)


class PermisosYAdminTests(Base):
    URL_CONTENIDO = "/admin/sitio/trabajo/"
    URL_CONSULTAS = "/admin/sitio/consulta/"

    def usuario(self, nombre, grupo):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=True)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def test_permisos_por_rol(self):
        gerente = self.usuario("ger", "gerente")
        adm = self.usuario("adm", "administracion")
        jefe = self.usuario("jefe", "jefe")
        mec = self.usuario("mec", "mecanico")
        for u in (gerente, adm):
            self.assertTrue(u.has_perms(["sitio.change_trabajo", "sitio.add_publicacion", "sitio.delete_consulta"]))
        self.assertTrue(jefe.has_perms(["sitio.view_consulta", "sitio.change_consulta"]))
        self.assertFalse(jefe.has_perm("sitio.change_trabajo"))
        self.assertFalse(jefe.has_perm("sitio.delete_consulta"))
        self.assertFalse(any(p.startswith("sitio.") for p in mec.get_all_permissions()))

    def test_admin_segun_rol(self):
        def codigos(user):
            self.client.force_login(user)
            return [self.client.get(u).status_code for u in (self.URL_CONTENIDO, self.URL_CONSULTAS)]

        self.assertEqual(codigos(self.usuario("adm", "administracion")), [200, 200])
        self.assertEqual(codigos(self.usuario("jefe", "jefe")), [403, 200])
        self.assertEqual(codigos(self.usuario("mec", "mecanico")), [403, 403])

    def test_consultas_no_se_crean_desde_el_admin(self):
        self.client.force_login(self.usuario("ger", "gerente"))
        self.assertEqual(self.client.get(self.URL_CONSULTAS + "add/").status_code, 403)

    def test_cargar_trabajo_con_galeria_desde_el_admin(self):
        self.client.force_login(self.usuario("adm", "administracion"))
        r = self.client.post("/admin/sitio/trabajo/add/", {
            "tipo": "clasico", "titulo": "Torino 380W", "auto": "IKA Torino 1970", "resumen": "Restauración.",
            "descripcion": "", "video_url": VIDEO_OK, "fecha": "2026-10-01", "publicado": "on", "slug": "",
            "fotos-TOTAL_FORMS": "1", "fotos-INITIAL_FORMS": "0", "fotos-MIN_NUM_FORMS": "0",
            "fotos-MAX_NUM_FORMS": "1000",
            "fotos-0-imagen": jpg_con_metadatos(800, 600), "fotos-0-epigrafe": "Así llegó",
            "fotos-0-etapa": "antes", "fotos-0-orden": "0",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].errors)
        t = Trabajo.objects.get(slug="torino-380w")
        self.assertEqual((t.parte, t.fotos.count(), t.publicado), ("prepa", 1, True))

    def test_accion_publicar(self):
        self.client.force_login(self.usuario("adm", "administracion"))
        t = self.trabajo()
        self.client.post(self.URL_CONTENIDO, {"action": "publicar", "_selected_action": [t.pk]})
        t.refresh_from_db()
        self.assertTrue(t.publicado)
