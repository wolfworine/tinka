# Tinka Estadística

Generador de combinaciones para **La Tinka**, **Kábala** y **Gana Diario**, basado en el
histórico real de sorteos y un modelo estadístico validado con backtest.

## Uso

Doble clic en **`iniciar.bat`**. Cada vez que se ejecuta:

1. Descarga los sorteos nuevos (incremental: solo lo que falta) → `data/*.csv`
2. Recalcula el modelo → `web/modelo.json`
3. Levanta la web en http://127.0.0.1:8765 y abre el navegador

Dentro de la web, el botón **↻ Actualizar datos** hace lo mismo (pasos 1 y 2) sin cerrar nada.
Requisito: Python 3.10+ (no usa librerías externas).

## Estructura

| Ruta | Qué hace |
|---|---|
| `iniciar.bat` | Actualiza la base, recalcula el modelo e inicia la web |
| `src/scraper.py` | Descarga resultados desde tinkaresultados.com (sitio independiente) |
| `src/modelo.py` | Calcula señales por número, elige pesos por backtest y exporta `web/modelo.json` |
| `src/red_neuronal.py` | Red LSTM (PyTorch) evaluada con el mismo backtest |
| `src/servidor.py` | Sirve `web/` y expone `POST /api/actualizar` |
| `data/` | Base local: `tinka.csv`, `kabala.csv`, `ganadiario.csv` |
| `data/tinka_historico.csv` | Tinka desde 1994 (github.com/jcchg/tinka-sorteos). Se baja una vez; `python src/scraper.py tinka --forzar-historico` lo renueva |
| `web/` | Interfaz (HTML/CSS/JS sin dependencias) |

Comandos sueltos: `python src/scraper.py [tinka|kabala|ganadiario]`, `python src/modelo.py`.

## Datos

- **La Tinka:** 2,791 sorteos (oct 1994 – hoy). `tinka.csv` (desde 2018, con número de sorteo y Boliyapa)
  manda; el histórico completa lo anterior a 2018 y los huecos. En el periodo común ambas fuentes
  coinciden en el 98.4% de los sorteos.
- **Kábala:** desde abril 2024. **Gana Diario:** desde diciembre 2023.

## El algoritmo

Para cada número se combinan tres señales (normalizadas):

- **frec**: frecuencia histórica dentro del rango de bolillas vigente (detecta cambios de reglas).
- **rec**: frecuencia reciente con decaimiento exponencial (vida media 25 sorteos).
- **atraso**: sorteos desde su última salida vs. lo esperado.

`prob(n) ∝ exp(w1·frec + w2·rec + w3·atraso)`. La web ofrece varios perfiles de pesos
(equilibrado, frecuentes, calientes, atrasados) más un perfil **óptimo** buscado por grilla.
Todos se evalúan con una validación walk-forward sobre los últimos 150 sorteos (en cada
sorteo solo se "ve" el pasado) y la tabla de resultados se muestra en la web. Si ninguna
combinación de pesos le gana al azar, el óptimo queda en 0 (azar puro).

### Red neuronal LSTM (`src/red_neuronal.py`, opcional)

Si PyTorch está instalado (`pip install torch`), se agrega la estrategia **Red neuronal LSTM**:
recibe los últimos 20 sorteos como vectores multi-hot, pasa por una capa LSTM de 48 neuronas
y devuelve un logit por número (softmax × k = probabilidad). Se entrena con log-verosimilitud,
dropout 0.3, weight decay y early stopping sobre el 15% final. En el backtest se reentrena
cada 30 sorteos usando solo el pasado, y se mide igual que las demás estrategias. Sin
PyTorch, el resto funciona igual y la estrategia simplemente no aparece.

Los juegos amplían su rango con el tiempo (la Tinka pasó de 1–45 a 1–53 en 2026), así que
cada número se compara con lo esperado solo desde que existe.

La web muestrea 6 (o 5) números con esas probabilidades y aplica filtros:

- suma dentro del 80% central histórico, balance de impares/bajos observado,
- descarta combinaciones que ya salieron,
- opcional "evitar combinaciones populares": secuencias, todos ≤31 (fechas), progresiones, misma terminación.

Cada jugada muestra su **afinidad con el modelo** (percentil frente a combinaciones al azar),
la **probabilidad real** (1 en C(N,k)) y cuántas veces habría acertado 3+ en el histórico.

## Aviso

Los sorteos son aleatorios y todas las combinaciones tienen la misma probabilidad. El
backtest que se ve en la web mide cuánto se aparta el modelo del azar; espera que sea casi
nada. Evitar combinaciones populares no te hace ganar más seguido, pero reduce la chance de
compartir el pozo. Juega con responsabilidad.
