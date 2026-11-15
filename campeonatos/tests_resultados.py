from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command

from portal import servicios as sp
from portal.models import Membresia

from . import servicios as s
from .models import Campeonato, Fecha, Resultado, TipoCarrera
from .tabla import tabla_posiciones
from .tests import Base

R = Resultado
ER = Resultado.Estado


class ResultadosBase(Base):
    def setUp(self):
        super().setUp()
        self.en_curso()
        self.camp.puntos_vuelta_rapida = Decimal("1")
        self.camp.save()
        self.ana = self.piloto("ana", self.asoc)
        self.pedro = self.piloto("pedro", self.asoc)
        for p, n in ((self.juan, "7"), (self.ana, "8"), (self.pedro, "9")):
            s.inscribirse(p, self.clase1, n)
        self.fecha = s.crear_fecha(self.camp, self.mod, numero=1, circuito="Rafaela", dia=date.today() - timedelta(days=1))
        self.final = self.fecha.carreras.get()

    def cargar(self, perfil, carrera=None, **datos):
        return s.cargar_resultado(perfil, carrera or self.final, **datos)


class CargaTests(ResultadosBase):
    def test_puntos_calculados_por_el_sistema(self):
        r = self.cargar(self.juan, posicion=1, pole=True, vuelta_rapida=True)
        self.assertEqual((r.puntos, r.estado), (Decimal("22.00"), ER.PROVISORIO))  # 20 + 1 + 1

    def test_condiciones(self):
        self.assertEqual(self.cargar(self.juan, posicion=3, condicion=R.Condicion.ABANDONO).puntos, Decimal("0"))
        self.camp.abandonos_suman = True
        self.camp.save()
        self.assertEqual(self.cargar(self.juan, posicion=3, condicion=R.Condicion.ABANDONO).puntos, Decimal("15.00"))
        dsq = self.cargar(self.ana, posicion=1, condicion=R.Condicion.DESCALIFICADO, pole=True)
        self.assertEqual((dsq.puntos, dsq.posicion), (Decimal("0"), None))

    def test_multiplicador_y_series(self):
        f2 = s.crear_fecha(self.camp, self.mod, numero=2, circuito="Paraná", dia=date.today(),
                           multiplicador=Decimal("2"))
        s.definir_tabla_puntos(self.camp, self.mod, [5, 3], tipo=TipoCarrera.SERIE)
        serie = s.agregar_carrera(f2, self.mod, "Serie 1")
        self.assertEqual(self.cargar(self.juan, f2.carreras.get(nombre="Final"), posicion=2).puntos, Decimal("34.00"))
        self.assertEqual(self.cargar(self.juan, serie, posicion=1).puntos, Decimal("10.00"))
        with self.assertRaises(ValidationError):
            self.cargar(self.ana, serie, posicion=2, pole=True)  # la serie no da bonus

    def test_corregir_dentro_del_plazo(self):
        self.cargar(self.juan, posicion=5)
        r = self.cargar(self.juan, posicion=4)
        self.assertEqual((r.posicion, Resultado.objects.count()), (4, 1))

    def test_fuera_de_plazo_o_fecha_futura(self):
        vieja = s.crear_fecha(self.camp, self.mod, numero=2, circuito="X", dia=date.today() - timedelta(days=20))
        futura = s.crear_fecha(self.camp, self.mod, numero=3, circuito="Y", dia=date.today() + timedelta(days=3))
        for f in (vieja, futura):
            with self.assertRaises(ValidationError):
                self.cargar(self.juan, f.carreras.get(), posicion=1)

    def test_solo_inscriptos(self):
        with self.assertRaises(ValidationError):
            self.cargar(self.piloto("nuevo", self.asoc), posicion=1)

    def test_validado_ya_no_lo_toca_el_piloto(self):
        r = self.cargar(self.juan, posicion=2)
        s.validar_resultado(r, self.mod)
        with self.assertRaises(ValidationError):
            self.cargar(self.juan, posicion=1)


class ConflictoTests(ResultadosBase):
    def test_misma_posicion_queda_observada_y_se_resuelve_sola(self):
        a = self.cargar(self.juan, posicion=1)
        b = self.cargar(self.ana, posicion=1)
        a.refresh_from_db()
        self.assertEqual((a.estado, b.estado), (ER.OBSERVADO, ER.OBSERVADO))
        self.cargar(self.ana, posicion=2)  # Ana corrige
        a.refresh_from_db()
        self.assertEqual(a.estado, ER.PROVISORIO)

    def test_dos_poles(self):
        self.cargar(self.juan, posicion=1, pole=True)
        b = self.cargar(self.ana, posicion=2, pole=True)
        self.assertEqual(b.estado, ER.OBSERVADO)
        self.assertIn("pole", b.motivo)

    def test_el_validado_manda(self):
        a = self.cargar(self.juan, posicion=1)
        s.validar_resultado(a, self.mod)
        b = self.cargar(self.ana, posicion=1)
        a.refresh_from_db()
        self.assertEqual((a.estado, b.estado), (ER.VALIDADO, ER.OBSERVADO))

    def test_moderador_resuelve_validando_uno(self):
        a = self.cargar(self.juan, posicion=1)
        b = self.cargar(self.ana, posicion=1)
        s.validar_resultado(a, self.mod)
        b.refresh_from_db()
        self.assertEqual(b.estado, ER.OBSERVADO)
        s.corregir_resultado(b, self.mod, "Llegó segunda según la planilla", posicion=2)
        b.refresh_from_db()
        self.assertEqual((b.estado, b.puntos), (ER.VALIDADO, Decimal("17.00")))


