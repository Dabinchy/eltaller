"""Genera static/img/brand/campeonatos.svg: placa amarilla inclinada, bandera a cuadros y texto en trazos."""
import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FUENTE = "/usr/share/fonts/opentype/inter/InterDisplay-BlackItalic.otf"
dst = sys.argv[1]

font = TTFont(FUENTE)
gs = font.getGlyphSet()
cmap = font.getBestCmap()
upm = font["head"].unitsPerEm
hmtx = font["hmtx"]


def texto_a_path(texto, x, y_base, tam, espaciado=0.0):
    esc = tam / upm
    pen = SVGPathPen(gs)
    cx = x
    for ch in texto:
        g = cmap[ord(ch)]
        tp = TransformPen(pen, (esc, 0, 0, -esc, cx, y_base))
        gs[g].draw(tp)
        cx += hmtx[g][0] * esc + espaciado
    return pen.getCommands(), cx - espaciado - x


AMARILLO, NEGRO, BLANCO = "#F5B700", "#111111", "#FFFFFF"
TAM = 100
ALTO = 140
SKEW = 14                 # inclinación de la placa (grados, hacia la derecha)
FILAS = 4
LADO = ALTO / FILAS
BANDERA = 4 * LADO        # bandera a cuadros de 4 x 4
DIV = 9                   # franja negra entre bandera y texto
FRANJA = 16               # franja negra de abajo
GAP = 26

import math

t = math.tan(math.radians(SKEW))
d_texto, ancho_texto = texto_a_path("CAMPEONATOS", 0, 0, TAM, espaciado=1.5)
ancho_placa = BANDERA + DIV + GAP + ancho_texto + GAP
MARGEN = 14
x0 = MARGEN + t * ALTO     # skewX corre la base a la izquierda
y0 = MARGEN
vb_w = x0 + ancho_placa + MARGEN
vb_h = ALTO + 2 * MARGEN

cuadros = "".join(
    f'<rect x="{c * LADO:.1f}" y="{f * LADO:.1f}" width="{LADO:.1f}" height="{LADO:.1f}"/>'
    for f in range(FILAS) for c in range(4) if (f + c) % 2 == 0
)
cap = 0.727 * TAM
medio = (ALTO - FRANJA) / 2            # centro de la zona amarilla
tx = x0 + BANDERA + DIV + GAP - t * medio
ty = y0 + medio + cap / 2

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb_w:.0f} {vb_h:.0f}" role="img" aria-label="Campeonatos">
  <title>Campeonatos</title>
  <defs><clipPath id="placa"><rect width="{ancho_placa:.1f}" height="{ALTO}" rx="10"/></clipPath></defs>
  <g transform="translate({x0:.1f} {y0}) skewX({-SKEW})">
    <rect width="{ancho_placa:.1f}" height="{ALTO}" rx="10" fill="none" stroke="{NEGRO}" stroke-width="24"/>
    <rect width="{ancho_placa:.1f}" height="{ALTO}" rx="10" fill="none" stroke="{BLANCO}" stroke-width="15"/>
    <rect width="{ancho_placa:.1f}" height="{ALTO}" rx="10" fill="{AMARILLO}"/>
    <g clip-path="url(#placa)">
      <rect width="{BANDERA:.1f}" height="{ALTO}" fill="{BLANCO}"/>
      <g fill="{NEGRO}">{cuadros}</g>
      <rect x="{BANDERA:.1f}" width="{DIV}" height="{ALTO}" fill="{NEGRO}"/>
      <rect x="{BANDERA:.1f}" y="{ALTO - FRANJA}" width="{ancho_placa:.1f}" height="{FRANJA}" fill="{NEGRO}"/>
    </g>
  </g>
  <path transform="translate({tx:.1f} {ty:.1f})" fill="{NEGRO}" d="{d_texto}"/>
</svg>
'''
open(dst, "w").write(svg)
print(dst, f"{vb_w:.0f}x{vb_h:.0f}", len(svg), "bytes")
