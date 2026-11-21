"""
Carga una base de DEMOSTRACIÓN con datos de ejemplo: el sitio de las tres partes con textos y
fotos, el panel (clientes, vehículos, órdenes, turnos), el portal (pilotos, autos, cliente que
sigue su taller) y campeonatos con fechas, resultados y tabla de posiciones.

Va en una base aparte (no toca los datos reales). Ver demo/LEEME.md. En Windows (PowerShell):

    $env:DJANGO_DEMO="1"
    python manage.py migrate
    python manage.py cargar_demo
    python manage.py runserver

Todos los usuarios de la demo tienen la contraseña "demo1234" (se listan al terminar).
Las fotos (Wikimedia Commons, licencias libres; ver demo/CREDITOS.md) vienen en demo/fotos/.
Si falta alguna, se intenta bajar (demo/fotos.json) y si no, se usa una imagen de reemplazo.

Opciones: --reiniciar borra la demo y la vuelve a cargar; --si-hace-falta no hace nada si ya está
cargada (lo usa demo/iniciar_demo.bat).
"""
from __future__ import annotations

import json
import random
import time as reloj
import urllib.request
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

CLAVE = "demo1234"
FOTOS = Path(settings.BASE_DIR) / "demo" / "fotos"
MANIFIESTO = Path(settings.BASE_DIR) / "demo" / "fotos.json"
AGENTE = "ElTallerDemo/1.0 (carga de demo local; https://meta.wikimedia.org/wiki/User-Agent_policy)"


def bajar_fotos(escribir) -> int:
    """Baja de Wikimedia Commons las fotos de demo/fotos.json que falten. Devuelve cuántas faltan todavía."""
    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    FOTOS.mkdir(parents=True, exist_ok=True)
    pendientes = [(k, v) for k, v in manifiesto.items() if not (FOTOS / f"{k}.jpg").exists()]
    if pendientes:
        escribir(f"Bajando {len(pendientes)} fotos de Wikimedia Commons (sólo la primera vez)...")
    faltan = 0
    for clave, datos in pendientes:
        original = datos["url"].split("?")[0]          # sin los parámetros de seguimiento (?utm_...)
        ruta, nombre = original.split("/wikipedia/commons/")[1], original.rsplit("/", 1)[1]
        miniatura = nombre if len(nombre) <= 160 else "thumbnail.jpg"   # Commons abrevia los nombres largos
        urls = [f"https://upload.wikimedia.org/wikipedia/commons/thumb/{ruta}/1280px-{miniatura}", original]
        contenido = None
        for intento in range(3):
            for url in urls:
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENTE}), timeout=60) as r:
                        contenido = r.read()
                    break
                except Exception:  # sin internet, límite de pedidos, etc.: se reintenta y si no, imagen de reemplazo
                    continue
            if contenido:
                break
            reloj.sleep(5 * (intento + 1))
        if not contenido:
            faltan += 1
            escribir(f"  no se pudo bajar {clave} (se usa una imagen de reemplazo)")
            continue
        im = Image.open(BytesIO(contenido)).convert("RGB")
        im.thumbnail((1600, 1600))
        im.save(FOTOS / f"{clave}.jpg", format="JPEG", quality=84, optimize=True)
        escribir(f"  {clave} ✓")
        reloj.sleep(1)
    return faltan


