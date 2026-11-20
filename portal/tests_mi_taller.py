from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from clientes.models import Cliente
from core.models import Sucursal, Usuario
from productos.models import Producto
from taller.models import OrdenItem, OrdenTrabajo, Tecnico, Turno, Vehiculo

from . import acceso_taller as mt
from . import servicios
from . import servicios_contenido as sc
from .models import AccesoCliente, Asociacion, Membresia, PerfilPiloto

E = OrdenTrabajo.Estado


class Base(TestCase):
    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.adm = Usuario.objects.create_user("adm", password="x", is_staff=True, sucursal=self.suc)
        self.adm.groups.add(Group.objects.get(name="administracion"))
        self.gerente = Usuario.objects.create_user("gerente", password="x", is_staff=True)
        self.gerente.groups.add(Group.objects.get(name="gerente"))

        # Un equipo (cliente) con dos autos; el dueño es titular y Ana es piloto del equipo.
        self.equipo = Cliente.objects.create(nombre="Equipo Rojo")
        self.auto1 = Vehiculo.objects.create(cliente=self.equipo, vin="CH-1", marca="Ford", modelo="Falcon")
        self.auto2 = Vehiculo.objects.create(cliente=self.equipo, vin="CH-2", marca="Chevrolet", modelo="Chevy")
        self.dueno = self.portal("dueno")
        self.acceso(self.dueno, AccesoCliente.Rol.TITULAR)
        self.ana = self.portal("ana")
        self.acceso(self.ana, AccesoCliente.Rol.PILOTO)

        # Ana maneja sólo el auto 1: su auto del portal está vinculado a ese vehículo.
        asoc = Asociacion.objects.create(nombre="Pista Norte")
        servicios.aprobar_membresia(Membresia.objects.create(usuario=self.ana, asociacion=asoc), self.gerente)
        perfil_ana = PerfilPiloto.objects.create(usuario=self.ana, nombre_publico="Ana")
        auto_portal = sc.crear_auto(perfil_ana, marca="Ford", modelo="Falcon")
        sc.vincular_vehiculo(auto_portal, self.auto1, self.gerente)

        self.servicio = Producto.objects.create(nombre="Mano de obra", tipo="SERVICIO", precio_base=Decimal("1000"))
        self.ot1 = self.orden(self.auto1)
        self.ot2 = self.orden(self.auto2)

    def portal(self, nombre):
        return Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL)

    def acceso(self, usuario, rol, cliente=None):
        a = AccesoCliente.objects.create(usuario=usuario)
        servicios.aprobar_acceso(a, self.gerente, cliente=cliente or self.equipo, rol=rol)
        return a

    def orden(self, vehiculo):
        o = OrdenTrabajo.objects.create(sucursal=self.suc, vehiculo=vehiculo, creada_por=self.adm)
        OrdenItem.objects.create(orden=o, producto=self.servicio)
        return o


class VisibilidadTests(Base):
    def test_titular_ve_todo_piloto_solo_lo_que_maneja(self):
        self.assertEqual(set(mt.ordenes_del_cliente(self.dueno)), {self.ot1, self.ot2})
        self.assertEqual(set(mt.ordenes_del_cliente(self.ana)), {self.ot1})
        self.assertEqual(set(mt.vehiculos_del_cliente(self.ana)), {self.auto1})

    def test_no_ve_ordenes_de_otro_dueno(self):
        # El auto 1 se vende a otro cliente: la orden vieja sigue siendo del equipo.
        nuevo = Cliente.objects.create(nombre="Comprador")
        self.auto1.cliente = nuevo
        self.auto1.save()
        comprador = self.portal("comprador")
        self.acceso(comprador, AccesoCliente.Rol.TITULAR, cliente=nuevo)
        self.assertNotIn(self.ot1, mt.ordenes_del_cliente(comprador))
        ot_nueva = self.orden(self.auto1)
        self.assertIn(ot_nueva, mt.ordenes_del_cliente(comprador))

    def test_acceso_revocado_no_ve_nada(self):
        acceso = self.dueno.accesos_cliente.get()
        servicios.revocar_acceso(acceso, self.gerente, "Dejó de ser cliente")
        self.assertFalse(mt.ordenes_del_cliente(self.dueno).exists())

    def test_staff_no_usa_el_portal(self):
        self.assertFalse(mt.ordenes_del_cliente(self.adm).exists())


