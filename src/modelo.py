"""Construye el modelo estadístico a partir de los CSV de data/ y lo exporta a
web/modelo.json para que la web genere combinaciones.

Cada número recibe un puntaje combinando tres señales (calculadas solo con
sorteos anteriores al que se evalúa):
  - frec: frecuencia histórica suavizada dentro del rango vigente
  - rec:  frecuencia reciente con decaimiento exponencial (números "calientes")
  - atraso: sorteos desde su última salida vs. lo esperado ("números debidos")
Los pesos de cada señal se eligen con un backtest walk-forward sobre los
últimos sorteos, maximizando la log-verosimilitud frente al azar puro. El
resultado del backtest se exporta tal cual para que la web lo muestre.
"""
import csv
import itertools
import json
import math
from datetime import date, datetime
from pathlib import Path

import red_neuronal

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
SALIDA = RAIZ / "web" / "modelo.json"

JUEGOS = {"tinka": 6, "kabala": 6, "ganadiario": 5}
NOMBRES = {"tinka": "La Tinka", "kabala": "Kábala", "ganadiario": "Gana Diario"}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
BACKTEST = 150          # sorteos usados para validar pesos
VIDA_MEDIA = 25         # sorteos para la señal reciente
GRID = [-0.3, -0.1, 0.0, 0.1, 0.3]
# perfiles fijos que la web ofrece como estrategias (pesos frec, rec, atraso)
PERFILES = {
    "equilibrado": (0.15, 0.15, 0.15),
    "frecuentes": (0.3, 0.0, 0.0),
    "calientes": (0.0, 0.3, 0.0),
    "atrasados": (0.0, 0.0, 0.3),
}


def cargar(juego, k):
    ruta = DATA / f"{juego}.csv"
    if not ruta.exists():
        return []
    with open(ruta, encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    out = []
    for r in filas:
        bolas = [int(r[f"b{i}"]) for i in range(1, k + 1)]
        d = {"sorteo": int(r["sorteo"]), "fecha": r["fecha"], "bolas": bolas}
        if "boliyapa" in r:
            d["boliyapa"] = int(r["boliyapa"])
        out.append(d)
    if juego == "tinka":
        out = sumar_historico(out)
    return out


def sumar_historico(sorteos):
    """Agrega a la Tinka los sorteos de data/tinka_historico.csv (desde 1994) que
    faltan en tinka.csv: todos los anteriores a su primer sorteo y los huecos
    posteriores. Si ambas fuentes tienen un sorteo, manda tinka.csv. Un sorteo
    histórico a 3 días o menos de uno propio se descarta (misma jugada con otra fecha)."""
    ruta = DATA / "tinka_historico.csv"
    if not ruta.exists() or not sorteos:
        return sorteos
    propias = {date.fromisoformat(s["fecha"]) for s in sorteos if s["fecha"]}
    primera = min(propias)
    extra = []
    with open(ruta, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = date.fromisoformat(r["fecha"])
            if d >= primera and any(abs((d - p).days) <= 3 for p in propias):
                continue
            extra.append({"sorteo": None, "fecha": r["fecha"],
                          "bolas": [int(r[f"b{i}"]) for i in range(1, 7)]})
    return sorted(sorteos + extra, key=lambda s: s["fecha"])


def anotar_rango(sorteos):
    """Los juegos amplían su rango con el tiempo (la Tinka pasó de 1-45 a 1-53).
    Un número existe desde su primera aparición; el rango de cada sorteo (N_t) es
    el mayor número aparecido hasta ese momento."""
    maximo = 0
    for s in sorteos:
        maximo = max(maximo, *s["bolas"])
        s["N"] = maximo
    return maximo


def zscore(v):
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v)) or 1.0
    return [max(-2.0, min(2.0, (x - m) / sd)) for x in v]   # recorta extremos


