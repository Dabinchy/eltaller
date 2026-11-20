"""El Prepa en vector: calca la silueta (rojo) y las partes blancas del PNG limpio con potrace."""
import sys

import numpy as np
import potrace
from PIL import Image
from scipy import ndimage

src, dst = sys.argv[1], sys.argv[2]
ESC = 4
im = Image.open(src).convert("RGBA")
grande = im.resize((im.width * ESC, im.height * ESC), Image.LANCZOS)
a = np.asarray(grande).astype(float)
alpha = a[..., 3]
rgb = a[..., :3]

orig = np.asarray(im).astype(float)
rojos = (orig[..., 3] > 250) & (orig[..., 0] > 150) & (orig[..., 1] < 60)
rojo = np.median(orig[rojos][:, :3], axis=0).astype(int)
color_rojo = "#{:02X}{:02X}{:02X}".format(*rojo)

silueta = ndimage.gaussian_filter((alpha > 128).astype(float), 1.2) > 0.5
blanco = (rgb.min(axis=2) > 185) & (alpha > 128)
blanco = ndimage.gaussian_filter(blanco.astype(float), 1.2) > 0.5


def calcar(mask):
    bm = potrace.Bitmap(~mask)   # potracer calca los píxeles en False
    plist = bm.trace(turdsize=40, alphamax=1.1, opticurve=True, opttolerance=0.4)
    partes = []
    for curva in plist:
        P = lambda p: f"{p.x / ESC:.2f} {p.y / ESC:.2f}"
        d = [f"M{P(curva.start_point)}"]
        for s in curva.segments:
            if s.is_corner:
                d.append(f"L{P(s.c)}L{P(s.end_point)}")
            else:
                d.append(f"C{P(s.c1)} {P(s.c2)} {P(s.end_point)}")
        partes.append("".join(d) + "Z")
    return "".join(partes)


d_sil = calcar(silueta)
d_bla = calcar(blanco)
w, h = im.size
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-label="El Prepa">
  <title>El Prepa</title>
  <path fill="{color_rojo}" fill-rule="evenodd" d="{d_sil}"/>
  <path fill="#FFFFFF" fill-rule="evenodd" d="{d_bla}"/>
</svg>
'''
open(dst, "w").write(svg)
print(dst, f"{w}x{h}", color_rojo, f"{len(svg) / 1024:.0f} KB")
