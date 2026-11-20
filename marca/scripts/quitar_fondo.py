"""Quita el fondo gris de un logo JPG: PNG transparente, recortado y achicado."""
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

src, dst, ancho, min_area = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
im = np.asarray(Image.open(src).convert("RGB")).astype(np.float64)
h, w, _ = im.shape

# Color de fondo: mediana de los bordes.
borde = np.concatenate([im[0], im[-1], im[:, 0], im[:, -1]])
bg = np.median(borde, axis=0)

dist = np.sqrt(((im - bg) ** 2).sum(axis=2))
cerca = dist < 38
lab, n = ndimage.label(cerca)
toca = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
fondo = np.isin(lab, list(toca))
# Huecos cerrados (agujero de la llave, espacio entre letras): el gris exacto del fondo.
exacto = dist <= 3
lab_e, n_e = ndimage.label(exacto)
areas_e = ndimage.sum(exacto, lab_e, range(1, n_e + 1))
huecos = np.isin(lab_e, [i for i, ar in enumerate(areas_e, start=1) if ar >= 40])
# El hueco crece sólo por píxeles grises neutros más oscuros que el blanco del logo (no se come
# el borde blanco); el borde se suaviza después según el brillo (ver más abajo).
neutro = (im.max(axis=2) - im.min(axis=2)) < 20
grisaceo = neutro & (im.min(axis=2) < 251) & (im.min(axis=2) > 215)
huecos = ndimage.binary_propagation(huecos, mask=grisaceo)
fondo |= huecos
banda_huecos = ndimage.binary_dilation(huecos, iterations=3) & ~huecos & neutro

# Franja de 3 px alrededor del fondo: "color a transparente" (bordes suaves, sin halo gris).
franja = ndimage.binary_dilation(fondo, iterations=3) & ~fondo
alpha = np.ones((h, w))
alpha[fondo] = 0.0
a = np.where(im < bg, (bg - im) / np.maximum(bg, 1), (im - bg) / np.maximum(255 - bg, 1)).max(axis=2)
a = np.clip(a, 0, 1)
alpha[franja] = a[franja]

rgb = im.copy()
sel = franja & (a > 0.01)
rgb[sel] = ((im[sel] - bg) / a[sel][:, None]) + bg
rgb = np.clip(rgb, 0, 255)

# Borde de los huecos: blanco con transparencia según el brillo (247 = fondo, 254 = blanco),
# y filtro de mediana para borrar puntitos sueltos del JPG.
lum = im.min(axis=2)
a_h = np.clip((lum - bg.min()) / (254 - bg.min()), 0, 1)
alpha_h = alpha.copy()
alpha_h[banda_huecos] = a_h[banda_huecos]
alpha_h = np.where(banda_huecos | huecos, ndimage.median_filter(alpha_h, size=3), alpha_h)
alpha_h[huecos & ~ndimage.binary_dilation(~huecos, iterations=1)] = 0
alpha = alpha_h
rgb[banda_huecos] = 255

# Quitar manchas sueltas (restos del escaneo).
opaco = alpha > 0.5
lab2, n2 = ndimage.label(opaco)
areas = ndimage.sum(opaco, lab2, range(1, n2 + 1))
for i, ar in enumerate(areas, start=1):
    if ar < min_area:
        m = ndimage.binary_dilation(lab2 == i, iterations=3)
        alpha[m] = 0

# Artefactos del JPG en el contorno: píxeles claros pegados a lo transparente (el borde de
# los logos es de color: rojo en El Prepa, negro en El Taller). Dos pasadas.
for _ in range(2):
    transp = alpha < 0.05
    pegado = ndimage.binary_dilation(transp, iterations=1) & ~transp
    claro = rgb.min(axis=2) > 150
    alpha[pegado & claro] = 0

out = np.dstack([rgb, alpha * 255]).astype(np.uint8)
img = Image.fromarray(out, "RGBA")
bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
img = img.crop(bbox)
pad = 6
lienzo = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
lienzo.paste(img, (pad, pad))
if lienzo.width > ancho:
    lienzo = lienzo.resize((ancho, round(lienzo.height * ancho / lienzo.width)), Image.LANCZOS)
lienzo.save(dst, optimize=True)
print(dst, lienzo.size, "fondo", bg.round(), "manchas quitadas", int((areas < min_area).sum()))
