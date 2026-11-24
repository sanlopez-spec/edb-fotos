"""Descarga y normaliza fotos de producto para la tienda de EDB.

Lee pedidos/*.csv (columnas: codigo,url,lote). Para cada fila:
- descarga la imagen,
- si el fondo no es blanco, lo quita (rembg),
- recorta el producto, quita manchas sueltas y reflejos,
- lo centra en un lienzo blanco de 1280x1280, a ~85% de alto,
- guarda <lote>/<codigo>.jpg.
Escribe <lote>/_informe.csv y <lote>/_vista_previa.jpg.
"""
import csv, glob, io, os, sys, traceback
import numpy as np, cv2, requests
from PIL import Image, ImageDraw

LADO, ALTO, ANCHO = 1280, 1088, 1152
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_rembg = None

def resolver_pagina(u):
    """'pagina:<url>' -> URL de la imagen principal de esa página (og:image, o wp-content/uploads)."""
    if not u.startswith("pagina:"):
        return u
    import re
    html = requests.get(u[7:], headers=UA, timeout=60).text
    m = re.search(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)', html) or \
        re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html)
    if m:
        img = m.group(1).replace("&amp;", "&")
        if img.startswith("//"): img = "https:" + img
        img = re.sub(r"-(?:480|640|320)-0\.(webp|jpg|png)", r"-1024-1024.\1", img)  # Tiendanube: versión grande
        return img
    for m in re.finditer(r'(https?://[^"\'\s)]+/wp-content/uploads/[^"\'\s)]+\.(?:webp|png|jpe?g))', html):
        img = m.group(1)
        nombre = img.rsplit("/", 1)[-1].lower()
        if any(x in nombre for x in ("logo", "cropped", "image-1024", "since")) or re.match(r"^\d(-\d)?\.png$", nombre):
            continue
        return re.sub(r"-\d+x\d+(?=\.\w+$)", "", img)
    raise ValueError("sin imagen de producto en " + u[7:])

def quitar_fondo(im):
    global _rembg
    if _rembg is None:
        from rembg import remove, new_session
        _rembg = (remove, new_session("isnet-general-use"))
    remove, ses = _rembg
    return remove(im, session=ses)

def a_blanco(im):
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im); im = bg
    return im.convert("RGB")

def fondo_blanco(a):
    h, w = a.shape[:2]; b = max(2, min(h, w) // 50)
    borde = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3), a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    return (borde.min(axis=1) >= 235).mean() > 0.9

