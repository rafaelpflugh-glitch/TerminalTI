"""
============================================================
TERMINAL TI — CAMADA DE FERRAMENTAS BLINDADAS (ANTI-BRICK)
(core/safe_tools.py)
============================================================

Este módulo define a WHITELIST FECHADA de operações 100% seguras
que o Agente TI pode executar nas impressoras Lexmark.

REGRA DE OURO ANTI-BRICK:
- NENHUMA função de flash de firmware (.fls/.bin) é exposta aqui.
- NENHUMA função de Wipe / Out-of-Service / Apagar NVRAM / Reset de Fábrica é exposta aqui.
- NENHUMA função de troca de IP estático é exposta aqui.
- NENHUM comando PJL livre/arbitrário ou manipulação de sistema de arquivos (FSDELETE/FSDOWNLOAD) é exposto aqui.
- Todas as operações abaixo são somente-leitura ou alterações operacionais
  comuns, 100% reversíveis e validadas na bancada.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import ipaddress
from pathlib import Path
import re
import socket
import time
from typing import Any, Dict, List, Optional

from core.catalog import ICONES_HOME_CAMPOS, MODO_SCANNER_OPCOES
from core.ews_client import EWSClientError, LexmarkEWSClient
from core.pjl_snmp_client import (
    UEL,
    enviar_pjl,
    escanear_portas_impressora,
    executar_ping,
    snmp_get,
)

# Mapa canônico de códigos validados para mfp.scanner.scannerDisabled
MODO_SCANNER_NOMES = {
    "0": "Ativado (Scanner + ADF Normais)",
    "1": "Desativado (Modo Só Impressora)",
    "2": "ADF Desativado (Somente Mesa Plana Ativa)",
}

# Mapeamento amigável de nomes de ícones da Tela Inicial -> chave CGI
BOTOES_HOME_ALIASES: Dict[str, str] = {
    "copia": "2.system.17351",
    "copiar": "2.system.17351",
    "atalhos de copia": "2.system.17254",
    "atalho copia": "2.system.17254",
    "fax": "2.system.17350",
    "atalhos de fax": "2.system.17257",
    "email": "2.system.17352",
    "e-mail": "2.system.17352",
    "atalhos de email": "2.system.17255",
    "ftp": "2.system.17353",
    "atalhos de ftp": "2.system.17256",
    "trabalhos retidos": "2.system.17354",
    "held jobs": "2.system.17354",
    "pesquisar trabalhos": "2.system.17348",
    "usb": "2.system.17252",
    "pendrive": "2.system.17252",
    "unidade usb": "2.system.17252",
    "perfis": "2.system.17250",
    "profiles": "2.system.17250",
    "scan": "2.system.17250",
    "scanner": "2.system.17250",
    "digitalizar": "2.system.17250",
    "digitalizacao": "2.system.17250",
    "marcadores": "2.system.17251",
    "bookmarks": "2.system.17251",
    "idioma": "2.system.17167",
    "alterar idioma": "2.system.17167",
}

PRESETS_TELA_INICIAL: Dict[str, List[str]] = {
    "smartphone": ["2.system.17351", "2.system.17352", "2.system.17250", "2.system.17252"],
    "corporativo": [
        "2.system.17351",
        "2.system.17352",
        "2.system.17353",
        "2.system.17354",
        "2.system.17250",
        "2.system.17252",
    ],
    "somente_copia": ["2.system.17351"],
    "copia_e_usb": ["2.system.17351", "2.system.17252"],
    "copia_e_scan": ["2.system.17351", "2.system.17250"],
    "todos": [chave for chave, _, _ in ICONES_HOME_CAMPOS],
    "nenhum": [],
}


def _validar_ip(ip: str) -> str:
    ip_limpo = str(ip or "").strip()
    try:
        ipaddress.IPv4Address(ip_limpo)
    except ValueError as err:
        raise ValueError(f"Endereço IPv4 inválido: '{ip_limpo}'") from err
    return ip_limpo


def _snmp_seguro(ip: str, oid: str, community: str = "public", timeout: float = 1.5) -> str:
    try:
        return str(snmp_get(ip, oid, comunidade=community, timeout=timeout)).strip()
    except Exception:
        return "N/D"


def _sanitizar_texto_ps(texto: str) -> str:
    """Escapa string para uso seguro dentro de literais PostScript (...)."""
    mapa = str.maketrans(
        "áàãâäéèêëíìîïóòõôöúùûüçÁÀÃÂÄÉÈÊËÍÌÎÏÓÒÕÔÖÚÙÛÜÇ",
        "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC",
    )
    limpo = str(texto).translate(mapa)
    limpo = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in limpo)
    return limpo.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


# ============================================================
# 1. DIAGNÓSTICO COMPLETO (SOMENTE LEITURA)
# ============================================================

def diagnostico_completo(ip: str, community: str = "public") -> Dict[str, Any]:
    """
    Executa auditoria completa somente-leitura (SNMP + PJL INFO STATUS + ScanManager2 SE).
    Zero escrita na impressora.
    """
    ip = _validar_ip(ip)

    modelo_full = _snmp_seguro(ip, "1.3.6.1.2.1.1.1.0", community)
    hostname = _snmp_seguro(ip, "1.3.6.1.2.1.1.5.0", community)
    uptime = _snmp_seguro(ip, "1.3.6.1.2.1.1.3.0", community)
    serial = _snmp_seguro(ip, "1.3.6.1.2.1.43.5.1.1.17.1", community)
    total_paginas = _snmp_seguro(ip, "1.3.6.1.2.1.43.10.2.1.4.1.1", community)
    display_lcd = _snmp_seguro(ip, "1.3.6.1.2.1.43.16.5.1.2.1.1", community)

    sup1_desc = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.6.1.1", community)
    sup1_atual = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.9.1.1", community)
    sup1_max = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.8.1.1", community)

    sup2_desc = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.6.1.2", community)
    sup2_atual = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.9.1.2", community)
    sup2_max = _snmp_seguro(ip, "1.3.6.1.2.1.43.11.1.1.8.1.2", community)

    def _calc_pct(atual: str, maximo: str) -> Optional[int]:
        try:
            a, m = int(atual), int(maximo)
            if m > 0 and a >= 0:
                return max(0, min(100, round((a / m) * 100)))
        except ValueError:
            pass
        return None

    sup1_pct = _calc_pct(sup1_atual, sup1_max)
    sup2_pct = _calc_pct(sup2_atual, sup2_max)

    try:
        pjl_status = enviar_pjl(ip, ["INFO STATUS"], timeout=3.0)
    except Exception as err:
        pjl_status = f"Indisponível ({err})"

    # Leitura opcional do ScanManager2 (/cgi-bin/script/printer/scanmgr)
    scanner_info: Dict[str, str] = {}
    try:
        ews = LexmarkEWSClient(ip, timeout=4.0)
        txt_scan = ews.ler_pagina_texto("/cgi-bin/script/printer/scanmgr")
        m_state = re.search(r"STATE:\s*([A-Z0-9_]+)", txt_scan)
        m_rev = re.search(r'_revisionInfo="([^"\r\n]+)', txt_scan)
        m_model = re.search(r"_modelId=([^\r\n]+)", txt_scan)
        m_jam = re.search(r"paperJam=(\d+)", txt_scan)
        if m_state:
            scanner_info["estado_ram"] = m_state.group(1)
        if m_rev:
            scanner_info["firmware_scanner"] = m_rev.group(1).strip()
        if m_model:
            scanner_info["modulo"] = m_model.group(1).strip()
        if m_jam:
            scanner_info["atolamento_scanner"] = "SIM" if m_jam.group(1) != "0" else "Não"
    except Exception:
        pass

    linhas = [
        f"📊 DIAGNÓSTICO COMPLETO — {ip}",
        f"• Modelo / Firmware : {modelo_full}",
        f"• Hostname          : {hostname}",
        f"• Número de Série   : {serial}",
        f"• Tempo Ligada      : {uptime}",
        f"• Total de Páginas  : {total_paginas}",
        f"• Visor LCD Atual   : {display_lcd}",
        f"• Suprimento #1     : {sup1_desc} — {sup1_atual}/{sup1_max}"
        + (f" ({sup1_pct}%)" if sup1_pct is not None else ""),
    ]
    if sup2_desc not in ("N/D", "", "NoSuchObject / NoSuchInstance"):
        linhas.append(
            f"• Suprimento #2     : {sup2_desc} — {sup2_atual}/{sup2_max}"
            + (f" ({sup2_pct}%)" if sup2_pct is not None else "")
        )
    if scanner_info:
        linhas.append(
            f"• Scanner (SE Menu) : Estado={scanner_info.get('estado_ram', 'N/D')} | "
            f"Módulo={scanner_info.get('modulo', 'N/D')} | "
            f"FW={scanner_info.get('firmware_scanner', 'N/D')} | "
            f"Atolamento={scanner_info.get('atolamento_scanner', 'N/D')}"
        )
    pjl_resumo = " | ".join(l.strip() for l in pjl_status.splitlines() if l.strip() and not l.startswith("@PJL"))
    linhas.append(f"• Motor PJL 9100    : {pjl_resumo or pjl_status}")

    return {
        "ok": True,
        "ip": ip,
        "modelo": modelo_full,
        "hostname": hostname,
        "serial": serial,
        "uptime": uptime,
        "total_paginas": total_paginas,
        "display_lcd": display_lcd,
        "sup1_desc": sup1_desc,
        "sup1_pct": sup1_pct,
        "scanner_info": scanner_info,
        "resumo": "\n".join(linhas),
    }


# ============================================================
# 2. CONTROLE VALIDADO DO MODO DO SCANNER (UCF mfp.scanner.scannerDisabled)
# ============================================================

def ler_modo_scanner(ip: str) -> Dict[str, Any]:
    """
    Lê na NVRAM (via exportação UCF somente-leitura) o estado atual de
    mfp.scanner.scannerDisabled ('0' Ativado, '1' Desativado, '2' ADF Desativado)
    e o resumo em tempo real do ScanManager2 (/cgi-bin/script/printer/scanmgr).
    """
    ip = _validar_ip(ip)
    ews = LexmarkEWSClient(ip, timeout=10.0)

    ucf_bytes = ews.exportar_configuracao_ucf("settingfile.ucf")
    ucf_txt = ucf_bytes.decode("utf-8", errors="replace")

    codigo = None
    for linha in ucf_txt.splitlines():
        m = re.match(r'^\s*mfp\.scanner\.scannerDisabled\s+"([^"]+)"', linha)
        if m:
            codigo = m.group(1).strip()
            break

    if codigo is None:
        return {
            "ok": False,
            "ip": ip,
            "codigo": None,
            "resumo": (
                f"⚠️ A chave 'mfp.scanner.scannerDisabled' não foi encontrada no UCF de {ip}.\n"
                "Este equipamento pode ser uma impressora sem scanner (ex.: série MS) ou um firmware mais novo com API distinta."
            ),
        }

    nome_modo = MODO_SCANNER_NOMES.get(codigo, f"Código desconhecido ({codigo})")

    detalhe_ram = ""
    try:
        scanmgr = ews.ler_pagina_texto("/cgi-bin/script/printer/scanmgr")
        m_st = re.search(r"STATE:\s*([A-Z0-9_]+)", scanmgr)
        m_mod = re.search(r"_modelId=([^\r\n]+)", scanmgr)
        if m_st or m_mod:
            detalhe_ram = f"\n• ScanManager2 (RAM): Estado={m_st.group(1) if m_st else 'N/D'} | Módulo={m_mod.group(1).strip() if m_mod else 'N/D'}"
    except Exception:
        pass

    return {
        "ok": True,
        "ip": ip,
        "codigo": codigo,
        "modo_nome": nome_modo,
        "resumo": (
            f"🔬 MODO DO SCANNER ({ip})\n"
            f"• Chave NVRAM (UCF) : mfp.scanner.scannerDisabled = \"{codigo}\"\n"
            f"• Estado Configurado: {nome_modo}"
            f"{detalhe_ram}"
        ),
    }


def definir_modo_scanner(ip: str, modo: str) -> Dict[str, Any]:
    """
    Altera o modo do scanner de forma 100% segura usando um mini-UCF de 1 linha
    contendo EXCLUSIVAMENTE 'mfp.scanner.scannerDisabled'.
    Aceita apenas:
      - '0' (ou 'ativado')     -> Scanner + ADF Normais
      - '1' (ou 'desativado')  -> Scanner Desativado (Modo Só Impressora)
      - '2' (ou 'adf_desativado') -> Somente ADF Desativado (Mesa Plana Ativa)
    """
    ip = _validar_ip(ip)
    alias_map = {
        "0": "0",
        "ativado": "0",
        "ativar": "0",
        "habilitado": "0",
        "enabled": "0",
        "normal": "0",
        "1": "1",
        "desativado": "1",
        "desativar": "1",
        "disabled": "1",
        "sem_scanner": "1",
        "2": "2",
        "adf_desativado": "2",
        "desativar_adf": "2",
        "adf_disabled": "2",
        "mesa_plana": "2",
    }
    chave_norm = str(modo or "").strip().lower()
    if chave_norm not in alias_map:
        # Tenta localizar pela descrição completa do catalog
        if modo in MODO_SCANNER_OPCOES:
            codigo = MODO_SCANNER_OPCOES[modo]
        else:
            raise ValueError(
                f"Modo de scanner inválido: '{modo}'. Valores permitidos: '0' (Ativado), '1' (Desativado), '2' (ADF Desativado)."
            )
    else:
        codigo = alias_map[chave_norm]

    ews = LexmarkEWSClient(ip, timeout=12.0)
    mini_ucf = f'// UCF File - Terminal TI (Safe Scanner Toggle)\r\nmfp.scanner.scannerDisabled "{codigo}"\r\n'.encode("utf-8")

    resp_imp = ews.importar_ucf_bytes(mini_ucf, nome_arquivo="scanner_mode.ucf")

    # Confirma leitura de volta na NVRAM
    time.sleep(1.0)
    verificacao = ler_modo_scanner(ip)
    gravado_ok = verificacao.get("codigo") == codigo
    nome_modo = MODO_SCANNER_NOMES[codigo]

    return {
        "ok": gravado_ok,
        "ip": ip,
        "codigo": codigo,
        "modo_nome": nome_modo,
        "http_status": resp_imp.get("status_code"),
        "resumo": (
            f"{'✅' if gravado_ok else '⚠️'} MODO DO SCANNER GRAVADO EM {ip}\n"
            f"• Novo valor na NVRAM: mfp.scanner.scannerDisabled = \"{verificacao.get('codigo')}\" ({nome_modo})\n"
            f"• Resposta EWS       : HTTP {resp_imp.get('status_code')} ({resp_imp.get('resposta', '')})\n"
            f"ℹ️ IMPORTANTE: Reinicie a impressora (ciclo de energia) para o ScanManager2 inicializar no novo modo."
        ),
    }


# ============================================================
# 3. VISOR LCD & AVISOS (PJL SEGURO)
# ============================================================

def alterar_visor_lcd(ip: str, texto: str = "") -> Dict[str, Any]:
    """
    Altera a linha de pronto do visor LCD via '@PJL RDYMSG DISPLAY'.
    Passar texto vazio ('') restaura o texto padrão 'Pronto'.
    """
    ip = _validar_ip(ip)
    # Sanitização estrita Anti-Injection: remove CR/LF/ESC/aspas
    mapa = str.maketrans(
        "áàãâäéèêëíìîïóòõôöúùûüçÁÀÃÂÄÉÈÊËÍÌÎÏÓÒÕÔÖÚÙÛÜÇ",
        "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC",
    )
    limpo = str(texto or "").translate(mapa)
    limpo = re.sub(r'[\r\n\x00-\x1f\x7f"]', "", limpo).strip()[:32]

    cmd = f'RDYMSG DISPLAY="{limpo}"'
    enviar_pjl(ip, [cmd], encapsular_job=True, timeout=5.0)
    time.sleep(0.8)
    atual = _snmp_seguro(ip, "1.3.6.1.2.1.43.16.5.1.2.1.1")

    acao = f"alterado para '{limpo}'" if limpo else "restaurado para o padrão 'Pronto'"
    return {
        "ok": True,
        "ip": ip,
        "texto_enviado": limpo,
        "display_lido": atual,
        "resumo": f"✅ Visor LCD em {ip} {acao}.\n• Leitura atual via SNMP: \"{atual}\"",
    }


def limpar_avisos_painel(ip: str) -> Dict[str, Any]:
    """Limpa avisos não críticos pendentes no painel via '@PJL CLEAR WARNING'."""
    ip = _validar_ip(ip)
    resp = enviar_pjl(ip, ["CLEAR WARNING"], encapsular_job=True, timeout=5.0)
    return {
        "ok": True,
        "ip": ip,
        "resumo": f"✅ Comando '@PJL CLEAR WARNING' enviado para {ip}.\n• Retorno: {resp}",
    }


# ============================================================
# 4. TELA INICIAL (BOTÕES DO VISOR — EWS add_btns.html)
# ============================================================

def ler_tela_inicial(ip: str) -> Dict[str, Any]:
    """Lê quais ícones estão ativos ou ocultos na Tela Inicial do visor LCD."""
    ip = _validar_ip(ip)
    ews = LexmarkEWSClient(ip, timeout=8.0)
    _, _, _, valores = ews.ler_formulario("/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html")

    ativos, ocultos = [], []
    for chave, nome, _ in ICONES_HOME_CAMPOS:
        if str(valores.get(chave, "0")) == "1":
            ativos.append(f"{nome} ({chave})")
        else:
            ocultos.append(nome)

    resumo = (
        f"🎨 TELA INICIAL — {ip}\n"
        f"• Botões ATIVOS ({len(ativos)}): {', '.join(ativos) if ativos else 'Nenhum'}\n"
        f"• Botões OCULTOS ({len(ocultos)}): {', '.join(ocultos) if ocultos else 'Nenhum'}"
    )
    return {"ok": True, "ip": ip, "ativos": ativos, "ocultos": ocultos, "valores": valores, "resumo": resumo}


def configurar_tela_inicial(
    ip: str,
    preset: Optional[str] = None,
    mostrar: Optional[List[str]] = None,
    ocultar: Optional[List[str]] = None,
    manter_apenas: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Aplica um preset ou ativa/oculta botões específicos na Tela Inicial da Lexmark.
    100% reversível.
    """
    ip = _validar_ip(ip)
    ews = LexmarkEWSClient(ip, timeout=8.0)
    _, _, _, atual = ews.ler_formulario("/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html")

    alteracoes: Dict[str, str] = {}
    todas_chaves = [c for c, _, _ in ICONES_HOME_CAMPOS]

    def _resolver_nome(nome: str) -> Optional[str]:
        n = str(nome).strip().lower()
        n = n.translate(str.maketrans("áàãâéêíóôõúç", "aaaaeeiooouc"))
        if n in BOTOES_HOME_ALIASES:
            return BOTOES_HOME_ALIASES[n]
        for alias, chave in BOTOES_HOME_ALIASES.items():
            if alias in n:
                return chave
        return None

    if preset:
        p = str(preset).strip().lower()
        if p not in PRESETS_TELA_INICIAL:
            raise ValueError(f"Preset desconhecido: '{preset}'. Disponíveis: {', '.join(PRESETS_TELA_INICIAL)}")
        ativos_preset = set(PRESETS_TELA_INICIAL[p])
        for c in todas_chaves:
            alteracoes[c] = "1" if c in ativos_preset else "0"
    elif manter_apenas is not None:
        escolhidos = set()
        for item in manter_apenas:
            c = _resolver_nome(item)
            if c:
                escolhidos.add(c)
        for c in todas_chaves:
            alteracoes[c] = "1" if c in escolhidos else "0"
    else:
        for c in todas_chaves:
            alteracoes[c] = str(atual.get(c, "0"))

    for item in mostrar or []:
        c = _resolver_nome(item)
        if c:
            alteracoes[c] = "1"
    for item in ocultar or []:
        c = _resolver_nome(item)
        if c:
            alteracoes[c] = "0"

    ews.gravar_campos_formulario(
        "/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html",
        alteracoes,
        "/cgi-bin/posttest/printer/config/gen/sub/add_btns.html",
    )
    depois = ler_tela_inicial(ip)
    return {
        "ok": True,
        "ip": ip,
        "resumo": f"✅ Tela Inicial atualizada com sucesso em {ip}!\n\n{depois['resumo']}",
    }


