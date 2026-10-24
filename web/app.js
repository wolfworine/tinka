"use strict";

let MODELO = null;
let juego = "tinka";
let referencia = [];   // puntajes de combinaciones al azar, para calcular percentiles
const $ = (id) => document.getElementById(id);
const fmt = (n) => n.toLocaleString("es-PE");

async function cargarModelo() {
  const r = await fetch("modelo.json?t=" + Date.now());
  if (!r.ok) throw new Error("No se encontró modelo.json. Ejecuta iniciar.bat.");
  MODELO = await r.json();
  if (!MODELO.juegos[juego]) juego = Object.keys(MODELO.juegos)[0];
  pintarTabs();
  pintarJuego();
}

function pintarTabs() {
  const tabs = $("tabs");
  tabs.innerHTML = "";
  for (const [id, j] of Object.entries(MODELO.juegos)) {
    const b = document.createElement("button");
    b.textContent = j.nombre;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-selected", id === juego);
    b.onclick = () => { juego = id; pintarTabs(); pintarJuego(); };
    tabs.appendChild(b);
  }
}

const J = () => MODELO.juegos[juego];
// probabilidad de cada número según la estrategia elegida ("azar" se mide con el perfil equilibrado)
const perfil = () => ($("modo").value === "azar" ? "equilibrado" : $("modo").value);
const prob = (n) => J().numeros[n - 1].prob[perfil()];

function pintarJuego() {
  const j = J();
  $("estado").textContent =
    `${j.nombre}: ${fmt(j.sorteos_modelo)} sorteos analizados (${j.desde} → ${j.hasta}) · ` +
    `último sorteo #${j.ultimo_sorteo} · modelo generado ${MODELO.generado.replace("T", " ")}`;
  $("resultados").innerHTML = "";
  pintarEstrategia();
  pintarUltimos();
  pintarPatrones();
  $("rangos").textContent = Object.values(MODELO.juegos)
    .map((g) => `${g.nombre}: ${g.k} números del 1 al ${g.N} (${fmt(g.combinaciones)} combinaciones), sorteos ${g.dias.join(", ")}`)
    .join(" · ");
}

function pintarEstrategia() {
  const j = J();
  referencia = Array.from({ length: 4000 }, () => puntaje(muestrear(uniforme(), j.k)));
  referencia.sort((a, b) => a - b);
  pintarBacktest();
  pintarGrafico();
}

/* ---------- generación ---------- */

const uniforme = () => J().numeros.map(() => 1);

function pesos(modo) {
  const j = J();
  if (modo === "azar") return uniforme();
  return j.numeros.map((x) => x.prob[modo]);
}

function muestrear(w, k) {
  const disp = w.map((p, i) => [i + 1, p]);
  const out = [];
  for (let s = 0; s < k; s++) {
    const tot = disp.reduce((a, [, p]) => a + p, 0);
    let r = Math.random() * tot, i = 0;
    while (i < disp.length - 1 && (r -= disp[i][1]) > 0) i++;
    out.push(disp.splice(i, 1)[0][0]);
  }
  return out.sort((a, b) => a - b);
}

// log-razón de la combinación frente al azar según el modelo
function puntaje(c) {
  const j = J(), base = j.k / j.N;
  return c.reduce((a, n) => a + Math.log(prob(n) / base), 0);
}

function percentil(s) {
  let lo = 0, hi = referencia.length;
  while (lo < hi) { const m = (lo + hi) >> 1; referencia[m] < s ? (lo = m + 1) : (hi = m); }
  return Math.round((100 * lo) / referencia.length);
}

function pasaFiltros(c, anti, yaSalieron) {
  const j = J(), p = j.patrones;
  const suma = c.reduce((a, b) => a + b, 0);
  if (suma < p.suma_p10 || suma > p.suma_p90) return false;
  const imp = c.filter((x) => x % 2).length;
  const baj = c.filter((x) => x <= Math.floor(j.N / 2)).length;
  if ((p.impares[imp] || 0) < 0.05 || (p.bajos[baj] || 0) < 0.05) return false;
  if (yaSalieron.has(c.join("-"))) return false;
  if (anti) {
    let run = 1, maxRun = 1;
    for (let i = 1; i < c.length; i++) { run = c[i] - c[i - 1] === 1 ? run + 1 : 1; maxRun = Math.max(maxRun, run); }
    if (maxRun >= 3) return false;                                  // secuencias 5-6-7
    if (j.N > 31 && c.every((x) => x <= 31)) return false;          // "fechas de cumpleaños"
    const d = c[1] - c[0];
    if (c.every((x, i) => i === 0 || x - c[i - 1] === d)) return false; // progresiones 5-10-15-20
    if (c.every((x) => x % 10 === c[0] % 10)) return false;         // misma terminación
  }
  return true;
}