class PresupuestoTests(Base):
    def test_titular_aprueba_presupuesto(self):
        mt.aprobar_presupuesto(self.ot1, self.dueno)
        self.ot1.refresh_from_db()
        self.assertEqual(self.ot1.estado, E.APROBADA)
        self.assertEqual(self.ot1.total, Decimal("1000.00"))
        ultimo = self.ot1.historial.last()
        self.assertEqual((ultimo.estado_nuevo, ultimo.usuario), (E.APROBADA, self.dueno))

    def test_piloto_del_equipo_no_aprueba(self):
        with self.assertRaises(PermissionDenied):
            mt.aprobar_presupuesto(self.ot1, self.ana)

    def test_solo_presupuestos_pendientes(self):
        mt.aprobar_presupuesto(self.ot1, self.dueno)
        with self.assertRaises(ValidationError):
            mt.aprobar_presupuesto(self.ot1, self.dueno)


class ComentarioTests(Base):
    def test_interno_y_visible(self):
        mt.comentar_orden(self.ot1, self.adm, "Pedir repuesto al proveedor")          # interno
        mt.comentar_orden(self.ot1, self.adm, "El auto está listo el jueves", visible_piloto=True)
        c = mt.comentar_orden(self.ot1, self.ana, "¿Pueden revisar los frenos?", visible_piloto=False)
        self.assertTrue(c.visible_piloto)  # lo del cliente siempre se ve
        self.assertEqual(mt.comentarios_visibles(self.ot1, self.ana).count(), 2)
        self.assertEqual(mt.comentarios_visibles(self.ot1, self.adm).count(), 3)

    def test_quien_puede_comentar(self):
        with self.assertRaises(PermissionDenied):
            mt.comentar_orden(self.ot2, self.ana, "Hola")  # no maneja ese auto
        mec = Usuario.objects.create_user("mec", password="x", is_staff=True)
        mec.groups.add(Group.objects.get(name="mecanico"))
        with self.assertRaises(PermissionDenied):
            mt.comentar_orden(self.ot1, mec, "x")  # no está asignado
        self.ot1.tecnico = Tecnico.objects.create(nombre="Mec", usuario=mec)
        self.ot1.save()
        mt.comentar_orden(self.ot1, mec, "Cambié pastillas")

    def test_comentario_vacio(self):
        with self.assertRaises(ValidationError):
            mt.comentar_orden(self.ot1, self.dueno, "   ")


class TurnoTests(Base):
    def test_pedir_turno(self):
        inicio = timezone.now() + timedelta(days=2)
        t = mt.solicitar_turno(self.ana, vehiculo=self.auto1, sucursal=self.suc, inicio=inicio, motivo="Service")
        self.assertEqual((t.estado, t.cliente, t.creado_por), (Turno.Estado.PENDIENTE, self.equipo, self.ana))
        self.assertIn(t, mt.turnos_del_cliente(self.ana))

    def test_solo_sus_vehiculos_y_fechas_futuras(self):
        futuro = timezone.now() + timedelta(days=2)
        with self.assertRaises(PermissionDenied):
            mt.solicitar_turno(self.ana, vehiculo=self.auto2, sucursal=self.suc, inicio=futuro)
        with self.assertRaises(ValidationError):
            mt.solicitar_turno(self.ana, vehiculo=self.auto1, sucursal=self.suc,
                               inicio=timezone.now() - timedelta(hours=1))

    def test_respeta_el_cupo(self):
        self.suc.cupo_turnos = 1
        self.suc.save()
        inicio = timezone.now() + timedelta(days=2)
        mt.solicitar_turno(self.dueno, vehiculo=self.auto2, sucursal=self.suc, inicio=inicio)
        with self.assertRaises(ValidationError):
            mt.solicitar_turno(self.ana, vehiculo=self.auto1, sucursal=self.suc, inicio=inicio)