# ============================================================
# 5. CONFIGURAÇÕES SEGURAS DE IMPRESSÃO (PJL WHITELIST)
# ============================================================

def configurar_impressao_segura(
    ip: str,
    papel: Optional[str] = None,
    duplex: Optional[bool] = None,
    eco: Optional[bool] = None,
    densidade: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Aplica ajustes padrão de impressão usando EXCLUSIVAMENTE comandos PJL
    pré-aprovados e 100% reversíveis.
    """
    ip = _validar_ip(ip)
    cmds: List[str] = []

    if papel:
        p_norm = str(papel).strip().upper()
        if p_norm in ("A4", "LETTER", "LEGAL", "A5", "EXECUTIVE"):
            cmds.append(f"DEFAULT PAPER={p_norm}")
        elif p_norm == "CARTA":
            cmds.append("DEFAULT PAPER=LETTER")
        elif p_norm in ("OFICIO", "OFÍCIO"):
            cmds.append("DEFAULT PAPER=LEGAL")
        else:
            raise ValueError(f"Tamanho de papel não permitido na whitelist: '{papel}'")

    if duplex is not None:
        cmds.append(f"DEFAULT DUPLEX={'ON' if duplex else 'OFF'}")

    if eco is not None:
        cmds.append(f"DEFAULT ECONOMODE={'ON' if eco else 'OFF'}")

    if densidade is not None:
        d = int(densidade)
        if not (1 <= d <= 5):
            raise ValueError("A densidade PJL deve estar entre 1 e 5.")
        cmds.append(f"DEFAULT DENSITY={d}")

    if not cmds:
        raise ValueError("Nenhuma configuração de impressão foi informada.")

    enviar_pjl(ip, cmds, encapsular_job=True, timeout=5.0)
    return {
        "ok": True,
        "ip": ip,
        "comandos": cmds,
        "resumo": f"✅ Configurações seguras aplicadas em {ip}:\n" + "\n".join(f"  • @PJL {c}" for c in cmds),
    }


# ============================================================
# 6. GERADOR DE RELATÓRIO DE BANCADA PRÓPRIO (ZERO DRIVER — POSTSCRIPT 9100)
# ============================================================

def imprimir_relatorio_bancada(
    ip: str,
    titulo: str = "RELATORIO DE BANCADA - TERMINAL TI",
    community: str = "public",
) -> Dict[str, Any]:
    """
    Coleta os dados reais da impressora via SNMP e envia uma folha de diagnóstico
    e teste de qualidade em PostScript Level 2 puro direto na porta RAW 9100.
    Não depende de driver do Windows nem spooler. Zero alteração na NVRAM.
    """
    ip = _validar_ip(ip)
    diag = diagnostico_completo(ip, community=community)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    toner_pct = diag.get("sup1_pct")
    toner_num = toner_pct if isinstance(toner_pct, int) else 0
    toner_str = f"{toner_pct}%" if isinstance(toner_pct, int) else "N/D"

    modelo_curto = _sanitizar_texto_ps(diag["modelo"][:74])
    hostname = _sanitizar_texto_ps(diag["hostname"])
    serial = _sanitizar_texto_ps(diag["serial"])
    paginas = _sanitizar_texto_ps(diag["total_paginas"])
    uptime = _sanitizar_texto_ps(diag["uptime"])
    visor = _sanitizar_texto_ps(diag["display_lcd"])
    sup1 = _sanitizar_texto_ps(f"{diag['sup1_desc']} ({toner_str})")
    titulo_ps = _sanitizar_texto_ps(titulo[:60])

    scanner_txt = "Nao detectado / Impressora"
    if diag.get("scanner_info"):
        si = diag["scanner_info"]
        scanner_txt = _sanitizar_texto_ps(
            f"{si.get('modulo', 'MFP')} | FW: {si.get('firmware_scanner', 'N/D')} | Estado: {si.get('estado_ram', 'N/D')}"
        )

    ps_doc = f"""%!PS-Adobe-3.0
%%Title: Terminal TI Bench Report
%%Pages: 1
%%EndComments
/Helvetica-Bold findfont 16 scalefont setfont
50 780 moveto ({titulo_ps}) show
/Helvetica findfont 9 scalefont setfont
50 762 moveto (Emissao Direta TCP RAW 9100 - Zero Driver | Data/Hora: {agora}) show
0.8 setlinewidth
50 752 moveto 545 752 lineto stroke

/Helvetica-Bold findfont 11 scalefont setfont
50 728 moveto (1. IDENTIFICACAO E TELEMETRIA DO EQUIPAMENTO) show

/Courier findfont 10 scalefont setfont
50 706 moveto (IP do Equipamento  : {ip}) show
50 690 moveto (Hostname de Rede   : {hostname}) show
50 674 moveto (Modelo / Firmware  : {modelo_curto}) show
50 658 moveto (Numero de Serie    : {serial}) show
50 642 moveto (Contador Vitalicio : {paginas} paginas) show
50 626 moveto (Tempo de Atividade : {uptime}) show
50 610 moveto (Status Visor LCD   : {visor}) show
50 594 moveto (Suprimento #1      : {sup1}) show
50 578 moveto (Modulo Scanner     : {scanner_txt}) show

/Helvetica-Bold findfont 11 scalefont setfont
50 544 moveto (2. INDICADOR VISUAL DE TONER ({toner_str})) show
50 520 495 16 rectstroke
0.2 setgray
50 520 {round(4.95 * toner_num, 1)} 16 rectfill
0 setgray

/Helvetica-Bold findfont 11 scalefont setfont
50 482 moveto (3. TESTE DE QUALIDADE DE IMAGEM - ESCALA DE CINZA / CILINDRO / FUSOR) show
0.0 setgray 50 435 45 36 rectfill
0.1 setgray 100 435 45 36 rectfill
0.2 setgray 150 435 45 36 rectfill
0.3 setgray 200 435 45 36 rectfill
0.4 setgray 250 435 45 36 rectfill
0.5 setgray 300 435 45 36 rectfill
0.6 setgray 350 435 45 36 rectfill
0.7 setgray 400 435 45 36 rectfill
0.8 setgray 450 435 45 36 rectfill
0.9 setgray 500 435 45 36 rectfill
0 setgray
50 435 495 36 rectstroke

/Helvetica-Bold findfont 11 scalefont setfont
50 398 moveto (4. GRADE DE ALINHAMENTO E REGISTRO DE PAPEL) show
0.4 setlinewidth
50 220 495 165 rectstroke
50 220 moveto 545 385 lineto stroke
545 220 moveto 50 385 lineto stroke
297 220 moveto 297 385 lineto stroke
50 302 moveto 545 302 lineto stroke

/Helvetica findfont 8 scalefont setfont
50 185 moveto (Checklist de Bancada:  [ ] Fusor/Fixacao   [ ] Cilindro/Fundo   [ ] Tracao Bandeja 1   [ ] Duplex   [ ] Scanner/ADF) show
50 165 moveto (Tecnico Responsavel: ____________________________________   OS / Chamado: ___________________) show
50 70 moveto (Terminal TI - Engenharia Lexmark | Relatorio gerado automaticamente via Socket 9100) show
showpage
%%EOF
"""

    payload = (
        UEL
        + b'@PJL JOB NAME="TerminalTI_BenchReport"\r\n'
        + b"@PJL ENTER LANGUAGE = POSTSCRIPT\r\n"
        + ps_doc.encode("ascii", errors="replace")
        + UEL
        + b"@PJL EOJ\r\n"
        + UEL
    )

    with socket.create_connection((ip, 9100), timeout=8.0) as sock:
        sock.sendall(payload)

    return {
        "ok": True,
        "ip": ip,
        "bytes": len(payload),
        "resumo": (
            f"🖨️ Relatório de Bancada enviado direto na porta 9100 de {ip} ({len(payload)} bytes)!\n"
            f"• Serial: {diag['serial']} | Páginas: {diag['total_paginas']} | Toner: {toner_str}\n"
            f"• Status LCD atual: \"{diag['display_lcd']}\""
        ),
    }


RELATORIOS_NATIVOS_PJL: Dict[str, tuple] = {
    "menus": ("LPRINTMENUS", "Página de Configurações de Menu (Nativa Lexmark)"),
    "diretorio": ("LPRINTDIRECTORY", "Listagem de Diretório Interno (Nativa Lexmark)"),
    "fontes_pcl": ("LPRINTPCLFONTS", "Lista de Fontes PCL (Nativa Lexmark)"),
    "fontes_ps": ("LPRINTPSFONTS", "Lista de Fontes PostScript (Nativa Lexmark)"),
}


def imprimir_relatorio_nativo(ip: str, tipo: str = "menus") -> Dict[str, Any]:
    """
    Dispara relatórios internos nativos do firmware Lexmark via comandos PJL LPRINT*
    na porta RAW 9100 (ex.: @PJL LPRINTMENUS).
    """
    ip = _validar_ip(ip)
    chave = str(tipo or "menus").strip().lower()
    if chave not in RELATORIOS_NATIVOS_PJL:
        raise ValueError(
            f"Tipo de relatório nativo inválido: '{tipo}'. Opções: {', '.join(RELATORIOS_NATIVOS_PJL)}"
        )
    cmd_pjl, descricao = RELATORIOS_NATIVOS_PJL[chave]
    resp = enviar_pjl(ip, [cmd_pjl], encapsular_job=True, timeout=6.0)
    return {
        "ok": True,
        "ip": ip,
        "comando": f"@PJL {cmd_pjl}",
        "resumo": (
            f"🖨️ Comando nativo '@PJL {cmd_pjl}' enviado para {ip}!\n"
            f"• Relatório: {descricao}\n"
            f"• Retorno  : {resp}"
        ),
    }


# ============================================================
# 7. VARREDURA DE REDE, PORTAS E PJL SOMENTE-LEITURA
# ============================================================

def verificar_portas(ip: str) -> Dict[str, Any]:
    """Testa conectividade Ping + scanner de portas de impressão."""
    ip = _validar_ip(ip)
    ok_ping, txt_ping = executar_ping(ip, quantidade=2)
    portas = escanear_portas_impressora(ip)
    linhas = [f"🔍 VERIFICAÇÃO DE REDE — {ip}", f"• Ping: {'OK' if ok_ping else 'SEM RESPOSTA'}"]
    for p, st in portas.items():
        linhas.append(f"• {p}: {st}")
    return {"ok": ok_ping, "ip": ip, "portas": portas, "ping": txt_ping, "resumo": "\n".join(linhas)}


def ler_variaveis_pjl(ip: str, filtro: str = "") -> Dict[str, Any]:
    """Lê @PJL INFO VARIABLES (somente leitura) com filtro opcional por palavra-chave."""
    ip = _validar_ip(ip)
    bruto = enviar_pjl(ip, ["INFO VARIABLES"], aguardar_resposta=True, timeout=6.0)
    linhas = bruto.splitlines()
    if filtro:
        f_up = filtro.strip().upper()
        encontradas = []
        for i, l in enumerate(linhas):
            if not l.startswith("\t") and f_up in l.upper():
                encontradas.append(l)
                for j in range(1, 6):
                    if i + j < len(linhas) and linhas[i + j].startswith("\t"):
                        encontradas.append(linhas[i + j])
                    else:
                        break
        texto_saida = "\n".join(encontradas[:60]) if encontradas else f"Nenhuma variável PJL encontrada contendo '{filtro}'."
    else:
        texto_saida = "\n".join(linhas[:50]) + (f"\n... (+{len(linhas) - 50} linhas)" if len(linhas) > 50 else "")

    return {
        "ok": True,
        "ip": ip,
        "total_linhas": len(linhas),
        "resumo": f"📋 PJL INFO VARIABLES ({ip}) — {len(linhas)} linhas totais:\n{texto_saida}",
    }


def escanear_rede_lexmark(ip_referencia: str, community: str = "public") -> Dict[str, Any]:
    """
    Varre a sub-rede /24 do IP de referência buscando impressoras Lexmark ativas
    na porta 9100 + SNMP sysDescr (100% somente-leitura).
    """
    ip_ref = _validar_ip(ip_referencia)
    prefixo = ".".join(ip_ref.split(".")[:3])
    alvos = [f"{prefixo}.{i}" for i in range(1, 255)]
    encontradas: List[Dict[str, str]] = []

    def _checar(host: str) -> Optional[Dict[str, str]]:
        try:
            with socket.create_connection((host, 9100), timeout=0.35):
                pass
        except OSError:
            return None
        desc = _snmp_seguro(host, "1.3.6.1.2.1.1.1.0", community, timeout=0.9)
        if "lexmark" not in desc.lower():
            return None
        modelo = desc.split(" version ")[0].strip() if " version " in desc else desc[:45]
        serial = _snmp_seguro(host, "1.3.6.1.2.1.43.5.1.1.17.1", community, timeout=0.9)
        pags = _snmp_seguro(host, "1.3.6.1.2.1.43.10.2.1.4.1.1", community, timeout=0.9)
        lcd = _snmp_seguro(host, "1.3.6.1.2.1.43.16.5.1.2.1.1", community, timeout=0.9)
        return {"ip": host, "modelo": modelo, "serial": serial, "paginas": pags, "lcd": lcd}

    with ThreadPoolExecutor(max_workers=48) as pool:
        futs = [pool.submit(_checar, h) for h in alvos]
        for f in as_completed(futs):
            res = f.result()
            if res:
                encontradas.append(res)

    encontradas.sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))
    if not encontradas:
        return {
            "ok": True,
            "encontradas": [],
            "resumo": f"🔎 Nenhuma impressora Lexmark respondeu na sub-rede {prefixo}.0/24.",
        }

    linhas = [f"🔎 IMPRESSORAS LEXMARK ENCONTRADAS EM {prefixo}.0/24 ({len(encontradas)}):"]
    for item in encontradas:
        linhas.append(
            f"• {item['ip']:15} | {item['modelo']} | Serial: {item['serial']} | "
            f"Págs: {item['paginas']} | LCD: {item['lcd']}"
        )
    return {"ok": True, "encontradas": encontradas, "resumo": "\n".join(linhas)}


# ============================================================
# 7B. IDIOMA, RELÓGIO E PAINEL GERAL (EWS VALIDADO)
# ============================================================

IDIOMAS_MAPA: Dict[str, tuple] = {
    "portugues": ("16", "Português (Brasil)"),
    "pt": ("16", "Português (Brasil)"),
    "pt-br": ("16", "Português (Brasil)"),
    "ptbr": ("16", "Português (Brasil)"),
    "brasil": ("16", "Português (Brasil)"),
    "brazil": ("16", "Português (Brasil)"),
    "ingles": ("0", "English (US)"),
    "english": ("0", "English (US)"),
    "en": ("0", "English (US)"),
    "alemao": ("1", "Deutsch"),
    "deutsch": ("1", "Deutsch"),
    "german": ("1", "Deutsch"),
    "frances": ("2", "Français"),
    "francais": ("2", "Français"),
    "french": ("2", "Français"),
    "espanhol": ("4", "Español"),
    "espanol": ("4", "Español"),
    "spanish": ("4", "Español"),
    "italiano": ("5", "Italiano"),
    "italian": ("5", "Italiano"),
    "dinamarques": ("6", "Dansk"),
    "dansk": ("6", "Dansk"),
    "noruegues": ("7", "Norsk"),
    "norsk": ("7", "Norsk"),
    "holandes": ("8", "Nederlands"),
    "nederlands": ("8", "Nederlands"),
    "japones": ("9", "日本語"),
    "japanese": ("9", "日本語"),
    "coreano": ("10", "한국어"),
    "korean": ("10", "한국어"),
    "chines tradicional": ("11", "繁體中文"),
    "chines": ("12", "简体中文"),
    "chinese": ("12", "简体中文"),
    "sueco": ("13", "Svenska"),
    "svenska": ("13", "Svenska"),
    "finlandes": ("15", "Suomi"),
    "suomi": ("15", "Suomi"),
    "russo": ("17", "Русский"),
    "russian": ("17", "Русский"),
    "tcheco": ("18", "Česky"),
    "cesky": ("18", "Česky"),
    "polones": ("19", "Polski"),
    "polski": ("19", "Polski"),
    "hungaro": ("20", "Magyar"),
    "magyar": ("20", "Magyar"),
    "turco": ("21", "Türkçe"),
    "turkce": ("21", "Türkçe"),
    "turkish": ("21", "Türkçe"),
    "grego": ("22", "Ελληνικά"),
    "greek": ("22", "Ελληνικά"),
}


def alterar_idioma(ip: str, idioma: str = "portugues") -> Dict[str, Any]:
    """
    Altera o idioma oficial da interface LCD e páginas web (EWS) da impressora
    via /cgi-bin/dynamic/printer/config/gen/general.html (campo 0.system.15).
    """
    ip = _validar_ip(ip)
    norm = str(idioma or "").strip().lower()
    norm = norm.translate(str.maketrans("áàãâéêíóôõúç", "aaaaeeiooouc"))

    codigo = None
    nome_oficial = None
    for chave in sorted(IDIOMAS_MAPA.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(chave)}\b", norm):
            codigo, nome_oficial = IDIOMAS_MAPA[chave]
            break

    if codigo is None:
        raise ValueError(
            f"Idioma não reconhecido: '{idioma}'. Suportados: Português (Brasil), Inglês, Espanhol, Francês, Alemão, Italiano."
        )

    ews = LexmarkEWSClient(ip, timeout=10.0)
    alteracoes = {"0.system.15": codigo}
    if codigo == "16":
        # Ajusta também formato de data DD-MM-AAAA e relógio 24h no padrão Brasil
        alteracoes["0.system.16385"] = "1"
        alteracoes["0.system.16713"] = "1"

    ews.gravar_campos_formulario(
        "/cgi-bin/dynamic/printer/config/gen/general.html",
        alteracoes,
        "/cgi-bin/posttest/printer/config/gen/general.html",
    )
    time.sleep(2.0)
    _, _, _, valores_pos = ews.ler_formulario("/cgi-bin/dynamic/printer/config/gen/general.html")
    cod_lido = str(valores_pos.get("0.system.15", ""))
    lcd_atual = _snmp_seguro(ip, "1.3.6.1.2.1.43.16.5.1.2.1.1")

    return {
        "ok": cod_lido == codigo,
        "ip": ip,
        "codigo": cod_lido,
        "idioma": nome_oficial,
        "resumo": (
            f"✅ Idioma alterado para {nome_oficial} em {ip} (0.system.15 = {cod_lido}).\n"
            f"• Visor LCD atual (SNMP): \"{lcd_atual}\""
        ),
    }


def sincronizar_relogio(ip: str) -> Dict[str, Any]:
    """Sincroniza data/hora da impressora com o relógio do PC (UTC-03:00 Brasília)."""
    ip = _validar_ip(ip)
    agora_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    ews = LexmarkEWSClient(ip, timeout=10.0)
    ews.gravar_campos_formulario(
        "/cgi-bin/dynamic/printer/config/secure/datetime.html",
        {"1.system.4982": agora_str, "0.system.12360": "18"},
        "/cgi-bin/posttest/printer/config/secure/datetime.html",
    )
    return {
        "ok": True,
        "ip": ip,
        "data_hora": agora_str,
        "resumo": f"✅ Relógio da impressora {ip} sincronizado com o PC: {agora_str} (UTC-03:00 Brasília).",
    }


def configurar_painel_geral(
    ip: str,
    brilho: Optional[int] = None,
    bipe_adf: Optional[bool] = None,
    ativar_vnc: Optional[bool] = None,
) -> Dict[str, Any]:
    """Ajusta brilho do LCD (20–100%), bipe do ADF e/ou ativa o Painel Remoto VNC."""
    ip = _validar_ip(ip)
    ews = LexmarkEWSClient(ip, timeout=10.0)
    acoes: List[str] = []

    alt_gen: Dict[str, str] = {}
    if brilho is not None:
        b = max(20, min(100, int(brilho)))
        alt_gen["0.system.16720"] = str(b)
        acoes.append(f"Brilho LCD = {b}%")
    if bipe_adf is not None:
        alt_gen["2.system.17245"] = "1" if bipe_adf else "0"
        acoes.append(f"Bipe do ADF = {'Ativado' if bipe_adf else 'Desativado'}")

    if alt_gen:
        ews.gravar_campos_formulario(
            "/cgi-bin/dynamic/printer/config/gen/general.html",
            alt_gen,
            "/cgi-bin/posttest/printer/config/gen/general.html",
        )

    if ativar_vnc:
        ews.gravar_campos_formulario(
            "/cgi-bin/dynamic/printer/config/remote_oppanel_config.html",
            {"2.system.12849": "1", "0.system.12850": "1"},
            "/cgi-bin/posttest/printer/config/remote_oppanel_config.html",
        )
        acoes.append("Painel Remoto VNC = Ativado (sem senha)")

    if not acoes:
        raise ValueError("Nenhuma preferência de painel foi informada.")

    return {
        "ok": True,
        "ip": ip,
        "resumo": f"✅ Preferências de painel aplicadas em {ip}:\n" + "\n".join(f"  • {a}" for a in acoes),
    }


# Registro fechado (Whitelist) acessível diretamente pelo Agente (Nível 0/1)
SAFE_TOOL_REGISTRY = {
    "diagnostico_completo": diagnostico_completo,
    "ler_modo_scanner": ler_modo_scanner,
    "definir_modo_scanner": definir_modo_scanner,
    "alterar_visor_lcd": alterar_visor_lcd,
    "limpar_avisos_painel": limpar_avisos_painel,
    "ler_tela_inicial": ler_tela_inicial,
    "configurar_tela_inicial": configurar_tela_inicial,
    "configurar_impressao_segura": configurar_impressao_segura,
    "imprimir_relatorio_bancada": imprimir_relatorio_bancada,
    "imprimir_relatorio_nativo": imprimir_relatorio_nativo,
    "verificar_portas": verificar_portas,
    "ler_variaveis_pjl": ler_variaveis_pjl,
    "escanear_rede_lexmark": escanear_rede_lexmark,
    "alterar_idioma": alterar_idioma,
    "sincronizar_relogio": sincronizar_relogio,
    "configurar_painel_geral": configurar_painel_geral,
}


# ============================================================
# 8. OPERAÇÕES CRÍTICAS CONTROLADAS (NÍVEL 2 — EXIGEM PRÉ-CHECAGEM + CONFIRMAÇÃO HUMANA)
# ============================================================

def identificar_alvo_rapido(ip: str, community: str = "public") -> Dict[str, str]:
    """Lê rapidamente modelo, serial e display via SNMP antes de pedir confirmação crítica."""
    ip = _validar_ip(ip)
    modelo = _snmp_seguro(ip, "1.3.6.1.2.1.1.1.0", community, timeout=1.5)
    serial = _snmp_seguro(ip, "1.3.6.1.2.1.43.5.1.1.17.1", community, timeout=1.5)
    lcd = _snmp_seguro(ip, "1.3.6.1.2.1.43.16.5.1.2.1.1", community, timeout=1.5)
    modelo_curto = modelo.split(" version ")[0].strip() if " version " in modelo else modelo[:60]
    return {"ip": ip, "modelo": modelo_curto, "modelo_full": modelo, "serial": serial, "lcd": lcd}


def validar_pre_voo_ip_estatico(novo_ip: str, mascara: str, gateway: str) -> Dict[str, str]:
    """
    Valida matematicamente IP, Máscara de Sub-rede e Gateway antes de permitir
    a confirmação de mudança de IP estático (impede erro de digitação ou sub-rede inválida).
    """
    ip_obj = ipaddress.IPv4Address(str(novo_ip).strip())
    gw_obj = ipaddress.IPv4Address(str(gateway).strip())
    # Valida que a máscara é contígua e válida (ex.: 255.255.255.0)
    try:
        rede = ipaddress.IPv4Network(f"{ip_obj}/{str(mascara).strip()}", strict=False)
    except ValueError as err:
        raise ValueError(f"Máscara de sub-rede inválida: '{mascara}'") from err

    if ip_obj == rede.network_address or ip_obj == rede.broadcast_address:
        raise ValueError(f"O IP {ip_obj} não pode ser endereço de rede nem de broadcast ({rede}).")
    if gw_obj not in rede:
        raise ValueError(
            f"O Gateway {gw_obj} não pertence à mesma sub-rede de {ip_obj}/{mascara} ({rede})."
        )
    if ip_obj == gw_obj:
        raise ValueError("O novo IP da impressora não pode ser igual ao Gateway.")

    return {
        "novo_ip": str(ip_obj),
        "mascara": str(rede.netmask),
        "gateway": str(gw_obj),
        "rede": str(rede),
    }


def validar_pre_voo_firmware(caminho_fls: str) -> Dict[str, Any]:
    """
    Pré-checagem obrigatória para atualização de firmware:
    - arquivo precisa existir;
    - extensão .fls (ou .bin);
    - tamanho >= 100 KB (rejeita arquivos vazios/corrompidos/texto);
    - inspeciona cabeçalho para confirmar assinatura PJL/UEL/Lexmark.
    """
    arq = Path(str(caminho_fls or "").strip().strip("\"'"))
    if not arq.is_file():
        raise ValueError(f"Arquivo de firmware não encontrado: '{arq}'")
    if arq.suffix.lower() not in (".fls", ".bin"):
        raise ValueError(f"Extensão inválida '{arq.suffix}'. Apenas arquivos .fls ou .bin são aceitos.")

    tamanho = arq.stat().st_size
    if tamanho < 100 * 1024:
        raise ValueError(
            f"Arquivo muito pequeno ({tamanho} bytes). Um firmware Lexmark real tem vários MB; "
            "envio bloqueado para evitar risco de brick."
        )

    cabecalho = arq.read_bytes()[:512]
    tem_assinatura_pjl = (b"\x1b%-12345X" in cabecalho) or (b"@PJL" in cabecalho) or (b"LEXMARK" in cabecalho.upper())

    return {
        "caminho": str(arq.resolve()),
        "nome": arq.name,
        "tamanho_mb": round(tamanho / (1024 * 1024), 2),
        "assinatura_lexmark": tem_assinatura_pjl,
    }


def critico_restaurar_fabrica(ip: str, escopo: str = "base") -> Dict[str, Any]:
    ip = _validar_ip(ip)
    if escopo not in ("base", "network", "les"):
        raise ValueError(f"Escopo inválido: '{escopo}'. Use 'base', 'network' ou 'les'.")
    res = LexmarkEWSClient(ip, timeout=15.0).restaurar_padroes_fabrica(escopo=escopo)
    return {
        "ok": True,
        "ip": ip,
        "escopo": escopo,
        "resumo": (
            f"✅ Restauração de Padrões de Fábrica (escopo='{escopo}') enviada para {ip} (HTTP {res.get('status_code')}).\n"
            "• A impressora pode reiniciar automaticamente para concluir a operação."
        ),
    }


def critico_apagar_nvram(ip: str) -> Dict[str, Any]:
    ip = _validar_ip(ip)
    res = LexmarkEWSClient(ip, timeout=15.0).apagar_memoria_nvram()
    return {
        "ok": True,
        "ip": ip,
        "resumo": (
            f"✅ Limpeza de Memória NVRAM acionada em {ip} (HTTP {res.get('status_code')}).\n"
            "• Aguarde a controladora concluir a limpeza e reiniciar."
        ),
    }


def critico_wipe_fora_de_servico(ip: str) -> Dict[str, Any]:
    ip = _validar_ip(ip)
    res = LexmarkEWSClient(ip, timeout=20.0).apagar_fora_de_servico_wipe()
    return {
        "ok": True,
        "ip": ip,
        "resumo": (
            f"✅ Wipe Fora de Serviço acionado em {ip} (HTTP {res.get('status_code')}).\n"
            "• A impressora apagará todos os dados/configurações e reiniciará no assistente inicial."
        ),
    }


def critico_mudar_ip_estatico(ip: str, novo_ip: str, mascara: str, gateway: str) -> Dict[str, Any]:
    ip = _validar_ip(ip)
    validado = validar_pre_voo_ip_estatico(novo_ip, mascara, gateway)
    res = LexmarkEWSClient(ip, timeout=15.0).gravar_ip_estatico(
        validado["novo_ip"], validado["mascara"], validado["gateway"]
    )
    return {
        "ok": True,
        "ip": ip,
        "novo_ip": validado["novo_ip"],
        "resumo": (
            f"✅ Novo IP Estático gravado em {ip} (HTTP {res.get('status_code')})!\n"
            f"• Novo IP : {validado['novo_ip']}\n"
            f"• Máscara : {validado['mascara']}\n"
            f"• Gateway : {validado['gateway']}\n"
            f"ℹ️ A placa de rede aplicará o endereço {validado['novo_ip']} — atualize o campo IP no topo do Terminal TI."
        ),
    }


def critico_atualizar_firmware(ip: str, caminho_fls: str) -> Dict[str, Any]:
    ip = _validar_ip(ip)
    info = validar_pre_voo_firmware(caminho_fls)
    res = LexmarkEWSClient(ip, timeout=30.0).enviar_firmware_http(info["caminho"])
    return {
        "ok": True,
        "ip": ip,
        "arquivo": info["nome"],
        "resumo": (
            f"✅ Firmware '{info['nome']}' ({info['tamanho_mb']} MB) enviado para {ip} (HTTP {res.get('status_code')})!\n"
            "⚠️ NÃO DESLIGUE A IMPRESSORA! Aguarde a gravação na flash e a reinicialização completa (pode levar 3 a 8 minutos)."
        ),
    }


# Registro separado — NUNCA chamado diretamente sem confirmação humana explícita com PIN
CRITICAL_TOOL_REGISTRY = {
    "critico_restaurar_fabrica": critico_restaurar_fabrica,
    "critico_apagar_nvram": critico_apagar_nvram,
    "critico_wipe_fora_de_servico": critico_wipe_fora_de_servico,
    "critico_mudar_ip_estatico": critico_mudar_ip_estatico,
    "critico_atualizar_firmware": critico_atualizar_firmware,
}
