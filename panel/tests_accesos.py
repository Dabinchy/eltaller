"""Accesos al portal desde el panel (/panel/clientes/accesos/): sólo la gerencia aprueba, rechaza o revoca."""
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings

from clientes.models import Cliente
from core.models import Usuario
from portal.models import AccesoCliente
from taller.models import Vehiculo

E = AccesoCliente.Estado


@override_settings(ALLOWED_HOSTS=["testserver"])
class AccesosPanelTests(TestCase):
    def setUp(self):
        self.gerente = self.personal("gerente", "gerente")
        self.cliente = Cliente.objects.create(nombre="Juan Pérez", doc_tipo="DNI", doc_numero="30111222")
        self.otro = Cliente.objects.create(nombre="Equipo Rojo")
        Vehiculo.objects.create(cliente=self.otro, patente="AB123CD", marca="Ford", modelo="Falcon")
        self.usuario = Usuario.objects.create_user("juanp", password="x", tipo=Usuario.Tipo.PORTAL,
                                                   email="juan@example.com")
        self.acceso = AccesoCliente.objects.create(usuario=self.usuario, nombre_declarado="Juan Pérez",
                                                   doc_declarado="30.111.222", nota="Traje el Fiesta en marzo")
        self.url = f"/panel/clientes/accesos/{self.acceso.pk}/"

    def personal(self, nombre, grupo):
        u = Usuario.objects.create_user(nombre, password="x", is_staff=True)
        u.groups.add(Group.objects.get(name=grupo))
        return u

    def test_solo_gerencia_y_superusuario(self):
        for grupo in ("administracion", "jefe", "mecanico"):
            self.client.force_login(self.personal(grupo, grupo))
            self.assertEqual(self.client.get("/panel/clientes/accesos/").status_code, 403, grupo)
            self.assertEqual(self.client.get(self.url).status_code, 403, grupo)
            r = self.client.post(self.url, {"accion": "aprobar", "cliente": self.cliente.pk, "rol": "TITULAR"})
            self.assertEqual(r.status_code, 403, grupo)
        # Un usuario del portal (por ejemplo, un moderador) ni siquiera entra al panel
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.get("/panel/clientes/accesos/"), "/portal/", fetch_redirect_response=False)
        self.acceso.refresh_from_db()
        self.assertEqual(self.acceso.estado, E.PENDIENTE)
        su = Usuario.objects.create_superuser("root", password="x")
        self.client.force_login(su)
        self.assertEqual(self.client.get("/panel/clientes/accesos/").status_code, 200)

    def test_bandeja_y_sugeridos_por_documento(self):
        self.client.force_login(self.gerente)
        r = self.client.get("/panel/clientes/accesos/")
        self.assertContains(r, "Juan Pérez")
        self.assertContains(r, "Traje el Fiesta en marzo")
        r = self.client.get(self.url)
        self.assertContains(r, "30.111.222")
        self.assertContains(r, "juan@example.com")
        self.assertContains(r, f'value="{self.cliente.pk}"')     # sugerido: coincide el documento
        self.assertNotContains(r, f'value="{self.otro.pk}"')
        r = self.client.get(self.url + "?q=AB123")                 # buscar por patente
        self.assertContains(r, f'value="{self.otro.pk}"')

    def test_aprobar_exige_cliente(self):
        self.client.force_login(self.gerente)
        r = self.client.post(self.url, {"accion": "aprobar", "rol": "TITULAR"})
        self.assertContains(r, "Elegí a qué cliente corresponde")
        self.acceso.refresh_from_db()
        self.assertEqual(self.acceso.estado, E.PENDIENTE)
        r = self.client.post(self.url, {"accion": "aprobar", "cliente": self.cliente.pk, "rol": "PILOTO"})
        self.assertRedirects(r, "/panel/clientes/accesos/")
        self.acceso.refresh_from_db()
        self.assertEqual((self.acceso.estado, self.acceso.cliente, self.acceso.rol, self.acceso.resuelto_por),
                         (E.APROBADO, self.cliente, "PILOTO", self.gerente))

    def test_rechazar_y_revocar_con_motivo(self):
        self.client.force_login(self.gerente)
        self.client.post(self.url, {"accion": "rechazar", "motivo": ""}, follow=True)
        self.acceso.refresh_from_db()
        self.assertEqual(self.acceso.estado, E.PENDIENTE)       # sin motivo no se rechaza
        self.client.post(self.url, {"accion": "rechazar", "motivo": "No es cliente del taller"})
        self.acceso.refresh_from_db()
        self.assertEqual((self.acceso.estado, self.acceso.motivo), (E.RECHAZADO, "No es cliente del taller"))

        otro = AccesoCliente.objects.create(usuario=self.usuario, nombre_declarado="Juan Pérez")
        url = f"/panel/clientes/accesos/{otro.pk}/"
        self.client.post(url, {"accion": "aprobar", "cliente": self.cliente.pk, "rol": "TITULAR"})
        r = self.client.get(url)
        self.assertContains(r, "Revocar el acceso")
        self.client.post(url, {"accion": "revocar", "motivo": "Vendió el auto"})
        otro.refresh_from_db()
        self.assertEqual(otro.estado, E.REVOCADO)
        self.assertContains(self.client.get("/panel/clientes/accesos/?estado=REVOCADO"), "Juan Pérez")
