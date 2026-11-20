"""Páginas de El Taller (Parte 2 del frontend): contenido, formularios anti-spam y consultas en el panel."""
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings

from core.models import Empresa, Usuario

from .models import Consulta, FotoTrabajo, Portada, Servicio, Testimonio, Trabajo
from .tests_contenido import MEDIA, jpg_con_metadatos

VIDEO = "https://youtu.be/dQw4w9WgXcQ"


@override_settings(ALLOWED_HOSTS=["testserver"], MEDIA_ROOT=MEDIA, SITIO_CONSULTAS_POR_IP_HORA=2)
class Base(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()


class PaginasTests(Base):
    def test_sin_contenido_se_ven_textos_por_defecto(self):
        r = self.client.get("/")
        self.assertContains(r, "Mecánica y mantenimiento")
        self.assertNotContains(r, "Trabajos recientes")
        self.assertNotContains(r, "Lo que dicen nuestros clientes")
        for url in ("/servicios/", "/trabajos/", "/presupuesto/", "/contacto/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_portada_con_contenido(self):
        Portada.objects.create(parte="taller", titulo="Tu auto en buenas manos", subtitulo="Desde 1985.",
                               imagen=jpg_con_metadatos(800, 400), video_url=VIDEO)
        Servicio.objects.create(titulo="Alineación y balanceo", resumen="Con equipo computarizado.", publicado=True)
        Servicio.objects.create(titulo="Servicio oculto", resumen="x")
        Trabajo.objects.create(titulo="Gol Trend", resumen="Distribución", publicado=True, destacado=True)
        Trabajo.objects.create(titulo="Proyecto de El Prepa", resumen="x", tipo="clasico", publicado=True)
        Testimonio.objects.create(nombre="Marcela G.", texto="Muy buena atención", publicado=True)
        Testimonio.objects.create(nombre="Prepa", texto="x", parte="prepa", publicado=True)

        r = self.client.get("/")
        self.assertContains(r, "Tu auto en buenas manos")
        self.assertContains(r, "sitio-hero-foto")
        self.assertContains(r, 'data-video="https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"')
        self.assertContains(r, "Alineación y balanceo")
        self.assertNotContains(r, "Servicio oculto")
        self.assertContains(r, "Gol Trend")
        self.assertNotContains(r, "Proyecto de El Prepa")   # es de El Prepa, no de El Taller
        self.assertContains(r, "Marcela G.")
        self.assertNotContains(r, ">Prepa<")

    def test_trabajo_con_galeria_y_sin_publicar(self):
        t = Trabajo.objects.create(titulo="Fiesta Kinetic", resumen="Embrague", publicado=True, video_url=VIDEO)
        FotoTrabajo.objects.create(trabajo=t, imagen=jpg_con_metadatos(600, 400), etapa="antes", epigrafe="Así llegó")
        FotoTrabajo.objects.create(trabajo=t, imagen=jpg_con_metadatos(600, 400), etapa="despues")
        r = self.client.get("/trabajos/fiesta-kinetic/")
        self.assertContains(r, "Así llegó")
        self.assertContains(r, ">Antes<")
        self.assertContains(r, ">Después<")
        self.assertContains(r, "data-galeria")
        self.assertContains(self.client.get("/trabajos/"), "Fiesta Kinetic")

        oculto = Trabajo.objects.create(titulo="Borrador", resumen="x")
        clasico = Trabajo.objects.create(titulo="Torino", resumen="x", tipo="clasico", publicado=True)
        self.assertEqual(self.client.get(f"/trabajos/{oculto.slug}/").status_code, 404)
        self.assertEqual(self.client.get(f"/trabajos/{clasico.slug}/").status_code, 404)  # es de El Prepa

    def test_contacto_y_whatsapp_con_datos_de_la_empresa(self):
        Empresa.objects.create(nombre="El Taller", whatsapp="+54 9 294 455-1234", direccion="Mitre 100",
                               mapa_url="https://maps.app.goo.gl/abc", instagram="el.taller")
        r = self.client.get("/contacto/")
        self.assertContains(r, "https://wa.me/5492944551234")
        self.assertContains(r, "Cómo llegar")
        self.assertContains(r, "https://www.instagram.com/el.taller/")
        self.assertContains(self.client.get("/"), 'class="sitio-wa"')
        self.assertNotContains(self.client.get("/campeonatos/"), 'class="sitio-wa"')


class FormulariosTests(Base):
    DATOS = {"nombre": "Ana", "telefono": "2944 123456", "email": "", "vehiculo": "Fiat 128",
             "mensaje": "Ruido al frenar", "web": ""}

    def test_presupuesto_crea_consulta(self):
        r = self.client.post("/presupuesto/", self.DATOS)
        self.assertRedirects(r, "/consulta-enviada/presupuesto/")
        c = Consulta.objects.get()
        self.assertEqual((c.tipo, c.parte, c.estado, c.vehiculo), ("presupuesto", "taller", "nueva", "Fiat 128"))
        self.assertContains(self.client.get(r["Location"]), "Recibimos tu consulta")

    def test_contacto_sin_vehiculo(self):
        datos = {**self.DATOS, "telefono": "", "email": "ana@example.com"}
        datos.pop("vehiculo")
        self.assertRedirects(self.client.post("/contacto/", datos), "/consulta-enviada/contacto/")
        self.assertEqual(Consulta.objects.get().tipo, "contacto")

    def test_necesita_telefono_o_email(self):
        r = self.client.post("/presupuesto/", {**self.DATOS, "telefono": ""})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Dejá un teléfono o un email")
        self.assertFalse(Consulta.objects.exists())

    def test_robot_no_guarda_nada(self):
        r = self.client.post("/presupuesto/", {**self.DATOS, "web": "http://spam.example"})
        self.assertRedirects(r, "/consulta-enviada/presupuesto/")   # se lo despide como si nada
        self.assertFalse(Consulta.objects.exists())

    def test_limite_por_conexion(self):
        for _ in range(2):
            self.client.post("/presupuesto/", self.DATOS)
        r = self.client.post("/presupuesto/", self.DATOS)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "muchas consultas")
        self.assertEqual(Consulta.objects.count(), 2)

    def test_gracias_de_un_tipo_que_no_existe(self):
        self.assertEqual(self.client.get("/consulta-enviada/otra-cosa/").status_code, 404)


class PanelTests(Base):
    def usuario(self, nombre, grupo, staff=True):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=staff)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def test_tarjeta_y_menu_de_consultas(self):
        Consulta.objects.create(tipo="presupuesto", nombre="Ana", mensaje="x", telefono="1")
        Consulta.objects.create(tipo="contacto", nombre="Beto", mensaje="x", telefono="2", estado="respondida")
        self.client.force_login(self.usuario("jefe", "jefe"))
        r = self.client.get("/panel/")
        self.assertContains(r, "Consultas nuevas del sitio")
        self.assertContains(r, 'href="/panel/sitio/consultas/"')  # la bandeja está en el panel, no en el admin
        self.assertContains(r, "Consultas del sitio")
        self.assertNotContains(r, "/admin/sitio/consulta/")

    def test_mecanico_no_ve_consultas(self):
        self.client.force_login(self.usuario("mec", "mecanico"))
        r = self.client.get("/panel/")
        self.assertNotContains(r, "Consultas nuevas del sitio")
        self.assertNotContains(r, "Consultas del sitio")
