from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from core.models import Usuario
from portal import servicios as sp
from portal import servicios_contenido as sc
from portal.models import Asociacion, Membresia, PerfilPiloto

from . import servicios as s
from .models import Campeonato, Carrera, Fecha, Inscripcion, TipoCarrera


class Base(TestCase):
    def setUp(self):
        self.gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="gerente"))
        self.asoc = Asociacion.objects.create(nombre="Pista Norte")
        self.otra = Asociacion.objects.create(nombre="Karting Sur")
        self.mod = self.portal("mod")
        sp.aprobar_membresia(
            Membresia.objects.create(usuario=self.mod, asociacion=self.asoc, rol=Membresia.Rol.MODERADOR), self.gerente
        )
        self.camp = s.crear_campeonato(self.asoc, self.mod, nombre="TC Pista", temporada=2026, puntos_pole=1)
        s.definir_tabla_puntos(self.camp, self.mod, [20, 17, 15, 13, 11])
        self.clase1 = s.crear_categoria(self.camp, self.mod, "Clase 1")
        self.clase2 = s.crear_categoria(self.camp, self.mod, "Clase 2")
        self.juan = self.piloto("juan", self.asoc)

    def portal(self, nombre):
        return Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL)

    def piloto(self, nombre, asociacion, **kw):
        u = self.portal(nombre)
        sp.aprobar_membresia(Membresia.objects.create(usuario=u, asociacion=asociacion), self.gerente)
        return PerfilPiloto.objects.create(usuario=u, nombre_publico=nombre.title(), **kw)

    def en_curso(self):
        s.cambiar_estado(self.camp, self.mod, Campeonato.Estado.EN_CURSO)


class EstructuraTests(Base):
    def test_solo_moderadores_de_la_asociacion(self):
        mod_sur = self.portal("mod_sur")
        sp.aprobar_membresia(
            Membresia.objects.create(usuario=mod_sur, asociacion=self.otra, rol=Membresia.Rol.MODERADOR), self.gerente
        )
        with self.assertRaises(PermissionDenied):
            s.crear_categoria(self.camp, mod_sur, "Intrusa")
        with self.assertRaises(PermissionDenied):
            s.crear_campeonato(self.asoc, self.juan.usuario, nombre="Trucho", temporada=2026)
        s.crear_categoria(self.camp, self.gerente, "Invitados")  # el gerente puede

    def test_tabla_de_puntos(self):
        self.assertEqual(self.camp.puntos_por_posicion(TipoCarrera.FINAL, 1), Decimal("20"))
        self.assertEqual(self.camp.puntos_por_posicion(TipoCarrera.FINAL, 9), Decimal("0"))
        s.definir_tabla_puntos(self.camp, self.mod, [5, 3, 1], tipo=TipoCarrera.SERIE)
        self.assertEqual(self.camp.puntos_por_posicion(TipoCarrera.SERIE, 2), Decimal("3"))
        s.definir_tabla_puntos(self.camp, self.mod, [25, 18])  # reemplaza la de finales
        self.assertEqual(self.camp.tabla_puntos.filter(tipo_carrera=TipoCarrera.FINAL).count(), 2)

    def test_fecha_nace_con_final_y_admite_series(self):
        f = s.crear_fecha(self.camp, self.mod, numero=1, circuito="Rafaela", dia=date(2026, 3, 1))
        final = f.carreras.get()
        self.assertEqual((final.nombre, final.tipo, final.otorga_bonus), ("Final", TipoCarrera.FINAL, True))
        s.agregar_carrera(f, self.mod, "Serie 1")
        self.assertEqual(f.carreras.count(), 2)

    def test_categorias_de_la_fecha(self):
        todas = s.crear_fecha(self.camp, self.mod, numero=1, circuito="A", dia=date(2026, 3, 1))
        solo1 = s.crear_fecha(self.camp, self.mod, numero=2, circuito="B", dia=date(2026, 4, 1), categorias=[self.clase1])
        self.assertTrue(todas.corre_categoria(self.clase2))
        self.assertFalse(solo1.corre_categoria(self.clase2))

    def test_plazo_de_carga(self):
        hoy = date.today()
        f = s.crear_fecha(self.camp, self.mod, numero=1, circuito="A", dia=hoy - timedelta(days=3))
        self.assertTrue(f.carga_abierta)
        vieja = s.crear_fecha(self.camp, self.mod, numero=2, circuito="B", dia=hoy - timedelta(days=30))
        futura = s.crear_fecha(self.camp, self.mod, numero=3, circuito="C", dia=hoy + timedelta(days=5))
        self.assertFalse(vieja.carga_abierta)
        self.assertFalse(futura.carga_abierta)

    def test_borrador_no_visible(self):
        self.assertFalse(self.camp.visible_en_web)
        self.en_curso()
        self.assertTrue(self.camp.visible_en_web)


class InscripcionTests(Base):
    def test_inscribirse(self):
        self.en_curso()
        i = s.inscribirse(self.juan, self.clase1, "#7")
        self.assertEqual((i.numero, i.estado), ("7", Inscripcion.Estado.ACTIVA))

    def test_inscripciones_cerradas_en_borrador(self):
        with self.assertRaises(ValidationError):
            s.inscribirse(self.juan, self.clase1, "7")

    def test_solo_miembros_de_la_asociacion(self):
        self.en_curso()
        with self.assertRaises(PermissionDenied):
            s.inscribirse(self.piloto("sur", self.otra), self.clase1, "8")

    def test_numero_unico_por_categoria(self):
        self.en_curso()
        s.inscribirse(self.juan, self.clase1, "7")
        ana = self.piloto("ana", self.asoc)
        with self.assertRaises(ValidationError):
            s.inscribirse(ana, self.clase1, "7")
        s.inscribirse(ana, self.clase2, "7")  # en otra categoría sí

    def test_auto_propio(self):
        self.en_curso()
        ana = self.piloto("ana", self.asoc)
        auto_ana = sc.crear_auto(ana, marca="Ford", modelo="Falcon")
        with self.assertRaises(PermissionDenied):
            s.inscribirse(self.juan, self.clase1, "7", auto=auto_ana)

    def test_baja_y_reinscripcion(self):
        self.en_curso()
        i = s.inscribirse(self.juan, self.clase1, "7")
        with self.assertRaises(ValidationError):
            s.dar_de_baja(i, self.mod, "")  # el moderador necesita motivo
        s.dar_de_baja(i, self.mod, "No pagó la inscripción")
        ana = self.piloto("ana", self.asoc)
        s.inscribirse(ana, self.clase1, "7")  # el número quedó libre
        i = s.inscribirse(self.juan, self.clase1, "77")
        self.assertEqual(i.estado, Inscripcion.Estado.ACTIVA)

    def test_menor_sin_consentimiento_aparece_con_numero(self):
        self.en_curso()
        hoy = date.today()
        nene = self.piloto("nene", self.asoc, fecha_nacimiento=date(hoy.year - 12, 1, 1))
        i = s.inscribirse(nene, self.clase1, "23")
        self.assertEqual(i.nombre_mostrado, "Piloto #23")
        sp.registrar_consentimiento_tutor(nene, self.mod)
        i.piloto.refresh_from_db()
        self.assertEqual(i.nombre_mostrado, "Nene")
