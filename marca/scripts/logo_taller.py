"""
Logo de El Taller en vector (SVG), redibujado a partir del original:
banda inclinada con franjas roja y azul, "EL TALLER" y una llave combinada de verdad
(boca abierta a 15° arriba, estrella de 12 puntas abajo), con borde blanco y negro tipo calco.
"""
import math
import sys

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

dst = sys.argv[1]

ROJO, ROJO_OSC = "#F80308", "#B80006"
AZUL, AZUL_OSC = "#013ECA", "#002A8C"
NEGRO, BLANCO = "#0A0A0A", "#FFFFFF"


def a_path(g, nd=1):
    g = g.simplify(0.35 if nd == 1 else 0.05, preserve_topology=True)
    polys = g.geoms if isinstance(g, MultiPolygon) else [g]
    out = []
    for p in polys:
        for anillo in [p.exterior, *p.interiors]:
            pts = list(anillo.coords)
            out.append("M" + "L".join(f"{x:.{nd}f} {y:.{nd}f}" for x, y in pts[:-1]) + "Z")
    return "".join(out)


def redondear(g, r):
    """Redondea esquinas convexas (abrir) y cóncavas (cerrar)."""
    return g.buffer(-r, join_style=1).buffer(2 * r, join_style=1).buffer(-r, join_style=1)


# ---------------- Llave combinada (sistema local: vertical, boca arriba) ----------------
F = 100                         # medida entre caras de la tuerca (boca y estrella)
H = (0, -395)                   # centro de la cabeza de boca
R = (0, 400)                    # centro del ojo (estrella)

cabeza = Point(H).buffer(128, 128)
# Boca: ranura de ancho F con fondo redondeado, inclinada 15° (como las llaves reales)
ranura = unary_union([box(-F / 2, H[1] - 400, F / 2, H[1] + 22), Point(0, H[1] + 22).buffer(F / 2, 64)])
ranura = affinity.rotate(ranura, 15, origin=H)

mango = Polygon([(-46, -270), (46, -270), (38, 0), (46, 290), (-46, 290), (-38, 0)])
ojo = Point(R).buffer(110, 128)

hexa = Polygon([(R[0] + (F / math.sqrt(3)) * math.cos(math.radians(a)),
                 R[1] + (F / math.sqrt(3)) * math.sin(math.radians(a))) for a in range(0, 360, 60)])
estrella = unary_union([hexa, affinity.rotate(hexa, 30, origin=R)])
estrella = estrella.buffer(-3, join_style=1).buffer(3, join_style=1)

cuerpo = unary_union([cabeza, mango, ojo])
cuerpo = cuerpo.buffer(70, join_style=1).buffer(-70, join_style=1)   # cuello suave (filetes)
llave = cuerpo.difference(ranura).difference(estrella)
llave = llave.buffer(-7, join_style=1).buffer(7, join_style=1)        # puntas de la boca redondeadas

# Posición en el logo (como el original: cruza la banda inclinada, boca arriba a la derecha)
llave = affinity.translate(affinity.rotate(llave, 12, origin=(0, 0)), 617, 487)
estrella_g = affinity.translate(affinity.rotate(estrella, 12, origin=(0, 0)), 617, 487)

# ---------------- Banda ----------------
C = (751, 459)
ANG = -15.2
BW, BH = 1360, 320
ROJA, AZULH = 60, 60


def en_banda(g):
    return affinity.translate(affinity.rotate(g, ANG, origin=(0, 0)), *C)


banda = en_banda(redondear(box(-BW / 2, -BH / 2, BW / 2, BH / 2), 14))
franja_roja = en_banda(box(-BW / 2 - 5, -BH / 2 - 5, BW / 2 + 5, -BH / 2 + ROJA)).intersection(banda)
franja_azul = en_banda(box(-BW / 2 - 5, BH / 2 - AZULH, BW / 2 + 5, BH / 2 + 5)).intersection(banda)

# Mitad de arriba (roja) y de abajo (azul) de la llave: corte por el centro de la banda
arriba = en_banda(box(-5000, -5000, 5000, 0))
abajo = en_banda(box(-5000, 0, 5000, 5000))

# ---------------- Borde tipo calco ----------------
todo = unary_union([banda, llave.union(estrella_g)])
blanco = todo.buffer(21, join_style=1)
negro = todo.buffer(28, join_style=1)

# Bisel de la llave: cara un poco más chica, el borde queda más oscuro (chaflán)
cara = llave.buffer(-11, join_style=1)