def señales_incrementales(sorteos, N, k, desde):
    """Recorre el histórico una sola vez y entrega, para cada t >= desde, las
    señales calculadas solo con sorteos anteriores a t. Cada número se compara
    con lo esperado para él (k/N_t) solo en los sorteos en que ya existía."""
    obs = [0.0] * N
    esp = [0.0] * N
    rec = [0.0] * N
    ultimo = [-1] * N
    primero = [None] * N
    decay = 0.5 ** (1 / VIDA_MEDIA)
    for t, s in enumerate(sorteos):
        if t >= desde:
            yield t, _snapshot(obs, esp, rec, ultimo, primero, t, N, k)
        Nt = s["N"]
        p = k / Nt
        salio = set(s["bolas"])
        for b in salio:
            if primero[b - 1] is None:
                primero[b - 1] = t
        for i in range(Nt):
            if primero[i] is None:
                continue
            hit = 1.0 if i + 1 in salio else 0.0
            obs[i] += hit
            esp[i] += p
            rec[i] = rec[i] * decay + (hit - p)
            if hit:
                ultimo[i] = t
    yield len(sorteos), _snapshot(obs, esp, rec, ultimo, primero, len(sorteos), N, k)


def _snapshot(obs, esp, rec, ultimo, primero, T, N, k):
    frec = [(o + 1) / (e + 1) for o, e in zip(obs, esp)]       # observado/esperado suavizado
    ciclo = N / k
    atraso = [((T - (u if u >= 0 else (f if f is not None else T))) / ciclo)
              for u, f in zip(ultimo, primero)]
    return {"frec": zscore(frec), "rec": zscore(rec), "atraso": zscore(atraso)}


def probabilidades(sig, w, k):
    """Probabilidad marginal de que cada número salga (suma = k)."""
    sc = [math.exp(w[0] * f + w[1] * r + w[2] * a)
          for f, r, a in zip(sig["frec"], sig["rec"], sig["atraso"])]
    tot = sum(sc)
    return [min(0.999, k * x / tot) for x in sc]


def backtest(sorteos, N, k):
    n_test = min(BACKTEST, max(0, len(sorteos) - 100))
    if n_test < 20:
        return (0.0, 0.0, 0.0), None
    inicio = len(sorteos) - n_test
    sigs = [sig for t, sig in señales_incrementales(sorteos, N, k, inicio) if t < len(sorteos)]
    prueba = sorteos[inicio:]

    def medir(probs):
        """Log-verosimilitud y aciertos del top-k para una lista de vectores de
        probabilidad (uno por sorteo de prueba)."""
        ll, aciertos = 0.0, 0
        for p, s in zip(probs, prueba):
            Nt = s["N"]
            salio = set(s["bolas"])
            ll += sum(math.log(max(1e-9, p[i] if i + 1 in salio else 1 - p[i])) for i in range(Nt))
            top = sorted(range(Nt), key=lambda i: -p[i])[:k]
            aciertos += sum(1 for i in top if i + 1 in salio)
        return ll, aciertos / n_test

    def evaluar(w):
        return medir([probabilidades({c: v[:s["N"]] for c, v in sig.items()}, w, k)
                      for sig, s in zip(sigs, prueba)])

    base_ll, _ = evaluar((0.0, 0.0, 0.0))
    celdas = sum(s["N"] for s in prueba)
    mejor, mejor_ll = (0.0, 0.0, 0.0), base_ll
    for w in itertools.product(GRID, repeat=3):
        ll, _ = evaluar(w)
        if ll > mejor_ll + 1e-9:
            mejor, mejor_ll = w, ll

    perfiles = dict(PERFILES, optimo=mejor)
    azar = sum(k * k / s["N"] for s in prueba) / n_test
    resultado = {}
    for nombre, w in perfiles.items():
        ll, hits = evaluar(w)
        if not any(w):          # sin pesos todo empata: el top-k sería 1..k, no el azar
            hits = azar
        resultado[nombre] = {
            "pesos": dict(zip(("frec", "rec", "atraso"), w)),
            "aciertos_top": round(hits, 3),
            "mejora_logver_pct": round(100 * (math.exp((ll - base_ll) / celdas) - 1), 4),
        }
    if red_neuronal.disponible():
        ll, hits = medir(red_neuronal.walk_forward(sorteos, N, k, inicio))
        resultado["red_neuronal"] = {
            "pesos": {"tipo": f"LSTM {red_neuronal.OCULTAS} neuronas, ventana {red_neuronal.VENTANA} sorteos"},
            "aciertos_top": round(hits, 3),
            "mejora_logver_pct": round(100 * (math.exp((ll - base_ll) / celdas) - 1), 4),
        }
    return perfiles, {
        "sorteos_evaluados": n_test,
        "aciertos_esperados_azar": round(azar, 3),
        "perfiles": resultado,
    }


