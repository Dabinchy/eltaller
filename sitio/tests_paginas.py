"""
Páginas públicas que completan el sitio (Fase 3 del frontend): novedades, El Prepa (secciones,
proyectos y "Contanos tu proyecto"), vista previa de borradores y herramientas del personal
(barra "Editar esta página" y lápices que llevan al panel y vuelven).
"""
import atexit
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Usuario

from .models import Consulta, Portada, Publicacion, Servicio, Testimonio, Trabajo

MEDIA = tempfile.mkdtemp(prefix="media_sitio_paginas_test_")
# Se borra al terminar la corrida (no al terminar cada clase: en paralelo la comparten).
atexit.register(shutil.rmtree, MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=MEDIA, ALLOWED_HOSTS=["testserver"])
class Base(TestCase):
    def setUp(self):
        cache.clear()

    def personal(self, nombre, grupo):
        u = Usuario.objects.create_user(nombre, password="x")
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def novedad(self, **kw):
        datos = {"titulo": "Nuevo elevador", "resumen": "Sumamos un elevador.", "publicada": True}
        datos.update(kw)
        return Publicacion.objects.create(**datos)

    def trabajo(self, **kw):
        datos = {"titulo": "Falcon Sprint", "resumen": "Restauración completa.", "publicado": True}
        datos.update(kw)
        return Trabajo.objects.create(**datos)


class NovedadesTests(Base):
    def test_lista_solo_publicadas_y_filtro_por_parte(self):
        self.novedad()
        self.novedad(titulo="Calendario 2027", parte="campeonatos")
        self.novedad(titulo="Borrador secreto", publicada=False)
        self.novedad(titulo="Programada", fecha=timezone.now() + timedelta(days=2))
        r = self.client.get("/publicaciones/")
        self.assertContains(r, "Nuevo elevador")
        self.assertContains(r, "Calendario 2027")
        self.assertNotContains(r, "Borrador secreto")
        self.assertNotContains(r, "Programada")
        r = self.client.get("/publicaciones/?parte=campeonatos")
        self.assertContains(r, "Calendario 2027")
        self.assertNotContains(r, "Nuevo elevador")
        self.assertContains(r, 'data-parte="campeonatos">')   # con el encabezado de Campeonatos

    def test_detalle_con_el_encabezado_de_su_parte(self):
        n = self.novedad(titulo="Taller de setup", parte="prepa", cuerpo="Primer párrafo.\n\nSegundo.")
        self.novedad(titulo="Otra de El Prepa", parte="prepa")
        self.novedad(titulo="Una de El Taller", parte="taller")
        r = self.client.get(f"/publicaciones/{n.slug}/")
        self.assertContains(r, '<body class="cc-app sitio d-flex flex-column min-vh-100" data-parte="prepa">')
        self.assertContains(r, "<p>Segundo.</p>", html=True)
        self.assertContains(r, "Otra de El Prepa")          # más novedades de la misma parte
        self.assertNotContains(r, "Una de El Taller")
        self.assertContains(r, 'href="/publicaciones/?parte=prepa"')

    def test_menu_de_cada_parte_lleva_a_sus_novedades(self):
        self.assertContains(self.client.get("/prepa/"), 'href="/publicaciones/?parte=prepa"')
        self.assertContains(self.client.get("/campeonatos/"), 'href="/publicaciones/?parte=campeonatos"')

    def test_portadas_muestran_las_ultimas(self):
        self.novedad(titulo="Novedad del taller")
        self.novedad(titulo="Novedad del prepa", parte="prepa")
        self.assertContains(self.client.get("/"), "Novedad del taller")
        self.assertNotContains(self.client.get("/"), "Novedad del prepa")
        self.assertContains(self.client.get("/prepa/"), "Novedad del prepa")


class VistaPreviaTests(Base):
    def test_borrador_y_programada_solo_para_el_personal(self):
        borrador = self.novedad(titulo="Borrador", publicada=False)
        programada = self.novedad(titulo="Programada", fecha=timezone.now() + timedelta(days=2))
        trabajo = self.trabajo(publicado=False)
        urls = (f"/publicaciones/{borrador.slug}/", f"/publicaciones/{programada.slug}/", f"/trabajos/{trabajo.slug}/")
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404, url)
        # Un mecánico tampoco
        self.client.force_login(self.personal("mec", "mecanico"))
        self.assertEqual(self.client.get(urls[0]).status_code, 404)
        # Administración sí, con el aviso y sin indexar
        self.client.force_login(self.personal("adm", "administracion"))
        r = self.client.get(urls[0])
        self.assertContains(r, "Vista previa.")
        self.assertContains(r, '<meta name="robots" content="noindex">')
        self.assertContains(self.client.get(urls[1]), "Programada: se ve en la web desde el")
        self.assertContains(self.client.get(urls[2]), "Borrador: todavía no se ve en la web.")

    def test_panel_ofrece_vista_previa_o_ver_en_la_web(self):
        self.client.force_login(self.personal("adm", "administracion"))
        t = self.trabajo(publicado=False)
        self.assertContains(self.client.get(f"/panel/sitio/trabajos/{t.pk}/"), "Vista previa")
        t.publicado = True
        t.save()
        r = self.client.get(f"/panel/sitio/trabajos/{t.pk}/")
        self.assertContains(r, "Ver en la web")
        self.assertContains(r, f'href="/trabajos/{t.slug}/"')