# ---------------- Texto ----------------
font = TTFont("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
upm = font["head"].unitsPerEm
cap_em = 0.729
zona = BH - ROJA - AZULH
CAP = 160
tam = CAP / cap_em
esc = tam / upm


def ancho_de(texto, espacio_factor):
    w = 0
    for ch in texto:
        adv = hmtx[cmap[ord(ch)]][0] * esc
        w += adv * (espacio_factor if ch == " " else 1)
    return w


texto = "EL TALLER"
ESPACIO = 0.55
ancho = ancho_de(texto, ESPACIO)
objetivo = BW - 90
sx = objetivo / ancho
pen = SVGPathPen(gs)
cx = 0.0
for ch in texto:
    g = cmap[ord(ch)]
    adv = hmtx[g][0] * esc
    if ch != " ":
        gs[g].draw(TransformPen(pen, (esc * sx, 0, 0, -esc, cx * sx, 0)))
    cx += adv * (ESPACIO if ch == " " else 1)
from fontTools.pens.boundsPen import BoundsPen
bp = BoundsPen(gs)
for ch in "ELTAR":
    gs[cmap[ord(ch)]].draw(bp)
_, ymin_f, _, ymax_f = bp.bounds
alto_real = (ymax_f - ymin_f) * esc
y_base = -BH / 2 + ROJA + zona / 2 + alto_real / 2 + ymin_f * esc
x_ini = -objetivo / 2
texto_svg = (f'<path transform="translate({C[0]} {C[1]}) rotate({ANG}) translate({x_ini:.1f} {y_base:.1f})" '
             f'fill="{NEGRO}" d="{pen.getCommands()}"/>')

# Unión llave-franja sin línea: la franja tapa 5 px de la llave sólo en el borde de la banda
borde_banda = banda.buffer(5).difference(banda.buffer(-1))

# ---------------- SVG ----------------
minx, miny, maxx, maxy = negro.bounds
M = 4
vb = f"{minx - M:.0f} {miny - M:.0f} {maxx - minx + 2 * M:.0f} {maxy - miny + 2 * M:.0f}"


def parte_llave(mitad, base, oscuro):
    borde = llave.intersection(mitad)
    face = cara.intersection(mitad)
    return f'<path fill="{oscuro}" fill-rule="evenodd" d="{a_path(borde)}"/>' \
           f'<path fill="{base}" fill-rule="evenodd" d="{a_path(face)}"/>'


svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="El Taller">
  <title>El Taller</title>
  <path fill="{NEGRO}" fill-rule="evenodd" d="{a_path(negro)}"/>
  <path fill="{BLANCO}" fill-rule="evenodd" d="{a_path(blanco)}"/>
  {parte_llave(arriba, ROJO, ROJO_OSC)}
  {parte_llave(abajo, AZUL, AZUL_OSC)}
  <path fill="{BLANCO}" stroke="{NEGRO}" stroke-width="6" stroke-linejoin="round" d="{a_path(estrella_g)}"/>
  <path fill="{BLANCO}" d="{a_path(banda)}"/>
  <path fill="{ROJO}" d="{a_path(franja_roja.union(cara.intersection(borde_banda).intersection(franja_roja.buffer(6))))}"/>
  <path fill="{AZUL}" d="{a_path(franja_azul.union(cara.intersection(borde_banda).intersection(franja_azul.buffer(6))))}"/>
  {texto_svg}
</svg>
'''
open(dst, "w").write(svg)
print(dst, vb, f"{len(svg) / 1024:.0f} KB", "escala texto x", round(sx, 3))

# ---------------- Ícono de pestaña (64x64) con la misma llave ----------------
if len(sys.argv) > 2:
    # Llave más corta para que a 16 px se siga leyendo (mismas cabezas, mango acortado)
    D = 190
    cab_i, ran_i = affinity.translate(cabeza, 0, D), affinity.translate(ranura, 0, D)
    ojo_i, est_i = affinity.translate(ojo, 0, -D), affinity.translate(estrella, 0, -D)
    mango_i = box(-50, -240, 50, 240)
    base = unary_union([cab_i, mango_i, ojo_i]).buffer(70, join_style=1).buffer(-70, join_style=1)
    l2 = base.difference(ran_i).difference(est_i).buffer(-7, join_style=1).buffer(7, join_style=1)
    e2 = est_i
    # centrar y escalar a 64 px, en diagonal (40°)
    l2 = affinity.rotate(l2, 40, origin=(0, 0)); e2 = affinity.rotate(e2, 40, origin=(0, 0))
    minx, miny, maxx, maxy = l2.buffer(60).bounds
    k = 60 / max(maxx - minx, maxy - miny)
    cxm, cym = (minx + maxx) / 2, (miny + maxy) / 2
    T = lambda g: affinity.translate(affinity.scale(affinity.translate(g, -cxm, -cym), k, k, origin=(0, 0)), 32, 32)
    l2, e2 = T(l2), T(e2)
    mitad_sup = affinity.rotate(box(-100, -100, 100, 32), 40, origin=(32, 32))
    mitad_inf = affinity.rotate(box(-100, 32, 100, 164), 40, origin=(32, 32))
    cara2 = l2.buffer(-1.2, join_style=1)

    def p(g):
        return a_path(g, nd=2).replace("M", "M").strip()

    ico = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="1" y="1" width="62" height="62" rx="14" fill="#fff" stroke="{NEGRO}" stroke-width="2"/>
  <path fill="{NEGRO}" fill-rule="evenodd" d="{p(l2.union(e2).buffer(2.4, join_style=1))}"/>
  <path fill="{ROJO_OSC}" fill-rule="evenodd" d="{p(l2.intersection(mitad_sup))}"/>
  <path fill="{ROJO}" fill-rule="evenodd" d="{p(cara2.intersection(mitad_sup))}"/>
  <path fill="{AZUL_OSC}" fill-rule="evenodd" d="{p(l2.intersection(mitad_inf))}"/>
  <path fill="{AZUL}" fill-rule="evenodd" d="{p(cara2.intersection(mitad_inf))}"/>
  <path fill="#fff" stroke="{NEGRO}" stroke-width="1" stroke-linejoin="round" d="{p(e2)}"/>
</svg>
'''
    open(sys.argv[2], "w").write(ico)
    print(sys.argv[2], len(ico))