def patrones(sorteos, N, k):
    # las sumas se reescalan al rango actual para poder usar todo el histórico
    sumas = sorted(round(sum(s["bolas"]) * (N + 1) / (s["N"] + 1)) for s in sorteos)
    pct = lambda q: sumas[min(len(sumas) - 1, int(q * len(sumas)))]
    impares, bajos, consecutivos = {}, {}, 0
    for s in sorteos:
        b = s["bolas"]
        i = sum(x % 2 for x in b)
        lo = sum(x <= s["N"] // 2 for x in b)
        impares[i] = impares.get(i, 0) + 1
        bajos[lo] = bajos.get(lo, 0) + 1
        consecutivos += any(b[j + 1] - b[j] == 1 for j in range(k - 1))
    tot = len(sorteos)
    return {
        "suma_p10": pct(0.10), "suma_p90": pct(0.90),
        "suma_media": round(sum(sumas) / tot, 1),
        "impares": {str(a): round(c / tot, 4) for a, c in sorted(impares.items())},
        "bajos": {str(a): round(c / tot, 4) for a, c in sorted(bajos.items())},
        "con_consecutivos": round(consecutivos / tot, 4),
    }


def dias_sorteo(sorteos):
    cuenta = {}
    for s in sorteos[-60:]:
        try:
            d = datetime.strptime(s["fecha"], "%Y-%m-%d").weekday()
        except ValueError:
            continue
        cuenta[d] = cuenta.get(d, 0) + 1
    if not cuenta:
        return []
    umbral = max(cuenta.values()) * 0.3
    return [DIAS[d] for d in sorted(cuenta) if cuenta[d] >= umbral]


def construir(juego, k):
    sorteos = cargar(juego, k)
    if not sorteos:
        return None
    N = anotar_rango(sorteos)
    perfiles, bt = backtest(sorteos, N, k)
    if bt is None:
        perfiles = dict(PERFILES, optimo=(0.0, 0.0, 0.0))
    *_, (_, sig) = señales_incrementales(sorteos, N, k, len(sorteos))
    probs = {nombre: probabilidades(sig, w, k) for nombre, w in perfiles.items()}
    if red_neuronal.disponible():
        probs["red_neuronal"] = red_neuronal.siguiente(sorteos, N, k)
    frec = [0] * N
    for s in sorteos:
        for b in s["bolas"]:
            frec[b - 1] += 1
    ultimo = {}
    for t, s in enumerate(sorteos):
        for b in s["bolas"]:
            ultimo[b] = t
    numeros = [{
        "n": i + 1,
        "prob": {nombre: round(p[i], 5) for nombre, p in probs.items()},
        "frec": frec[i],
        "atraso": len(sorteos) - 1 - ultimo.get(i + 1, -1),
    } for i in range(N)]
    return {
        "nombre": NOMBRES[juego],
        "k": k,
        "N": N,
        "combinaciones": math.comb(N, k),
        "total_historico": len(sorteos),
        "sorteos_modelo": len(sorteos),
        "desde": sorteos[0]["fecha"],
        "hasta": sorteos[-1]["fecha"],
        "ultimo_sorteo": max(s["sorteo"] or 0 for s in sorteos),
        "dias": dias_sorteo(sorteos),
        "optimo_es_azar": not any(perfiles["optimo"]),
        "backtest": bt,
        "patrones": patrones(sorteos, N, k),
        "numeros": numeros,
        "ultimos": [{k2: v for k2, v in s.items()} for s in sorteos[-12:]][::-1],
        "historial": [s["bolas"] for s in sorteos],
        # 7.ª bolilla de cada sorteo (None si el juego no la tiene o no hay dato)
        "boliyapas": [s.get("boliyapa") for s in sorteos],
    }


def main():
    salida = {"generado": datetime.now().isoformat(timespec="seconds"), "juegos": {}}
    for juego, k in JUEGOS.items():
        m = construir(juego, k)
        if m:
            salida["juegos"][juego] = m
            bt = m["backtest"] or {"perfiles": {}}
            print(f"[{juego}] rango 1-{m['N']} | {m['sorteos_modelo']} sorteos ({m['desde']} a {m['hasta']}) "
                  f"| aciertos top-{k} al azar: {bt.get('aciertos_esperados_azar')}")
            for nombre, r in bt["perfiles"].items():
                print(f"    {nombre:<12} pesos {r['pesos']}  aciertos {r['aciertos_top']}  logver {r['mejora_logver_pct']:+}%")
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Modelo guardado en {SALIDA}")


if __name__ == "__main__":
    main()
