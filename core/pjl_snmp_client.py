"""
============================================================
TERMINAL TI — MOTOR PJL 9100, SNMP NATIVO E DIAGNÓSTICO DE REDE
(core/pjl_snmp_client.py)
============================================================

Implementa:
- Envio e leitura PJL na porta RAW 9100 (com ou sem JOB/EOJ);
- Injeção de XML VCC / eSF e arquivos de firmware (.fls / .bin) na 9100;
- Motor SNMPv2c UDP nativo em puro Python (GET e SET para String e Inteiro),
  não dependendo de versão específica do PySNMP;
- Ping ICMP e Scanner de portas de impressora (80, 443, 161, 515, 631, 9100).
"""

from __future__ import annotations

import os
import random
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union


UEL = b"\x1b%-12345X"


# ============================================================
# CLIENTE PJL / RAW 9100
# ============================================================

def enviar_pjl(
    ip: str,
    comandos: List[str],
    porta: int = 9100,
    encapsular_job: bool = True,
    aguardar_resposta: bool = False,
    timeout: float = 6.0,
) -> str:
    """
    Envia um lote de comandos PJL para a porta RAW 9100 e retorna
    a resposta textual da controladora (quando houver).
    """
    ip_limpo = str(ip).strip()
    if not ip_limpo:
        raise ValueError("IP da impressora não informado.")

    linhas = []
    if encapsular_job:
        linhas.append('@PJL JOB NAME="TerminalTI_Eng"')

    for cmd in comandos:
        c = cmd.strip()
        if not c:
            continue
        if not c.upper().startswith("@PJL"):
            c = f"@PJL {c}"
        linhas.append(c)
        if any(c.upper().startswith(f"@PJL {k}") for k in ("INFO", "DINQUIRE", "INQUIRE", "USTATUS")):
            aguardar_resposta = True

    if encapsular_job:
        linhas.append("@PJL EOJ")

    corpo = "\r\n".join(linhas) + "\r\n"
    payload = UEL + corpo.encode("cp1252", errors="replace") + UEL

    resposta_bytes = bytearray()
    with socket.create_connection((ip_limpo, int(porta)), timeout=timeout) as sock:
        sock.sendall(payload)
        sock.settimeout(2.5 if aguardar_resposta else 0.8)
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resposta_bytes.extend(chunk)
            except socket.timeout:
                break
            except OSError:
                break

    if not resposta_bytes:
        return "Job PJL enviado e processado pela porta 9100."

    texto = (
        resposta_bytes.decode("utf-8", errors="replace")
        .replace("\x1b%-12345X", "")
        .replace("\x0c", "")
        .strip()
    )
    return texto or "Job PJL processado com sucesso."


def injetar_arquivo_raw(
    ip: str,
    caminho_arquivo: str,
    porta: int = 9100,
    progresso_cb: Optional[Callable[[int, int], None]] = None,
    timeout: float = 30.0,
) -> int:
    """
    Transmite um arquivo bruto (.fls, .bin, .pjl, .prn, .xml) diretamente
    para a porta RAW 9100 em blocos de 64 KB com callback de progresso.
    """
    arq = Path(caminho_arquivo)
    if not arq.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {arq}")

    tamanho_total = arq.stat().st_size
    enviados = 0

    with open(arq, "rb") as fp, socket.create_connection((str(ip).strip(), int(porta)), timeout=timeout) as sock:
        while True:
            bloco = fp.read(65536)
            if not bloco:
                break
            sock.sendall(bloco)
            enviados += len(bloco)
            if progresso_cb:
                progresso_cb(enviados, tamanho_total)
        try:
            sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass

    return enviados


def injetar_xml_vcc(ip: str, xml_conteudo: str, porta: int = 9100) -> int:
    """
    Injeta um pacote XML de configuração (padrão Lexmark NPA/VCC) via porta 9100.
    """
    dados = xml_conteudo.strip().encode("utf-8")
    payload = UEL + b"@PJL\r\n" + dados + b"\r\n" + UEL
    with socket.create_connection((str(ip).strip(), int(porta)), timeout=10.0) as sock:
        sock.sendall(payload)
        try:
            sock.shutdown(socket.SHUT_WR)
        except Exception:
            pass
    return len(payload)


# ============================================================
# CODIFICADOR / DECODIFICADOR SNMPv2c NATIVO (ASN.1 BER PURO PYTHON)
# ============================================================

