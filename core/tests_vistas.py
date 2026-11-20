import shutil
import tempfile

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import Sucursal, Usuario
from portal import servicios as sp
from portal import servicios_contenido as sc
from portal.models import Asociacion, Membresia, PerfilPiloto
from portal.models_contenido import Archivo

PRIVADO = tempfile.mkdtemp(prefix="privado_vistas_test_")


@override_settings(ALLOWED_HOSTS=["testserver"], PRIVATE_MEDIA_ROOT=PRIVADO)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVADO, ignore_errors=True)

    def setUp(self):
        self.suc = Sucursal.objects.create(nombre="Central")
        self.gerente = self.personal("gerente", "gerente")
        self.adm = self.personal("adm", "administracion", sucursal=self.suc)
        self.mec = self.personal("mec", "mecanico")
        self.asoc = Asociacion.objects.create(nombre="Pista Norte")
        self.piloto = Usuario.objects.create_user("piloto", password="x", tipo=Usuario.Tipo.PORTAL)
        sp.aprobar_membresia(Membresia.objects.create(usuario=self.piloto, asociacion=self.asoc), self.gerente)
        self.perfil = PerfilPiloto.objects.create(usuario=self.piloto, nombre_publico="Juan Pérez")

    def personal(self, nombre, grupo, **kw):
        u = Usuario.objects.create_user(nombre, password="x", **kw)
        u.groups.add(Group.objects.get(name=grupo))
        return u


class IngresoTests(Base):
    def test_cada_uno_va_a_su_lugar(self):
        r = self.client.post("/ingresar/", {"username": "adm", "password": "x"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/panel/")
        self.client.post("/salir/")
        r = self.client.post("/ingresar/", {"username": "piloto", "password": "x"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/portal/")

    def test_areas_cruzadas_redirigen(self):
        self.client.force_login(self.piloto)
        self.assertRedirects(self.client.get("/panel/"), "/portal/")
        self.client.force_login(self.adm)
        self.assertRedirects(self.client.get("/portal/"), "/panel/")

    def test_sin_sesion_pide_ingresar(self):
        self.assertRedirects(self.client.get("/panel/"), "/ingresar/?next=/panel/")

    def test_portada_y_marca_por_area(self):
        from core.models import Empresa

        # Aunque Empresa tenga otro logo cargado, la marca es siempre El Taller.
        if Empresa.objects.exists():
            Empresa.objects.update(logo="empresa/otro_logo.png")
        else:
            Empresa(nombre="Otro nombre", logo="empresa/otro_logo.png").save()
        r = self.client.get("/")
        self.assertContains(r, "el-taller.png")
        self.assertNotContains(r, "otro_logo")
        self.client.force_login(self.piloto)
        self.assertContains(self.client.get("/portal/"), "el-prepa.png")
        self.client.force_login(self.adm)
        self.assertContains(self.client.get("/panel/"), "el-taller.png")

    def test_salir_es_por_post(self):
        self.client.force_login(self.adm)
        self.assertEqual(self.client.get("/salir/").status_code, 405)
        self.assertRedirects(self.client.post("/salir/"), "/")


class PanelTests(Base):
    def test_inicio_por_rol(self):
        self.client.force_login(self.adm)
        r = self.client.get("/panel/")
        self.assertContains(r, "Órdenes en curso")
        self.assertContains(r, "Ventas por cobrar")
        self.assertContains(r, "Accesos al portal pendientes")
        self.client.force_login(self.mec)
        r = self.client.get("/panel/")
        self.assertContains(r, "Mis órdenes")
        self.assertNotContains(r, "Ventas por cobrar")

    def test_menu_solo_muestra_lo_permitido(self):
        self.client.force_login(self.adm)
        r = self.client.get("/panel/")
        self.assertContains(r, "Accesos al portal")  # administración aprueba accesos de clientes
        self.client.force_login(self.mec)
        self.assertNotContains(self.client.get("/panel/"), "Accesos al portal")


class PortalTests(Base):
    def test_inicio_muestra_pendientes(self):
        nuevo = sp.registrar_cuenta(
            username="nuevo", email="n@x.com", password="UnaClave-Segura-2026", nombre="Ana", apellido="Gómez",
            dni="40111222", fecha_nacimiento="2000-01-01", asociacion=self.asoc,
        )
        self.client.force_login(nuevo)
        r = self.client.get("/portal/")
        self.assertContains(r, "En revisión")
        self.assertContains(r, "Pista Norte")

    def test_texto_de_usuario_se_escapa(self):
        self.piloto.first_name = "<script>alert(1)</script>"
        self.piloto.save()
        self.client.force_login(self.piloto)
        r = self.client.get("/portal/")
        self.assertNotContains(r, "<script>alert(1)</script>")
        self.assertContains(r, "&lt;script&gt;")


class DescargaTests(Base):
    def subir(self, visibilidad, tipo=Archivo.Tipo.SETUP, nombre="setup.pdf"):
        auto = sc.crear_auto(self.perfil, marca="Ford", modelo="Falcon")
        return sc.subir_archivo_piloto(
            self.perfil, tipo=tipo, titulo="Setup", visibilidad=visibilidad, auto=auto,
            archivo=SimpleUploadedFile(nombre, b"%PDF-1.4 contenido"),
        )

    def test_privado_solo_para_sus_pilotos(self):
        a = self.subir(Archivo.Visibilidad.PRIVADO)
        url = f"/archivos/{a.pk}/"
        self.assertEqual(self.client.get(url).status_code, 404)        # anónimo
        self.client.force_login(self.adm)
        self.assertEqual(self.client.get(url).status_code, 404)        # el taller tampoco
        self.client.force_login(self.piloto)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))  # setups siempre se descargan
        self.assertEqual(r["Content-Type"], "application/octet-stream")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn("private", r["Cache-Control"])

    def test_publico_aprobado_para_todos(self):
        a = self.subir(Archivo.Visibilidad.PUBLICO)
        url = f"/archivos/{a.pk}/"
        self.assertEqual(self.client.get(url).status_code, 404)  # todavía sin aprobar
        mod = Usuario.objects.create_user("mod", password="x", tipo=Usuario.Tipo.PORTAL)
        sp.aprobar_membresia(
            Membresia.objects.create(usuario=mod, asociacion=self.asoc, rol=Membresia.Rol.MODERADOR), self.gerente
        )
        sc.aprobar_archivo(a, mod)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertIn("public", r["Cache-Control"])

    @override_settings(PRIVATE_X_ACCEL_PREFIX="/_privado/")
    def test_en_produccion_lo_entrega_nginx(self):
        a = self.subir(Archivo.Visibilidad.PRIVADO)
        self.client.force_login(self.piloto)
        r = self.client.get(f"/archivos/{a.pk}/")
        self.assertTrue(r["X-Accel-Redirect"].startswith("/_privado/archivos/"))
        self.assertEqual(r.content, b"")

    def test_foto_de_perfil_privada_hasta_publicarse(self):
        from io import BytesIO

        from PIL import Image

        salida = BytesIO()
        Image.new("RGB", (100, 100), "red").save(salida, format="PNG")
        self.perfil.foto = SimpleUploadedFile("foto.png", salida.getvalue())
        self.perfil.save()
        url = f"/archivos/pilotos/{self.perfil.slug}/foto/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.piloto)
        r = self.client.get(url + "?mini=1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Disposition"].startswith("inline"))
