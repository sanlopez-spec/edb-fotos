"""Busca candidatos de foto en Mercado Libre para cada fila de busquedas/*.csv (codigo,consulta).
Escribe busquedas/<lote>/: _candidatos.csv (codigo,n,img) y _hoja_N.jpg (hojas de contacto numeradas)."""
import csv, glob, io, os, re, sys, time
import requests
from PIL import Image, ImageDraw
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "es-AR,es;q=0.9"}
PAT = re.compile(r'http2\.mlstatic\.com/D_(?:NQ_|Q_)?NP_(?:2X_)?(\d{5,7}-ML[A-Z]\d+_\d{6})')
def slug(q): return re.sub(r'[^a-z0-9]+', '-', q.lower()).strip('-')
def candidatos(q, maxn):
    ids = []
    for url in [f"https://listado.mercadolibre.com.ar/{slug(q)}", f"https://listado.mercadolibre.com.ar/{slug(q)}_NoIndex_True"]:
        try:
            h = requests.get(url, headers=UA, timeout=40).text
        except Exception as e:
            print("error", url, e); continue
        print("DEBUG", url, len(h), h.count("mlstatic"), h[:300].replace("\n"," "))
        for m in PAT.finditer(h):
            if m.group(1) not in ids: ids.append(m.group(1))
        if len(ids) >= maxn: break
    return [f"https://http2.mlstatic.com/D_NQ_NP_2X_{i}-F.webp" for i in ids[:maxn]]
VTEX = ["https://www.jumbo.com.ar", "https://www.carrefour.com.ar", "https://www.vea.com.ar"]
TITULOS = {}
def vtex(q, maxn):
    urls = []
    for base in VTEX:
        data = []
        try:
            r = requests.get(base + "/api/io/_v/api/intelligent-search/product_search/", params={"query": q, "count": 5, "page": 1, "locale": "es-AR"}, headers=UA, timeout=40)
            if r.ok: data = r.json().get("products", [])
        except Exception as e:
            print("error vtex-is", base, e)
        if not data:
            try:
                r = requests.get(base + "/api/catalog_system/pub/products/search", params={"ft": q, "_from": 0, "_to": 4}, headers=UA, timeout=40)
                data = r.json() if r.ok else []
            except Exception as e:
                print("error vtex", base, e); continue
        for p in data:
            for it in p.get("items", [])[:1]:
                for im in it.get("images", [])[:2]:
                    u = im.get("imageUrl")
                    if u and u not in urls:
                        urls.append(u); TITULOS[u] = (base.split(".")[1] + ": " + p.get("productName", ""))[:60]
        print("DEBUG vtex", base, q, len(data))
        if len(urls) >= maxn: break
    return urls[:maxn]
def ddg(q, maxn):
    try:
        s = requests.Session(); s.headers.update(UA)
        h = s.get("https://duckduckgo.com/", params={"q": q, "iax": "images", "ia": "images"}, timeout=40).text
        m = re.search(r'vqd=["\']?([\d-]+)', h)
        if not m:
            print("DEBUG ddg sin vqd", q); return []
        s.headers.update({"Referer": "https://duckduckgo.com/", "Accept": "application/json"})
        r = s.get("https://duckduckgo.com/i.js", params={"l": "ar-es", "o": "json", "q": q, "vqd": m.group(1), "f": ",,,,,", "p": "1"}, timeout=40)
        urls = [x["image"] for x in r.json().get("results", []) if x.get("image")]
        print("DEBUG ddg", q, len(urls)); return urls[:maxn]
    except Exception as e:
        print("error ddg", q, e); return []
def bing(q, maxn):
    try:
        h = requests.get("https://www.bing.com/images/search", params={"q": q, "form": "HDRSC2", "first": "1"}, headers=UA, timeout=40).text
    except Exception as e:
        print("error bing", e); return []
    urls = []
    for m in re.finditer(r'murl&quot;:&quot;(.*?)&quot;', h):
        u = m.group(1)
        if u not in urls: urls.append(u)
    print("DEBUG bing", q, len(h), len(urls))
    return urls[:maxn]
def main():
    for f in sorted(glob.glob("busquedas/*.csv")):
        lote = os.path.splitext(os.path.basename(f))[0]
        out = os.path.join("busquedas", lote)
        if os.path.exists(os.path.join(out, "_candidatos.csv")): continue
        os.makedirs(out, exist_ok=True)
        filas = [r for r in csv.DictReader(open(f, encoding="utf-8")) if r.get("codigo")]
        res, celdas = [], []
        for r in filas:
            cod, q = r["codigo"].strip(), r["consulta"].strip()
            lista = vtex(q, 8)
            if len(lista) < 8:
                lista += [u for u in ddg(q, 8) if u not in lista]
                time.sleep(2)
            if len(lista) < 8:
                lista += [u for u in bing(q, 12) if u not in lista]
                time.sleep(3)
            for n, img in enumerate(lista[:8], 1):
                res.append((cod, n, img))
                try:
                    b = requests.get(img, headers=UA, timeout=40); b.raise_for_status()
                    im = Image.open(io.BytesIO(b.content)).convert("RGB"); celdas.append((cod, n, im))
                except Exception:
                    pass
        with open(os.path.join(out, "_candidatos.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["codigo", "n", "img", "ancho", "alto", "titulo"])
            dims = {(c, n): im.size for c, n, im in celdas}
            for c, n, img in res: w.writerow([c, n, img, *dims.get((c, n), ("", "")), TITULOS.get(img, "")])
        T, COLS = 300, 8
        porcod = {}
        for c, n, im in celdas: porcod.setdefault(c, []).append((n, im))
        cods = list(porcod)
        for k in range(0, len(cods), 6):
            grupo = cods[k:k + 6]
            sh = Image.new("RGB", (COLS * T, len(grupo) * (T + 22)), (200, 200, 200)); dr = ImageDraw.Draw(sh)
            for fi, c in enumerate(grupo):
                for n, im in porcod[c]:
                    t = im.copy(); t.thumbnail((T - 6, T - 6))
                    x, y = (n - 1) * T, fi * (T + 22)
                    sh.paste(Image.new("RGB", (T - 4, T - 4), (255, 255, 255)), (x + 2, y + 2))
                    sh.paste(t, (x + 2 + (T - 6 - t.width) // 2, y + 2 + (T - 6 - t.height) // 2))
                    dr.text((x + 6, y + T + 3), f"{c} #{n} {im.width}x{im.height}", fill=(0, 0, 0))
            sh.save(os.path.join(out, f"_hoja_{k // 6 + 1}.jpg"), quality=85)
        print(lote, len(res), "candidatos")
if __name__ == "__main__": main()
