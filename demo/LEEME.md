# Base de demostración

Datos de ejemplo para mostrar el sistema: el sitio de El Taller, El Prepa y Campeonatos con textos y
fotos, el panel (clientes, vehículos, órdenes, turnos, consultas), el portal (pilotos, autos, un
cliente que sigue su taller) y dos campeonatos con fechas, resultados y tabla de posiciones.

**No toca tus datos reales:** usa otra base (`demo.sqlite3`) y otras carpetas de archivos
(`media_demo/` y `privado_demo/`). Se activa con la variable de entorno `DJANGO_DEMO=1`.

## Abrirla (Windows)

**Doble clic en `demo\iniciar_demo.bat`.** Activa el entorno virtual (`.venv`), prepara la base de
demo (la primera vez la carga, tarda unos segundos), arranca el servidor y abre el navegador en
<http://127.0.0.1:8000/>. Para cerrarla: Ctrl+C en esa ventana.

Para dejarla como nueva (por ejemplo, después de probar cosas): doble clic en `demo\reiniciar_demo.bat`.

Las fotos ya vienen en `demo/fotos/`: no hace falta internet.

### A mano (PowerShell)

```powershell
$env:DJANGO_DEMO="1"
python manage.py migrate
python manage.py cargar_demo          # --reiniciar para borrarla y cargarla de nuevo
python manage.py runserver
```

> `$env:DJANGO_DEMO="1"` vale para esa ventana de PowerShell. Sin esa variable, Django usa tu base real.

## Usuarios (contraseña de todos: `demo1234`)

| Usuario | Rol | Qué mostrar |
|---|---|---|
| `carlos` | Gerente (PIN de caja 1234) | Todo el panel; **Sitio web**; **Accesos al portal** (Rodrigo pidió acceso); cobrar la Hilux en Por cobrar |
| `lucia` | Administración (PIN de caja 5678) | Cargar novedades, trabajos con fotos, servicios; consultas |
| `javier` | Jefe de taller | Órdenes, turnos y consultas del sitio |
| `pablo` | Mecánico | Sólo sus órdenes asignadas |
| `admin` | Superusuario | Todo, incluido el admin de Django (`/admin/`) |
| `laura` | Moderadora de Karting del Valle | Moderación (una cuenta y un auto pendientes), campeonato, novedades |
| `hernan` | Moderador de Turismo Pista del Sur | Lo mismo en su asociación |
| `storres` | Piloto | Su perfil, su auto, sus campeonatos y resultados |
| `marcela` | Clienta del taller | **Mi taller**: su 208 con el presupuesto del embrague para aprobar |
| `rodrigo` | Cliente pendiente | Pidió ver su taller: lo aprueba la gerencia |

## Recorrido sugerido

1. **Sitio público** (sin ingresar): portada de El Taller → Trabajos (con galería antes/después) →
   pestaña El Prepa → Proyectos → pestaña Campeonatos → un campeonato con su tabla → Novedades.
2. Ingresar como **lucia**: arriba del sitio aparece la barra del personal y los lápices para editar;
   en el panel, **Sitio web** para cargar o publicar contenido sin entrar al admin.
3. Como **laura** (moderadora): Moderación → pendientes, Novedades de su asociación, su campeonato.
4. Como **marcela** (clienta): Mi taller → aprobar el presupuesto.
5. Como **carlos** (gerente): Accesos al portal → aprobar a Rodrigo eligiendo su ficha de cliente.

## Empezar de cero

`demo\reiniciar_demo.bat` (o `python manage.py cargar_demo --reiniciar` con `DJANGO_DEMO=1`). Sólo
borra la base de demo y sus archivos; nunca tu base real.

Las fotos tienen licencias libres; los autores están en [CREDITOS.md](CREDITOS.md).
