"""Contenido del sitio público desde el panel (/panel/sitio/): permisos, altas, publicación, galería y consultas."""
import atexit
import shutil
import tempfile
from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from core.models import Usuario
from sitio.models import Consulta, FotoTrabajo, Portada, Publicacion, Servicio, Testimonio, Trabajo

MEDIA = tempfile.mkdtemp(prefix="media_panel_sitio_test_")
# Se borra al terminar la corrida (no al terminar cada clase: en paralelo la comparten).
atexit.register(shutil.rmtree, MEDIA, ignore_errors=True)


def jpg(nombre="foto.jpg", color="blue") -> SimpleUploadedFile:
    salida = BytesIO()
    Image.new("RGB", (800, 600), color).save(salida, format="JPEG")
    return SimpleUploadedFile(nombre, salida.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA, ALLOWED_HOSTS=["testserver"])
class Base(TestCase):
    def setUp(self):
        self.gerente = self.personal("gerente", "gerente")
        self.adm = self.personal("adm", "administracion")
        self.jefe = self.personal("jefe", "jefe")
        self.mec = self.personal("mec", "mecanico")

    def personal(self, nombre, grupo):
        u = Usuario.objects.create_user(nombre, password="x")
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def trabajo(self, **kw):
        datos = {"titulo": "Falcon Sprint", "resumen": "Restauración completa."}
        datos.update(kw)
        return Trabajo.objects.create(**datos)