def procesar(im, solo=None):
    nota = []
    im0 = im
    a = np.array(a_blanco(im))
    if not fondo_blanco(a):
        a = np.array(a_blanco(quitar_fondo(im0.convert("RGB")))); nota.append("fondo quitado automáticamente")
    g = a.min(axis=2); h, w = g.shape
    mask = np.zeros((h + 2, w + 2), np.uint8); tmp = a.copy()
    for (x, y) in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]:
        if g[y, x] >= 235:
            cv2.floodFill(tmp, mask, (x, y), (255, 255, 255), (12, 12, 12), (12, 12, 12), cv2.FLOODFILL_FIXED_RANGE | 4 | (255 << 8))
    bgm = mask[1:-1, 1:-1] > 0; a[bgm] = 255; g = a.min(axis=2)
    obj = ((~bgm) & (g < 240)).astype(np.uint8)
    k = max(3, int(min(h, w) * 0.01))
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(obj, np.ones((k, k), np.uint8)))
    areas = st[1:, cv2.CC_STAT_AREA]; big = areas.max()
    keep = [i + 1 for i, ar in enumerate(areas) if ar >= 0.15 * big]
    if solo == "izq" and len(keep) > 1:
        keep = [min(keep, key=lambda i: st[i, cv2.CC_STAT_LEFT])]; nota.append("solo objeto izquierdo")
    km = np.isin(lab, keep) & (obj > 0)
    # Conservar todo lo que queda dentro de la silueta (envolvente convexa) de cada objeto,
    # para no borrar logos o textos que en botellas blancas quedan como islas sueltas.
    dentro = np.zeros((h, w), np.uint8)
    for i in keep:
        pts = cv2.findNonZero(((lab == i) & (obj > 0)).astype(np.uint8))
        if pts is not None:
            cv2.fillConvexPoly(dentro, cv2.convexHull(pts), 1)
    a[dentro == 0] = 255
    ys, xs = np.where(km); y0, y1 = ys.min(), ys.max()
    strong = (km & (g < 170)).sum(axis=1).astype(float)
    mid = strong[y0 + int((y1 - y0) * 0.3):y0 + int((y1 - y0) * 0.8)]
    ref = np.median(mid) if len(mid) else 0
    if ref > 5:
        filas = np.where(strong[y0:y1 + 1] >= 0.2 * ref)[0]; last = y0 + filas.max()
        if (y1 - last) > 0.03 * (y1 - y0):
            a[last + 1:, :] = 255; y1 = last; nota.append("reflejo recortado")
    ys, xs = np.where(km[:y1 + 1]); x0, x1 = xs.min(), xs.max()
    crop = Image.fromarray(a[y0:y1 + 1, x0:x1 + 1]); cw, ch = crop.size
    s = min(ALTO / ch, ANCHO / cw)
    if s > 3: nota.append(f"baja resolución (original {cw}x{ch}px)")
    crop = crop.resize((max(1, round(cw * s)), max(1, round(ch * s))), Image.LANCZOS)
    lienzo = Image.new("RGB", (LADO, LADO), "white")
    lienzo.paste(crop, ((LADO - crop.size[0]) // 2, (LADO - crop.size[1]) // 2))
    return lienzo, "; ".join(nota)

def main():
    filas = []
    for f in sorted(glob.glob("pedidos/*.csv")):
        with open(f, encoding="utf-8") as fh:
            filas += [r for r in csv.DictReader(fh) if r.get("codigo") and r.get("url")]
    lotes = {}
    for r in filas:
        lote = (r.get("lote") or "lote").strip(); cod = r["codigo"].strip(); url = r["url"].strip()
        os.makedirs(lote, exist_ok=True)
        destino = os.path.join(lote, f"{cod}.jpg")
        if os.path.exists(destino): lotes.setdefault(lote, []).append((cod, "ya existía", "")); continue
        try:
            im, err = None, None
            solo = None
            if url.endswith("@@izq"): url, solo = url[:-5], "izq"
            for u in [x.strip() for x in url.split("|") if x.strip()]:
                try:
                    u = resolver_pagina(u)
                    resp = requests.get(u, headers=UA, timeout=60); resp.raise_for_status()
                    im = Image.open(io.BytesIO(resp.content)); im.load(); break
                except Exception as e:
                    err = e; im = None
            if im is None: raise err
            out, nota = procesar(im, solo)
            out.save(destino, quality=90)
            lotes.setdefault(lote, []).append((cod, "ok", nota))
        except Exception as e:
            lotes.setdefault(lote, []).append((cod, "error", f"{type(e).__name__}: {e}"[:200]))
            traceback.print_exc()
    for lote, res in lotes.items():
        with open(os.path.join(lote, "_informe.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["codigo", "estado", "nota"]); w.writerows(res)
        fotos = sorted(p for p in glob.glob(os.path.join(lote, "*.jpg")) if not os.path.basename(p).startswith("_"))
        if fotos:
            T, cols = 220, 10; rows = (len(fotos) + cols - 1) // cols
            sh = Image.new("RGB", (cols * T, rows * (T + 22)), (210, 210, 210)); dr = ImageDraw.Draw(sh)
            for i, p in enumerate(fotos):
                x, y = (i % cols) * T, (i // cols) * (T + 22)
                sh.paste(Image.open(p).resize((T - 6, T - 6)), (x + 3, y + 3)); dr.text((x + 6, y + T), os.path.basename(p)[:-4], fill=(0, 0, 0))
            sh.save(os.path.join(lote, "_vista_previa.jpg"), quality=85)
    print({k: len(v) for k, v in lotes.items()})

if __name__ == "__main__":
    main()
