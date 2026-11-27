"""
============================================================
TERMINAL TI v2.0 — PONTO DE ENTRADA (main.py)
============================================================

Inicia por padrão a interface desktop moderna v2 (HTML/CSS/SVG
em janela limpa nativa via Chrome/Edge --app, troca de tela em 0 ms).
- `python main.py 192.168.14.134` -> abre v2 já apontando para o IP
- `python main.py --v1`           -> abre a interface clássica Tkinter v1
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def iniciar(ip_inicial: str = "192.168.14.134", forcar_v1: bool = False):
    if forcar_v1:
        from interface.app_window import TerminalTIApp
        app = TerminalTIApp(ip_inicial=ip_inicial)
        app.mainloop()
        return

    from web_ui.server import iniciar_web_app
    iniciar_web_app(ip_inicial=ip_inicial, abrir_janela=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    forcar_v1 = "--v1" in args
    ips = [a for a in args if not a.startswith("-")]
    ip_arg = ips[0] if ips else "192.168.14.134"
    iniciar(ip_arg, forcar_v1=forcar_v1)