class PrepaTests(Base):
    def test_seccion_con_sus_servicios_y_proyectos(self):
        Servicio.objects.create(parte="prepa", seccion="competicion", titulo="Jaulas homologadas", resumen="x", publicado=True)
        Servicio.objects.create(parte="prepa", seccion="clasicos", titulo="Tapicería de época", resumen="x", publicado=True)
        self.trabajo(titulo="Uno de pista", tipo="competicion")
        self.trabajo(titulo="Torino restaurado", tipo="clasico")
        r = self.client.get("/prepa/competicion/")
        self.assertContains(r, "Jaulas homologadas")
        self.assertContains(r, "Uno de pista")
        self.assertNotContains(r, "Tapicería de época")
        self.assertNotContains(r, "Torino restaurado")
        self.assertContains(r, 'href="/prepa/proyectos/?tipo=competicion"')
        # Sin servicios cargados: textos por defecto
        self.assertContains(self.client.get("/prepa/personalizacion/"), "Potencia")

    def test_proyectos_lista_filtro_y_detalle(self):
        pista = self.trabajo(titulo="Uno de pista", tipo="competicion")
        self.trabajo(titulo="Torino restaurado", tipo="clasico")
        calle = self.trabajo(titulo="Gol de calle", tipo="calle")
        r = self.client.get("/prepa/proyectos/")
        self.assertContains(r, "Uno de pista")
        self.assertContains(r, "Torino restaurado")
        self.assertNotContains(r, "Gol de calle")   # los de calle son de El Taller
        r = self.client.get("/prepa/proyectos/?tipo=clasico")
        self.assertNotContains(r, "Uno de pista")
        r = self.client.get(f"/prepa/proyectos/{pista.slug}/")
        self.assertContains(r, "Contanos tu proyecto")
        self.assertContains(r, 'href="/prepa/proyectos/"')
        # Cada uno en su parte
        self.assertEqual(self.client.get(f"/prepa/proyectos/{calle.slug}/").status_code, 404)
        self.assertEqual(self.client.get(f"/trabajos/{pista.slug}/").status_code, 404)

    def test_portada_con_contenido_del_panel(self):
        Portada.objects.create(parte="prepa", titulo="Preparamos tu auto", subtitulo="Pista, calle y clásicos.")
        Testimonio.objects.create(parte="prepa", nombre="Juan P.", texto="Impecable.", publicado=True)
        self.trabajo(titulo="Uno de pista", tipo="competicion", destacado=True)
        r = self.client.get("/prepa/")
        self.assertContains(r, "Preparamos tu auto")
        self.assertContains(r, "Pista, calle y clásicos.")
        self.assertContains(r, "Juan P.")
        self.assertContains(r, "Uno de pista")

    def test_contanos_tu_proyecto(self):
        r = self.client.post("/prepa/consulta/", {"nombre": "Lucas", "telefono": "2944123456",
                                                  "vehiculo": "Clio", "mensaje": "Quiero correr regularidad."})
        self.assertRedirects(r, "/consulta-enviada/proyecto/")
        c = Consulta.objects.get()
        self.assertEqual((c.tipo, c.parte, c.vehiculo), ("proyecto", "prepa", "Clio"))
        r = self.client.get("/consulta-enviada/proyecto/")
        self.assertContains(r, 'data-parte="prepa">')
        self.assertContains(r, "Volver a El Prepa")


class HerramientasPersonalTests(Base):
    def test_barra_y_lapices_solo_para_quien_edita(self):
        t = self.trabajo(destacado=True)
        Testimonio.objects.create(nombre="Marcela", texto="Excelente.", publicado=True)
        r = self.client.get("/")
        self.assertNotContains(r, "Estás viendo el sitio como personal")
        self.assertNotContains(r, "sitio-lapiz")
        # El jefe responde consultas pero no edita contenido: sin barra
        self.client.force_login(self.personal("jefe", "jefe"))
        self.assertNotContains(self.client.get("/"), "Estás viendo el sitio como personal")
        # Administración: barra con "Editar la portada" y lápices en trabajos y testimonios
        self.client.force_login(self.personal("adm", "administracion"))
        r = self.client.get("/")
        self.assertContains(r, "Estás viendo el sitio como personal")
        self.assertContains(r, 'href="/panel/sitio/portadas/taller/?next=/"')
        self.assertContains(r, f'href="/panel/sitio/trabajos/{t.pk}/editar/?next=/"')
        self.assertContains(r, "Editar este testimonio")
        r = self.client.get(f"/trabajos/{t.slug}/")
        self.assertContains(r, f'/panel/sitio/trabajos/{t.pk}/editar/?next=/trabajos/{t.slug}/')

    def test_editar_desde_el_sitio_vuelve_a_la_pagina(self):
        self.client.force_login(self.personal("adm", "administracion"))
        t = self.trabajo()
        url = f"/panel/sitio/trabajos/{t.pk}/editar/?next=/trabajos/{t.slug}/"
        r = self.client.get(url)
        self.assertContains(r, f'href="/trabajos/{t.slug}/">Cancelar')
        r = self.client.post(url, {
            "tipo": "calle", "titulo": "Falcon Sprint 1978", "auto": "", "resumen": "Restauración completa.",
            "descripcion": "", "video_url": "", "fecha": "2026-10-01", "publicado": "on",
        })
        self.assertRedirects(r, f"/trabajos/{t.slug}/")
        t.refresh_from_db()
        self.assertEqual(t.titulo, "Falcon Sprint 1978")
        # Un next de otro sitio no se sigue
        r = self.client.post("/panel/sitio/portadas/taller/?next=https://malo.com/",
                             {"titulo": "Hola", "subtitulo": "", "video_url": ""})
        self.assertRedirects(r, "/panel/sitio/portadas/")

    def test_cliente_del_portal_no_ve_herramientas(self):
        u = Usuario.objects.create_user("piloto", password="x", tipo=Usuario.Tipo.PORTAL)
        self.client.force_login(u)
        self.assertNotContains(self.client.get("/"), "Estás viendo el sitio como personal")
