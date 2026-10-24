"""Red neuronal LSTM para estimar la probabilidad de cada número en el próximo
sorteo a partir de la secuencia de los últimos VENTANA sorteos.

Entrada: por cada sorteo, un vector multi-hot de tamaño N (1 = el número salió).
Salida: un logit por número; softmax sobre los números vigentes × k = probabilidad
marginal de salir. Se entrena con la log-verosimilitud de los números que salieron.

El backtest es walk-forward: la red se reentrena cada REENTRENO sorteos usando
solo sorteos anteriores al bloque que va a predecir.
Requiere PyTorch; si no está instalado, disponible() devuelve False.
"""
import importlib.util

torch = nn = None   # PyTorch se importa recién al usar la red (es pesado y opcional)

VENTANA = 20        # sorteos que ve la red para predecir el siguiente
OCULTAS = 48        # neuronas de la capa LSTM
EPOCAS = 80
PACIENCIA = 8       # épocas sin mejorar en validación antes de parar
REENTRENO = 30      # cada cuántos sorteos se reentrena en el backtest
SEMILLA = 7


def disponible():
    return importlib.util.find_spec("torch") is not None


def _cargar_torch():
    global torch, nn
    if torch is None:
        import torch as _torch
        torch, nn = _torch, _torch.nn
        torch.set_num_threads(4)


def _crear_red(N):
    class LSTMLoteria(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(N, OCULTAS, batch_first=True)
            self.drop = nn.Dropout(0.3)
            self.salida = nn.Linear(OCULTAS, N)

        def forward(self, x):
            h, _ = self.lstm(x)
            return self.salida(self.drop(h[:, -1]))

    return LSTMLoteria()


def _tensores(sorteos, N):
    """Matriz multi-hot (T, N) y máscara de números vigentes en cada sorteo."""
    T = len(sorteos)
    hot = torch.zeros(T, N)
    vigente = torch.zeros(T, N, dtype=torch.bool)
    for t, s in enumerate(sorteos):
        hot[t, [b - 1 for b in s["bolas"]]] = 1.0
        vigente[t, : s["N"]] = True
    return hot, vigente


def _perdida(logits, objetivo, mascara):
    logits = logits.masked_fill(~mascara, -1e9)
    logp = torch.log_softmax(logits, dim=1)
    return -(logp * objetivo).sum(1).mean()


def _entrenar(hot, vigente, hasta, N):
    """Entrena con los sorteos [0, hasta). Usa el último 15% como validación."""
    torch.manual_seed(SEMILLA)
    idx = list(range(VENTANA, hasta))
    if len(idx) < 40:
        return None
    corte = int(len(idx) * 0.85)
    X = torch.stack([hot[t - VENTANA:t] for t in idx])
    Y, M = hot[idx], vigente[idx]
    tr, va = slice(0, corte), slice(corte, None)

    red = _crear_red(N)
    opt = torch.optim.Adam(red.parameters(), lr=2e-3, weight_decay=1e-4)
    mejor, estado, sin_mejora = float("inf"), None, 0
    for _ in range(EPOCAS):
        red.train()
        perm = torch.randperm(corte)
        for i in range(0, corte, 64):
            b = perm[i:i + 64]
            opt.zero_grad()
            _perdida(red(X[tr][b]), Y[tr][b], M[tr][b]).backward()
            opt.step()
        red.eval()
        with torch.no_grad():
            v = _perdida(red(X[va]), Y[va], M[va]).item()
        if v < mejor - 1e-4:
            mejor, sin_mejora = v, 0
            estado = {k: t.clone() for k, t in red.state_dict().items()}
        else:
            sin_mejora += 1
            if sin_mejora >= PACIENCIA:
                break
    red.load_state_dict(estado)
    red.eval()
    return red


def _predecir(red, hot, t, mascara, k):
    with torch.no_grad():
        logits = red(hot[t - VENTANA:t].unsqueeze(0))[0].masked_fill(~mascara, -1e9)
        p = torch.softmax(logits, 0) * k
    return [min(0.999, float(x)) for x in p]


def walk_forward(sorteos, N, k, inicio):
    """Probabilidades para cada sorteo t >= inicio, usando solo sorteos < t."""
    _cargar_torch()
    hot, vigente = _tensores(sorteos, N)
    out, red = [], None
    for t in range(inicio, len(sorteos)):
        if red is None or (t - inicio) % REENTRENO == 0:
            red = _entrenar(hot, vigente, t, N)
        if red is None:
            out.append([k / sorteos[t]["N"]] * N)
        else:
            out.append(_predecir(red, hot, t, vigente[t], k))
    return out


def siguiente(sorteos, N, k):
    """Probabilidades para el próximo sorteo, entrenando con todo el histórico."""
    _cargar_torch()
    hot, vigente = _tensores(sorteos, N)
    red = _entrenar(hot, vigente, len(sorteos), N)
    if red is None:
        return [k / N] * N
    return _predecir(red, hot, len(sorteos), torch.ones(N, dtype=torch.bool), k)
