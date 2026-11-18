from datetime import date, timedelta
from decimal import Decimal

from django.test import override_settings

from portal import servicios as sp
from portal.models import Asociacion, Membresia, PerfilPiloto

from . import servicios as s
from .models import Campeonato, Inscripcion, Resultado
from .tests import Base


@override_settings(ALLOWED_HOSTS=["testserver"])
class PortalCampeonatoTests(Base):
    def setUp(self):
        super().setUp()
        self.en_curso()
        self.fecha = s.crear_fecha(self.camp, self.mod, numero=1, circuito="Rafaela", dia=date.today() - timedelta(days=1))
        self.final = self.fecha.carreras.get()
        self.client.force_login(self.juan.usuario)

    def url(self, extra=""):
        return f"/portal/campeonatos/{self.camp.slug}/{extra}"

    def inscribirse(self, numero="7"):
        return self.client.post(self.url("inscribirse/"), {"categoria": self.clase1.pk, "numero": numero})

    def test_inscripcion_carga_y_tabla(self):
        self.assertContains(self.client.get("/portal/campeonatos/"), "TC Pista")
        self.inscribirse()
        insc = Inscripcion.objects.get(piloto=self.juan)
        self.client.post(f"/portal/campeonatos/carreras/{self.final.pk}/inscripciones/{insc.pk}/resultado/", {
            f"r{self.final.pk}-{insc.pk}-condicion": "FINALIZO", f"r{self.final.pk}-{insc.pk}-posicion": "1",
            f"r{self.final.pk}-{insc.pk}-pole": "on",
        })
        r = Resultado.objects.get()
        self.assertEqual((r.puntos, r.estado), (Decimal("21.00"), Resultado.Estado.PROVISORIO))
        pagina = self.client.get(self.url())
        self.assertContains(pagina, "Tabla · Clase 1")
        self.assertContains(pagina, "Corregir")

    def test_conflicto_avisa(self):
        ana = self.piloto("ana", self.asoc)
        s.inscribirse(ana, self.clase1, "8")
        s.cargar_resultado(ana, self.final, posicion=1)
        self.inscribirse()
        insc = Inscripcion.objects.get(piloto=self.juan)
        r = self.client.post(f"/portal/campeonatos/carreras/{self.final.pk}/inscripciones/{insc.pk}/resultado/", {
            f"r{self.final.pk}-{insc.pk}-condicion": "FINALIZO", f"r{self.final.pk}-{insc.pk}-posicion": "1",
        }, follow=True)
        self.assertContains(r, "quedó observado")

    def test_no_ve_campeonatos_de_otra_asociacion_ni_borradores(self):
        otro = s.crear_campeonato(self.asoc, self.mod, nombre="Borrador", temporada=2026)
        self.assertEqual(self.client.get(f"/portal/campeonatos/{otro.slug}/").status_code, 404)
        sur = self.piloto("sur", self.otra)
        self.client.force_login(sur.usuario)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_no_carga_resultado_de_otro(self):
        ana = self.piloto("ana", self.asoc)
        insc_ana = s.inscribirse(ana, self.clase1, "8")
        r = self.client.post(f"/portal/campeonatos/carreras/{self.final.pk}/inscripciones/{insc_ana.pk}/resultado/",
                             {f"r{self.final.pk}-{insc_ana.pk}-condicion": "FINALIZO"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Resultado.objects.exists())

    def test_baja(self):
        self.inscribirse()
        insc = Inscripcion.objects.get(piloto=self.juan)
        self.client.post(f"/portal/campeonatos/inscripciones/{insc.pk}/baja/")
        insc.refresh_from_db()
        self.assertEqual(insc.estado, Inscripcion.Estado.BAJA)

    def test_menu(self):
        self.assertContains(self.client.get("/portal/"), "/portal/campeonatos/")
