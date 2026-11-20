# Marca: logos para imprimir y cómo se generan

## stickers/

| Archivo | Para qué |
|---|---|
| `el-taller.svg` | El Taller (logo original) en vector. Es el que hay que mandar a la imprenta: se imprime nítido en cualquier tamaño. |
| `el-taller-4000px.png` | El Taller, PNG transparente de 4000 px de ancho (hasta ~34 cm a 300 dpi). |
| `el-prepa.svg` | El Prepa en vector. |
| `el-prepa-4000px.png` | El Prepa, PNG transparente de 4000 px. |
| `el-prepa-contorno-blanco.svg` / `-4000px.png` | El Prepa con un borde blanco alrededor, para stickers troquelados (el corte va por afuera del blanco). |

Los vectores se calcaron de los JPG originales (`static/img/brand/el-taller.jpg` y `el-prepa.jpg`): mismo dibujo,
con bordes limpios. El Taller ya trae su propio borde blanco y negro tipo calco.

Colores: rojo `#F80308`, azul `#013ECA` (El Taller) · rojo `#D6050B` (El Prepa) · amarillo `#F5B700` (Campeonatos).

## scripts/

Generan los logos. Necesitan, además de `requirements.txt`:
`pip install numpy scipy fonttools potracer` (y Playwright sólo para exportar PNG desde el SVG).

- `quitar_fondo.py original.jpg salida.png ancho area_min`: quita el fondo gris de un JPG (PNG transparente).
- `vectorizar_taller.py taller_limpio.png salida.svg`: El Taller en vector, a partir del PNG de `quitar_fondo.py`.
- `vectorizar_prepa.py prepa_limpio.png salida.svg`: El Prepa en vector, igual.
- `logo_campeonatos.py salida.svg`: logo de Campeonatos.
- `favicons.py carpeta`: íconos de pestaña de las tres partes.
