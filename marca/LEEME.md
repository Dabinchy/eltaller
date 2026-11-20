# Marca: logos para imprimir y cómo se generan

## stickers/

| Archivo | Para qué |
|---|---|
| `el-taller.svg` | El Taller en vector. Es el que hay que mandar a la imprenta: se imprime nítido en cualquier tamaño. |
| `el-taller-4000px.png` | El Taller, PNG transparente de 4000 px de ancho (hasta ~34 cm a 300 dpi). |
| `el-prepa.svg` | El Prepa en vector. |
| `el-prepa-4000px.png` | El Prepa, PNG transparente de 4000 px. |
| `el-prepa-contorno-blanco.svg` / `-4000px.png` | El Prepa con un borde blanco alrededor, para stickers troquelados (el corte va por afuera del blanco). |

El Taller ya trae su propio borde blanco y negro tipo calco.

Colores: rojo `#F80308`, azul `#013ECA` (El Taller) · rojo `#D6050B` (El Prepa) · amarillo `#F5B700` (Campeonatos).

## scripts/

Generan los logos de `static/img/brand/`. Necesitan, además de `requirements.txt`:
`pip install numpy scipy shapely fonttools potracer` (y Playwright sólo para exportar PNG).

- `logo_taller.py salida.svg [icono.svg]`: El Taller en vector (banda, texto y llave combinada) y su ícono de pestaña.
- `logo_campeonatos.py salida.svg`: logo de Campeonatos.
- `quitar_fondo.py original.jpg salida.png ancho area_min`: quita el fondo gris de un JPG.
- `vectorizar_prepa.py prepa_limpio.png salida.svg`: pasa El Prepa a vector (con potrace), a partir del PNG que deja `quitar_fondo.py`.
- `favicons.py carpeta`: íconos de El Prepa y Campeonatos (el de El Taller lo genera `logo_taller.py`; si se corre este, no copiar su `icono-taller.svg`).

Los textos usan tipografías libres (DejaVu Sans Bold e Inter) convertidas a trazos: los SVG no dependen de las fuentes instaladas.
