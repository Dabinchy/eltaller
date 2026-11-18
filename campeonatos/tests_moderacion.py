from datetime import date, timedelta
from decimal import Decimal

from django.test import override_settings

from portal import servicios as sp
from portal.models import Membresia

from . import servicios as s
from .models import Campeonato, Fecha, Inscripcion, Resultado, TipoCarrera
from .tests import Base

ER = Resultado.Estado


@override_settings(ALLOWED_HOSTS=["testserver"])
class GestionTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.mod)

    def test_armar_campeonato_desde_cero(self):
        r = self.client.post("/portal/moderacion/campeonatos/", {
            "asociacion": self.asoc.pk, "nombre": "Zonal", "temporada": "2026", "plazo_carga_dias": "7",
            "puntos_pole": "1", "puntos_vuelta_rapida": "1",
        })
        c = Campeonato.objects.get(nombre="Zonal")
        self.assertRedirects(r, f"/portal/moderacion/campeonatos/{c.pk}/")
        base = f"/portal/moderacion/campeonatos/{c.pk}/"
        self.client.post(base + "categorias/", {"nombre": "Promocional", "orden": "1"})
        self.client.post(base + "puntos/", {"tipo": "FINAL", "puntos": "25, 18, 15"})
        self.client.post(base + "puntos/", {"tipo": "SERIE", "puntos": "5;3;1"})
        self.client.post(base + "fechas/", {"numero": "1", "circuito": "Rafaela", "dia": "2026-03-01", "multiplicador": "1"})
        f = c.fechas.get()
        self.client.post(f"/portal/moderacion/campeonatos/fechas/{f.pk}/carreras/", {"nombre": "Serie 1", "tipo": "SERIE"})
        self.client.post(base + "estado/", {"estado": "EN_CURSO"})
        c.refresh_from_db()
        self.assertEqual(c.estado, Campeonato.Estado.EN_CURSO)
        self.assertEqual(c.puntos_por_posicion(TipoCarrera.FINAL, 2), Decimal("18"))
        self.assertEqual(c.puntos_por_posicion(TipoCarrera.SERIE, 3), Decimal("1"))
        self.assertEqual(f.carreras.count(), 2)
        self.assertContains(self.client.get(base), "Serie 1")

    def test_puntos_invalidos(self):
        r = self.client.post(f"/portal/moderacion/campeonatos/{self.camp.pk}/puntos/", {"tipo": "FINAL", "puntos": "veinte"}, follow=True)
        self.assertContains(r, "sólo números")

    def test_no_toca_campeonatos_de_otra_asociacion(self):
        mod_sur = self.portal("mod_sur")
        sp.aprobar_membresia(Membresia.objects.create(usuario=mod_sur, asociacion=self.otra, rol=Membresia.Rol.MODERADOR), self.gerente)
        self.client.force_login(mod_sur)
        self.assertEqual(self.client.get(f"/portal/moderacion/campeonatos/{self.camp.pk}/").status_code, 404)
        self.assertNotContains(self.client.get("/portal/moderacion/campeonatos/"), "TC Pista")

    def test_piloto_no_entra(self):
        self.client.force_login(self.juan.usuario)
        self.assertEqual(self.client.get("/portal/moderacion/campeonatos/").status_code, 403)


@override_settings(ALLOWED_HOSTS=["testserver"])
class ResultadosModTests(Base):
    def setUp(self):
        super().setUp()
        self.en_curso()
        self.ana = self.piloto("ana", self.asoc)
        s.inscribirse(self.juan, self.clase1, "7")
        s.inscribirse(self.ana, self.clase1, "8")
        self.fecha = s.crear_fecha(self.camp, self.mod, numero=1, circuito="Rafaela", dia=date.today() - timedelta(days=1))
        self.final = self.fecha.carreras.get()
        self.client.force_login(self.mod)
        self.url = f"/portal/moderacion/campeonatos/fechas/{self.fecha.pk}/resultados/"

    def test_conflicto_se_resuelve_corrigiendo(self):
        s.cargar_resultado(self.juan, self.final, posicion=1)
        s.cargar_resultado(self.ana, self.final, posicion=1)
        r = self.client.get(self.url)
        self.assertContains(r, "Otro piloto también cargó el puesto 1")
        res_ana = Resultado.objects.get(inscripcion__piloto=self.ana)
        self.client.post(f"/portal/moderacion/campeonatos/resultados/{res_ana.pk}/", {
            "accion": "corregir", "condicion": "FINALIZO", "posicion": "2", "motivo": "Planilla oficial",
        })
        estados = dict(Resultado.objects.values_list("inscripcion__piloto__nombre_publico", "estado"))
        self.assertEqual(estados, {"Juan": ER.PROVISORIO, "Ana": ER.VALIDADO})

    def test_validar_todos_y_anular(self):
        s.cargar_resultado(self.juan, self.final, posicion=1)
        s.cargar_resultado(self.ana, self.final, posicion=2)
        self.client.post(f"/portal/moderacion/campeonatos/carreras/{self.final.pk}/categorias/{self.clase1.pk}/validar/")
        self.assertEqual(Resultado.objects.filter(estado=ER.VALIDADO).count(), 2)
        r = Resultado.objects.get(inscripcion__piloto=self.ana)
        resp = self.client.post(f"/portal/moderacion/campeonatos/resultados/{r.pk}/", {"accion": "anular"}, follow=True)
        self.assertContains(resp, "Indicá el motivo")
        self.client.post(f"/portal/moderacion/campeonatos/resultados/{r.pk}/", {"accion": "anular", "motivo": "No largó"})
        r.refresh_from_db()
        self.assertEqual(r.estado, ER.ANULADO)

    def test_muestra_quien_falta_cargar(self):
        s.cargar_resultado(self.juan, self.final, posicion=1)
        self.assertContains(self.client.get(self.url), "Sin cargar: #8 Ana")

    def test_baja_de_inscripcion(self):
        insc = Inscripcion.objects.get(piloto=self.ana)
        self.client.post(f"/portal/moderacion/campeonatos/inscripciones/{insc.pk}/baja/", {"motivo": "No pagó"})
        insc.refresh_from_db()
        self.assertEqual((insc.estado, insc.motivo_baja), (Inscripcion.Estado.BAJA, "No pagó"))

    def test_menu_de_moderador(self):
        self.assertContains(self.client.get("/portal/"), "/portal/moderacion/campeonatos/")
