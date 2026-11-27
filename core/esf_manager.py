"""
============================================================
TERMINAL TI — GERENCIADOR DE EMBARCADOS (eSF / NDD)
(core/esf_manager.py)
============================================================

Gerencia aplicativos embarcados Lexmark eSF (como NDD Print / nddPrint,
Digitalizar para Rede, Cópia do Cartão, etc.) pelos endpoints nativos:
- /cgi-bin/dynamic/printer/config/gen/unifiedSolutions_apps.html
- /cgi-bin/dynamic/printer/config/gen/unifiedSolutions_bundles.html
- /cgi-bin/dynamic/printer/config/gen/unifiedSolutions_install.html
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from core.ews_client import EWSClientError, LexmarkEWSClient
from core.ntp_brasil import sincronizar_hora_brasilia


def listar_apps_embarcados(ip: str) -> Dict[str, Any]:
    """
    Lê a tabela de aplicativos embarcados instalados em unifiedSolutions_apps.html
    e retorna lista estruturada com app_id, nome, versão, licença e status.
    """
    ews = LexmarkEWSClient(ip, timeout=12)
    html = ews.ler_pagina_texto("/cgi-bin/dynamic/printer/config/gen/unifiedSolutions_apps.html")

    apps: List[Dict[str, Any]] = []
    linhas_tr = re.findall(r"<TR[^>]*>(.*?)</TR>", html, re.I | re.S)
    for tr in linhas_tr:
        # Procura ID do app no link de nome ou no toggleState('appId', 'Acao')
        m_toggle = re.search(r"toggleState\s*\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", tr, re.I)
        m_id = re.search(r'ID="([^"]+)"[^>]*>(.*?)</A>', tr, re.I | re.S)
        if not m_toggle and not m_id:
            continue

        app_id = m_toggle.group(1) if m_toggle else m_id.group(1)
        acao_toggle = m_toggle.group(2) if m_toggle else ""
        nome = re.sub(r"<[^>]+>", "", m_id.group(2)).strip() if m_id else app_id

        tds = re.findall(r"<TD[^>]*>(.*?)</TD>", tr, re.I | re.S)
        limpos = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", td)).replace("&nbsp;", "").strip() for td in tds]

        versao = limpos[2] if len(limpos) > 2 else "N/D"
        licenca = limpos[4] if len(limpos) > 4 else "N/D"
        ativo = acao_toggle.lower().startswith(("desativ", "stop", "parar", "disable"))
        pode_desinstalar = "ConfirmDelete(" in tr

        eh_ndd = any(k in (app_id + " " + nome).lower() for k in ("ndd", "nddprint", "printwayy", "papercut"))
        apps.append(
            {
                "app_id": app_id,
                "nome": nome,
                "versao": versao,
                "licenca": licenca,
                "ativo": ativo,
                "acao_toggle": acao_toggle,
                "pode_desinstalar": pode_desinstalar,
                "eh_ndd": eh_ndd,
            }
        )

    linhas_resumo = [f"📦 APLICATIVOS EMBARCADOS (eSF) EM {ip} ({len(apps)} encontrados):"]
    if not apps:
        linhas_resumo.append("• Nenhum aplicativo embarcado listado (ou modelo sem suporte a eSF clássico).")
    for a in apps:
        st = "🟢 ATIVO" if a["ativo"] else "⚪ PARADO"
        tag_ndd = " [NDD/BILHETAGEM]" if a["eh_ndd"] else ""
        linhas_resumo.append(
            f"• {st} | {a['nome']} ({a['app_id']}) v{a['versao']} | Licença: {a['licenca']}{tag_ndd}"
        )

    return {"ok": True, "ip": ip, "apps": apps, "resumo": "\n".join(linhas_resumo)}


def alternar_estado_app(ip: str, app_id: str, acao_toggle: str) -> Dict[str, Any]:
    """
    Ativa ou Desativa um aplicativo embarcado via POST em unifiedSolutions_bundles.html.
    """
    ews = LexmarkEWSClient(ip, timeout=20)
    url = ews._url("/cgi-bin/dynamic/printer/config/gen/unifiedSolutions_bundles.html")
    payload = {
        "appId": str(app_id).strip(),
        "state": str(acao_toggle).strip(),
        "appType": "",
    }
    try:
        resp = ews.session.post(url, data=payload, timeout=25)
        resp.raise_for_status()
        return {
            "ok": True,
            "ip": ip,
            "app_id": app_id,
            "acao": acao_toggle,
            "resumo": f"✅ Comando '{acao_toggle}' enviado para o app '{app_id}' em {ip} (HTTP {resp.status_code}).",
        }
    except Exception as err:
        raise EWSClientError(f"Falha ao alterar estado do app '{app_id}': {err}") from err


def desinstalar_app_embarcado(ip: str, app_id: str, nome_app: str, soln_type: str = "eSF") -> Dict[str, Any]:
    """Desinstala um aplicativo embarcado não-nativo (ex.: NDD antigo antes de reinstalar)."""
    ews = LexmarkEWSClient(ip, timeout=30)
    url = ews._url("/cgi-bin/dynamic/printer/config/gen/unifiedSolutions_bundles.html")
    payload = {
        "appId": str(app_id).strip(),
        "state": str(nome_app).strip(),
        "appType": str(soln_type).strip(),
    }
    try:
        resp = ews.session.post(url, data=payload, timeout=45)
        resp.raise_for_status()
        return {
            "ok": True,
            "ip": ip,
            "app_id": app_id,
            "resumo": f"🗑️ Desinstalação do app '{nome_app}' ({app_id}) enviada para {ip} (HTTP {resp.status_code}).",
        }
    except Exception as err:
        raise EWSClientError(f"Falha ao desinstalar '{nome_app}': {err}") from err


def instalar_app_embarcado(
    ip: str,
    caminho_arquivo: str,
    sincronizar_hora_antes: bool = True,
    caminho_config_esf_ucf: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Instala um pacote embarcado eSF (ex.: NDD Print .fls ou licença .lic) via
    /cgi-bin/dynamic/printer/config/gen/unifiedSolutions_install.html.

    Boas práticas de campo embutidas:
    1. Valida extensão (.fls, .lic, .jar, .zip) e arquivo existente.
    2. Opcionalmente sincroniza o relógio com o Horário Oficial de Brasília (NTP.br)
       antes da instalação (evita falhas de certificado/token no NDD).
    3. Faz upload multipart oficial no campo 'input_file'.
    4. Opcionalmente aplica o arquivo settingfileesf.ucf logo após a instalação.
    """
    arq = Path(str(caminho_arquivo or "").strip().strip("\"'"))
    if not arq.is_file():
        raise EWSClientError(f"Arquivo do embarcado não encontrado: {arq}")
    if arq.suffix.lower() not in (".fls", ".lic", ".jar", ".zip"):
        raise EWSClientError(f"Extensão '{arq.suffix}' não suportada para app embarcado. Use .fls ou .lic.")

    etapas: List[str] = []

    if sincronizar_hora_antes:
        try:
            r_ntp = sincronizar_hora_brasilia(ip, ativar_ntp_nativo=False)
            etapas.append(f"🕒 Pré-checagem de relógio: {r_ntp['data_hora_brt']} BRT ({r_ntp['fonte']})")
        except Exception as err_ntp:
            etapas.append(f"⚠️ Não foi possível sincronizar hora antes (prosseguindo): {err_ntp}")

    ews = LexmarkEWSClient(ip, timeout=20)
    url = ews._url("/cgi-bin/dynamic/printer/config/gen/unifiedSolutions_install.html")
    try:
        # GET preparatório na sessão
        ews.session.get(url, timeout=15)
        with open(arq, "rb") as fp:
            files = {"input_file": (arq.name, fp, "application/octet-stream")}
            resp = ews.session.post(url, files=files, timeout=180)
            resp.raise_for_status()
    except Exception as err:
        raise EWSClientError(f"Falha ao enviar embarcado '{arq.name}' para {ip}: {err}") from err

    html_resp = ews._decodificar(resp)
    m_st = re.search(r'id="status_msg"[^>]*>(.*?)</span>', html_resp, re.I | re.S)
    status_ews = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m_st.group(1))).strip() if m_st else "Pacote enviado (HTTP 200)"
    etapas.append(f"📦 Upload '{arq.name}' ({round(arq.stat().st_size / 1024, 1)} KB): {status_ews}")

    if caminho_config_esf_ucf:
        cfg_arq = Path(caminho_config_esf_ucf)
        if cfg_arq.is_file():
            r_cfg = ews.importar_configuracao_ucf(str(cfg_arq))
            etapas.append(f"⚙️ Configuração '{cfg_arq.name}' aplicada (HTTP {r_cfg.get('status_code')})")

    return {
        "ok": True,
        "ip": ip,
        "arquivo": arq.name,
        "status_ews": status_ews,
        "resumo": (
            f"✅ Instalação de embarcado concluída em {ip}!\n"
            + "\n".join(f"• {e}" for e in etapas)
            + "\nℹ️ O subsistema eSF/Java pode levar 30 a 90 segundos para inicializar o novo app no painel."
        ),
    }
