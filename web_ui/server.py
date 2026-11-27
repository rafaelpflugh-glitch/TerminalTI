"""
============================================================
TERMINAL TI v2.0 — SERVIDOR LOCAL DA INTERFACE DESKTOP
(web_ui/server.py)
============================================================

Servidor HTTP local multithread (127.0.0.1 apenas, zero dependências extras)
que serve a interface moderna em HTML/CSS/SVG e abre como janela desktop
nativa via Microsoft Edge / Google Chrome (--app), sem barra de navegador.
"""

from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import webbrowser

from core.agent import (
    TerminalTIAgent,
    carregar_config_agente,
    salvar_config_agente,
    testar_chave_gemini,
)
from core.backup_exporter import exportar_backup_estruturado, importar_ucf_seguro
from core.catalog import (
    ICONES_HOME_CAMPOS,
    MODO_SCANNER_OPCOES,
    ORIGEM_PADRAO_OPCOES,
    TAMANHO_PAPEL_OPCOES,
    TIPO_PAPEL_OPCOES,
)
from core.esf_manager import (
    alternar_estado_app,
    desinstalar_app_embarcado,
    instalar_app_embarcado,
    listar_apps_embarcados,
)
from core.ews_client import (
    LexmarkEWSClient,
    definir_credenciais_ews,
    limpar_credenciais_ews,
    obter_credenciais_ews,
)
from core.ntp_brasil import ler_status_relogio_impressora, sincronizar_hora_brasilia
from core.pjl_snmp_client import enviar_pjl, escanear_portas_impressora, snmp_get
from core.safe_tools import (
    _snmp_seguro,
    alterar_idioma,
    alterar_visor_lcd,
    configurar_impressao_segura,
    configurar_painel_geral,
    configurar_tela_inicial,
    definir_modo_scanner,
    diagnostico_completo,
    escanear_rede_lexmark,
    imprimir_relatorio_bancada,
    imprimir_relatorio_nativo,
    ler_modo_scanner,
    ler_tela_inicial,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
HIST_IPS_PATH = ROOT_DIR / "historico_ips.json"

_AGENTE_SINGLETON = TerminalTIAgent()
_AGENTE_LOCK = threading.Lock()


def _carregar_historico_ips(ip_inicial: str = "192.168.14.134") -> List[str]:
    ips: List[str] = [ip_inicial] if ip_inicial else ["192.168.14.134"]
    if HIST_IPS_PATH.is_file():
        try:
            salvos = json.loads(HIST_IPS_PATH.read_text(encoding="utf-8"))
            if isinstance(salvos, list):
                for item in salvos:
                    s = str(item).strip()
                    if s and s not in ips:
                        ips.append(s)
        except Exception:
            pass
    return ips[:15]


def _registrar_ip_historico(ip: str) -> List[str]:
    ip_limpo = str(ip or "").strip()
    ips = _carregar_historico_ips(ip_limpo)
    if ip_limpo:
        ips = [ip_limpo] + [x for x in ips if x != ip_limpo]
        try:
            HIST_IPS_PATH.write_text(json.dumps(ips[:15], indent=2), encoding="utf-8")
        except Exception:
            pass
    return ips[:15]


def _escolher_pasta_windows(inicial: str) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        pasta = filedialog.askdirectory(title="Selecionar Pasta de Destino", initialdir=inicial or str(ROOT_DIR))
        root.destroy()
        return pasta or ""
    except Exception:
        return ""


def _salvar_temp_base64(nome: str, b64_data: str) -> Path:
    raw = base64.b64decode(b64_data.split(",")[-1])
    seguro = Path(nome or "upload.bin").name
    tmp_dir = Path(tempfile.mkdtemp(prefix="terminalti_"))
    destino = tmp_dir / seguro
    destino.write_bytes(raw)
    return destino


def _dispatch_api(path: str, body: Dict[str, Any], ip_inicial: str) -> Dict[str, Any]:
    ip = str(body.get("ip") or ip_inicial or "192.168.14.134").strip()
    community = str(body.get("community") or "public").strip() or "public"

    # 1. Estado inicial / catálogo
    if path == "/api/state":
        ips = _carregar_historico_ips(ip_inicial)
        cred = obter_credenciais_ews(ip)
        cfg_ag = carregar_config_agente()
        return {
            "ok": True,
            "ip_inicial": ip_inicial,
            "historico_ips": ips,
            "backup_dir_padrao": str(ROOT_DIR / "Backups"),
            "auth_ativa": bool(cred and (cred.usuario or cred.senha or cred.pin or cred.usar_https)),
            "auth_https": bool(cred.usar_https) if cred else False,
            "agente": {
                "usar_llm": bool(cfg_ag.get("usar_llm", False)),
                "tem_chave": bool(cfg_ag.get("api_key")),
                "modelo_gemini": cfg_ag.get("modelo_gemini", "gemini-flash-lite-latest"),
            },
            "catalogos": {
                "home_botoes": [{"key": k, "nome": n, "desc": d} for k, n, d in ICONES_HOME_CAMPOS],
                "scanner_modos": [{"nome": n, "valor": v} for n, v in MODO_SCANNER_OPCOES.items()],
                "origens": [{"nome": n, "valor": v} for n, v in ORIGEM_PADRAO_OPCOES.items()],
                "tamanhos": [{"nome": n, "valor": v} for n, v in TAMANHO_PAPEL_OPCOES.items()],
                "tipos": [{"nome": n, "valor": v} for n, v in TIPO_PAPEL_OPCOES.items()],
            },
        }

    # 2. Dashboard (Telemetria completa)
    if path == "/api/dashboard":
        ips = _registrar_ip_historico(ip)
        diag = diagnostico_completo(ip, community=community)

        s2_desc = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.6.1.2", community)
        s2_cur = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.9.1.2", community)
        s2_max = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.8.1.2", community)
        s2_pct = None
        try:
            if int(s2_max) > 0 and int(s2_cur) >= 0:
                s2_pct = max(0, min(100, round((int(s2_cur) / int(s2_max)) * 100)))
        except Exception:
            pass

        relogio = {"hora_impressora": "N/D", "ntp_ativo": False, "servidor_ntp": ""}
        try:
            relogio = ler_status_relogio_impressora(ip)
        except Exception:
            pass

        cred = obter_credenciais_ews(ip)
        return {
            "ok": True,
            "historico_ips": ips,
            "diag": diag,
            "sup2": {
                "desc": "" if s2_desc in ("N/D", "NoSuchObject / NoSuchInstance") else s2_desc,
                "atual": s2_cur,
                "max": s2_max,
                "pct": s2_pct,
            },
            "relogio": relogio,
            "auth_ativa": bool(cred and (cred.usuario or cred.senha or cred.pin or cred.usar_https)),
            "auth_https": bool(cred.usar_https) if cred else False,
        }

    # 3. Descoberta de rede Lexmark
    if path == "/api/discover":
        return escanear_rede_lexmark(ip, community=community)

    # 4. Autenticação EWS / HTTPS (somente RAM)
    if path == "/api/auth/set":
        definir_credenciais_ews(
            ip,
            usuario=body.get("usuario", ""),
            senha=body.get("senha", ""),
            pin=body.get("pin", ""),
            usar_https=bool(body.get("usar_https", False)),
        )
        return {"ok": True, "mensagem": f"Credenciais de sessão ativadas em RAM para {ip}."}

    if path == "/api/auth/clear":
        limpar_credenciais_ews(ip)
        return {"ok": True, "mensagem": f"Credenciais removidas da sessão para {ip}."}

    if path == "/api/auth/test":
        r = LexmarkEWSClient(
            ip,
            usuario=body.get("usuario", ""),
            senha=body.get("senha", ""),
            pin=body.get("pin", ""),
            usar_https=bool(body.get("usar_https", False)),
        ).testar_conexao_ews()
        return {"ok": True, "resultado": r, "mensagem": f"Acesso validado via {r['protocolo']} (HTTP {r['status_code']}) — {r['autenticado']}"}

    # 5. NTP Oficial de Brasília
    if path == "/api/ntp/read":
        return {"ok": True, "relogio": ler_status_relogio_impressora(ip)}

    if path == "/api/ntp/sync":
        return sincronizar_hora_brasilia(
            ip,
            ativar_ntp_nativo=bool(body.get("ativar_ntp_nativo", False)),
            servidor_ntp=str(body.get("servidor_ntp") or "a.st1.ntp.br"),
        )

    # 6. Modo do Scanner MFP
    if path == "/api/scanner/read":
        return ler_modo_scanner(ip)

    if path == "/api/scanner/set":
        return definir_modo_scanner(ip, str(body.get("modo", "0")))

    # 7. Idioma / Visor / Painel
    if path == "/api/system/language":
        return alterar_idioma(ip, str(body.get("idioma", "portugues")))

    if path == "/api/system/display":
        return alterar_visor_lcd(ip, str(body.get("texto", "")))

    if path == "/api/system/panel":
        return configurar_painel_geral(
            ip,
            brilho=body.get("brilho"),
            bipe_adf=body.get("bipe_adf"),
            ativar_vnc=body.get("ativar_vnc"),
        )

    # 8. Tela Inicial & Papel & Wallpaper
    if path == "/api/home/read":
        return ler_tela_inicial(ip)

    if path == "/api/home/preset":
        return configurar_tela_inicial(ip, preset=str(body.get("preset", "corporativo")))

    if path == "/api/home/apply":
        valores = body.get("valores") or {}
        alt = {str(k): ("1" if bool(v) else "0") for k, v in valores.items()}
        LexmarkEWSClient(ip).gravar_campos_formulario(
            "/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html",
            alt,
            "/cgi-bin/posttest/printer/config/gen/sub/add_btns.html",
        )
        return ler_tela_inicial(ip)

    if path == "/api/paper/apply":
        alt_ews = {}
        if body.get("origem"):
            alt_ews["0.system.1782"] = str(body["origem"])
        if body.get("tamanho"):
            alt_ews["0.system.1790"] = str(body["tamanho"])
        if body.get("tipo"):
            alt_ews["0.system.1791"] = str(body["tipo"])
        if alt_ews:
            LexmarkEWSClient(ip).gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/papermenu.html",
                alt_ews,
                "/cgi-bin/posttest/printer/config/gen/papermenu.html",
            )
        r_pjl = configurar_impressao_segura(
            ip,
            papel=body.get("papel_pjl"),
            duplex=body.get("duplex"),
            eco=body.get("eco"),
            densidade=body.get("densidade"),
        )
        return {"ok": True, "resumo": f"Configurações de papel aplicadas no EWS e PJL.\n{r_pjl['resumo']}"}

    if path == "/api/wallpaper/upload":
        tmp = _salvar_temp_base64(body.get("nome", "wallpaper.jpg"), body.get("conteudo_b64", ""))
        try:
            res = LexmarkEWSClient(ip).enviar_papel_parede(str(tmp), redimensionar=True)
            return {"ok": True, "resumo": f"Papel de parede enviado e ajustado para 800x414 ({res.get('arquivo')})."}
        finally:
            tmp.unlink(missing_ok=True)

    # 9. Embarcados (eSF / NDD)
    if path == "/api/esf/list":
        return listar_apps_embarcados(ip)

    if path == "/api/esf/toggle":
        return alternar_estado_app(ip, str(body.get("app_id", "")), str(body.get("acao", "Desativar")))

    if path == "/api/esf/uninstall":
        return desinstalar_app_embarcado(ip, str(body.get("app_id", "")), str(body.get("nome", "")))

    if path == "/api/esf/install":
        tmp_app = _salvar_temp_base64(body.get("nome", "app.fls"), body.get("conteudo_b64", ""))
        tmp_cfg = None
        if body.get("cfg_b64"):
            tmp_cfg = _salvar_temp_base64(body.get("cfg_nome", "settingfileesf.ucf"), body.get("cfg_b64", ""))
        try:
            return instalar_app_embarcado(
                ip,
                str(tmp_app),
                sincronizar_hora_antes=bool(body.get("sincronizar_hora", True)),
                caminho_config_esf_ucf=str(tmp_cfg) if tmp_cfg else None,
            )
        finally:
            tmp_app.unlink(missing_ok=True)
            if tmp_cfg:
                tmp_cfg.unlink(missing_ok=True)

    # 10. Backup 4 Categorias & Importação Segura
    if path == "/api/backup/pick_folder":
        pasta = _escolher_pasta_windows(str(body.get("inicial") or (ROOT_DIR / "Backups")))
        return {"ok": True, "pasta": pasta}

    if path == "/api/backup/export":
        pasta = str(body.get("pasta") or (ROOT_DIR / "Backups")).strip()
        return exportar_backup_estruturado(
            ip=ip,
            pasta_destino=pasta,
            incluir_configuracoes=bool(body.get("configuracoes", True)),
            incluir_embarcados=bool(body.get("embarcados", True)),
            incluir_rede=bool(body.get("rede", True)),
            incluir_arquivos=bool(body.get("arquivos", True)),
            gerar_zip=bool(body.get("gerar_zip", True)),
            community=community,
        )

    if path == "/api/backup/import":
        tmp = _salvar_temp_base64(body.get("nome", "settingfile.ucf"), body.get("conteudo_b64", ""))
        try:
            return importar_ucf_seguro(ip, str(tmp), ignorar_chaves_rede=bool(body.get("preservar_ip", True)))
        finally:
            tmp.unlink(missing_ok=True)

    # 11. Relatórios 9100
    if path == "/api/reports/bench":
        return imprimir_relatorio_bancada(ip, titulo=str(body.get("titulo") or "RELATORIO DE BANCADA - TERMINAL TI"), community=community)

    if path == "/api/reports/native":
        return imprimir_relatorio_nativo(ip, tipo=str(body.get("tipo") or "menus"))

    # 12. Engenharia (PJL, SNMP, EWS/SE, Portas)
    if path == "/api/engineering/pjl":
        cmd = str(body.get("comando") or "INFO STATUS").strip()
        resp = enviar_pjl(ip, [cmd], aguardar_resposta=True, timeout=6.0)
        return {"ok": True, "resumo": resp}

    if path == "/api/engineering/snmp":
        oid = str(body.get("oid") or "1.3.6.1.2.1.1.1.0").strip().split()[0]
        val = snmp_get(ip, oid, comunidade=community, timeout=3.0)
        return {"ok": True, "oid": oid, "valor": val, "resumo": f"{oid} = {val}"}

    if path == "/api/engineering/ews":
        ep = str(body.get("endpoint") or "/cgi-bin/dynamic/se_index.html").strip()
        txt = LexmarkEWSClient(ip).ler_pagina_texto(ep)
        return {"ok": True, "endpoint": ep, "resumo": txt[:12000]}

    if path == "/api/engineering/ports":
        portas = escanear_portas_impressora(ip)
        return {"ok": True, "portas": portas, "resumo": "\n".join(f"{k}: {v}" for k, v in portas.items())}

    # 13. Agente TI (inclui confirmação crítica com PIN!)
    if path == "/api/agent/command":
        cmd = str(body.get("comando") or "").strip()
        with _AGENTE_LOCK:
            resp = _AGENTE_SINGLETON.processar_comando(cmd, ip_padrao=ip, community=community)
        pend = None
        if resp.confirmacao_pendente is not None:
            p = resp.confirmacao_pendente
            pend = {
                "token": p.token,
                "tool": p.tool,
                "titulo": p.titulo,
                "ip": p.ip,
                "modelo": p.modelo_detectado,
                "serial": p.serial_detectado,
                "parametros": p.resumo_parametros,
                "riscos": p.riscos,
                "segundos": p.segundos_restantes(),
            }
        return {
            "ok": resp.ok,
            "motor": resp.motor,
            "acao": resp.acao,
            "mensagem": resp.mensagem,
            "confirmacao_pendente": pend,
        }

    if path == "/api/agent/config":
        cfg_atual = carregar_config_agente()
        nova_chave = str(body.get("api_key") or "").strip()
        if not nova_chave and body.get("manter_chave_atual"):
            nova_chave = cfg_atual.get("api_key", "")
        usar = bool(body.get("usar_llm", False))
        modelo = str(body.get("modelo_gemini") or cfg_atual.get("modelo_gemini") or "gemini-flash-lite-latest")
        salvar_config_agente(nova_chave, usar, modelo)
        with _AGENTE_LOCK:
            _AGENTE_SINGLETON.recarregar_config()
        return {
            "ok": True,
            "agente": {"usar_llm": usar, "tem_chave": bool(nova_chave), "modelo_gemini": modelo},
            "mensagem": "Configuração da API Google Gemini atualizada.",
        }

    if path == "/api/agent/test_key":
        chave = str(body.get("api_key") or "").strip() or carregar_config_agente().get("api_key", "")
        modelo = str(body.get("modelo_gemini") or "gemini-flash-lite-latest").strip()
        ok, msg = testar_chave_gemini(chave, modelo)
        return {"ok": ok, "mensagem": msg}

    # 14. Firmware upload para fluxo crítico (salva em temp e solicita confirmação com PIN via Agente!)
    if path == "/api/critical/prepare_firmware":
        tmp = _salvar_temp_base64(body.get("nome", "firmware.fls"), body.get("conteudo_b64", ""))
        with _AGENTE_LOCK:
            resp = _AGENTE_SINGLETON.processar_comando(f'atualizar firmware "{tmp}"', ip_padrao=ip, community=community)
        pend = None
        if resp.confirmacao_pendente is not None:
            p = resp.confirmacao_pendente
            pend = {
                "token": p.token,
                "tool": p.tool,
                "titulo": p.titulo,
                "ip": p.ip,
                "modelo": p.modelo_detectado,
                "serial": p.serial_detectado,
                "parametros": p.resumo_parametros,
                "riscos": p.riscos,
                "segundos": p.segundos_restantes(),
            }
        return {"ok": resp.ok, "motor": resp.motor, "acao": resp.acao, "mensagem": resp.mensagem, "confirmacao_pendente": pend}

    return {"ok": False, "erro": f"Endpoint desconhecido: {path}"}


