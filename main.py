"""
============================================================
TERMINAL TI — PONTO DE ENTRADA (main.py)
============================================================

Aplicação independente de Engenharia e Bancada para administração
completa de impressoras Lexmark via EWS HTTP/CGI, PJL RAW 9100
e SNMPv2c Nativo.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from interface.app_window import TerminalTIApp


def iniciar(ip_inicial: str = "192.168.14.134"):
    app = TerminalTIApp(ip_inicial=ip_inicial)
    app.mainloop()


if __name__ == "__main__":
    ip_arg = sys.argv[1] if len(sys.argv) > 1 else "192.168.14.134"
    iniciar(ip_arg)
