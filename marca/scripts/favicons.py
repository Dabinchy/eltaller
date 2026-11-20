"""Íconos de pestaña (64x64) de las tres partes."""
import sys

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

dest = sys.argv[1]
NEGRO = "#111111"

# ---------- El Taller: llave roja (boca) y azul (ojo), como en el logo ----------
boca = "M28 2.7A12 12 0 1 0 36 2.7L36 9A4 4 0 0 1 28 9Z"
mango_sup = "M26.5 20H37.5V33H26.5Z"
mango_inf = "M26.5 32H37.5V44H26.5Z"
ojo = "M32 41A10 10 0 1 1 32 61A10 10 0 1 1 32 41ZM32 46.5A4.5 4.5 0 1 0 32 55.5A4.5 4.5 0 1 0 32 46.5Z"
llave = f'''<g transform="translate(32 32) rotate(40) scale(.86) translate(-32 -32)" stroke-linejoin="round">
    <g fill="{NEGRO}" stroke="{NEGRO}" stroke-width="6" fill-rule="evenodd">
      <path d="{boca}"/><path d="{mango_sup}"/><path d="{mango_inf}"/><path d="{ojo}"/>
    </g>
    <g fill-rule="evenodd">
      <path fill="#F5050B" d="{boca}"/><path fill="#F5050B" d="{mango_sup}"/>
      <path fill="#0040CC" d="{mango_inf}"/><path fill="#0040CC" d="{ojo}"/>
    </g>
  </g>'''
taller = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="1" y="1" width="62" height="62" rx="14" fill="#fff" stroke="{NEGRO}" stroke-width="2"/>
  {llave}
</svg>
'''

# ---------- El Prepa: "P" itálica blanca con líneas de velocidad sobre rojo ----------
font = TTFont("/usr/share/fonts/opentype/inter/InterDisplay-BlackItalic.otf")
gs, cmap = font.getGlyphSet(), font.getBestCmap()
upm = font["head"].unitsPerEm
g = cmap[ord("P")]
bp = BoundsPen(gs)
gs[g].draw(bp)
xmin, ymin, xmax, ymax = bp.bounds
alto = 40
esc = alto / (ymax - ymin)
ancho = (xmax - xmin) * esc
ox = 32 - ancho / 2 + 6 - xmin * esc
oy = 32 + alto / 2 + ymin * esc
pen = SVGPathPen(gs)
gs[g].draw(TransformPen(pen, (esc, 0, 0, -esc, ox, oy)))
prepa = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#E3171B"/>
  <g fill="#fff">
    <path d="{pen.getCommands()}"/>
    <path d="M9 22h13l-1.4 5H7.6zM6 31h12l-1.4 5H4.6zM3 40h11l-1.4 5H1.6z" opacity=".9"/>
  </g>
</svg>
'''

# ---------- Campeonatos: bandera a cuadros sobre amarillo ----------
cuad = []
L = 9
for f in range(3):
    for c in range(4):
        color = NEGRO if (f + c) % 2 == 0 else "#fff"
        cuad.append(f'<rect x="{c * L}" y="{f * L}" width="{L}" height="{L}" fill="{color}"/>')
campeonatos = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#F5B700"/>
  <rect x="13" y="9" width="5" height="47" rx="2.5" fill="{NEGRO}"/>
  <g transform="translate(18 12) skewY(8)">
    <rect x="-1.5" y="-1.5" width="{4 * L + 3}" height="{3 * L + 3}" fill="{NEGRO}"/>
    {''.join(cuad)}
  </g>
</svg>
'''

for nombre, svg in (("icono-taller.svg", taller), ("icono-prepa.svg", prepa), ("icono-campeonatos.svg", campeonatos)):
    open(f"{dest}/{nombre}", "w").write(svg)
    print(nombre, len(svg))