def _criar_handler(ip_inicial: str):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args):
            pass  # Mantém o console limpo

        def _enviar_json(self, dados: Dict[str, Any], status: int = 200):
            raw = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parsed = urlparse(self.path)
            rota = parsed.path

            if rota == "/api/state":
                try:
                    self._enviar_json(_dispatch_api(rota, {}, ip_inicial))
                except Exception as err:
                    self._enviar_json({"ok": False, "erro": str(err)}, status=500)
                return

            if rota == "/" or rota == "":
                rota = "/index.html"

            alvo = (STATIC_DIR / rota.lstrip("/")).resolve()
            if not str(alvo).startswith(str(STATIC_DIR.resolve())) or not alvo.is_file():
                self.send_error(404, "Not Found")
                return

            mime, _ = mimetypes.guess_type(str(alvo))
            raw = alvo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            parsed = urlparse(self.path)
            rota = parsed.path
            length = int(self.headers.get("Content-Length") or "0")
            body_raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
            except Exception:
                body = {}
            try:
                res = _dispatch_api(rota, body, ip_inicial)
                self._enviar_json(res, status=200)
            except Exception as err:
                self._enviar_json({"ok": False, "erro": str(err)}, status=200)

    return _Handler


def _encontrar_navegador_app() -> Optional[str]:
    candidatos = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / r"Google\Chrome\Application\chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / r"Google\Chrome\Application\chrome.exe",
    ]
    for c in candidatos:
        if c.is_file():
            return str(c)
    return None


def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def iniciar_web_app(ip_inicial: str = "192.168.14.134", abrir_janela: bool = True) -> None:
    porta = _porta_livre()
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), _criar_handler(ip_inicial))
    url = f"http://127.0.0.1:{porta}/"

    th = threading.Thread(target=servidor.serve_forever, daemon=True)
    th.start()
    print(f"Terminal TI v2.0 ativo em {url} (IP inicial: {ip_inicial})")

    if not abrir_janela:
        return

    navegador = _encontrar_navegador_app()
    if navegador:
        perfil_app = Path(tempfile.gettempdir()) / "TerminalTI_AppProfile"
        perfil_app.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [
                navegador,
                f"--app={url}",
                "--window-size=1280,820",
                f"--user-data-dir={perfil_app}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            servidor.shutdown()
    else:
        webbrowser.open(url)
        try:
            th.join()
        except KeyboardInterrupt:
            servidor.shutdown()