// Genera combinaciones en bucle y se queda solo con las que alcanzan la afinidad mínima.
function generar() {
  const j = J();
  const cant = +$("cantidad").value, modo = $("modo").value, anti = $("anti").checked;
  const minimo = +$("minimo").value;
  const w = pesos(modo);
  const yaSalieron = new Set(j.historial.map((d) => [...d].sort((a, b) => a - b).join("-")));
  const vistas = new Set(), jugadas = [];
  const limite = performance.now() + 3000;   // como máximo 3 s de búsqueda
  let evaluadas = 0;
  while (jugadas.length < cant && performance.now() < limite) {
    const c = muestrear(w, j.k), key = c.join("-");
    if (vistas.has(key)) continue;
    vistas.add(key);
    evaluadas++;
    if (!pasaFiltros(c, anti, yaSalieron)) continue;
    const pct = percentil(puntaje(c));
    if (pct >= minimo) jugadas.push({ c, pct });
  }
  jugadas.sort((a, b) => b.pct - a.pct);
  const resumen = `<p class="nota">Se evaluaron <b>${fmt(evaluadas)}</b> combinaciones y ` +
    (jugadas.length < cant
      ? `solo <b>${jugadas.length}</b> de ${cant} alcanzaron afinidad ≥ ${minimo}% en 3 s. Prueba otra estrategia o baja el mínimo.`
      : `se muestran las ${cant} con afinidad ≥ ${minimo}%.`) +
    ` Recuerda: la afinidad mide cuánto encaja con la estrategia, no sube la probabilidad real de ganar.</p>`;
  $("resultados").innerHTML = resumen + jugadas.map(({ c, pct }) => tarjeta(c, pct)).join("");
}

function tarjeta(c, pct) {
  const j = J();
  // la Boliyapa es la 7.ª bolilla del sorteo: si está en la jugada mejora el premio de 2 a 5 aciertos
  const yapas = j.boliyapas || [], conYapa = yapas.some(Boolean);
  const aciertos = {};
  j.historial.forEach((d, t) => {
    const h = d.filter((x) => c.includes(x)).length;
    const yapa = h < j.k && yapas[t] && c.includes(yapas[t]) ? 1 : 0;
    if (h + yapa >= j.k - 3) { const key = 2 * h + yapa; aciertos[key] = (aciertos[key] || 0) + 1; }
  });
  const hist = Object.keys(aciertos).sort((a, b) => b - a)
    .map((key) => `${key >> 1} aciertos${key & 1 ? " + Boliyapa" : ""}: <b>${aciertos[key]}</b>`)
    .join(" · ") || "sin coincidencias relevantes";
  // 5 de las 6 ganadoras (6 formas) y el número restante de la jugada es la Boliyapa
  const lineaYapa = conYapa ? `<div class="metricas"><span>Boliyapa (7.ª bolilla del sorteo): no se elige, se compara con tus
      ${j.k} números. Acertar ${j.k - 1} + Boliyapa: <b>1 en ${fmt(Math.round(j.combinaciones / j.k))}</b>
      (segundo premio, no el pozo)</span></div>` : "";
  const suma = c.reduce((a, b) => a + b, 0);
  const bolas = c.map((n) => {
    return `<div class="bola" title="Prob. ${(prob(n) * 100).toFixed(2)}%">${n}</div>`;
  }).join("");
  const probs = c.map((n) => `${n}: ${(prob(n) * 100).toFixed(2)}%`).join(" · ");
  return `<div class="jugada">
    <div class="bolas">${bolas}</div>
    <div class="medidor" title="Afinidad con el modelo"><span style="width:${pct}%"></span></div>
    <div class="metricas">
      <span>Afinidad con el modelo: <b>${pct}%</b> (mejor que el ${pct}% de combinaciones al azar)</span>
      <span>Probabilidad real de acertar ${j.k}: <b>1 en ${fmt(j.combinaciones)}</b></span>
      <span>Suma: <b>${suma}</b></span>
    </div>
    <div class="metricas"><span>Prob. estimada por la estrategia — ${probs}</span></div>
    ${lineaYapa}
    <div class="metricas"><span>Si la hubieras jugado en los ${fmt(j.historial.length)} sorteos anteriores: ${hist}</span></div>
  </div>`;
}

/* ---------- paneles ---------- */

const NOMBRES_PERFIL = {
  equilibrado: "Equilibrado", optimo: "Óptimo", frecuentes: "Frecuentes",
  calientes: "Calientes", atrasados: "Atrasados", red_neuronal: "Red neuronal LSTM",
};

