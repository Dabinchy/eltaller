import shutil
import tempfile
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from core.models import Usuario

from . import servicios
from .models import Asociacion, Membresia, PerfilPiloto
from .models_contenido import Archivo, Auto, PilotoAuto

PRIVADO = tempfile.mkdtemp(prefix="privado_contenido_test_")


def foto():
    salida = BytesIO()
    Image.new("RGB", (300, 200), "blue").save(salida, format="JPEG")
    return SimpleUploadedFile("foto.jpg", salida.getvalue(), content_type="image/jpeg")


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
        self.juan = self.piloto("juan")
        self.ana = self.piloto("ana")

    def piloto(self, nombre):
        u = Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL)
        servicios.aprobar_membresia(Membresia.objects.create(usuario=u, asociacion=self.asoc), self.gerente)
        return PerfilPiloto.objects.create(usuario=u, nombre_publico=nombre.title())

    def crear_auto(self):
        self.client.force_login(self.juan.usuario)
        self.client.post("/portal/autos/nuevo/", {"marca": "Ford", "modelo": "Falcon", "numero_competicion": "7"})
        return Auto.objects.get()


class AutosTests(Base):
    def test_crear_editar_y_publicar(self):
        a = self.crear_auto()
        self.assertEqual(a.principal, self.juan)
        self.client.post(f"/portal/autos/{a.pk}/editar/", {"marca": "Ford", "modelo": "Falcon", "categoria": "TC Pista"})
        self.client.post(f"/portal/autos/{a.pk}/publicar/", {"publicar": "1"})
        a.refresh_from_db()
        self.assertEqual((a.categoria, a.publicado, a.aprobado), ("TC Pista", True, False))
        self.assertContains(self.client.get(f"/portal/autos/{a.pk}/"), "esperando aprobación")

    def test_invitacion_completa(self):
        a = self.crear_auto()
        r = self.client.post(f"/portal/autos/{a.pk}/invitar/", {"piloto": "@ana"}, follow=True)
        self.assertContains(r, "Invitación enviada")
        self.client.force_login(self.ana.usuario)
        self.assertContains(self.client.get("/portal/autos/"), "te invita a ser piloto")
        inv = PilotoAuto.objects.get(piloto=self.ana)
        self.client.post(f"/portal/invitaciones/{inv.pk}/", {"aceptar": "1"})
        self.assertEqual(self.client.get(f"/portal/autos/{a.pk}/").status_code, 200)
        r = self.client.get(f"/portal/autos/{a.pk}/")
        self.assertNotContains(r, 'action="/portal/autos/%d/editar/"' % a.pk)  # sólo el principal edita
        self.client.post(f"/portal/autos/{a.pk}/pilotos/{self.ana.pk}/quitar/")  # salir
        self.assertEqual(self.client.get(f"/portal/autos/{a.pk}/").status_code, 404)

    def test_invitar_a_alguien_que_no_existe(self):
        a = self.crear_auto()
        r = self.client.post(f"/portal/autos/{a.pk}/invitar/", {"piloto": "fantasma"}, follow=True)
        self.assertContains(r, "No encontramos un piloto aprobado")

    def test_auto_ajeno_no_existe_para_mi(self):
        a = self.crear_auto()
        self.client.force_login(self.ana.usuario)
        self.assertEqual(self.client.get(f"/portal/autos/{a.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/portal/autos/{a.pk}/publicar/", {"publicar": "1"}).status_code, 404)

    def test_transferir(self):
        a = self.crear_auto()
        PilotoAuto.objects.create(auto=a, piloto=self.ana, estado=PilotoAuto.Estado.ACEPTADA)
        self.client.post(f"/portal/autos/{a.pk}/pilotos/{self.ana.pk}/principal/")
        self.assertEqual(a.principal, self.ana)


class ArchivosTests(Base):
    def test_subir_foto_portada_y_borrar(self):
        a = self.crear_auto()
        self.client.post(f"/portal/autos/{a.pk}/archivos/", {
            "tipo": "FOTO", "titulo": "Largada", "visibilidad": "PUBLICO", "archivo": foto(),
        })
        f = Archivo.objects.get()
        self.assertEqual((f.auto, f.aprobado), (a, False))
        self.client.post(f"/portal/autos/{a.pk}/portada/", {"archivo": f.pk})
        a.refresh_from_db()
        self.assertEqual(a.portada, f)
        self.assertContains(self.client.get(f"/portal/autos/{a.pk}/"), "en revisión")
        self.client.post(f"/portal/archivos/{f.pk}/borrar/", {"volver": f"/portal/autos/{a.pk}/"})
        self.assertFalse(Archivo.objects.exists())

    def test_video_por_link_y_visibilidad(self):
        self.client.force_login(self.juan.usuario)
        self.client.post("/portal/archivos/subir/", {
            "tipo": "VIDEO", "titulo": "Onboard", "visibilidad": "PRIVADO", "url_video": "https://youtu.be/dQw4w9WgXcQ",
        })
        v = Archivo.objects.get()
        self.assertEqual(v.piloto, self.juan)
        self.assertContains(self.client.get("/portal/archivos/"), "youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.client.post(f"/portal/archivos/{v.pk}/visibilidad/", {"visibilidad": "PUBLICO"})
        v.refresh_from_db()
        self.assertEqual(v.visibilidad, Archivo.Visibilidad.PUBLICO)

    def test_formato_invalido_avisa(self):
        self.client.force_login(self.juan.usuario)
        r = self.client.post("/portal/archivos/subir/", {
            "tipo": "SETUP", "titulo": "x", "visibilidad": "PRIVADO",
            "archivo": SimpleUploadedFile("virus.exe", b"MZ"),
        }, follow=True)
        self.assertContains(r, "Formato no permitido")

    def test_no_se_toca_archivo_ajeno(self):
        self.client.force_login(self.juan.usuario)
        self.client.post("/portal/archivos/subir/", {"tipo": "SETUP", "titulo": "Setup", "visibilidad": "PRIVADO",
                                                     "archivo": SimpleUploadedFile("s.pdf", b"%PDF")})
        s = Archivo.objects.get()
        self.client.force_login(self.ana.usuario)
        self.assertEqual(self.client.post(f"/portal/archivos/{s.pk}/visibilidad/", {"visibilidad": "PUBLICO"}).status_code, 404)
        self.client.post(f"/portal/archivos/{s.pk}/borrar/")
        self.assertTrue(Archivo.objects.filter(pk=s.pk).exists())

    def test_volver_solo_a_direcciones_internas(self):
        self.client.force_login(self.juan.usuario)
        self.client.post("/portal/archivos/subir/", {"tipo": "SETUP", "titulo": "Setup", "visibilidad": "PRIVADO",
                                                     "archivo": SimpleUploadedFile("s.pdf", b"%PDF")})
        s = Archivo.objects.get()
        r = self.client.post(f"/portal/archivos/{s.pk}/visibilidad/", {"visibilidad": "PILOTO", "volver": "https://malo.com/"})
        self.assertRedirects(r, "/portal/archivos/")
