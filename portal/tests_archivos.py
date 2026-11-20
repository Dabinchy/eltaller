import atexit
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from clientes.models import Cliente
from core.models import Sucursal, Usuario
from taller.models import OrdenTrabajo, Tecnico, Vehiculo

from . import servicios
from . import servicios_contenido as sc
from .models import Asociacion, Membresia, PerfilPiloto
from .models_contenido import Archivo, video_embed
from .permisos import puede_ver_archivo

PRIVADO = tempfile.mkdtemp(prefix="privado_archivos_test_")
# Se borra al terminar la corrida (no al terminar cada clase: en paralelo la comparten).
atexit.register(shutil.rmtree, PRIVADO, ignore_errors=True)
V = Archivo.Visibilidad
T = Archivo.Tipo


def foto(nombre="foto.jpg"):
    salida = BytesIO()
    Image.new("RGB", (2500, 1000), "blue").save(salida, format="JPEG")
    return SimpleUploadedFile(nombre, salida.getvalue(), content_type="image/jpeg")


def archivo(nombre, kb=1):
    return SimpleUploadedFile(nombre, b"x" * kb * 1024)


@override_settings(PRIVATE_MEDIA_ROOT=PRIVADO)
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
        self.extrano = self.piloto("extrano", self.otra)
        self.auto = sc.crear_auto(self.juan, marca="Ford", modelo="Falcon")
        sc.responder_invitacion(sc.invitar_piloto(self.auto, self.juan, self.ana), self.ana, aceptar=True)
        self.personal = Usuario.objects.create_user("adm", password="x", is_staff=True)

    def portal(self, nombre):
        return Usuario.objects.create_user(nombre, password="x", tipo=Usuario.Tipo.PORTAL)

    def piloto(self, nombre, asociacion):
        u = self.portal(nombre)
        servicios.aprobar_membresia(Membresia.objects.create(usuario=u, asociacion=asociacion), self.gerente)
        return PerfilPiloto.objects.create(usuario=u, nombre_publico=nombre.title())

    def subir(self, visibilidad=V.PRIVADO, tipo=T.SETUP, nombre="setup.pdf", **kw):
        return sc.subir_archivo_piloto(
            self.juan, tipo=tipo, titulo="Setup Rafaela", visibilidad=visibilidad,
            archivo=archivo(nombre), auto=kw.pop("auto", self.auto), **kw,
        )


