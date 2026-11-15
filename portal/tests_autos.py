from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from clientes.models import Cliente
from core.models import Usuario
from taller.models import Vehiculo

from . import servicios
from . import servicios_contenido as sc
from .models import Asociacion, Membresia, PerfilPiloto, RegistroModeracion
from .models_contenido import Auto, Palmares, PilotoAuto


class Base(TestCase):
    def setUp(self):
        self.gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="gerente"))
        self.asoc = Asociacion.objects.create(nombre="Pista Norte")
        self.otra = Asociacion.objects.create(nombre="Karting Sur")
        self.mod = self.portal("mod")
        servicios.aprobar_membresia(
            Membresia.objects.create(usuario=self.mod, asociacion=self.asoc, rol=Membresia.Rol.MODERADOR), self.gerente
        )
        self.juan = self.piloto("juan", self.asoc)
        self.ana = self.piloto("ana", self.asoc)

    def portal(self, nombre):
        return Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL)

    def piloto(self, nombre, asociacion, aprobar=True):
        u = self.portal(nombre)
        m = Membresia.objects.create(usuario=u, asociacion=asociacion)
        if aprobar:
            servicios.aprobar_membresia(m, self.gerente)
        return PerfilPiloto.objects.create(usuario=u, nombre_publico=nombre.title())

    def auto(self, perfil=None, **kw):
        datos = dict(marca="Ford", modelo="Falcon", numero_competicion="7")
        datos.update(kw)
        return sc.crear_auto(perfil or self.juan, **datos)


class AutoTests(Base):
    def test_crear_auto_deja_al_creador_como_principal(self):
        a = self.auto()
        self.assertEqual(a.principal, self.juan)
        self.assertEqual(a.slug, "ford-falcon-7")

    def test_piloto_pendiente_no_crea_contenido(self):
        pendiente = self.piloto("nuevo", self.asoc, aprobar=False)
        with self.assertRaises(PermissionDenied):
            self.auto(pendiente)

    def test_solo_el_principal_publica(self):
        a = self.auto()
        with self.assertRaises(PermissionDenied):
            sc.publicar_auto(a, self.ana, True)
        sc.publicar_auto(a, self.juan, True)
        self.assertTrue(a.publicado)

    def test_un_solo_principal(self):
        a = self.auto()
        with self.assertRaises(Exception):
            PilotoAuto.objects.create(auto=a, piloto=self.ana, principal=True, estado="ACEPTADA")


class InvitacionTests(Base):
    def test_invitar_aceptar_y_transferir(self):
        a = self.auto()
        inv = sc.invitar_piloto(a, self.juan, self.ana)
        self.assertEqual(inv.estado, PilotoAuto.Estado.PENDIENTE)
        self.assertNotIn(self.ana, a.pilotos_aceptados())
        sc.responder_invitacion(inv, self.ana, aceptar=True)
        self.assertIn(self.ana, a.pilotos_aceptados())
        sc.transferir_principal(a, self.juan, self.ana)
        self.assertEqual(a.principal, self.ana)

    def test_solo_el_invitado_responde(self):
        a = self.auto()
        inv = sc.invitar_piloto(a, self.juan, self.ana)
        with self.assertRaises(PermissionDenied):
            sc.responder_invitacion(inv, self.juan, aceptar=True)

    def test_rechazar_y_reinvitar(self):
        a = self.auto()
        inv = sc.invitar_piloto(a, self.juan, self.ana)
        sc.responder_invitacion(inv, self.ana, aceptar=False)
        inv = sc.invitar_piloto(a, self.juan, self.ana)
        self.assertEqual(inv.estado, PilotoAuto.Estado.PENDIENTE)

    def test_solo_el_principal_invita_y_quita(self):
        a = self.auto()
        sc.responder_invitacion(sc.invitar_piloto(a, self.juan, self.ana), self.ana, aceptar=True)
        tercero = self.piloto("pedro", self.asoc)
        with self.assertRaises(PermissionDenied):
            sc.invitar_piloto(a, self.ana, tercero)
        with self.assertRaises(PermissionDenied):
            sc.transferir_principal(a, self.ana, self.ana)  # sólo el principal transfiere
        sc.responder_invitacion(sc.invitar_piloto(a, self.juan, tercero), tercero, aceptar=True)
        with self.assertRaises(PermissionDenied):
            sc.quitar_piloto(a, self.ana, tercero)  # un acompañante no quita a otro
        sc.quitar_piloto(a, self.ana, self.ana)  # cualquiera puede salir
        self.assertNotIn(self.ana, a.pilotos_aceptados())

    def test_principal_no_sale_sin_transferir(self):
        a = self.auto()
        with self.assertRaises(ValidationError):
            sc.quitar_piloto(a, self.juan, self.juan)

    def test_no_se_invita_a_pendientes(self):
        a = self.auto()
        with self.assertRaises(ValidationError):
            sc.invitar_piloto(a, self.juan, self.piloto("nuevo", self.asoc, aprobar=False))


