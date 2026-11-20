"""El comando cargar_demo arma una demo completa y coherente (y no se carga encima de datos reales)."""
import atexit
import shutil
import tempfile
from io import BytesIO, StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from campeonatos.models import Resultado
from core.models import Usuario
from sitio.models import Publicacion, Trabajo
from taller.models import OrdenTrabajo

MEDIA = tempfile.mkdtemp(prefix="media_demo_test_")
atexit.register(shutil.rmtree, MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=MEDIA, PRIVATE_MEDIA_ROOT=MEDIA, ALLOWED_HOSTS=["testserver"],
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CargarDemoTests(TestCase):
    def test_no_se_carga_sin_la_base_de_demo(self):
        with self.assertRaisesMessage(CommandError, "DJANGO_DEMO=1"):
            call_command("cargar_demo", "--sin-fotos", stdout=StringIO())

    def test_carga_completa(self):
        salida = StringIO()
        call_command("cargar_demo", "--forzar", "--sin-fotos", stdout=salida)
        self.assertIn("Base de demostración cargada", salida.getvalue())
        self.assertTrue(Usuario.objects.filter(username="carlos", groups__name="gerente").exists())
        self.assertEqual(Trabajo.objects.publicados().count(), 11)
        self.assertTrue(Publicacion.objects.filter(asociacion__isnull=False, autor__username="laura").exists())
        self.assertEqual(OrdenTrabajo.objects.filter(estado=OrdenTrabajo.Estado.PRESUPUESTO).count(), 1)
        self.assertTrue(Resultado.objects.filter(estado=Resultado.Estado.VALIDADO).exists())
        self.assertTrue(Resultado.objects.filter(estado=Resultado.Estado.PROVISORIO).exists())
        # Las páginas principales se ven
        for url in ("/", "/trabajos/", "/prepa/", "/prepa/proyectos/", "/campeonatos/", "/publicaciones/",
                    "/pilotos/", "/asociaciones/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        camp = self.client.get("/campeonatos/")
        self.assertContains(camp, "Turismo Pista Regional")
        # No se carga dos veces
        with self.assertRaisesMessage(CommandError, "ya tiene datos"):
            call_command("cargar_demo", "--forzar", "--sin-fotos", stdout=StringIO())


class BajarFotosTests(TestCase):
    """La descarga de fotos de la demo: guarda las que llegan y sigue (con reemplazo) si alguna falla."""

    def test_baja_las_que_puede(self):
        import json
        from pathlib import Path
        from unittest import mock

        from PIL import Image

        from core.management.commands import cargar_demo as cd

        carpeta = Path(tempfile.mkdtemp(prefix="fotos_demo_test_"))
        self.addCleanup(shutil.rmtree, carpeta, ignore_errors=True)
        manifiesto = carpeta / "fotos.json"
        manifiesto.write_text(json.dumps({
            "buena": {"url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Auto.jpg"},
            "mala": {"url": "https://upload.wikimedia.org/wikipedia/commons/c/cd/" + "x" * 170 + ".jpg"},
        }))
        salida = BytesIO()
        Image.new("RGB", (2400, 1600), "red").save(salida, format="JPEG")
        pedidas = []

        class Respuesta:
            def __init__(self, datos): self.datos = datos
            def read(self): return self.datos
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def abrir(req, timeout=None):
            pedidas.append(req.full_url)
            if "Auto.jpg" in req.full_url:
                return Respuesta(salida.getvalue())
            raise OSError("429")

        with mock.patch.object(cd, "FOTOS", carpeta / "fotos"), mock.patch.object(cd, "MANIFIESTO", manifiesto), \
                mock.patch.object(cd.urllib.request, "urlopen", abrir), mock.patch.object(cd.reloj, "sleep"):
            faltan = cd.bajar_fotos(lambda *_: None)
        self.assertEqual(faltan, 1)
        im = Image.open(carpeta / "fotos" / "buena.jpg")
        self.assertEqual(im.size, (1600, 1067))                        # achicada
        self.assertIn("/thumb/a/ab/Auto.jpg/1280px-Auto.jpg", pedidas[0])
        self.assertTrue(any("1280px-thumbnail.jpg" in u for u in pedidas))   # nombre largo: miniatura abreviada
        self.assertFalse((carpeta / "fotos" / "mala.jpg").exists())
