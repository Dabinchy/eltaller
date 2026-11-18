from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone

from clientes.models import Cliente
from core.models import Sucursal, Usuario
from productos.models import Producto
from taller.models import OrdenItem, OrdenTrabajo, Turno, Vehiculo

from . import acceso_taller as mt
from . import servicios
from .models import AccesoCliente
from .models_contenido import OrdenComentario

E = OrdenTrabajo.Estado


@override_settings(ALLOWED_HOSTS=["testserver"])
class Base(TestCase):
    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.adm = Usuario.objects.create_user("adm", password="x", is_staff=True, sucursal=self.suc)
        self.adm.groups.add(Group.objects.get(name="administracion"))
        self.cliente = Cliente.objects.create(nombre="Equipo Rojo")
        self.auto = Vehiculo.objects.create(cliente=self.cliente, patente="AA111AA", marca="Ford", modelo="Falcon")
        self.titular = self.portal("dueno", AccesoCliente.Rol.TITULAR)
        self.mano = Producto.objects.create(nombre="Mano de obra", tipo="SERVICIO", precio_base=Decimal("5000"))
        self.orden = OrdenTrabajo.objects.create(sucursal=self.suc, vehiculo=self.auto, creada_por=self.adm)
        OrdenItem.objects.create(orden=self.orden, producto=self.mano)

    def portal(self, nombre, rol):
        u = Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL)
        servicios.aprobar_acceso(AccesoCliente.objects.create(usuario=u), self.adm, cliente=self.cliente, rol=rol)
        return u


class MiTallerTests(Base):
    def test_ve_sus_ordenes_y_aprueba_el_presupuesto(self):
        self.client.force_login(self.titular)
        r = self.client.get("/portal/taller/")
        self.assertContains(r, "esperando tu aprobación")
        r = self.client.get(f"/portal/taller/ordenes/{self.orden.pk}/")
        self.assertContains(r, "Aprobar presupuesto")
        self.assertNotContains(r, "costo")
        self.client.post(f"/portal/taller/ordenes/{self.orden.pk}/aprobar/")
        self.orden.refresh_from_db()
        self.assertEqual(self.orden.estado, E.APROBADA)
        self.assertContains(self.client.get(f"/portal/taller/ordenes/{self.orden.pk}/"), "Aprobada")

    def test_piloto_del_equipo_no_aprueba_ni_ve_autos_ajenos(self):
        piloto = self.portal("ana", AccesoCliente.Rol.PILOTO)
        self.client.force_login(piloto)
        self.assertEqual(self.client.get(f"/portal/taller/ordenes/{self.orden.pk}/").status_code, 404)

    def test_comentarios_internos_no_se_ven(self):
        mt.comentar_orden(self.orden, self.adm, "Interno: cobrar caro")
        mt.comentar_orden(self.orden, self.adm, "Listo el jueves", visible_piloto=True)
        self.client.force_login(self.titular)
        r = self.client.get(f"/portal/taller/ordenes/{self.orden.pk}/")
        self.assertContains(r, "Listo el jueves")
        self.assertNotContains(r, "cobrar caro")
        self.client.post(f"/portal/taller/ordenes/{self.orden.pk}/comentar/", {"texto": "¿Revisan los frenos?"})
        self.assertTrue(OrdenComentario.objects.filter(autor=self.titular, visible_piloto=True).exists())

    def test_pedir_turno(self):
        self.client.force_login(self.titular)
        manana = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT10:00")
        self.client.post("/portal/taller/turnos/", {"vehiculo": self.auto.pk, "sucursal": self.suc.pk,
                                                    "inicio": manana, "motivo": "Service"})
        t = Turno.objects.get()
        self.assertEqual((t.estado, t.creado_por), (Turno.Estado.PENDIENTE, self.titular))
        self.assertContains(self.client.get("/portal/taller/turnos/"), "Pendiente")

    def test_sin_acceso_aprobado(self):
        u = Usuario.objects.create_user("nuevo", password="x", tipo=Usuario.Tipo.PORTAL)
        AccesoCliente.objects.create(usuario=u)
        self.client.force_login(u)
        r = self.client.get("/portal/taller/", follow=True)
        self.assertContains(r, "se habilita cuando el taller aprueba")
