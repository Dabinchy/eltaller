"""
Novedades escritas por los moderadores (/portal/moderacion/novedades/): cada uno sólo de las
asociaciones que modera, siempre en Campeonatos, nunca de El Taller ni de El Prepa.
"""
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone

from campeonatos.models import Campeonato
from core.models import Usuario
from sitio.models import Publicacion

from . import servicios
from .models import Asociacion, Membresia, RegistroModeracion

M = Membresia
A = RegistroModeracion.Accion


@override_settings(ALLOWED_HOSTS=["testserver"])
class NovedadesModeradorTests(TestCase):
    def setUp(self):
        self.gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="gerente"))
        self.asoc = Asociacion.objects.create(nombre="Pista Norte")
        self.otra = Asociacion.objects.create(nombre="Karting Sur")
        self.mod = Usuario.objects.create_user("mod", password="x", tipo=Usuario.Tipo.PORTAL, first_name="Laura")
        servicios.aprobar_membresia(
            M.objects.create(usuario=self.mod, asociacion=self.asoc, rol=M.Rol.MODERADOR), self.gerente)
        self.camp = Campeonato.objects.create(asociacion=self.asoc, nombre="Zonal", temporada=2026,
                                              estado=Campeonato.Estado.EN_CURSO)
        self.camp_ajeno = Campeonato.objects.create(asociacion=self.otra, nombre="Karting", temporada=2026)
        self.client.force_login(self.mod)

    def datos(self, **kw):
        d = {"asociacion": self.asoc.pk, "campeonato": "", "titulo": "Cambios en la tabla",
             "resumen": "Se corrigió la fecha 3.", "cuerpo": "", "video_url": "",
             "fecha": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "publicada": "on"}
        d.update(kw)
        return d

    def test_escribe_novedad_de_su_asociacion(self):
        r = self.client.post("/portal/moderacion/novedades/nueva/",
                             self.datos(campeonato=self.camp.pk, parte="taller"))   # "parte" se ignora
        self.assertRedirects(r, "/portal/moderacion/novedades/")
        n = Publicacion.objects.get()
        self.assertEqual((n.parte, n.asociacion, n.campeonato, n.autor), ("campeonatos", self.asoc, self.camp, self.mod))
        self.assertTrue(RegistroModeracion.objects.filter(accion=A.CREAR, actor=self.mod, asociacion=self.asoc).exists())
        # Se ve en el sitio: lista de la asociación, página de la asociación y del campeonato
        self.assertContains(self.client.get(f"/publicaciones/?asociacion={self.asoc.slug}"), "Cambios en la tabla")
        self.assertContains(self.client.get(f"/asociaciones/{self.asoc.slug}/"), "Cambios en la tabla")
        self.assertContains(self.client.get(f"/campeonatos/{self.camp.slug}/"), "Cambios en la tabla")
        r = self.client.get(f"/publicaciones/{n.slug}/")
        self.assertContains(r, 'data-parte="campeonatos">')
        self.assertContains(r, f'href="/asociaciones/{self.asoc.slug}/"')

    def test_no_puede_usar_otra_asociacion_ni_otro_campeonato(self):
        r = self.client.post("/portal/moderacion/novedades/nueva/", self.datos(asociacion=self.otra.pk))
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/portal/moderacion/novedades/nueva/", self.datos(campeonato=self.camp_ajeno.pk))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Publicacion.objects.exists())

    def test_solo_ve_y_toca_las_de_su_asociacion(self):
        propia = Publicacion.objects.create(parte="campeonatos", asociacion=self.asoc, titulo="Propia", resumen="x")
        ajena = Publicacion.objects.create(parte="campeonatos", asociacion=self.otra, titulo="Ajena", resumen="x")
        del_taller = Publicacion.objects.create(parte="taller", titulo="Del taller", resumen="x", publicada=True)
        general = Publicacion.objects.create(parte="campeonatos", titulo="General", resumen="x", publicada=True)
        r = self.client.get("/portal/moderacion/novedades/")
        self.assertContains(r, "Propia")
        for titulo in ("Ajena", "Del taller", "General"):
            self.assertNotContains(r, titulo)
        for n in (ajena, del_taller, general):
            self.assertEqual(self.client.get(f"/portal/moderacion/novedades/{n.pk}/").status_code, 404)
            self.assertEqual(self.client.post(f"/portal/moderacion/novedades/{n.pk}/accion/",
                                              {"accion": "borrar"}).status_code, 404)
            self.assertEqual(self.client.post(f"/portal/moderacion/novedades/{n.pk}/", self.datos()).status_code, 404)
        self.assertEqual(Publicacion.objects.count(), 4)
        # Con la propia, sí: publicar, ocultar y borrar quedan en el historial
        for accion in ("publicar", "ocultar", "borrar"):
            self.client.post(f"/portal/moderacion/novedades/{propia.pk}/accion/", {"accion": accion})
        self.assertFalse(Publicacion.objects.filter(pk=propia.pk).exists())
        self.assertEqual(
            list(RegistroModeracion.objects.filter(actor=self.mod).order_by("pk").values_list("accion", flat=True)),
            [A.PUBLICAR, A.OCULTAR, A.BORRAR])

    def test_vista_previa_solo_de_lo_suyo(self):
        propia = Publicacion.objects.create(parte="campeonatos", asociacion=self.asoc, titulo="Borrador propio", resumen="x")
        ajena = Publicacion.objects.create(parte="campeonatos", asociacion=self.otra, titulo="Borrador ajeno", resumen="x")
        self.assertContains(self.client.get(f"/publicaciones/{propia.slug}/"), "Vista previa.")
        self.assertEqual(self.client.get(f"/publicaciones/{ajena.slug}/").status_code, 404)

    def test_menu_y_sin_moderacion_no_entra(self):
        self.assertContains(self.client.get("/portal/moderacion/"), "/portal/moderacion/novedades/")
        piloto = Usuario.objects.create_user("piloto", password="x", tipo=Usuario.Tipo.PORTAL)
        self.client.force_login(piloto)
        self.assertEqual(self.client.get("/portal/moderacion/novedades/").status_code, 403)

    def test_el_panel_no_mezcla_partes(self):
        """En el panel, una novedad de El Taller no puede tener asociación."""
        self.client.force_login(self.gerente)
        r = self.client.post("/panel/sitio/novedades/nueva/", {
            "parte": "taller", "asociacion": self.asoc.pk, "titulo": "X", "resumen": "x", "cuerpo": "",
            "video_url": "", "fecha": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertContains(r, "sólo para novedades de Campeonatos")
        self.assertFalse(Publicacion.objects.exists())
        # El personal ve quién la escribió
        Publicacion.objects.create(parte="campeonatos", asociacion=self.asoc, titulo="De Laura", resumen="x", autor=self.mod)
        r = self.client.get("/panel/sitio/novedades/")
        self.assertContains(r, "Laura (moderador)")
        self.assertContains(r, "Pista Norte")