function pintarBacktest() {
  const j = J(), bt = j.backtest;
  if (!bt) { $("backtest").innerHTML = "<p class='nota'>Pocos datos para validar.</p>"; return; }
  const azar = bt.aciertos_esperados_azar, sel = perfil();
  const filas = Object.entries(bt.perfiles).map(([id, r]) => {
    const dif = r.aciertos_top - azar;
    return `<tr class="${id === sel ? "sel" : ""}"><td>${NOMBRES_PERFIL[id] || id}</td>
      <td>${r.aciertos_top}</td><td class="${dif >= 0 ? "pos" : "neg"}">${dif >= 0 ? "+" : ""}${dif.toFixed(3)}</td>
      <td>${r.mejora_logver_pct >= 0 ? "+" : ""}${r.mejora_logver_pct}%</td></tr>`;
  }).join("");
  $("backtest").innerHTML = `
    <table class="tabla">
      <thead><tr><th>Estrategia</th><th>Aciertos top-${j.k}</th><th>vs azar</th><th>Verosimilitud</th></tr></thead>
      <tbody><tr><td>Azar puro</td><td>${azar}</td><td>—</td><td>0%</td></tr>${filas}</tbody>
    </table>
    <p class="nota">Validación walk-forward en los últimos ${bt.sorteos_evaluados} sorteos: para cada sorteo la estrategia
    solo vio el pasado y eligió sus ${j.k} números más probables. <b>Aciertos</b> = promedio de cuántos salieron.
    <b>Verosimilitud</b> &gt; 0 significa que predijo mejor que el azar.
    ${j.optimo_es_azar ? "Ninguna ponderación superó al azar, así que el perfil óptimo quedó en azar puro." : ""}
    Diferencias menores a ~0.15 aciertos son ruido estadístico: es lo esperable en un sorteo justo.</p>`;
}

function pintarUltimos() {
  const j = J();
  $("ultimos").innerHTML = j.ultimos.map((s) => `
    <div class="fila-sorteo"><span class="fecha">${s.sorteo ? "#" + s.sorteo : "histórico"}<br>${s.fecha}</span>
      <div class="bolas">${s.bolas.map((b) => `<div class="bola mini">${b}</div>`).join("")}
      ${s.boliyapa ? `<div class="bola mini bonus" title="Boliyapa">${s.boliyapa}</div>` : ""}</div>
    </div>`).join("");
}

function pintarGrafico() {
  const j = J(), base = j.k / j.N;
  const max = Math.max(...j.numeros.map((x) => prob(x.n))) * 1.08;
  const barras = j.numeros.map((x) => `<div class="barra ${prob(x.n) > base ? "hot" : ""}"
      style="height:${(100 * prob(x.n)) / max}%"
      title="Nº ${x.n}\nProb. estrategia: ${(prob(x.n) * 100).toFixed(2)}%\nSalió ${x.frec} veces\nAtraso: ${x.atraso} sorteos"></div>`).join("");
  $("grafico").innerHTML = barras + `<div class="base" style="bottom:${(100 * base) / max}%"></div>`;
  const ejes = document.querySelector(".ejes") || Object.assign(document.createElement("div"), { className: "ejes" });
  ejes.innerHTML = j.numeros.map((x) => `<span>${x.n % 5 === 0 || x.n === 1 ? x.n : ""}</span>`).join("");
  $("grafico").after(ejes);
}

function dist(titulo, obj) {
  const max = Math.max(...Object.values(obj));
  return `<div><h3>${titulo}</h3><div class="dist">${Object.entries(obj).map(([k, v]) =>
    `<div><span>${k}</span><i style="width:${(100 * v) / max}%"></i><span>${(v * 100).toFixed(1)}%</span></div>`).join("")}</div></div>`;
}

function pintarPatrones() {
  const j = J(), p = j.patrones;
  $("patrones").innerHTML = `
    <div><h3>Suma de los números</h3><p class="nota">El 80% de los sorteos suma entre <b>${p.suma_p10}</b> y <b>${p.suma_p90}</b> (media ${p.suma_media}). El generador descarta sumas fuera de ese rango.</p>
    <p class="nota">${(p.con_consecutivos * 100).toFixed(1)}% de los sorteos trae al menos un par consecutivo.</p></div>
    ${dist("Cantidad de impares", p.impares)}
    ${dist(`Cantidad de bajos (≤ ${Math.floor(j.N / 2)})`, p.bajos)}`;
}

/* ---------- actualización ---------- */

async function actualizar() {
  const btn = $("btn-actualizar"), log = $("log");
  if (location.protocol === "file:") {
    log.hidden = false;
    log.textContent = "Para actualizar desde la web, ábrela con iniciar.bat (servidor local).";
    return;
  }
  btn.disabled = true;
  btn.textContent = "Actualizando…";
  log.hidden = false;
  log.textContent = "Descargando sorteos nuevos y recalculando el modelo…";
  try {
    const r = await fetch("/api/actualizar", { method: "POST" });
    const d = await r.json();
    log.textContent = d.log;
    if (d.ok) await cargarModelo();
  } catch (e) {
    log.textContent = "Error: " + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "↻ Actualizar datos";
  }
}

$("btn-generar").onclick = generar;
$("modo").onchange = () => { $("resultados").innerHTML = ""; pintarEstrategia(); };
$("btn-actualizar").onclick = actualizar;
cargarModelo().catch((e) => { $("estado").textContent = e.message; });
