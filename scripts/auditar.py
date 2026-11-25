"""Audita las fotos de todos los productos publicados de estaciondebebidas.com.

Lee el sitemap de la tienda, abre cada página de producto y anota:
id, código (SKU), nombre, cantidad de fotos, primera imagen, si la primera es
una foto nueva (archivo con nombre = código), si la botella está cortada
(el objeto toca un borde de la imagen) y si la foto nueva está repetida.
Resultado: auditoria/catalogo.csv y auditoria/_cortadas_N.jpg (hojas de revisión).
"""
import csv, io, json, os, re, html
from concurrent.futures import ThreadPoolExecutor
import numpy as np, requests
from PIL import Image, ImageDraw

BASE = "https://www.estaciondebebidas.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
S = requests.Session(); S.headers.update(UA)


def locs(url):
    try:
        t = S.get(url, timeout=60).text
    except Exception as e:
        print("error sitemap", url, e); return []
    return [html.unescape(x) for x in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", t)]


def urls_productos():
    out, vistos, cola = [], set(), [BASE + "/sitemap.xml"]
    while cola:
        u = cola.pop()
        if u in vistos: continue
        vistos.add(u)
        for l in locs(u):
            if l.endswith(".xml"): cola.append(l)
            elif "/productos/" in l: out.append(l)
    return sorted(set(out))


def imagenes(t):
    # archivos de imagen de producto de la galería, en orden, sin repetir
    vis, res = set(), []
    for m in re.finditer(r"(?:https?:)?//[^\"'\s]*mitiendanube\.com/stores/[0-9/]+/products/([^\"'\s]+?)-(?:\d+|1024|640|480|320|240|100)-\d+\.(?:jpg|jpeg|png|webp)", t):
        f = m.group(1)
        if f not in vis:
            vis.add(f); res.append((f, m.group(0) if m.group(0).startswith("http") else "https:" + m.group(0)))
    return res


def cortada(url):
    try:
        u = re.sub(r"-\d+-\d+\.(jpg|jpeg|png|webp)$", r"-640-0.\1", url)
        im = Image.open(io.BytesIO(S.get(u, timeout=60).content)).convert("L")
        a = np.asarray(im)
        h, w = a.shape
        borde = np.concatenate([a[:3].ravel(), a[-3:].ravel(), a[:, :3].ravel(), a[:, -3:].ravel()])
        fondo_blanco = (borde > 235).mean() > 0.6
        if not fondo_blanco:
            return "", "fondo no blanco"
        m = a < 232
        lados = []
        if m[:2].mean() > 0.01: lados.append("arriba")
        if m[-2:].mean() > 0.01: lados.append("abajo")
        if m[:, :2].mean() > 0.01: lados.append("izquierda")
        if m[:, -2:].mean() > 0.01: lados.append("derecha")
        return ("si" if lados else "no"), ",".join(lados)
    except Exception as e:
        return "", f"error {e}"[:80]


def leer(url):
    try:
        t = S.get(url, timeout=60).text
    except Exception as e:
        return {"url": url, "error": str(e)[:100]}
    dec = lambda x: json.loads('"' + x + '"') if x else ""
    pid = re.search(r"LS\.product\s*=\s*\{\s*id\s*:\s*(\d+)", t)
    nombre = re.search(r"LS\.product\s*=\s*\{\s*id\s*:\s*\d+,\s*name\s*:\s*'((?:[^'\\]|\\.)*)'", t)
    sku = re.search(r'LS\.variants\s*=\s*\[\{.*?"sku":"((?:[^"\\]|\\.)*)"', t, re.S)
    cant = re.search(r'data-product-images-amount="(\d+)"', t)
    slides = re.findall(r'js-product-slide[^"]*"[^>]*data-image-position="\d+">\s*<a href="([^"]+)"', t)
    vis, imgs = set(), []
    for h in slides:
        f = re.search(r"/products/(.+?)-\d+-\d+\.\w+$", h)
        f = f.group(1) if f else h
        if f not in vis: vis.add(f); imgs.append((f, ("https:" + h) if h.startswith("//") else h))
    if not imgs:
        og = re.search(r'og:image" content="([^"]+)"', t)
        if og and "/products/" in og.group(1):
            f = re.search(r"/products/(.+?)-\d+-\d+\.\w+$", og.group(1))
            imgs = [(f.group(1) if f else og.group(1), og.group(1))]
    cod = dec(sku.group(1)) if sku else ""
    codl = cod.lower()
    nuevas = [f for f, _ in imgs if codl and f.startswith(codl + "-")]
    primera = imgs[0] if imgs else ("", "")
    es_nueva = bool(codl) and primera[0].startswith(codl + "-")
    c, lados = cortada(primera[1]) if primera[1] else ("", "")
    return {"url": url, "id": pid.group(1) if pid else "", "codigo": cod,
            "nombre": dec(nombre.group(1)) if nombre else "", "fotos": int(cant.group(1)) if cant else len(imgs),
            "primera": primera[1], "primera_nueva": "si" if es_nueva else "no",
            "fotos_nuevas": len(nuevas), "cortada": c, "detalle": lados, "error": ""}


def main():
    os.makedirs("auditoria", exist_ok=True)
    us = urls_productos()
    print(len(us), "productos en el sitemap")
    with ThreadPoolExecutor(8) as ex:
        filas = list(ex.map(leer, us))
    os.makedirs("auditoria", exist_ok=True)
    campos = ["id", "codigo", "nombre", "fotos", "primera_nueva", "fotos_nuevas", "cortada", "detalle", "primera", "url", "error"]
    with open("auditoria/catalogo.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore"); w.writeheader()
        for f in filas: w.writerow({k: f.get(k, "") for k in campos})
    cort = [f for f in filas if f.get("cortada") == "si"]
    T = 240
    for n in range(0, len(cort), 24):
        g = cort[n:n + 24]
        sh = Image.new("RGB", (8 * T, 3 * (T + 20)), (200, 200, 200)); dr = ImageDraw.Draw(sh)
        for i, f in enumerate(g):
            try:
                im = Image.open(io.BytesIO(S.get(f["primera"], timeout=60).content)).convert("RGB"); im.thumbnail((T - 4, T - 4))
                x, y = (i % 8) * T, (i // 8) * (T + 20)
                sh.paste(im, (x + 2, y + 2)); dr.text((x + 4, y + T + 2), f"{f['codigo']} {f['detalle']}"[:38], fill=(0, 0, 0))
            except Exception:
                pass
        sh.save(f"auditoria/_cortadas_{n // 24 + 1}.jpg", quality=85)
    print("listo:", len(filas), "productos,", len(cort), "posibles cortadas")


if __name__ == "__main__":
    main()
