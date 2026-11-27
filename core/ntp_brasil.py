"""
============================================================
TERMINAL TI — HORÁRIO OFICIAL DE BRASÍLIA (NTP.br)
(core/ntp_brasil.py)
============================================================

Consulta o horário oficial de Brasília (UTC-03:00) diretamente nos
servidores NTP oficiais do NIC.br (a.st1.ntp.br / b.st1.ntp.br / pool.ntp.br)
usando SNTP UDP 123 em Python puro (zero dependências extras), com fallback
via cabeçalho HTTP Date (HTTPS) quando o firewall bloqueia UDP 123.

Também permite configurar o Cliente NTP nativo da impressora Lexmark em
/cgi-bin/dynamic/printer/config/secure/datetime.html.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
import socket
import struct
from typing import Any, Dict, Tuple

import requests

from core.ews_client import LexmarkEWSClient

BRT = timezone(timedelta(hours=-3), name="BRT")
SERVIDORES_NTP_BR = ("a.st1.ntp.br", "b.st1.ntp.br", "pool.ntp.br")
NTP_DELTA = 2208988800  # Diferença entre 1900-01-01 e 1970-01-01 em segundos


def consultar_ntp_udp(servidor: str = "a.st1.ntp.br", timeout: float = 2.5) -> datetime:
    """Consulta horário UTC via pacote SNTP v3 (UDP porta 123) e converte para Brasília (UTC-03)."""
    pacote = b"\x1b" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(pacote, (servidor, 123))
        dados, _ = sock.recvfrom(1024)
    if len(dados) < 48:
        raise RuntimeError(f"Resposta NTP incompleta de {servidor}")
    segundos = struct.unpack("!12I", dados[:48])[10] - NTP_DELTA
    return datetime.fromtimestamp(segundos, tz=timezone.utc).astimezone(BRT)


def consultar_hora_https(timeout: float = 4.0) -> Tuple[datetime, str]:
    """Fallback quando a porta UDP 123 está bloqueada: lê cabeçalho HTTP Date via HTTPS."""
    for url in ("https://www.google.com/generate_204", "https://ntp.br/"):
        try:
            r = requests.head(url, timeout=timeout, allow_redirects=True)
            date_hdr = r.headers.get("Date")
            if date_hdr:
                dt_utc = parsedate_to_datetime(date_hdr)
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                return dt_utc.astimezone(BRT), f"HTTPS ({url.split('/')[2]})"
        except Exception:
            continue
    raise RuntimeError("Não foi possível obter horário via HTTPS.")


def obter_horario_brasilia() -> Tuple[datetime, str]:
    """
    Obtém o horário oficial de Brasília (UTC-03:00) na seguinte prioridade:
      1. SNTP oficial NIC.br (a.st1.ntp.br / b.st1.ntp.br / pool.ntp.br)
      2. Cabeçalho Date via HTTPS (se UDP 123 estiver bloqueado no firewall)
      3. Relógio local do PC (somente se estiver sem internet, com aviso)
    """
    for srv in SERVIDORES_NTP_BR:
        try:
            dt = consultar_ntp_udp(srv, timeout=2.2)
            return dt, f"NTP Oficial ({srv})"
        except Exception:
            continue

    try:
        return consultar_hora_https(timeout=3.5)
    except Exception:
        pass

    return datetime.now(BRT), "Relógio Local do PC (sem acesso NTP/internet)"


def ler_status_relogio_impressora(ip: str) -> Dict[str, str]:
    """Lê a data/hora atual e configuração NTP gravada em datetime.html da impressora."""
    ews = LexmarkEWSClient(ip, timeout=10)
    html = ews.ler_pagina_texto("/cgi-bin/dynamic/printer/config/secure/datetime.html")
    _, _, _, valores = ews.ler_formulario("/cgi-bin/dynamic/printer/config/secure/datetime.html")

    m_form = re.search(r"<form\b.*", html, re.I | re.S)
    trecho = m_form.group(0) if m_form else html
    m_atual = re.search(r"<td[^>]*>\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*</td>", trecho, re.I)
    if not m_atual:
        m_atual = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", trecho)
    hora_atual = m_atual.group(1) if m_atual else "N/D"
    return {
        "hora_impressora": hora_atual,
        "fuso_codigo": str(valores.get("0.system.12360", "")),
        "ntp_ativo": str(valores.get("2.system.12362", "0")) == "1",
        "servidor_ntp": str(valores.get("1.system.12363", "")).strip(),
    }


def sincronizar_hora_brasilia(
    ip: str,
    ativar_ntp_nativo: bool = False,
    servidor_ntp: str = "a.st1.ntp.br",
) -> Dict[str, Any]:
    """
    Sincroniza a impressora com o horário oficial de Brasília (UTC-03:00):
    - ativar_ntp_nativo=False: consulta NTP.br no Python e grava data/hora exata na impressora
      (funciona mesmo quando a impressora está isolada sem internet!).
    - ativar_ntp_nativo=True: grava fuso Brasília + ativa NTP nativo apontando para servidor_ntp
      (ex.: a.st1.ntp.br), mantendo a impressora sincronizada automaticamente.
    """
    dt_brt, fonte = obter_horario_brasilia()
    agora_str = dt_brt.strftime("%Y-%m-%d %H:%M")

    ews = LexmarkEWSClient(ip, timeout=12)
    antes = ler_status_relogio_impressora(ip)

    if ativar_ntp_nativo:
        srv_limpo = str(servidor_ntp or "a.st1.ntp.br").strip() or "a.st1.ntp.br"
        # Primeiro ajusta hora exata imediatamente, depois ativa o NTP nativo
        ews.gravar_campos_formulario(
            "/cgi-bin/dynamic/printer/config/secure/datetime.html",
            {"1.system.4982": agora_str, "0.system.12360": "18"},
            "/cgi-bin/posttest/printer/config/secure/datetime.html",
        )
        ews.gravar_campos_formulario(
            "/cgi-bin/dynamic/printer/config/secure/datetime.html",
            {
                "1.system.4982": "",
                "0.system.12360": "18",
                "2.system.12362": "1",
                "1.system.12363": srv_limpo,
                "0.system.5103": "0",
            },
            "/cgi-bin/posttest/printer/config/secure/datetime.html",
        )
        depois = ler_status_relogio_impressora(ip)
        resumo = (
            f"✅ Relógio ajustado + NTP Nativo ATIVADO em {ip}!\n"
            f"• Fonte da Hora   : {fonte} ({agora_str} BRT)\n"
            f"• Hora Antes      : {antes['hora_impressora']}\n"
            f"• Hora Agora      : {depois['hora_impressora']} (Fuso UTC-03:00 Brasília)\n"
            f"• NTP Nativo      : ATIVO ➜ Servidor '{depois['servidor_ntp']}'"
        )
    else:
        ews.gravar_campos_formulario(
            "/cgi-bin/dynamic/printer/config/secure/datetime.html",
            {"1.system.4982": agora_str, "0.system.12360": "18"},
            "/cgi-bin/posttest/printer/config/secure/datetime.html",
        )
        depois = ler_status_relogio_impressora(ip)
        resumo = (
            f"✅ Horário Oficial de Brasília sincronizado em {ip}!\n"
            f"• Fonte da Hora : {fonte}\n"
            f"• Hora Antes    : {antes['hora_impressora']}\n"
            f"• Hora Agora    : {depois['hora_impressora']} (UTC-03:00 Brasília)"
        )

    return {
        "ok": True,
        "ip": ip,
        "fonte": fonte,
        "data_hora_brt": agora_str,
        "antes": antes,
        "depois": depois,
        "resumo": resumo,
    }