def _ber_len(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    octets = []
    temp = length
    while temp > 0:
        octets.insert(0, temp & 0xFF)
        temp >>= 8
    return bytes([0x80 | len(octets)] + octets)


def _ber_tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _ber_len(len(value)) + value


def _ber_int(val: int) -> bytes:
    if val == 0:
        return _ber_tlv(0x02, b"\x00")
    octets = []
    temp = val
    while temp > 0:
        octets.insert(0, temp & 0xFF)
        temp >>= 8
    if octets[0] & 0x80:
        octets.insert(0, 0x00)
    return _ber_tlv(0x02, bytes(octets))


def _ber_str(val: Union[str, bytes]) -> bytes:
    b = val.encode("utf-8", errors="replace") if isinstance(val, str) else bytes(val)
    return _ber_tlv(0x04, b)


def _ber_oid(oid_str: str) -> bytes:
    partes = [int(x) for x in oid_str.strip(".").split(".") if x.strip()]
    if len(partes) < 2:
        raise ValueError(f"OID inválido: {oid_str}")
    body = bytearray([partes[0] * 40 + partes[1]])
    for sub in partes[2:]:
        if sub == 0:
            body.append(0)
        else:
            stack = []
            temp = sub
            while temp > 0:
                stack.insert(0, temp & 0x7F)
                temp >>= 7
            for i in range(len(stack) - 1):
                body.append(stack[i] | 0x80)
            body.append(stack[-1])
    return _ber_tlv(0x06, bytes(body))


def _parse_ber_len(data: bytes, idx: int) -> Tuple[int, int]:
    first = data[idx]
    idx += 1
    if not (first & 0x80):
        return first, idx
    num_octets = first & 0x7F
    length = 0
    for _ in range(num_octets):
        length = (length << 8) | data[idx]
        idx += 1
    return length, idx


def _parse_ber_tlv(data: bytes, idx: int) -> Tuple[int, bytes, int]:
    tag = data[idx]
    length, next_idx = _parse_ber_len(data, idx + 1)
    val = data[next_idx : next_idx + length]
    return tag, val, next_idx + length


def _decode_ber_int(val: bytes) -> int:
    if not val:
        return 0
    res = int.from_bytes(val, byteorder="big", signed=True)
    return res


def _decode_ber_value(tag: int, val: bytes) -> str:
    if tag == 0x02:  # INTEGER
        return str(_decode_ber_int(val))
    if tag in (0x41, 0x42, 0x43):  # Counter32, Gauge32, TimeTicks
        num = int.from_bytes(val, byteorder="big", signed=False)
        if tag == 0x43:
            segundos = num // 100
            horas = segundos // 3600
            minutos = (segundos % 3600) // 60
            return f"{horas}h {minutos}m ({num} ticks)"
        return str(num)
    if tag == 0x04:  # OCTET STRING
        try:
            return val.decode("utf-8")
        except UnicodeDecodeError:
            return val.decode("cp1252", errors="replace")
    if tag == 0x05:  # NULL
        return "NULL"
    if tag in (0x80, 0x81, 0x82):
        return "NoSuchObject / NoSuchInstance"
    return val.hex()


def _snmp_request_nativo(
    ip: str,
    oid: str,
    comunidade: str = "public",
    pdu_tag: int = 0xA0,  # 0xA0 = GetRequest, 0xA3 = SetRequest
    valor_set: Optional[Union[str, int]] = None,
    porta: int = 161,
    timeout: float = 3.5,
) -> Tuple[int, str]:
    """
    Executa SNMPv2c GET (0xA0) ou SET (0xA3) via UDP puro Python.
    Retorna (error_status, valor_formatado).
    """
    req_id = random.randint(10000, 999999)
    oid_bytes = _ber_oid(oid)

    if pdu_tag == 0xA3 and valor_set is not None:
        if isinstance(valor_set, int):
            val_bytes = _ber_int(valor_set)
        else:
            val_bytes = _ber_str(str(valor_set))
    else:
        val_bytes = b"\x05\x00"  # NULL

    varbind = _ber_tlv(0x30, oid_bytes + val_bytes)
    varbind_list = _ber_tlv(0x30, varbind)

    pdu_body = _ber_int(req_id) + _ber_int(0) + _ber_int(0) + varbind_list
    pdu = _ber_tlv(pdu_tag, pdu_body)

    # version = 1 (SNMPv2c)
    msg_body = _ber_int(1) + _ber_str(comunidade) + pdu
    pacote = _ber_tlv(0x30, msg_body)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(pacote, (str(ip).strip(), int(porta)))
        resp, _ = sock.recvfrom(8192)

    # Decodifica resposta SNMP
    _, seq_val, _ = _parse_ber_tlv(resp, 0)
    idx = 0
    _, _, idx = _parse_ber_tlv(seq_val, idx)  # version
    _, _, idx = _parse_ber_tlv(seq_val, idx)  # community
    _, pdu_resp, _ = _parse_ber_tlv(seq_val, idx)  # GetResponse PDU

    p_idx = 0
    _, _, p_idx = _parse_ber_tlv(pdu_resp, p_idx)  # req_id
    _, err_stat_b, p_idx = _parse_ber_tlv(pdu_resp, p_idx)  # error-status
    _, _, p_idx = _parse_ber_tlv(pdu_resp, p_idx)  # error-index
    _, vbl_b, _ = _parse_ber_tlv(pdu_resp, p_idx)  # varbind-list

    err_status = _decode_ber_int(err_stat_b)
    _, vb_b, _ = _parse_ber_tlv(vbl_b, 0)
    v_idx = 0
    _, _, v_idx = _parse_ber_tlv(vb_b, v_idx)  # oid
    v_tag, v_val, _ = _parse_ber_tlv(vb_b, v_idx)  # value

    return err_status, _decode_ber_value(v_tag, v_val)


def snmp_get(ip: str, oid: str, comunidade: str = "public", timeout: float = 3.5) -> str:
    err_status, valor = _snmp_request_nativo(
        ip=ip, oid=oid, comunidade=comunidade, pdu_tag=0xA0, timeout=timeout
    )
    if err_status != 0:
        raise RuntimeError(f"Erro SNMP Status={err_status} no OID {oid}")
    return valor


def snmp_set(
    ip: str,
    oid: str,
    valor: Union[str, int],
    comunidade: str = "private",
    timeout: float = 4.0,
) -> str:
    err_status, val_ret = _snmp_request_nativo(
        ip=ip,
        oid=oid,
        comunidade=comunidade,
        pdu_tag=0xA3,
        valor_set=valor,
        timeout=timeout,
    )
    codigos_erro = {
        1: "tooBig",
        2: "noSuchName (OID inexistente)",
        3: "badValue",
        4: "readOnly (Somente leitura)",
        5: "genErr",
        6: "noAccess (Acesso negado pela comunidade)",
        17: "notWritable (NVRAM bloqueada via SNMP para este OID)",
    }
    if err_status != 0:
        desc = codigos_erro.get(err_status, f"Código {err_status}")
        raise RuntimeError(f"Placa recusou SNMP SET: {desc}")
    return val_ret


# ============================================================
# DIAGNÓSTICO DE REDE (PING & SCAN DE PORTAS)
# ============================================================

def executar_ping(ip: str, pacotes: int = 3) -> str:
    ip_limpo = str(ip).strip()
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    proc = subprocess.run(
        ["ping", "-n", str(pacotes), "-w", "1500", ip_limpo],
        capture_output=True,
        text=True,
        encoding="cp850",
        errors="replace",
        startupinfo=startupinfo,
        timeout=10,
    )
    return proc.stdout.strip() or proc.stderr.strip()


def escanear_portas_impressora(ip: str) -> Dict[str, str]:
    portas = [
        (80, "HTTP / EWS"),
        (443, "HTTPS / SSL"),
        (515, "LPD / Spooler"),
        (631, "IPP Printing"),
        (9100, "RAW / PJL / PCL"),
    ]
    resultado: Dict[str, str] = {}
    ip_limpo = str(ip).strip()

    for porta, nome in portas:
        t0 = time.perf_counter()
        try:
            with socket.create_connection((ip_limpo, porta), timeout=1.2):
                ms = (time.perf_counter() - t0) * 1000
                resultado[f"{porta}/TCP ({nome})"] = f"ABERTA ({ms:.0f} ms)"
        except Exception:
            resultado[f"{porta}/TCP ({nome})"] = "FECHADA / FILTRADA"

    # Testa UDP 161 (SNMP)
    try:
        val = snmp_get(ip_limpo, "1.3.6.1.2.1.1.1.0", comunidade="public", timeout=1.5)
        resultado["161/UDP (SNMP)"] = f"ATIVA ({val[:45]}...)"
    except Exception:
        resultado["161/UDP (SNMP)"] = "SEM RESPOSTA"

    return resultado