class ModeracionAutoTests(Base):
    def test_aprobar_y_cambio_tras_aprobacion(self):
        a = self.auto()
        sc.publicar_auto(a, self.juan, True)
        self.assertFalse(a.visible_en_web)
        sc.aprobar_auto(a, self.mod)
        self.assertTrue(a.visible_en_web)
        a.descripcion = "Motor nuevo"
        a.save()
        self.assertTrue(a.cambio_tras_aprobacion)
        sc.marcar_auto_revisado(a, self.mod)
        self.assertFalse(a.cambio_tras_aprobacion)

    def test_moderador_piloto_del_auto_no_aprueba(self):
        servicios.aprobar_membresia(Membresia.objects.create(usuario=self.mod, asociacion=self.asoc), self.gerente)
        perfil_mod = PerfilPiloto.objects.create(usuario=self.mod, nombre_publico="Mod")
        a = self.auto(perfil_mod)
        with self.assertRaises(PermissionDenied):
            sc.aprobar_auto(a, self.mod)

    def test_moderador_de_otra_asociacion_no_aprueba(self):
        a = self.auto(self.piloto("sur", self.otra))
        with self.assertRaises(PermissionDenied):
            sc.aprobar_auto(a, self.mod)

    def test_retirar_exige_motivo(self):
        a = self.auto()
        sc.aprobar_auto(a, self.mod)
        with self.assertRaises(ValidationError):
            sc.retirar_aprobacion_auto(a, self.mod, "")
        sc.retirar_aprobacion_auto(a, self.mod, "Foto inapropiada")
        self.assertFalse(a.aprobado)


class VinculoTallerTests(Base):
    def setUp(self):
        super().setUp()
        cliente = Cliente.objects.create(nombre="Juan")
        self.vehiculo = Vehiculo.objects.create(cliente=cliente, vin="CH-1", marca="Ford", modelo="Falcon")

    def test_solo_personal_vincula(self):
        a = self.auto()
        with self.assertRaises(PermissionDenied):
            sc.vincular_vehiculo(a, self.vehiculo, self.mod)
        sc.vincular_vehiculo(a, self.vehiculo, self.gerente)
        self.assertEqual(a.vehiculo_taller, self.vehiculo)
        self.assertTrue(RegistroModeracion.objects.filter(accion="VINCULAR").exists())

    def test_un_vehiculo_un_auto(self):
        sc.vincular_vehiculo(self.auto(), self.vehiculo, self.gerente)
        with self.assertRaises(ValidationError):
            sc.vincular_vehiculo(self.auto(modelo="Chevy"), self.vehiculo, self.gerente)

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_vincular_desde_el_admin(self):
        a = self.auto()
        self.client.force_login(self.gerente)
        pa = a.pilotos.get()
        r = self.client.post(f"/admin/portal/auto/{a.pk}/change/", {
            "vehiculo": self.vehiculo.pk,
            # formulario de control de la tabla de pilotos (sólo lectura)
            "pilotos-TOTAL_FORMS": "1", "pilotos-INITIAL_FORMS": "1",
            "pilotos-MIN_NUM_FORMS": "0", "pilotos-MAX_NUM_FORMS": "1000",
            "pilotos-0-id": pa.pk, "pilotos-0-auto": a.pk,
        })
        self.assertEqual(r.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.vehiculo_taller, self.vehiculo)


class PalmaresTests(Base):
    def test_cambio_en_palmares_manda_el_perfil_a_revision(self):
        self.juan.perfil_publico = True
        self.juan.save()
        servicios.aprobar_perfil(self.juan, self.mod)
        Palmares.objects.create(piloto=self.juan, anio=2025, campeonato="TC Pista Norte", resultado="Campeón")
        self.juan.refresh_from_db()
        self.assertTrue(self.juan.cambio_tras_aprobacion)

    def test_anio_valido(self):
        with self.assertRaises(ValidationError):
            Palmares.objects.create(piloto=self.juan, anio=3000, campeonato="X", resultado="1°")
