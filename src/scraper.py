"""Descarga incremental de resultados de La Tinka, Kábala y Gana Diario.

Fuente: tinkaresultados.com (sitio informativo independiente). Guarda un CSV por
juego en data/. En cada ejecución solo descarga los sorteos que faltan.
"""
import csv
import html
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://www.tinkaresultados.com"
DATA = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (TinkaStats personal)"}
WORKERS = 6

MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], 1)}
MESES["setiembre"] = 9

JUEGOS = {
    "tinka": {
        "lista": "/sorteos-historicos",
        "patron_lista": r"jugada-(\d+)-del",
        "url": "/sorteos-historicos/jugada-{n}-del-1-01-2000",
        "n": 6,
        "campos": ["sorteo", "fecha", "b1", "b2", "b3", "b4", "b5", "b6", "boliyapa", "si_o_si"],
    },
    "kabala": {
        "lista": "/kabala/resultados-anteriores",
        "patron_lista": r"/kabala/resultados-anteriores/sorteo-(\d+)",
        "url": "/kabala/resultados-anteriores/sorteo-{n}",
        "n": 6,
        "campos": ["sorteo", "fecha", "b1", "b2", "b3", "b4", "b5", "b6"],
    },
    "ganadiario": {
        "lista": "/gana-diario/resultados-anteriores",
        "patron_lista": r"/gana-diario/resultados-anteriores/sorteo-(\d+)",
        "url": "/gana-diario/resultados-anteriores/sorteo-{n}",
        "n": 5,
        "campos": ["sorteo", "fecha", "b1", "b2", "b3", "b4", "b5"],
    },
}


def get(path, intentos=3):
    for i in range(intentos):
        try:
            req = urllib.request.Request(BASE + path, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code <= 500 or i == intentos - 1:   # el sitio responde 500 para sorteos que no tiene
                return None
            time.sleep(1.5 * (i + 1))
        except Exception:
            if i == intentos - 1:
                return None
            time.sleep(1.5 * (i + 1))


def texto(h):
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S)
    i = h.find("<main")
    if i >= 0:
        h = h[i:]
    h = html.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", h)


def fecha(t):
    m = re.search(r"(\d{1,2}) de ([a-záé]+)(?: de)? (\d{4})", t, re.I)
    if m and m.group(2).lower() in MESES:
        return f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"Fecha: (\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def parsear(juego, n, h):
    t = texto(h)
    if "No tenemos los resultados" in t:
        return None
    k = JUEGOS[juego]["n"]
    nums = r"((?:\d{1,2} ){%d})" % k
    if juego == "tinka":
        m = re.search(r"Jugada ganadora " + nums + r"Boliyapa (\d{1,2})", t + " ", re.I)
        if not m:
            return None
        bolas = sorted(int(x) for x in m.group(1).split())
        s = re.search(r"Sí o sí ((?:\d{1,2} )+)", t)
        sios = " ".join(str(int(x)) for x in s.group(1).split()) if s else ""
        return [n, fecha(t), *bolas, int(m.group(2)), sios]
    etiqueta = "Pozo Buenazo" if juego == "kabala" else "Jugada Ganadora"
    m = re.search(etiqueta + " " + nums, t + " ", re.I)
    if not m:
        return None
    return [n, fecha(t), *sorted(int(x) for x in m.group(1).split())]


def ultimo_sorteo(juego):
    h = get(JUEGOS[juego]["lista"]) or ""
    ids = [int(x) for x in re.findall(JUEGOS[juego]["patron_lista"], h)]
    ultimo = max(ids) if ids else 0
    # la lista a veces no incluye el sorteo de hoy: probar los siguientes
    while ultimo:
        h = get(JUEGOS[juego]["url"].format(n=ultimo + 1))
        if not h or not parsear(juego, ultimo + 1, h):
            break
        ultimo += 1
    return ultimo


def leer_csv(ruta):
    if not ruta.exists():
        return []
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def actualizar(juego):
    cfg = JUEGOS[juego]
    ruta = DATA / f"{juego}.csv"
    filas = leer_csv(ruta)
    existentes = {int(r["sorteo"]) for r in filas}
    ultimo = ultimo_sorteo(juego)
    if not ultimo:
        print(f"[{juego}] No se pudo leer el último sorteo (¿sin internet?).")
        return
    desde = max(existentes) + 1 if existentes else 1
    pendientes = [n for n in range(desde, ultimo + 1) if n not in existentes]
    print(f"[{juego}] en base: {len(existentes)} | último publicado: {ultimo} | por descargar: {len(pendientes)}")
    if not pendientes:
        return

    def tarea(n):
        h = get(cfg["url"].format(n=n))
        return parsear(juego, n, h) if h else None

    nuevos, hechos = [], 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for fila in ex.map(tarea, pendientes):
            hechos += 1
            if fila:
                nuevos.append(fila)
            if hechos % 100 == 0:
                print(f"  {hechos}/{len(pendientes)} revisados, {len(nuevos)} válidos")

    todas = [[r[c] for c in cfg["campos"]] for r in filas] + nuevos
    todas.sort(key=lambda r: int(r[0]))
    DATA.mkdir(exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cfg["campos"])
        w.writerows(todas)
    print(f"[{juego}] +{len(nuevos)} sorteos nuevos -> total {len(todas)}")


HISTORICO_URL = "https://raw.githubusercontent.com/jcchg/tinka-sorteos/main/sorteos.txt"


def actualizar_historico(forzar=False):
    """Histórico completo de la Tinka desde 1994 (repositorio público jcchg/tinka-sorteos,
    una bolilla por línea: numero;dd/mm/aaaa;marca). Complementa a tinka.csv, que solo
    llega hasta 2018. Se descarga una vez; con forzar=True se vuelve a bajar."""
    ruta = DATA / "tinka_historico.csv"
    if ruta.exists() and not forzar:
        return
    try:
        req = urllib.request.Request(HISTORICO_URL, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            texto_crudo = r.read().decode("utf-8-sig", errors="replace")
    except Exception as e:
        print(f"[historico] No se pudo descargar ({e}); se usará solo tinka.csv.")
        return
    sorteos = {}
    for linea in texto_crudo.splitlines():
        partes = linea.strip().split(";")
        m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", partes[1]) if len(partes) >= 2 else None
        if not m or not partes[0].isdigit():
            continue                        # líneas corruptas del archivo fuente
        fecha_iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        sorteos.setdefault(fecha_iso, []).append(int(partes[0]))
    filas = [[f, *sorted(b)] for f, b in sorted(sorteos.items()) if len(set(b)) == 6]
    DATA.mkdir(exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "b1", "b2", "b3", "b4", "b5", "b6"])
        w.writerows(filas)
    print(f"[historico] {len(filas)} sorteos de la Tinka ({filas[0][0]} a {filas[-1][0]})")


if __name__ == "__main__":
    juegos = sys.argv[1:] or list(JUEGOS)
    if "tinka" in juegos:
        actualizar_historico(forzar="--forzar-historico" in sys.argv)
    for j in juegos:
        if j in JUEGOS:
            actualizar(j)