class TiposTests(Base):
    def test_foto_procesada_y_tamano(self):
        a = sc.subir_archivo_piloto(self.juan, tipo=T.FOTO, titulo="Largada", archivo=foto(), auto=self.auto)
        self.assertTrue(a.miniatura)
        self.assertEqual(a.tamano_bytes, a.archivo.size)
        with a.archivo.open("rb") as f:
            self.assertEqual(max(Image.open(f).size), 2000)

    def test_formato_segun_tipo(self):
        self.subir(tipo=T.TELEMETRIA, nombre="vuelta.ld")
        with self.assertRaises(ValidationError):
            self.subir(tipo=T.SETUP, nombre="virus.exe")
        with self.assertRaises(ValidationError):
            self.subir(tipo=T.TELEMETRIA, nombre="foto.jpg")

    def test_tamano_maximo(self):
        with self.assertRaises(ValidationError):
            sc.subir_archivo_piloto(self.juan, tipo=T.SETUP, titulo="x", archivo=archivo("s.pdf", kb=11 * 1024),
                                    auto=self.auto)

    def test_videos(self):
        self.assertEqual(video_embed("https://youtu.be/dQw4w9WgXcQ"), "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertEqual(video_embed("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10"),
                         "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
        self.assertEqual(video_embed("https://vimeo.com/123456"), "https://player.vimeo.com/video/123456")
        self.assertIsNone(video_embed("https://sitio-raro.com/video"))
        self.assertIsNone(video_embed("javascript:alert(1)"))
        v = sc.subir_archivo_piloto(self.juan, tipo=T.VIDEO, titulo="Onboard", url_video="https://youtu.be/dQw4w9WgXcQ",
                                    auto=self.auto)
        self.assertEqual(v.tamano_bytes, 0)
        with self.assertRaises(ValidationError):
            sc.subir_archivo_piloto(self.juan, tipo=T.VIDEO, titulo="x", url_video="https://malo.com/v", auto=self.auto)


class CuotaTests(Base):
    def test_cuota_por_piloto(self):
        servicios.cambiar_cuota(self.juan, self.gerente, 1)  # 1 MB
        self.subir(nombre="a.pdf")  # 1 KB
        with self.assertRaises(ValidationError) as ctx:
            sc.subir_archivo_piloto(self.juan, tipo=T.SETUP, titulo="x", archivo=archivo("b.pdf", kb=1024),
                                    auto=self.auto)
        self.assertIn("usaste", str(ctx.exception))
        usados, total = sc.uso_cuota(self.juan)
        self.assertEqual((usados, total), (1024, 1024 * 1024))


class PermisosSubidaTests(Base):
    def test_solo_pilotos_del_auto_suben(self):
        with self.assertRaises(PermissionDenied):
            sc.subir_archivo_piloto(self.extrano, tipo=T.SETUP, titulo="x", archivo=archivo("s.pdf"), auto=self.auto)

    def test_piloto_no_elige_interno(self):
        with self.assertRaises(ValidationError):
            self.subir(visibilidad=V.INTERNO)

    def test_portada_debe_ser_foto_del_auto(self):
        f = sc.subir_archivo_piloto(self.juan, tipo=T.FOTO, titulo="Portada", archivo=foto(), auto=self.auto)
        sc.elegir_portada(self.auto, self.juan, f)
        self.assertEqual(self.auto.portada, f)
        otro = sc.crear_auto(self.juan, marca="Fiat", modelo="Uno")
        ajena = sc.subir_archivo_piloto(self.juan, tipo=T.FOTO, titulo="Otra", archivo=foto(), auto=otro)
        with self.assertRaises(ValidationError):
            sc.elegir_portada(self.auto, self.juan, ajena)


class VisibilidadTests(Base):
    def test_privado(self):
        a = self.subir(V.PRIVADO)
        self.assertTrue(puede_ver_archivo(self.juan.usuario, a))
        self.assertTrue(puede_ver_archivo(self.ana.usuario, a))        # compañera de auto
        self.assertFalse(puede_ver_archivo(self.personal, a))          # el taller NO
        self.assertFalse(puede_ver_archivo(self.extrano.usuario, a))
        self.assertFalse(puede_ver_archivo(AnonymousUser(), a))

    def test_compartido_con_el_taller(self):
        a = self.subir(V.PILOTO)
        self.assertTrue(puede_ver_archivo(self.personal, a))
        self.assertFalse(puede_ver_archivo(self.extrano.usuario, a))
        self.assertFalse(puede_ver_archivo(self.mod, a))

    def test_publico_requiere_aprobacion(self):
        a = self.subir(V.PUBLICO, tipo=T.TELEMETRIA, nombre="vuelta.csv")  # telemetría pública: permitido
        self.assertFalse(a.aprobado)
        self.assertFalse(puede_ver_archivo(AnonymousUser(), a))
        self.assertTrue(puede_ver_archivo(self.mod, a))  # el moderador lo ve para revisarlo
        sc.aprobar_archivo(a, self.mod)
        self.assertTrue(puede_ver_archivo(AnonymousUser(), a))

    def test_volver_a_publico_pide_nueva_aprobacion(self):
        a = self.subir(V.PUBLICO)
        sc.aprobar_archivo(a, self.mod)
        sc.cambiar_visibilidad(a, self.juan, V.PRIVADO)
        sc.cambiar_visibilidad(a, self.juan, V.PUBLICO)
        self.assertFalse(a.aprobado)

    def test_solo_el_autor_cambia_visibilidad(self):
        a = self.subir(V.PRIVADO)
        with self.assertRaises(PermissionDenied):
            sc.cambiar_visibilidad(a, self.ana, V.PUBLICO)


class ModeracionArchivoTests(Base):
    def test_no_modera_lo_propio_ni_otra_asociacion(self):
        a = self.subir(V.PUBLICO)
        mod_sur = self.portal("mod_sur")
        servicios.aprobar_membresia(
            Membresia.objects.create(usuario=mod_sur, asociacion=self.otra, rol=Membresia.Rol.MODERADOR), self.gerente
        )
        with self.assertRaises(PermissionDenied):
            sc.aprobar_archivo(a, mod_sur)
        with self.assertRaises(PermissionDenied):
            sc.aprobar_archivo(a, self.ana.usuario)  # aunque fuera moderadora: es piloto del auto

    def test_no_se_moderan_privados(self):
        with self.assertRaises(ValidationError):
            sc.aprobar_archivo(self.subir(V.PRIVADO), self.mod)


class OrdenYBorradoTests(Base):
    def setUp(self):
        super().setUp()
        suc = Sucursal.objects.create(nombre="Central")
        self.personal.sucursal = suc
        self.personal.save()
        self.personal.groups.add(Group.objects.get(name="administracion"))
        cliente = Cliente.objects.create(nombre="Juan")
        vehiculo = Vehiculo.objects.create(cliente=cliente, patente="AA111AA", marca="Ford", modelo="Falcon")
        self.orden = OrdenTrabajo.objects.create(sucursal=suc, vehiculo=vehiculo, creada_por=self.personal)

    def test_archivos_de_orden(self):
        a = sc.subir_archivo_orden(self.orden, self.personal, tipo=T.FOTO, titulo="Daño", archivo=foto())
        self.assertEqual(a.visibilidad, V.INTERNO)
        self.assertTrue(puede_ver_archivo(self.personal, a))
        self.assertFalse(puede_ver_archivo(self.juan.usuario, a))
        with self.assertRaises(PermissionDenied):
            sc.subir_archivo_orden(self.orden, self.juan.usuario, tipo=T.FOTO, titulo="x", archivo=foto())
        mec = Usuario.objects.create_user("mec", password="x", is_staff=True)
        mec.groups.add(Group.objects.get(name="mecanico"))
        with self.assertRaises(PermissionDenied):  # no está asignado a esta orden
            sc.subir_archivo_orden(self.orden, mec, tipo=T.FOTO, titulo="x", archivo=foto())
        self.orden.tecnico = Tecnico.objects.create(nombre="Mec", usuario=mec)
        self.orden.save()
        sc.subir_archivo_orden(self.orden, mec, tipo=T.FOTO, titulo="Terminado", archivo=foto())

    def test_borrar_quita_el_archivo_fisico(self):
        a = self.subir()
        ruta = Path(PRIVADO) / a.archivo.name
        self.assertTrue(ruta.exists())
        with self.assertRaises(PermissionDenied):
            sc.eliminar_archivo(a, self.extrano.usuario)
        with self.captureOnCommitCallbacks(execute=True):
            sc.eliminar_archivo(a, self.juan.usuario)
        self.assertFalse(ruta.exists())
        self.assertFalse(Archivo.objects.filter(pk=a.pk).exists())