class PermisosTests(Base):
    def test_mecanico_no_entra(self):
        self.client.force_login(self.mec)
        for url in ("/panel/sitio/", "/panel/sitio/novedades/", "/panel/sitio/consultas/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_jefe_solo_consultas(self):
        self.client.force_login(self.jefe)
        self.assertEqual(self.client.get("/panel/sitio/consultas/").status_code, 200)
        self.assertEqual(self.client.get("/panel/sitio/").status_code, 200)
        for url in ("/panel/sitio/novedades/", "/panel/sitio/trabajos/nuevo/", "/panel/sitio/servicios/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        t = self.trabajo()
        self.assertEqual(self.client.post(f"/panel/sitio/trabajos/{t.pk}/publicar/", {"valor": "1"}).status_code, 403)
        menu = self.client.get("/panel/").content.decode()
        self.assertIn("/panel/sitio/consultas/", menu)
        self.assertNotIn("/panel/sitio/novedades/", menu)

    def test_administracion_ve_todo_en_el_menu(self):
        self.client.force_login(self.adm)
        menu = self.client.get("/panel/").content.decode()
        for url in ("/panel/sitio/consultas/", "/panel/sitio/novedades/", "/panel/sitio/trabajos/",
                    "/panel/sitio/servicios/", "/panel/sitio/testimonios/", "/panel/sitio/portadas/"):
            self.assertIn(url, menu)
        self.assertNotIn("/admin/sitio/consulta/", menu)

    def test_tipo_invalido_y_portal(self):
        self.client.force_login(self.adm)
        self.assertEqual(self.client.post("/panel/sitio/usuarios/1/borrar/").status_code, 403)
        self.client.logout()
        self.assertRedirects(self.client.get("/panel/sitio/"), "/ingresar/?next=/panel/sitio/")


class NovedadesTests(Base):
    def datos(self, **kw):
        d = {"parte": "taller", "titulo": "Nuevo elevador", "resumen": "Sumamos un elevador.", "cuerpo": "Texto.",
             "video_url": "", "fecha": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "publicada": "on"}
        d.update(kw)
        return d

    def test_crear_con_foto_editar_y_quitar_foto(self):
        self.client.force_login(self.adm)
        r = self.client.post("/panel/sitio/novedades/nueva/", self.datos(portada=jpg()))
        self.assertRedirects(r, "/panel/sitio/novedades/")
        n = Publicacion.objects.get()
        self.assertTrue(n.publicada and n.portada and n.portada_miniatura)
        self.assertEqual(list(Publicacion.objects.publicadas()), [n])
        # La lista muestra la novedad y su estado
        self.assertContains(self.client.get("/panel/sitio/novedades/?estado=publicadas"), "Nuevo elevador")
        # Editar: quitar la foto y cambiar el título
        r = self.client.post(f"/panel/sitio/novedades/{n.pk}/", self.datos(titulo="Elevador nuevo", quitar_portada="on"))
        n.refresh_from_db()
        self.assertEqual(n.titulo, "Elevador nuevo")
        self.assertFalse(n.portada)
        self.assertFalse(n.portada_miniatura)

    def test_validaciones_del_modelo(self):
        self.client.force_login(self.adm)
        r = self.client.post("/panel/sitio/novedades/nueva/", self.datos(video_url="https://example.com/v"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "YouTube o Vimeo")
        self.assertFalse(Publicacion.objects.exists())

    def test_publicar_programada_y_ocultar(self):
        self.client.force_login(self.gerente)
        n = Publicacion.objects.create(titulo="Feria", resumen="x", fecha=timezone.now() + timedelta(days=3))
        r = self.client.post(f"/panel/sitio/novedades/{n.pk}/publicar/", {"valor": "1"}, follow=True)
        self.assertContains(r, "queda programado")
        n.refresh_from_db()
        self.assertTrue(n.publicada)
        self.assertFalse(Publicacion.objects.publicadas().exists())  # todavía no es la fecha
        self.assertContains(self.client.get("/panel/sitio/novedades/?estado=programadas"), "Feria")
        self.client.post(f"/panel/sitio/novedades/{n.pk}/publicar/", {"valor": "0"})
        n.refresh_from_db()
        self.assertFalse(n.publicada)

    def test_next_externo_se_ignora(self):
        self.client.force_login(self.adm)
        n = Publicacion.objects.create(titulo="X", resumen="x")
        r = self.client.post(f"/panel/sitio/novedades/{n.pk}/publicar/", {"valor": "1", "next": "https://malo.com/"})
        self.assertRedirects(r, "/panel/sitio/novedades/")
        r = self.client.post(f"/panel/sitio/novedades/{n.pk}/publicar/", {"valor": "0", "next": "/panel/sitio/"})
        self.assertRedirects(r, "/panel/sitio/")

    def test_borrar(self):
        self.client.force_login(self.adm)
        n = Publicacion.objects.create(titulo="Vieja", resumen="x")
        self.assertEqual(self.client.get(f"/panel/sitio/novedades/{n.pk}/borrar/").status_code, 405)
        self.client.post(f"/panel/sitio/novedades/{n.pk}/borrar/")
        self.assertFalse(Publicacion.objects.exists())


class TrabajosTests(Base):
    def test_crear_y_galeria(self):
        self.client.force_login(self.adm)
        r = self.client.post("/panel/sitio/trabajos/nuevo/", {
            "tipo": "clasico", "titulo": "Torino 380W", "auto": "IKA Torino", "resumen": "Restauración.",
            "descripcion": "", "video_url": "", "fecha": "2026-10-01", "publicado": "on",
        })
        t = Trabajo.objects.get()
        self.assertRedirects(r, f"/panel/sitio/trabajos/{t.pk}/")
        self.assertEqual(t.parte, "prepa")

        # Varias fotos de una vez, con etapa
        r = self.client.post(f"/panel/sitio/trabajos/{t.pk}/fotos/",
                             {"fotos": [jpg("a.jpg"), jpg("b.jpg", "red"), jpg("c.jpg", "green")], "etapa": "antes"},
                             follow=True)
        self.assertContains(r, "3 fotos agregadas")
        fotos = list(t.fotos.all())
        self.assertEqual([f.orden for f in fotos], [0, 1, 2])
        self.assertTrue(all(f.etapa == "antes" and f.miniatura for f in fotos))

        # Mover la última al principio
        self.client.post(f"/panel/sitio/fotos/{fotos[2].pk}/", {"accion": "subir"})
        self.client.post(f"/panel/sitio/fotos/{fotos[2].pk}/", {"accion": "subir"})
        self.assertEqual([f.pk for f in t.fotos.all()], [fotos[2].pk, fotos[0].pk, fotos[1].pk])

        # Epígrafe y etapa
        p = f"f{fotos[0].pk}"
        self.client.post(f"/panel/sitio/fotos/{fotos[0].pk}/",
                         {"accion": "guardar", f"{p}-epigrafe": "Así llegó", f"{p}-etapa": "proceso"})
        fotos[0].refresh_from_db()
        self.assertEqual((fotos[0].epigrafe, fotos[0].etapa), ("Así llegó", "proceso"))

        # Usar como portada
        self.client.post(f"/panel/sitio/fotos/{fotos[1].pk}/", {"accion": "portada"})
        t.refresh_from_db()
        self.assertTrue(t.portada and t.portada_miniatura)

        # Borrar una foto
        self.client.post(f"/panel/sitio/fotos/{fotos[1].pk}/", {"accion": "borrar"})
        self.assertEqual(t.fotos.count(), 2)

        # La ficha se muestra con la galería
        self.assertContains(self.client.get(f"/panel/sitio/trabajos/{t.pk}/"), "Así llegó")

    def test_subir_archivo_que_no_es_foto(self):
        self.client.force_login(self.adm)
        t = self.trabajo()
        txt = SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")
        r = self.client.post(f"/panel/sitio/trabajos/{t.pk}/fotos/", {"fotos": [txt]}, follow=True)
        self.assertContains(r, "virus.exe")
        self.assertFalse(FotoTrabajo.objects.exists())

    def test_destacar_y_lista(self):
        self.client.force_login(self.adm)
        t = self.trabajo(publicado=True)
        self.client.post(f"/panel/sitio/trabajos/{t.pk}/destacar/", {"valor": "1"})
        t.refresh_from_db()
        self.assertTrue(t.destacado)
        r = self.client.get("/panel/sitio/trabajos/?estado=destacados")
        self.assertContains(r, "Falcon Sprint")
        self.assertNotContains(self.client.get("/panel/sitio/trabajos/?estado=borradores"), "Falcon Sprint")

    def test_borrar_trabajo_con_fotos(self):
        self.client.force_login(self.gerente)
        t = self.trabajo()
        FotoTrabajo.objects.create(trabajo=t, imagen=jpg())
        self.client.post(f"/panel/sitio/trabajos/{t.pk}/borrar/")
        self.assertFalse(Trabajo.objects.exists())
        self.assertFalse(FotoTrabajo.objects.exists())


class ServiciosTestimoniosTests(Base):
    def test_servicio_prepa_necesita_seccion_y_orden(self):
        self.client.force_login(self.adm)
        datos = {"parte": "prepa", "seccion": "", "titulo": "Jaulas", "icono": "bi-shield-check",
                 "resumen": "Jaulas homologadas.", "descripcion": ""}
        r = self.client.post("/panel/sitio/servicios/nuevo/", datos)
        self.assertContains(r, "Elegí en qué sección de El Prepa aparece")
        datos["seccion"] = "competicion"
        self.client.post("/panel/sitio/servicios/nuevo/", datos)
        self.client.post("/panel/sitio/servicios/nuevo/", {**datos, "titulo": "Motores"})
        a, b = Servicio.objects.order_by("orden")
        self.assertEqual((a.titulo, b.titulo, a.orden, b.orden), ("Jaulas", "Motores", 0, 1))
        self.client.post(f"/panel/sitio/servicios/{b.pk}/mover/", {"direccion": "subir"})
        self.assertEqual(list(Servicio.objects.order_by("orden").values_list("titulo", flat=True)), ["Motores", "Jaulas"])
        # Lista agrupada
        self.assertContains(self.client.get("/panel/sitio/servicios/"), "El Prepa · Competición")

    def test_testimonio_crear_publicar_mover(self):
        self.client.force_login(self.adm)
        for nombre in ("Ana", "Beto"):
            self.client.post("/panel/sitio/testimonios/nuevo/", {"parte": "taller", "nombre": nombre, "detalle": "",
                                                                  "texto": "Excelente atención."})
        ana, beto = Testimonio.objects.order_by("orden")
        self.assertFalse(ana.publicado)
        self.client.post(f"/panel/sitio/testimonios/{ana.pk}/publicar/", {"valor": "1"})
        self.client.post(f"/panel/sitio/testimonios/{ana.pk}/mover/", {"direccion": "bajar"})
        ana.refresh_from_db()
        self.assertTrue(ana.publicado)
        self.assertEqual(list(Testimonio.objects.order_by("orden").values_list("nombre", flat=True)), ["Beto", "Ana"])
        # mover no aplica a novedades
        n = Publicacion.objects.create(titulo="X", resumen="x")
        self.assertEqual(self.client.post(f"/panel/sitio/novedades/{n.pk}/mover/").status_code, 403)


class PortadasTests(Base):
    def test_personalizar_y_editar_portada(self):
        self.client.force_login(self.adm)
        self.assertContains(self.client.get("/panel/sitio/portadas/"), "Personalizar")
        self.client.post("/panel/sitio/portadas/prepa/", {"titulo": "Preparamos tu auto", "subtitulo": "Pista y calle.",
                                                          "video_url": "", "imagen": jpg()})
        p = Portada.objects.get()
        self.assertEqual((p.parte, p.titulo), ("prepa", "Preparamos tu auto"))
        self.assertTrue(p.imagen)
        self.client.post("/panel/sitio/portadas/prepa/", {"titulo": "Otro", "subtitulo": "", "video_url": ""})
        p.refresh_from_db()
        self.assertEqual(p.titulo, "Otro")
        self.assertTrue(p.imagen)  # sin "quitar", la foto queda
        self.assertContains(self.client.get("/"), "Mecánica")  # la del taller sigue por defecto
        self.assertEqual(self.client.get("/panel/sitio/portadas/otra/").status_code, 403)


class ConsultasTests(Base):
    def setUp(self):
        super().setUp()
        self.c = Consulta.objects.create(tipo="presupuesto", nombre="Marcela", telefono="2944 55-1234",
                                         mensaje="Ruido en el tren delantero.")
        Consulta.objects.create(tipo="contacto", nombre="Viejo", email="a@b.com", mensaje="x",
                                estado=Consulta.Estado.ARCHIVADA)

    def test_bandeja_y_detalle(self):
        self.client.force_login(self.jefe)
        r = self.client.get("/panel/sitio/consultas/")
        self.assertContains(r, "Marcela")
        self.assertNotContains(r, "Viejo")  # por defecto, sólo las nuevas
        self.assertContains(self.client.get("/panel/sitio/consultas/?estado=archivada"), "Viejo")
        r = self.client.get(f"/panel/sitio/consultas/{self.c.pk}/")
        self.assertContains(r, "https://wa.me/5492944551234?text=")
        self.assertContains(r, 'href="tel:2944551234"')

    def test_jefe_responde_pero_no_borra(self):
        self.client.force_login(self.jefe)
        self.client.post(f"/panel/sitio/consultas/{self.c.pk}/", {"notas": "Le pasé precio.", "estado": "respondida"})
        self.c.refresh_from_db()
        self.assertEqual(self.c.estado, "respondida")
        self.assertEqual(self.c.respondida_por, self.jefe)
        self.assertEqual(self.c.notas, "Le pasé precio.")
        self.assertEqual(self.client.post(f"/panel/sitio/consultas/{self.c.pk}/borrar/").status_code, 403)
        self.client.force_login(self.gerente)
        self.client.post(f"/panel/sitio/consultas/{self.c.pk}/borrar/")
        self.assertFalse(Consulta.objects.filter(pk=self.c.pk).exists())

    def test_inicio_del_panel_lleva_a_la_bandeja(self):
        self.client.force_login(self.jefe)
        r = self.client.get("/panel/")
        self.assertContains(r, 'href="/panel/sitio/consultas/"')