def foto(clave: str) -> SimpleUploadedFile:
    """La foto demo/fotos/<clave>.jpg o, si no está, una imagen de reemplazo."""
    ruta = FOTOS / f"{clave}.jpg"
    if ruta.exists():
        return SimpleUploadedFile(f"{clave}.jpg", ruta.read_bytes(), content_type="image/jpeg")
    im = Image.new("RGB", (1600, 1000), (18, 26, 44))
    dr = ImageDraw.Draw(im)
    for y in range(1000):
        dr.line([(0, y), (1600, y)], fill=(18 + y // 25, 26 + y // 30, 44 + y // 12))
    dr.text((60, 900), clave.replace("_", " ").upper(), fill=(220, 230, 245))
    salida = BytesIO()
    im.save(salida, format="JPEG", quality=85)
    return SimpleUploadedFile(f"{clave}.jpg", salida.getvalue(), content_type="image/jpeg")


def logo(iniciales: str, color: tuple) -> SimpleUploadedFile:
    """Logo simple de una asociación (iniciales en un círculo)."""
    im = Image.new("RGB", (400, 400), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    dr.ellipse((20, 20, 380, 380), fill=color)
    try:
        from PIL import ImageFont

        fuente = ImageFont.truetype("DejaVuSans-Bold.ttf", 150)
    except OSError:
        fuente = None
    dr.text((200, 200), iniciales, fill=(255, 255, 255), anchor="mm", font=fuente)
    salida = BytesIO()
    im.save(salida, format="PNG")
    return SimpleUploadedFile(f"logo-{iniciales.lower()}.png", salida.getvalue(), content_type="image/png")


class Command(BaseCommand):
    help = "Carga datos de demostración (en la base aparte DJANGO_DEMO=1)."

    def add_arguments(self, parser):
        parser.add_argument("--forzar", action="store_true",
                            help="Cargar aunque no sea la base de demo (sólo en una base vacía).")
        parser.add_argument("--sin-fotos", action="store_true",
                            help="No bajar fotos de internet (usa las que haya y si no, imágenes de reemplazo).")
        parser.add_argument("--reiniciar", action="store_true",
                            help="Borrar la demo (base y archivos) y volver a cargarla. Sólo con DJANGO_DEMO=1.")
        parser.add_argument("--si-hace-falta", action="store_true",
                            help="Si la demo ya está cargada, no hacer nada.")

    # =====================================================================
    def handle(self, *args, **opciones):
        from core.models import Usuario

        if not settings.DEMO and not opciones["forzar"]:
            raise CommandError(
                "Por seguridad, la demo se carga en una base aparte. Activala con la variable "
                "DJANGO_DEMO=1 (en PowerShell: $env:DJANGO_DEMO=\"1\"), corré migrate y después cargar_demo."
            )
        if opciones["reiniciar"]:
            if not settings.DEMO:
                raise CommandError("--reiniciar sólo se puede usar en la base de demo (DJANGO_DEMO=1).")
            self.reiniciar()
        if Usuario.objects.exists():
            if opciones["si_hace_falta"]:
                self.stdout.write("La demo ya está cargada.")
                return
            raise CommandError(
                "Esta base ya tiene datos. Para empezar de cero: python manage.py cargar_demo --reiniciar "
                "(con DJANGO_DEMO=1)."
            )
        if not opciones["sin_fotos"]:
            bajar_fotos(self.stdout.write)
        self.rnd = random.Random(2026)
        self.hoy = timezone.localdate()
        with transaction.atomic():
            self.empresa_y_personal()
            self.sitio()
            self.taller()
            self.comunidad()
            self.campeonatos()
            self.novedades_y_consultas()
            self.cliente_del_portal()
        self.resumen()

    def reiniciar(self):
        """Vacía la base de demo y borra sus archivos subidos (nunca la base real: lo verifica handle)."""
        import shutil

        from django.core.management import call_command

        self.stdout.write("Borrando la demo anterior...")
        call_command("flush", interactive=False, verbosity=0)   # vuelve a crear grupos y permisos (post_migrate)
        for carpeta in (settings.MEDIA_ROOT, settings.PRIVATE_MEDIA_ROOT):
            if Path(carpeta).name.endswith("_demo"):        # por las dudas: sólo las carpetas de la demo
                shutil.rmtree(carpeta, ignore_errors=True)

    # =====================================================================
    # Empresa, sucursal y personal
    # =====================================================================
    def empresa_y_personal(self):
        from core.models import Empresa, Sucursal, Usuario
        from taller.models import Tecnico

        emp = Empresa.objects.first() or Empresa(nombre="El Taller")
        emp.nombre = "El Taller"
        emp.razon_social = "El Taller Demo SRL"
        emp.direccion = "Av. Mengelle 1450"
        emp.localidad = "Cipolletti"
        emp.provincia = "Río Negro"
        emp.codigo_postal = "8324"
        emp.telefono = "(0299) 477-0000"
        emp.whatsapp = "5492995550101"
        emp.email_contacto = "contacto@example.com"
        emp.horarios = "Lunes a viernes de 8 a 18 h\nSábados de 9 a 13 h"
        emp.instagram = "eltaller_demo"
        emp.descripcion_web = ("Taller mecánico familiar con más de 20 años en el Alto Valle. Mecánica general, "
                               "diagnóstico computarizado y mantenimiento, con presupuesto claro antes de arrancar.")
        emp.save()

        self.suc, _ = Sucursal.objects.get_or_create(nombre="Central", defaults={"direccion": emp.direccion})

        def personal(usuario, nombre, apellido, grupo, staff=False):
            u = Usuario.objects.create_user(
                usuario, password=CLAVE, first_name=nombre, last_name=apellido, email=f"{usuario}@example.com",
                is_staff=staff, sucursal=None if grupo == "gerente" else self.suc,
            )
            u.groups.add(Group.objects.get(name=grupo))
            return u

        Usuario.objects.create_superuser("admin", email="admin@example.com", password=CLAVE,
                                         first_name="Administrador", last_name="Demo")
        self.gerente = personal("carlos", "Carlos", "Romero", "gerente", staff=True)
        self.adm = personal("lucia", "Lucía", "Fernández", "administracion", staff=True)
        self.jefe = personal("javier", "Javier", "Sosa", "jefe")
        self.mec1 = personal("pablo", "Pablo", "Medina", "mecanico")
        self.mec2 = personal("nico", "Nicolás", "Paz", "mecanico")
        for u, pin in ((self.gerente, "1234"), (self.adm, "5678")):   # PIN para las acciones de caja (único)
            u.set_action_pin(pin)
            u.save()
        self.tec1 = Tecnico.objects.create(nombre="Pablo Medina", usuario=self.mec1)
        self.tec2 = Tecnico.objects.create(nombre="Nicolás Paz", usuario=self.mec2)
        self.usuarios = [
            ("Gerente", "carlos", "Ve y aprueba todo; accesos de clientes al portal"),
            ("Administración", "lucia", "Carga el contenido del sitio, clientes, ventas"),
            ("Jefe de taller", "javier", "Órdenes, turnos y consultas del sitio"),
            ("Mecánico", "pablo", "Sus órdenes asignadas"),
            ("Superusuario", "admin", "Todo, incluido el admin de Django"),
        ]

    # =====================================================================
    # Contenido del sitio: portadas, servicios, trabajos, testimonios
    # =====================================================================
    def sitio(self):
        from sitio.models import FotoTrabajo, Portada, Servicio, Testimonio, Trabajo

        Portada.objects.create(
            parte="taller", titulo="Mecánica de confianza en el Alto Valle",
            subtitulo="Service, diagnóstico y reparaciones con presupuesto claro antes de arrancar. "
                      "Seguí el trabajo de tu auto desde el celular.",
            imagen=foto("portada_taller"),
        )
        Portada.objects.create(
            parte="prepa", titulo="Preparamos autos para ganar",
            subtitulo="Competición, personalización y restauración de clásicos, con el respaldo de El Taller.",
            imagen=foto("portada_prepa"),
        )
        Portada.objects.create(
            parte="campeonatos", titulo="Campeonatos de la región",
            subtitulo="Fechas, resultados y tablas de posiciones de karting y turismo, cargados por cada asociación.",
            imagen=foto("portada_campeonatos"),
        )

        taller = [
            ("Service y mantenimiento", "bi-tools", "Aceite, filtros, correas y revisión general según el manual.",
             "Hacemos el service oficial de tu auto sin perder la garantía, con repuestos de primera marca.\n\n"
             "Incluye control de 30 puntos y te avisamos por WhatsApp si encontramos algo más.", "banco"),
            ("Frenos y suspensión", "bi-disc", "Pastillas, discos, amortiguadores y tren delantero.",
             "Medimos el desgaste y te mostramos las piezas antes de cambiarlas. Alineación y balanceo en el día.",
             "suspension"),
            ("Diagnóstico computarizado", "bi-cpu", "Escaneo de fallas con equipo de última generación.",
             "Leemos los códigos de error, revisamos sensores y te explicamos qué hay que hacer y qué puede esperar.",
             "diagnostico"),
            ("Distribución", "bi-gear", "Kit de distribución y bomba de agua con garantía.",
             "Cambiar la correa a tiempo evita roturas de motor caras. Te decimos cuándo le toca a tu auto.", "motor"),
            ("Electricidad del automotor", "bi-lightning-charge", "Baterías, alternadores, arranques y luces.", "", None),
            ("Aire acondicionado", "bi-thermometer-half", "Carga de gas, detección de pérdidas y limpieza.", "", None),
        ]
        for i, (titulo, icono, resumen, desc, img) in enumerate(taller):
            Servicio.objects.create(parte="taller", titulo=titulo, icono=icono, resumen=resumen, descripcion=desc,
                                    imagen=foto(img) if img else None, orden=i, publicado=True)

        prepa = [
            ("competicion", "Preparación de motor", "bi-speedometer2", "Motores para Turismo Pista, karting y regularidad, según reglamento."),
            ("competicion", "Seguridad homologada", "bi-shield-check", "Jaulas, butacas, arneses y matafuegos con certificación."),
            ("competicion", "Puesta a punto en pista", "bi-flag", "Te acompañamos en las pruebas y ajustamos el auto para cada circuito."),
            ("personalizacion", "Potencia y escape", "bi-lightning-charge", "Mejoras de admisión, escape y reprogramación con banco de pruebas."),
            ("personalizacion", "Llantas y suspensión", "bi-arrows-collapse-vertical", "Rebajes, coilovers y llantas que se ven bien y andan mejor."),
            ("clasicos", "Restauración integral", "bi-hourglass-split", "Chapa, pintura, mecánica y tapizado, respetando el original."),
            ("clasicos", "Mecánica de época", "bi-gear", "Motores y cajas de autos clásicos puestos a punto para disfrutarlos."),
        ]
        for i, (seccion, titulo, icono, resumen) in enumerate(prepa):
            Servicio.objects.create(parte="prepa", seccion=seccion, titulo=titulo, icono=icono, resumen=resumen,
                                    orden=i, publicado=True)

        def trabajo(tipo, titulo, auto, resumen, descripcion, portada, galeria, dias, destacado=True):
            t = Trabajo.objects.create(tipo=tipo, titulo=titulo, auto=auto, resumen=resumen, descripcion=descripcion,
                                       portada=foto(portada), fecha=self.hoy - timedelta(days=dias),
                                       destacado=destacado, publicado=True)
            for n, (clave, etapa, epigrafe) in enumerate(galeria):
                FotoTrabajo.objects.create(trabajo=t, imagen=foto(clave), etapa=etapa, epigrafe=epigrafe, orden=n)
            return t

        trabajo("calle", "Cambio de distribución y bomba de agua", "VW Gol Trend 1.6 2015",
                "Kit completo, bomba de agua y tensores a los 60.000 km.",
                "El cliente vino por un ruido en frío. Encontramos la correa con desgaste y la bomba con pérdida.\n\n"
                "Cambiamos el kit completo y la bomba, y le entregamos el auto en el día.",
                "gol", [("motor", "antes", "Así llegó: pérdida de refrigerante"), ("banco", "proceso", "Kit original"),
                        ("gol", "despues", "Listo para otros 60.000 km")], 12)
        trabajo("calle", "Frenos completos y tren delantero", "Toyota Hilux 2.8 2016",
                "Discos, pastillas, extremos de dirección y alineación.",
                "Una camioneta de trabajo que hace muchos kilómetros de ripio. Renovamos frenos y tren delantero.",
                "hilux", [("suspension", "proceso", "Revisión del tren delantero"), ("hilux", "despues", "Entregada")], 25)
        trabajo("calle", "Diagnóstico de falla intermitente", "Fiat Cronos 1.3 2024",
                "Testigo de motor encendido: era un sensor de oxígeno.",
                "Con el escáner encontramos el código y medimos el sensor en marcha. Cambio y borrado de fallas.",
                "cronos", [("diagnostico", "proceso", "Lectura de códigos de error")], 40)
        trabajo("calle", "Service de los 80.000 km", "Peugeot 208 1.6 2015",
                "Aceite, filtros, bujías y revisión de 30 puntos.", "", "p208", [], 55, destacado=False)
        trabajo("calle", "Embrague nuevo", "Ford Ranger 2.2 XLS 2017",
                "Kit de embrague y volante bimasa, con garantía de un año.", "", "ranger", [], 70, destacado=False)

        trabajo("competicion", "Motor de Turismo Pista Clase 2", "Turismo Pista · Clase 2",
                "Armado completo del motor según reglamento, con banco de pruebas.",
                "Desarmamos, medimos y armamos el motor pieza por pieza, respetando el reglamento técnico de la "
                "categoría. Después, puesta a punto en cada fecha del campeonato.", "motor",
                [("banco", "proceso", "Armado en el banco"), ("tc_peloton", "despues", "En carrera")], 30)
        trabajo("competicion", "Karting Senior para el zonal", "Karting · Senior",
                "Motor y chasis preparados para el Campeonato Zonal.",
                "Puesta a punto de motor y chasis, y acompañamiento en las pruebas antes de cada fecha.", "kart_3",
                [("kart_2", "proceso", "Pruebas en el kartódromo"), ("kart_1", "despues", "En carrera")], 45)
        trabajo("clasico", "Restauración IKA Torino 380 W", "IKA Torino 380 W 1967",
                "Un año de trabajo: chapa, pintura original y motor a nuevo.",
                "El auto llegó desarmado y con óxido en el piso. Lo restauramos respetando cada detalle de fábrica, "
                "con el proceso documentado foto por foto para el dueño.", "torino", [("torino", "despues", "Terminado")], 60)
        trabajo("clasico", "Ford Falcon Sprint 1978", "Ford Falcon Sprint 3.6",
                "Mecánica completa y pintura en sus colores originales.", "", "falcon", [], 90)
        trabajo("clasico", "Fiat 600 S", "Fiat 600 S 1982", "El primer auto del abuelo, otra vez en la calle.",
                "Lo trajeron sin funcionar después de veinte años guardado. Motor, frenos, instalación eléctrica y "
                "tapizado nuevos, manteniendo su pintura original.", "fiat600", [], 120)
        trabajo("personalizacion", "Golf GTI: potencia y estética", "Volkswagen Golf GTI 2017",
                "Reprogramación, escape completo y llantas 18\".", "", "golf", [], 35)

        for parte, nombre, detalle, texto in [
            ("taller", "Marcela G.", "Peugeot 208 · clienta desde 2019",
             "Me explicaron todo antes de arrancar y cumplieron con el plazo. Poder ver el avance desde el celular es buenísimo."),
            ("taller", "Raúl P.", "Toyota Hilux", "Atención impecable. Me mostraron las piezas viejas y el precio fue el del presupuesto."),
            ("taller", "Sofía L.", "VW Gol Trend", "Excelentes. Me salvaron un viaje: me atendieron en el día."),
            ("taller", "Jorge M.", "Ford Ranger", "Gente seria y que sabe. Hace años que llevo mis autos acá."),
            ("taller", "Carolina B.", "Fiat Cronos", "Me encontraron la falla que otro taller no pudo. Y me cobraron lo justo."),
            ("taller", "Hugo R.", "Peugeot 208", "Me avisaron por WhatsApp cada paso. Así da gusto dejar el auto."),
            ("prepa", "Martín A.", "Piloto de Turismo Pista", "El auto quedó impecable para la primera fecha y en cada carrera estuvieron al lado nuestro."),
            ("prepa", "Ana S.", "Dueña del Torino", "La restauración superó lo que imaginaba. Ver las fotos de cada etapa fue emocionante."),
            ("prepa", "Pedro V.", "Golf GTI", "Le ganaron potencia sin perder confiabilidad. Lo uso todos los días."),
        ]:
            Testimonio.objects.create(parte=parte, nombre=nombre, detalle=detalle, texto=texto, publicado=True)

    # =====================================================================
    # Taller: productos, clientes, vehículos, órdenes y turnos
    # =====================================================================
    def taller(self):
        from clientes.models import Cliente
        from productos.models import Categoria, Producto, ajustar_stock
        from taller.models import OrdenItem, OrdenTrabajo, Turno, Vehiculo

        cats = {n: Categoria.objects.create(nombre=n) for n in ("Lubricantes", "Filtros", "Frenos", "Distribución", "Mano de obra")}
        P = {}
        for clave, nombre, cat, marca, precio, stock in [
            ("aceite", "Aceite 5W30 sintético (4 L)", "Lubricantes", "Shell", "48900", 24),
            ("filtro_aceite", "Filtro de aceite", "Filtros", "Fram", "9800", 30),
            ("filtro_aire", "Filtro de aire", "Filtros", "Fram", "12500", 18),
            ("pastillas", "Pastillas de freno delanteras", "Frenos", "Ferodo", "38500", 12),
            ("discos", "Par de discos de freno", "Frenos", "Fremax", "96000", 6),
            ("kit_dist", "Kit de distribución con bomba", "Distribución", "SKF", "185000", 4),
            ("embrague", "Kit de embrague", "Distribución", "Sachs", "260000", 3),
        ]:
            P[clave] = Producto.objects.create(nombre=nombre, categoria=cats[cat], marca=marca, precio_base=Decimal(precio))
            ajustar_stock(sucursal=self.suc, producto=P[clave], delta=stock, tipo="COMPRA")
        P["mo"] = Producto.objects.create(nombre="Mano de obra (hora)", tipo="SERVICIO", categoria=cats["Mano de obra"],
                                          precio_base=Decimal("28000"))
        P["scanner"] = Producto.objects.create(nombre="Diagnóstico con escáner", tipo="SERVICIO",
                                               categoria=cats["Mano de obra"], precio_base=Decimal("35000"))

        self.clientes = {}
        self.vehiculos = {}
        for clave, nombre, doc, tel, autos in [
            ("marcela", "Marcela Gómez", "28444555", "2994 55-1234", [("AC123BD", "Peugeot", "208 1.6", 2019, 58000)]),
            ("raul", "Raúl Peralta", "23111999", "2994 12-3456", [("AA456CD", "Toyota", "Hilux 2.8", 2016, 182000)]),
            ("sofia", "Sofía López", "35222111", "2984 66-7788", [("AB789EF", "Volkswagen", "Gol Trend 1.6", 2015, 61000)]),
            ("jorge", "Jorge Martínez", "20555444", "2994 88-9900", [("AD321GH", "Ford", "Ranger 2.2", 2017, 140000),
                                                                      ("AE654IJ", "Fiat", "Cronos 1.3", 2024, 18000)]),
            ("rodrigo", "Rodrigo Díaz", "31777666", "2995 44-1122", [("AF987KL", "Renault", "Sandero 1.6", 2018, 90000)]),
        ]:
            c = Cliente.objects.create(nombre=nombre, doc_tipo="DNI", doc_numero=doc, telefono=tel,
                                       email=f"{clave}@example.com")
            self.clientes[clave] = c
            for patente, marca, modelo, anio, km in autos:
                self.vehiculos[patente] = Vehiculo.objects.create(cliente=c, patente=patente, marca=marca, modelo=modelo,
                                                                  anio=anio, km_actual=km)

        E = OrdenTrabajo.Estado

        def orden(cliente, patente, tecnico, motivo, diagnostico, items, estados, dias_atras):
            o = OrdenTrabajo.objects.create(
                sucursal=self.suc, cliente=self.clientes[cliente], vehiculo=self.vehiculos[patente], tecnico=tecnico,
                km_ingreso=self.vehiculos[patente].km_actual, motivo_cliente=motivo, diagnostico=diagnostico,
                creada_por=self.adm, fecha_ingreso=timezone.now() - timedelta(days=dias_atras),
                fecha_prometida=timezone.make_aware(datetime.combine(self.hoy + timedelta(days=2), time(18, 0))),
            )
            for prod, cant in items:
                OrdenItem.objects.create(orden=o, producto=P[prod], cantidad=Decimal(cant), tecnico=tecnico)
            o.recalcular_totales()
            for estado in estados:
                o.cambiar_estado(estado, user=self.gerente)
            return o

        self.orden_marcela = orden(
            "marcela", "AC123BD", self.tec1, "Patina el embrague en cuarta y quinta.",
            "Embrague con desgaste al límite. Se recomienda kit completo.", [("embrague", "1"), ("mo", "4")], [], 1)
        orden("sofia", "AB789EF", self.tec1, "Service de los 60.000 km.", "Service según manual.",
              [("aceite", "1"), ("filtro_aceite", "1"), ("filtro_aire", "1"), ("mo", "1.5")],
              [E.APROBADA, E.EN_PROCESO], 1)
        hilux = orden("raul", "AA456CD", self.tec2, "Ruido al frenar.", "Discos y pastillas gastados.",
                      [("discos", "1"), ("pastillas", "1"), ("mo", "2")], [E.APROBADA, E.EN_PROCESO, E.TERMINADA], 3)
        pastillas = orden("sofia", "AB789EF", self.tec2, "Cambio de pastillas.", "Pastillas al 10 %.",
                          [("pastillas", "1"), ("mo", "1")], [E.APROBADA, E.EN_PROCESO, E.TERMINADA], 4)
        orden("jorge", "AE654IJ", self.tec2, "Luz de motor encendida.", "Sensor de oxígeno con lectura errática.",
              [("scanner", "1"), ("mo", "1")], [E.APROBADA], 0)
        orden("jorge", "AD321GH", self.tec1, "Hace 140.000 km: cambio de distribución.", "",
              [("kit_dist", "1"), ("mo", "5")], [E.APROBADA, E.EN_PROCESO], 2)

        # Caja abierta y la Hilux entregada: queda una venta por cobrar en el panel.
        from core.models import Caja, SesionCaja

        caja = Caja.objects.create(sucursal=self.suc, numero=1, nombre="Caja mostrador")
        sesion = SesionCaja.objects.create(caja=caja, abierta_el=timezone.now(), abierta_por=self.adm,
                                           saldo_inicial=Decimal("50000"), saldo_estimado=Decimal("50000"))
        hilux.entregar(user=self.gerente, sesion=sesion)
        # Otra entregada y cobrada en efectivo: aparece en el listado de ventas
        pastillas.entregar(user=self.gerente, sesion=sesion)
        pastillas.refresh_from_db()
        pastillas.venta.finalizar(user=self.gerente)

        # Proveedores y compras: una confirmada (sumó stock) y otra en borrador
        from compras.models import Compra, CompraDetalle, Proveedor

        lubri = Proveedor.objects.create(nombre="Lubricentro Patagónico SA", documento="30711222339",
                                         telefono="(0299) 442-1100", email="ventas@example.com")
        Proveedor.objects.create(nombre="Repuestos del Valle SRL", documento="30699888771", telefono="(0299) 478-5500")
        c = Compra.objects.create(proveedor=lubri, sucursal=self.suc, creada_por=self.jefe,
                                  observaciones="Factura A 0003-00012345")
        for prod, cant, costo in (("aceite", "12", "31000"), ("filtro_aceite", "20", "5200"), ("filtro_aire", "10", "7100")):
            CompraDetalle.objects.create(compra=c, producto=P[prod], cantidad=Decimal(cant), costo_unitario=Decimal(costo))
        c.refresh_from_db()
        c.confirmar(user=self.gerente)
        borrador = Compra.objects.create(proveedor=lubri, sucursal=self.suc, creada_por=self.jefe,
                                         observaciones="Pedido para la semana que viene")
        CompraDetalle.objects.create(compra=borrador, producto=P["pastillas"], cantidad=Decimal("6"),
                                     costo_unitario=Decimal("24000"))

        manana = self.hoy + timedelta(days=1)
        for cliente, patente, dia, hora, motivo in [
            ("rodrigo", "AF987KL", self.hoy + timedelta(days=0 if timezone.localtime().hour < 15 else 1), 16, "Revisión de frenos"),
            ("sofia", "AB789EF", manana, 9, "Alineación y balanceo"),
            ("raul", "AA456CD", manana, 11, "Retira la camioneta"),
        ]:
            inicio = timezone.make_aware(datetime.combine(dia, time(hora, 0)))
            Turno.objects.create(sucursal=self.suc, cliente=self.clientes[cliente], vehiculo=self.vehiculos[patente],
                                 inicio=inicio, duracion_min=60, motivo=motivo, creado_por=self.adm)

    # =====================================================================
    # Comunidad de pilotos: asociaciones, moderadores, pilotos y autos
    # =====================================================================
    def _portal(self, usuario, nombre, apellido, dni):
        from core.models import Usuario

        return Usuario.objects.create_user(usuario, password=CLAVE, tipo=Usuario.Tipo.PORTAL, first_name=nombre,
                                           last_name=apellido, email=f"{usuario}@example.com", dni=dni)

    def comunidad(self):
        from portal import servicios as sp
        from portal.models import Asociacion, Membresia

        self.asoc_kart = Asociacion.objects.create(
            nombre="Karting del Valle", instagram="kartingdelvalle_demo", logo=logo("KV", (220, 38, 38)),
            descripcion="Asociación de karting del Alto Valle: campeonato zonal con categorías Junior y Senior.")
        self.asoc_tur = Asociacion.objects.create(
            nombre="Turismo Pista del Sur", instagram="turismopistasur_demo", logo=logo("TS", (37, 99, 235)),
            descripcion="Turismo Pista regional: Clase 2 y Clase 3 en los autódromos de la Patagonia.")

        def moderador(usuario, nombre, apellido, dni, asoc):
            u = self._portal(usuario, nombre, apellido, dni)
            sp.aprobar_membresia(Membresia.objects.create(usuario=u, asociacion=asoc, rol=Membresia.Rol.MODERADOR),
                                 self.gerente)
            return u

        self.mod_kart = moderador("laura", "Laura", "Ríos", "30123456", self.asoc_kart)
        self.mod_tur = moderador("hernan", "Hernán", "Castro", "27654321", self.asoc_tur)
        self.usuarios += [
            ("Moderadora · Karting del Valle", "laura", "Aprueba pilotos y fotos, carga campeonato y novedades"),
            ("Moderador · Turismo Pista del Sur", "hernan", "Igual, en su asociación"),
        ]

        nombres = ["Tomás Aguirre", "Valentina Ruiz", "Joaquín Herrera", "Camila Benítez", "Mateo Acosta",
                   "Lucas Molina", "Agustina Ortiz", "Franco Silva", "Martina Rojas", "Bruno Giménez", "Ignacio Vera",
                   "Julieta Suárez", "Santiago Torres", "Emilia Navarro", "Facundo Ríos", "Lautaro Cabrera",
                   "Delfina Correa", "Thiago Medina", "Renata Vázquez", "Gonzalo Paredes", "Milagros Ibáñez",
                   "Nahuel Quiroga", "Florencia Godoy", "Ezequiel Romero"]
        self.pilotos = {"kart": [], "tur": []}
        for i, nombre in enumerate(nombres):
            grupo = "kart" if i < 12 else "tur"
            asoc, mod = (self.asoc_kart, self.mod_kart) if grupo == "kart" else (self.asoc_tur, self.mod_tur)
            nombre_p, apellido = nombre.split(" ", 1)
            usuario = (nombre_p[0] + apellido).lower().replace("á", "a").replace("é", "e").replace("í", "i") \
                .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
            u = self._portal(usuario, nombre_p, apellido, f"{38000000 + i * 7919}")
            sp.aprobar_membresia(Membresia.objects.create(usuario=u, asociacion=asoc), self.gerente)
            perfil = self._perfil(u, nombre, grupo, i)
            sp.aprobar_perfil(perfil, mod)
            self.pilotos[grupo].append(perfil)
        self.usuarios.append(("Piloto", self.pilotos["tur"][0].usuario.username, "Su perfil, autos, archivos y resultados"))

        # Autos con foto (aprobados por su moderador)
        from portal import servicios_contenido as sc
        from portal.models_contenido import Archivo

        self.autos = {}
        for grupo, idx, marca, modelo, numero, categoria, img in [
            ("tur", 0, "Fiat", "Uno Turismo Pista", "12", "Clase 2", None),
            ("tur", 1, "Volkswagen", "Gol Turismo Pista", "7", "Clase 2", None),
            ("tur", 6, "Ford", "Ka Turismo Pista", "33", "Clase 3", None),
            ("kart", 0, "Kart", "Chasis Mini · motor 125", "21", "Senior", "kart_3"),
            ("kart", 1, "Kart", "Chasis Kosmic · motor 125", "5", "Senior", "kart_1"),
            ("kart", 6, "Kart", "Chasis Birel · motor 60", "44", "Junior", "kart_2"),
        ]:
            perfil = self.pilotos[grupo][idx]
            mod = self.mod_tur if grupo == "tur" else self.mod_kart
            a = sc.crear_auto(perfil, marca=marca, modelo=modelo, anio=2022, numero_competicion=numero, categoria=categoria,
                              descripcion=f"{marca} {modelo} preparado por El Prepa para el campeonato {self.hoy.year}.")
            if img:
                f = sc.subir_archivo_piloto(perfil, tipo=Archivo.Tipo.FOTO, titulo=f"{marca} {modelo}",
                                            visibilidad=Archivo.Visibilidad.PUBLICO, auto=a, archivo=foto(img))
                sc.aprobar_archivo(f, mod)
                sc.elegir_portada(a, perfil, f)
            sc.publicar_auto(a, perfil, True)
            sc.aprobar_auto(a, mod)
            self.autos[perfil.pk] = a

        # Pendientes para mostrar la moderación: una cuenta nueva y un auto sin aprobar
        nuevo = self._portal("fluna", "Federico", "Luna", "40111222")
        Membresia.objects.create(usuario=nuevo, asociacion=self.asoc_kart)
        perfil = self.pilotos["kart"][3]
        a = sc.crear_auto(perfil, marca="Kart", modelo="Chasis Tony · motor 125", anio=2023, numero_competicion="9",
                          categoria="Senior", descripcion="Recién armado para la segunda mitad del año.")
        sc.publicar_auto(a, perfil, True)

    def _perfil(self, usuario, nombre, grupo, i):
        from portal.models import PerfilPiloto

        anios = 19 + (i * 3) % 14
        desde = 2014 + i % 9
        bio = (f"Corro en {'karting' if grupo == 'kart' else 'Turismo Pista'} desde {desde}. "
               + self.rnd.choice(["Me gustan los circuitos rápidos y las carreras con lluvia.",
                                  "Mi objetivo este año es pelear el campeonato.",
                                  "Preparo el auto con mi familia y el equipo de El Prepa.",
                                  "Empecé en karting a los 10 años y nunca paré."]))
        return PerfilPiloto.objects.create(
            usuario=usuario, nombre_publico=nombre, bio=bio, perfil_publico=True,
            fecha_nacimiento=self.hoy.replace(year=self.hoy.year - anios) - timedelta(days=40 + i),
            licencia=f"LIC-{2026}-{100 + i}",
        )

    # =====================================================================
    # Campeonatos con fechas, resultados y tabla
    # =====================================================================
    def campeonatos(self):
        from campeonatos import servicios as s
        from campeonatos.models import Campeonato, Fecha

        def armar(asoc, mod, nombre, categorias, pilotos, circuitos, descripcion):
            camp = s.crear_campeonato(asoc, mod, nombre=nombre, temporada=self.hoy.year, descripcion=descripcion,
                                      puntos_pole=1, puntos_vuelta_rapida=1, plazo_carga_dias=60)
            s.definir_tabla_puntos(camp, mod, [25, 20, 16, 13, 11, 10, 9, 8, 7, 6])
            cats = [s.crear_categoria(camp, mod, c, orden=n) for n, c in enumerate(categorias)]
            s.cambiar_estado(camp, mod, Campeonato.Estado.EN_CURSO)
            inscriptos = {c.pk: [] for c in cats}
            for n, perfil in enumerate(pilotos):
                cat = cats[0] if n < len(pilotos) // 2 else cats[1]
                s.inscribirse(perfil, cat, str(n + 2), self.autos.get(perfil.pk))
                inscriptos[cat.pk].append(perfil)
            dias = [-50, -36, -22, -8, 6, 20]
            for numero, (dia, circuito) in enumerate(zip(dias, circuitos), start=1):
                ciudad = circuito.split(" de ")[-1].replace("Kartódromo ", "").replace("Circuito ", "")
                fecha = s.crear_fecha(camp, mod, numero=numero, nombre=f"Gran Premio {ciudad}",
                                      circuito=circuito, dia=self.hoy + timedelta(days=dia))
                if dia > 0:
                    continue
                final = fecha.carreras.get()
                for cat in cats:
                    orden = inscriptos[cat.pk][:]
                    self.rnd.shuffle(orden)
                    for pos, perfil in enumerate(orden, start=1):
                        s.cargar_resultado(perfil, final, posicion=pos, pole=pos == 1 and numero % 2 == 1,
                                           vuelta_rapida=pos == 2)
                    if dia < -10:  # la última fecha queda con resultados provisorios
                        s.validar_carrera(final, cat, mod)
                fecha.estado = Fecha.Estado.DISPUTADA
                fecha.save()
            return camp

        self.camp_kart = armar(
            self.asoc_kart, self.mod_kart, "Campeonato Zonal de Karting", ["Senior", "Junior"], self.pilotos["kart"],
            ["Kartódromo Cipolletti", "Kartódromo Neuquén", "Circuito Allen", "Kartódromo Cipolletti", "Kartódromo Roca", "Circuito Allen"],
            "Seis fechas en los kartódromos del Alto Valle. Suman los diez primeros, la pole y la vuelta rápida.")
        self.camp_tur = armar(
            self.asoc_tur, self.mod_tur, "Turismo Pista Regional", ["Clase 2", "Clase 3"], self.pilotos["tur"],
            ["Autódromo de Neuquén", "Autódromo de Viedma", "Autódromo de Trelew", "Autódromo de Neuquén",
             "Autódromo de Bahía Blanca", "Autódromo de Neuquén"],
            "El campeonato regional de Turismo Pista en los autódromos de la Patagonia.")

    # =====================================================================
    # Novedades y consultas
    # =====================================================================
    def novedades_y_consultas(self):
        from portal import servicios as sp
        from portal.models import RegistroModeracion
        from sitio.models import Consulta, Publicacion

        ahora = timezone.now()
        cuerpo = ("Seguimos creciendo para atenderte mejor.\n\n"
                  "Con este cambio reducimos los tiempos de espera y podemos darte turno en menos días. "
                  "Pedí el tuyo por WhatsApp o desde la web.")
        for parte, titulo, resumen, img, dias, extra in [
            ("taller", "Sumamos un segundo elevador", "Más rapidez para los turnos de mantenimiento.", "banco", 3, {}),
            ("taller", "Nuevo escáner para todas las marcas", "Diagnóstico más preciso, también para autos híbridos.", "diagnostico", 18, {}),
            ("taller", "Horario de verano", "De diciembre a febrero atendemos de 7 a 15 h.", None, 32, {}),
            ("prepa", "Abrimos cupos para la temporada que viene", "Si querés correr el año próximo, es momento de empezar el auto.", "portada_prepa", 8, {}),
            ("prepa", "El Torino 380 W, terminado", "Mirá las fotos de un año de restauración.", "torino", 50, {}),
            ("campeonatos", "Así quedó la tabla del Turismo Pista Regional", "Después de cuatro fechas, la Clase 2 está más pareja que nunca.",
             "tc_peloton", 6, {"asociacion": self.asoc_tur, "campeonato": self.camp_tur, "autor": self.mod_tur}),
            ("campeonatos", "Karting: se corrigió el resultado de la Fecha 3", "Revisamos los tiempos de la final Junior: cambia el podio.",
             "kart_3", 15, {"asociacion": self.asoc_kart, "campeonato": self.camp_kart, "autor": self.mod_kart}),
            ("campeonatos", "Ya está el calendario de la segunda mitad del año", "Seis fechas más, dos de ellas nocturnas.",
             "portada_campeonatos", 20, {"asociacion": self.asoc_kart, "autor": self.mod_kart}),
        ]:
            pub = Publicacion.objects.create(parte=parte, titulo=titulo, resumen=resumen, cuerpo=cuerpo,
                                             portada=foto(img) if img else None, fecha=ahora - timedelta(days=dias),
                                             publicada=True, **extra)
            if extra.get("autor"):
                sp.registrar(extra["autor"], RegistroModeracion.Accion.CREAR, pub, extra["asociacion"])
        Publicacion.objects.create(parte="taller", titulo="Jornada de revisión gratuita para invierno",
                                   resumen="Revisamos frenos, luces y neumáticos sin cargo.", cuerpo=cuerpo,
                                   fecha=ahora + timedelta(days=10), publicada=True)    # programada
        Publicacion.objects.create(parte="prepa", titulo="Borrador: nuevo banco de potencia",
                                   resumen="Todavía no está publicado: así se ve un borrador.", cuerpo=cuerpo)

        for tipo, parte, nombre, tel, email, vehiculo, mensaje, estado in [
            ("presupuesto", "taller", "Gabriela Sánchez", "2994 33-2211", "", "Chevrolet Onix 2020",
             "Hola, necesito presupuesto para el service de los 40.000 km. ¿Tienen turno esta semana?", "nueva"),
            ("presupuesto", "taller", "Diego Funes", "", "diego@example.com", "Renault Kangoo 2014",
             "Hace un ruido en la rueda delantera derecha cuando giro. ¿Cuánto saldría revisarla?", "nueva"),
            ("proyecto", "prepa", "Lucas Ferreyra", "2995 66-7788", "", "Renault Clio 2008",
             "Quiero preparar el Clio para correr regularidad el año que viene. ¿Por dónde arrancamos?", "nueva"),
            ("contacto", "taller", "Ana Paz", "1155554444", "", "", "¿Abren los sábados a la tarde?", "respondida"),
            ("contacto", "taller", "Mario Gil", "", "mario@example.com", "", "Gracias por la atención de ayer.", "archivada"),
        ]:
            c = Consulta.objects.create(tipo=tipo, parte=parte, nombre=nombre, telefono=tel, email=email,
                                        vehiculo=vehiculo, mensaje=mensaje)
            if estado != "nueva":
                c.marcar(estado, self.jefe)

    # =====================================================================
    # Cliente que sigue su taller desde el portal
    # =====================================================================
    def cliente_del_portal(self):
        from portal import servicios as sp
        from portal.models import AccesoCliente

        marcela = self._portal("marcela", "Marcela", "Gómez", "28444555")
        acceso = AccesoCliente.objects.create(usuario=marcela, nombre_declarado="Marcela Gómez", doc_declarado="28444555",
                                              nota="Tengo el 208 en el taller.")
        sp.aprobar_acceso(acceso, self.gerente, cliente=self.clientes["marcela"], rol=AccesoCliente.Rol.TITULAR)
        rodrigo = self._portal("rodrigo", "Rodrigo", "Díaz", "31777666")
        AccesoCliente.objects.create(usuario=rodrigo, nombre_declarado="Rodrigo Díaz", doc_declarado="31.777.666",
                                     nota="Llevé el Sandero el mes pasado a revisar los frenos.")
        self.usuarios += [
            ("Cliente del taller (portal)", "marcela", "Sigue su 208 y puede aprobar el presupuesto del embrague"),
            ("Cliente pendiente", "rodrigo", "Pidió acceso: lo aprueba la gerencia en Panel → Accesos al portal"),
        ]

    # =====================================================================
    def resumen(self):
        self.stdout.write(self.style.SUCCESS("\nBase de demostración cargada."))
        self.stdout.write("Con runserver: sitio http://127.0.0.1:8000/ · ingreso http://127.0.0.1:8000/ingresar/ "
                          "(el personal va al panel; pilotos, moderadores y clientes, al portal).")
        self.stdout.write(f"Contraseña de todos: {CLAVE} · PIN de caja: carlos 1234, lucia 5678\n")
        ancho = max(len(r) for r, _, _ in self.usuarios)
        for rol, usuario, que in self.usuarios:
            self.stdout.write(f"  {rol.ljust(ancho)}  {usuario.ljust(10)}  {que}")
        manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
        faltan = [c for c in manifiesto if not (FOTOS / f"{c}.jpg").exists()]
        if faltan:
            self.stdout.write(self.style.WARNING(
                f"\nFaltan {len(faltan)} fotos (se usaron imágenes de reemplazo). Con internet: "
                "python manage.py cargar_demo --reiniciar"))
        self.stdout.write("Fotos: Wikimedia Commons, licencias libres; autores en demo/CREDITOS.md.")
