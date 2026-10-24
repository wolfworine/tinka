"""Servidor local: sirve la carpeta web/ y expone POST /api/actualizar, que
descarga los sorteos nuevos y reconstruye el modelo (lo mismo que hace el .bat).

Uso: python src/servidor.py [puerto] [--sin-navegador]
"""
import contextlib
import io
import json
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modelo  # noqa: E402
import scraper  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"
candado = threading.Lock()


def actualizar_todo():
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        scraper.actualizar_historico()
        for juego in scraper.JUEGOS:
            scraper.actualizar(juego)
        modelo.main()
    return log.getvalue()


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        if self.path != "/api/actualizar":
            self.send_error(404)
            return
        if not candado.acquire(blocking=False):
            codigo, cuerpo = 409, {"ok": False, "log": "Ya hay una actualización en curso."}
        else:
            try:
                codigo, cuerpo = 200, {"ok": True, "log": actualizar_todo()}
            except Exception as e:  # se informa a la web en vez de tumbar el servidor
                codigo, cuerpo = 500, {"ok": False, "log": f"Error: {e}"}
            finally:
                candado.release()
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    puerto = int(args[0]) if args else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), partial(Handler, directory=str(WEB)))
    url = f"http://127.0.0.1:{puerto}/"
    print(f"Web disponible en {url}  (Ctrl+C para detener)")
    if "--sin-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