class ModeracionTests(ResultadosBase):
    def test_nadie_valida_lo_propio(self):
        sp.aprobar_membresia(Membresia.objects.create(usuario=self.mod, asociacion=self.asoc), self.gerente)
        from portal.models import PerfilPiloto

        perfil_mod = PerfilPiloto.objects.create(usuario=self.mod, nombre_publico="Mod")
        s.inscribirse(perfil_mod, self.clase1, "10")
        r = self.cargar(perfil_mod, posicion=4)
        with self.assertRaises(PermissionDenied):
            s.validar_resultado(r, self.mod)
        self.cargar(self.juan, posicion=1)
        self.assertEqual(s.validar_carrera(self.final, self.clase1, self.mod), 1)  # valida todo menos lo suyo

    def test_motivo_obligatorio(self):
        r = self.cargar(self.juan, posicion=1)
        for funcion in (s.observar_resultado, s.anular_resultado):
            with self.assertRaises(ValidationError):
                funcion(r, self.mod, "")
        s.anular_resultado(r, self.mod, "No corrió esa fecha")
        self.assertEqual(r.estado, ER.ANULADO)

    def test_piloto_no_modera(self):
        r = self.cargar(self.juan, posicion=1)
        with self.assertRaises(PermissionDenied):
            s.validar_resultado(r, self.ana.usuario)

    def test_validar_vencidos(self):
        r = self.cargar(self.juan, posicion=1)
        Fecha.objects.filter(pk=self.fecha.pk).update(dia=date.today() - timedelta(days=30))
        salida = StringIO()
        call_command("validar_resultados_vencidos", stdout=salida)
        r.refresh_from_db()
        self.assertEqual(r.estado, ER.VALIDADO)
        self.assertIn("1 resultado", salida.getvalue())


class TablaTests(ResultadosBase):
    def test_tabla_en_vivo_con_desempate(self):
        self.cargar(self.juan, posicion=1)    # 20
        self.cargar(self.ana, posicion=2)     # 17
        self.cargar(self.pedro, posicion=3)   # 15
        f2 = s.crear_fecha(self.camp, self.mod, numero=2, circuito="B", dia=date.today())
        final2 = f2.carreras.get()
        self.cargar(self.ana, final2, posicion=1)    # 17 + 20 = 37
        self.cargar(self.juan, final2, posicion=2)   # 20 + 17 = 37
        self.cargar(self.pedro, final2, posicion=3)  # 30
        filas, provisoria = tabla_posiciones(self.clase1)
        self.assertTrue(provisoria)
        # Empate en 37: misma cantidad de victorias y de segundos → el orden sigue por nombre.
        self.assertEqual([(f.nombre, f.puntos) for f in filas],
                         [("Ana", Decimal("37.00")), ("Juan", Decimal("37.00")), ("Pedro", Decimal("30.00"))])
        self.assertEqual(filas[0].victorias, 1)

    def test_desempate_por_victorias(self):
        s.definir_tabla_puntos(self.camp, self.mod, [10, 10, 10])
        self.cargar(self.juan, posicion=1)
        self.cargar(self.ana, posicion=2)
        filas, _ = tabla_posiciones(self.clase1)
        self.assertEqual(filas[0].nombre, "Juan")  # mismos puntos, más victorias

    def test_observados_no_suman(self):
        self.cargar(self.juan, posicion=1)
        self.cargar(self.ana, posicion=1)
        filas, _ = tabla_posiciones(self.clase1)
        self.assertTrue(all(f.puntos == 0 for f in filas))

    def test_inscriptos_sin_resultados_aparecen_en_cero(self):
        filas, provisoria = tabla_posiciones(self.clase1)
        self.assertEqual(len(filas), 3)
        self.assertFalse(provisoria)

    def test_link_al_perfil_solo_si_es_publico(self):
        self.cargar(self.juan, posicion=1)
        filas, _ = tabla_posiciones(self.clase1)
        self.assertIsNone(filas[0].perfil_publico_slug)
        self.juan.perfil_publico = True
        self.juan.save()
        sp.aprobar_perfil(self.juan, self.mod)
        filas, _ = tabla_posiciones(self.clase1)
        self.assertEqual(filas[0].perfil_publico_slug, self.juan.slug)

    def test_campeonato_finalizado_no_acepta_carga(self):
        s.cambiar_estado(self.camp, self.mod, Campeonato.Estado.FINALIZADO)
        with self.assertRaises(ValidationError):
            self.cargar(self.juan, posicion=1)
