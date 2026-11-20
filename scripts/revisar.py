"""Reprocesa con el procesar.py actual las fotos ya generadas desde pedidos/*.csv
y las compara con la versión guardada. Escribe en revision/:
- revision/<lote>/<codigo>.jpg  (versión nueva)
- revision/_informe.csv          (lote, codigo, diferencia media, píxeles distintos %)
- revision/_comparacion_N.jpg    (pares vieja | nueva de las que cambiaron)
"""
import csv, glob, io, os, traceback
import numpy as np, requests
from PIL import Image, ImageDraw
import procesar as P

def main():
    filas = []
    for f in sorted(glob.glob("pedidos/*.csv")):
        if os.path.basename(f) == "pernod4.csv":
            continue
        with open(f, encoding="utf-8") as fh:
            filas += [r for r in csv.DictReader(fh) if r.get("codigo") and r.get("url")]
    os.makedirs("revision", exist_ok=True)
    res, cambios = [], []
    for r in filas:
        lote, cod = r["lote"].strip(), r["codigo"].strip()
        viejo = os.path.join(lote, f"{cod}.jpg")
        if not os.path.exists(viejo):
            continue
        try:
            im = None
            for u in [x.strip() for x in r["url"].split("|") if x.strip()]:
                try:
                    resp = requests.get(u, headers=P.UA, timeout=60); resp.raise_for_status()
                    im = Image.open(io.BytesIO(resp.content)); im.load(); break
                except Exception:
                    im = None
            if im is None:
                res.append((lote, cod, "", "", "no se pudo descargar")); continue
            nuevo, nota = P.procesar(im)
            os.makedirs(os.path.join("revision", lote), exist_ok=True)
            nuevo.save(os.path.join("revision", lote, f"{cod}.jpg"), quality=90)
            a = np.asarray(Image.open(viejo).convert("RGB"), dtype=np.int16)
            b = np.asarray(nuevo, dtype=np.int16)
            d = np.abs(a - b).max(axis=2)
            media, pct = float(d.mean()), float((d > 40).mean() * 100)
            res.append((lote, cod, f"{media:.2f}", f"{pct:.2f}", nota))
            if pct > 0.3:
                cambios.append((lote, cod, viejo, nuevo))
        except Exception as e:
            res.append((lote, cod, "", "", f"error {type(e).__name__}: {e}"[:200])); traceback.print_exc()
    with open("revision/_informe.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["lote", "codigo", "dif_media", "pct_pixeles_distintos", "nota"]); w.writerows(res)
    T = 400
    for n in range(0, len(cambios), 6):
        grupo = cambios[n:n + 6]
        sh = Image.new("RGB", (2 * T, len(grupo) * (T + 24)), (210, 210, 210)); dr = ImageDraw.Draw(sh)
        for i, (lote, cod, viejo, nuevo) in enumerate(grupo):
            y = i * (T + 24)
            sh.paste(Image.open(viejo).convert("RGB").resize((T - 4, T - 4)), (2, y + 2))
            sh.paste(nuevo.resize((T - 4, T - 4)), (T + 2, y + 2))
            dr.text((6, y + T + 4), f"{lote}/{cod}  VIEJA | NUEVA", fill=(0, 0, 0))
        sh.save(f"revision/_comparacion_{n // 6 + 1}.jpg", quality=85)
    print(len(res), "revisadas,", len(cambios), "con cambios")

if __name__ == "__main__":
    main()
