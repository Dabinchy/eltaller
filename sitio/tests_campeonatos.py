"""Páginas públicas de Campeonatos: sólo se ve lo publicado y aprobado."""
from datetime import date, timedelta

from django.test import override_settings

from campeonatos import servicios as s
from campeonatos.models import Campeonato
from campeonatos.tests_resultados import ResultadosBase
from portal import servicios as sp
from portal import servicios_contenido as sc


@override_settings(ALLOWED_HOSTS=["testserver"])
class CampeonatosPublicosTests(ResultadosBase):
    """ResultadosBase: TC Pista 2026 en curso, Clase 1 con Juan #7, Ana #8 y Pedro #9, fecha 1 ayer."""

    def publicar_perfil(self, perfil):
        perfil.perfil_publico = True
        perfil.save()
        sp.aprobar_perfil(perfil, self.mod)
        return perfil

    def test_portada_con_podio_y_proximas_fechas(self):
        self.cargar(self.juan, posicion=1)
        self.cargar(self.ana, posicion=2)
        s.crear_fecha(self.camp, self.mod, numero=2, nombre="GP Paraná", circuito="Paraná",
                      dia=date.today() + timedelta(days=10))
        r = self.client.get("/campeonatos/")
        self.assertContains(r, "TC Pista 2026")
        self.assertContains(r, "GP Paraná")
        self.assertContains(r, "Juan")
        self.assertContains(r, "20 pts")
        self.assertContains(r, 'class="sitio-prov"')  # resultados provisorios

    def test_borrador_no_aparece(self):
        borrador = s.crear_campeonato(self.asoc, self.mod, nombre="Oculto", temporada=2026)
        self.assertNotContains(self.client.get("/campeonatos/"), "Oculto")
        self.assertEqual(self.client.get(f"/campeonatos/{borrador.slug}/").status_code, 404)

    def test_tabla_y_resultados_del_campeonato(self):
        self.cargar(self.ana, posicion=1, pole=True)
        self.cargar(self.juan, posicion=2)
        r = self.client.get(f"/campeonatos/{self.camp.slug}/")
        self.assertEqual(r.status_code, 200)
        tabla = r.context["tabla"]
        self.assertEqual([f.nombre for f in tabla[:2]], ["Ana", "Juan"])
        self.assertContains(r, "Rafaela")
        self.assertContains(r, 'title="Pole position"')
        # Sin perfil público aprobado, el nombre no lleva link
        self.assertNotContains(r, "/pilotos/ana/")
        self.publicar_perfil(self.ana)
        self.assertContains(self.client.get(f"/campeonatos/{self.camp.slug}/"), 'href="/pilotos/ana/"')

    def test_elegir_categoria(self):
        s.inscribirse(self.piloto("lucia", self.asoc), self.clase2, "21")
        r = self.client.get(f"/campeonatos/{self.camp.slug}/?categoria={self.clase2.pk}")
        self.assertEqual(r.context["elegida"], self.clase2)
        self.assertContains(r, "Lucia")
        # Una categoría inválida cae en la primera
        r = self.client.get(f"/campeonatos/{self.camp.slug}/?categoria=xx")
        self.assertEqual(r.context["elegida"], self.clase1)

    def test_menor_sin_consentimiento_solo_con_numero(self):
        self.juan.fecha_nacimiento = date.today().replace(year=date.today().year - 14)
        self.juan.save()
        self.cargar(self.juan, posicion=1)
        r = self.client.get(f"/campeonatos/{self.camp.slug}/")
        self.assertContains(r, "Piloto #7")
        self.assertNotContains(r, ">Juan<")

    def test_perfil_de_piloto(self):
        self.assertEqual(self.client.get("/pilotos/juan/").status_code, 404)  # no es público
        self.assertNotContains(self.client.get("/pilotos/"), "Juan")
        self.publicar_perfil(self.juan)
        self.cargar(self.juan, posicion=1)
        r = self.client.get("/pilotos/juan/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "TC Pista 2026")
        self.assertContains(r, "1° de 3")
        self.assertContains(r, 'href="/asociaciones/pista-norte/"')
        self.assertContains(self.client.get("/pilotos/"), 'href="/pilotos/juan/"')
        self.assertContains(self.client.get("/pilotos/?q=jua"), 'href="/pilotos/juan/"')
        self.assertNotContains(self.client.get("/pilotos/?q=zzz"), 'href="/pilotos/juan/"')

    def test_ficha_de_auto(self):
        self.publicar_perfil(self.juan)
        auto = sc.crear_auto(self.juan, marca="Ford", modelo="Falcon", numero_competicion="7", categoria="TC")
        self.assertEqual(self.client.get(f"/autos/{auto.slug}/").status_code, 404)  # sin publicar
        sc.publicar_auto(auto, self.juan, True)
        self.assertEqual(self.client.get(f"/autos/{auto.slug}/").status_code, 404)  # falta aprobación
        sc.aprobar_auto(auto, self.mod)
        r = self.client.get(f"/autos/{auto.slug}/")
        self.assertContains(r, "Ford Falcon")
        self.assertContains(r, 'href="/pilotos/juan/"')
        self.assertContains(self.client.get("/pilotos/juan/"), f'href="/autos/{auto.slug}/"')

    def test_asociaciones(self):
        self.assertContains(self.client.get("/asociaciones/"), "Pista Norte")
        r = self.client.get("/asociaciones/pista-norte/")
        self.assertContains(r, "TC Pista 2026")
        self.asoc.activa = False
        self.asoc.save()
        self.assertEqual(self.client.get("/asociaciones/pista-norte/").status_code, 404)
        self.assertEqual(self.client.get(f"/campeonatos/{self.camp.slug}/").status_code, 404)

    def test_finalizado_en_temporadas_anteriores(self):
        s.cambiar_estado(self.camp, self.mod, Campeonato.Estado.FINALIZADO)
        r = self.client.get("/campeonatos/")
        self.assertContains(r, "Temporadas anteriores")
        self.assertEqual(r.context["en_curso"], [])
