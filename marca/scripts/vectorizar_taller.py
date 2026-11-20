"""El Taller (logo original) en vector: calca por color (silueta negra, blanco, rojo y azul) con potrace."""
import sys

import numpy as np
import potrace
from PIL import Image
from scipy import ndimage

src, dst = sys.argv[1], sys.argv[2]
ESC = 2
im = Image.open(src).convert("RGBA")
a = np.asarray(im.resize((im.width * ESC, im.height * ESC), Image.LANCZOS)).astype(float)
alpha, rgb = a[..., 3], a[..., :3]
r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
dentro = alpha > 128

mascaras = {
    "silueta": dentro,
    "blanco": dentro & (rgb.min(axis=2) > 170),
    "rojo": dentro & (r > 140) & (g < 110) & (b < 110),
    "azul": dentro & (b > 120) & (r < 90) & (b - r > 70),
}
mascaras = {k: ndimage.gaussian_filter(m.astype(float), 1.0) > 0.5 for k, m in mascaras.items()}


def calcar(mask):
    plist = potrace.Bitmap(~mask).trace(turdsize=30, alphamax=1.0, opticurve=True, opttolerance=0.3)
    P = lambda p: f"{p.x / ESC:.2f} {p.y / ESC:.2f}"
    partes = []
    for curva in plist:
        d = [f"M{P(curva.start_point)}"]
        for s in curva.segments:
            d.append(f"L{P(s.c)}L{P(s.end_point)}" if s.is_corner else f"C{P(s.c1)} {P(s.c2)} {P(s.end_point)}")
        partes.append("".join(d) + "Z")
    return "".join(partes)


colores = {"silueta": "#0A0A0A", "blanco": "#FFFFFF", "rojo": "#F80308", "azul": "#013ECA"}
capas = "\n".join(
    f'  <path fill="{colores[k]}" fill-rule="evenodd" d="{calcar(m)}"/>' for k, m in mascaras.items()
)
w, h = im.size
open(dst, "w").write(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="El Taller">\n'
    f"  <title>El Taller</title>\n{capas}\n</svg>\n"
)
print(dst, f"{w}x{h}")
