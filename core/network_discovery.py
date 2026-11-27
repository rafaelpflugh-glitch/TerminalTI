"""
============================================================
TERMINAL TI v2.0 — MOTOR DE DESCOBERTA HÍBRIDA DE REDE
(core/network_discovery.py)
============================================================

Combina 4 camadas de descoberta em Python puro (zero dependências extras):
  1. Auto-detecção das sub-redes IPv4 ativas do PC (Wi-Fi / Ethernet)
  2. WS-Discovery Multicast (UDP 3702 — 239.255.255.250)
  3. mDNS / Bonjour Multicast (UDP 5353 — 224.0.0.251, _ipp/_pdl-datastream/_printer)
  4. SNMPv2c Broadcast (UDP 161 -> x.x.x.255) + Varredura TCP paralela (9100/80)

Enriquece cada impressora encontrada via SNMP (Modelo, Serial, Páginas, Toner, LCD)
com fallback HTTP (título da página EWS) caso SNMP esteja desativado.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import re
import socket
import struct
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

import requests
import urllib3

from core.pjl_snmp_client import _ber_int, _ber_oid, _ber_str, _ber_tlv, snmp_get

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Prefixos virtuais comuns (VirtualBox Host-Only, WSL/Hyper-V) colocados em baixa prioridade
_INTERFACES_IGNORAR = ("loopback", "vethernet", "wsl", "vmware", "virtualbox", "teredo", "isatap")


def detectar_subredes_locais(ip_referencia: str = "") -> List[Dict[str, str]]:
    """
    Detecta automaticamente as sub-redes IPv4 ativas das placas de rede do Windows
    (Ethernet / Wi-Fi), ignorando 127.x e APIPA 169.254.x.
    """
    subredes: List[Dict[str, str]] = []
    vistas: Set[str] = set()

    # 1. Consulta placas ativas via PowerShell (preciso no Windows)
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-NetIPAddress -AddressFamily IPv4 | "
            "Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | "
            "ForEach-Object { \"$($_.IPAddress)|$($_.PrefixLength)|$($_.InterfaceAlias)\" }",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=4, creationflags=0x08000000)
        for linha in proc.stdout.splitlines():
            partes = linha.strip().split("|")
            if len(partes) < 3:
                continue
            ip_local, prefix_str, alias = partes[0].strip(), partes[1].strip(), partes[2].strip()
            if any(ig in alias.lower() for ig in _INTERFACES_IGNORAR):
                continue
            # Ignora 192.168.56.x (VirtualBox Host-Only clássico) se houver outras placas reais
            if ip_local.startswith("192.168.56."):
                continue
            try:
                net = ipaddress.IPv4Network(f"{ip_local}/24", strict=False)
                cidr = str(net)
                if cidr not in vistas:
                    vistas.add(cidr)
                    subredes.append({
                        "ip_local": ip_local,
                        "prefixo": ".".join(ip_local.split(".")[:3]),
                        "cidr": cidr,
                        "broadcast": str(net.broadcast_address),
                        "interface": alias,
                    })
            except ValueError:
                continue
    except Exception:
        pass

    # 2. Fallback socket padrão (cross-platform)
    if not subredes:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip_local = s.getsockname()[0]
            if not ip_local.startswith(("127.", "169.254.")):
                net = ipaddress.IPv4Network(f"{ip_local}/24", strict=False)
                cidr = str(net)
                vistas.add(cidr)
                subredes.append({
                    "ip_local": ip_local,
                    "prefixo": ".".join(ip_local.split(".")[:3]),
                    "cidr": cidr,
                    "broadcast": str(net.broadcast_address),
                    "interface": "Interface Padrão",
                })
        except Exception:
            pass

    # 3. Inclui também a sub-rede do IP digitado no topo caso seja diferente (ex.: VPN/outra VLAN)
    ip_ref = str(ip_referencia or "").strip()
    if ip_ref:
        try:
            ipaddress.IPv4Address(ip_ref)
            net = ipaddress.IPv4Network(f"{ip_ref}/24", strict=False)
            cidr = str(net)
            if cidr not in vistas:
                vistas.add(cidr)
                subredes.append({
                    "ip_local": "",
                    "prefixo": ".".join(ip_ref.split(".")[:3]),
                    "cidr": cidr,
                    "broadcast": str(net.broadcast_address),
                    "interface": "Sub-rede do IP digitado",
                })
        except ValueError:
            pass

    return subredes


def descobrir_via_ws_discovery(timeout: float = 1.4) -> Dict[str, Set[str]]:
    """
    Envia Probe SOAP WS-Discovery (UDP 3702 multicast 239.255.255.250) para
    dispositivos de impressão na rede local (mesmo protocolo base usado pelo Windows/WSD).
    """
    achados: Dict[str, Set[str]] = {}
    msg_id = f"urn:uuid:{uuid.uuid4()}"
    probe = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        'xmlns:wsdp="http://schemas.xmlsoap.org/ws/2006/02/devprof">'
        "<soap:Header>"
        "<wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>"
        "<wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>"
        f"<wsa:MessageID>{msg_id}</wsa:MessageID>"
        "</soap:Header>"
        "<soap:Body><wsd:Probe><wsd:Types>wsdp:Device</wsd:Types></wsd:Probe></soap:Body>"
        "</soap:Envelope>"
    ).encode("utf-8")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(0.35)
            sock.sendto(probe, ("239.255.255.250", 3702))
            fim = time.time() + timeout
            while time.time() < fim:
                try:
                    data, addr = sock.recvfrom(8192)
                    ip = addr[0]
                    txt = data.decode("utf-8", errors="ignore").lower()
                    if any(k in txt for k in ("print", "lexmark", "mfp", "scan", "wsdp:device", "xaddrs")):
                        achados.setdefault(ip, set()).add("WSD")
                except socket.timeout:
                    continue
                except OSError:
                    break
    except Exception:
        pass
    return achados


def _montar_query_mdns(servico: str) -> bytes:
    """Constrói um pacote DNS PTR simples para consulta mDNS (UDP 5353)."""
    header = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in servico.split(".")) + b"\x00"
    question = qname + struct.pack("!HH", 12, 1)  # TYPE=PTR(12), CLASS=IN(1)
    return header + question


def descobrir_via_mdns(timeout: float = 1.4) -> Dict[str, Set[str]]:
    """
    Consulta serviços de impressão via mDNS / Bonjour (UDP 5353 multicast 224.0.0.251):
    _pdl-datastream._tcp.local (porta 9100), _ipp._tcp.local e _printer._tcp.local.
    """
    achados: Dict[str, Set[str]] = {}
    servicos = ("_pdl-datastream._tcp.local", "_ipp._tcp.local", "_printer._tcp.local")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            sock.settimeout(0.35)
            for srv in servicos:
                sock.sendto(_montar_query_mdns(srv), ("224.0.0.251", 5353))
            fim = time.time() + timeout
            while time.time() < fim:
                try:
                    data, addr = sock.recvfrom(4096)
                    ip = addr[0]
                    if not ip.startswith(("127.", "169.254.")):
                        achados.setdefault(ip, set()).add("mDNS")
                except socket.timeout:
                    continue
                except OSError:
                    break
    except Exception:
        pass
    return achados


def descobrir_via_snmp_broadcast(subredes: List[Dict[str, str]], community: str = "public", timeout: float = 1.3) -> Dict[str, Set[str]]:
    """
    Envia um único pacote SNMPv2c GET sysDescr em broadcast para cada sub-rede ativa.
    Impressoras com SNMP habilitado respondem em milissegundos.
    """
    achados: Dict[str, Set[str]] = {}
    varbind = _ber_tlv(0x30, _ber_oid("1.3.6.1.2.1.1.1.0") + b"\x05\x00")
    pdu = _ber_tlv(0xA0, _ber_int(7741) + _ber_int(0) + _ber_int(0) + _ber_tlv(0x30, varbind))
    pkt = _ber_tlv(0x30, _ber_int(1) + _ber_str(community) + pdu)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.3)
            for sr in subredes:
                try:
                    sock.sendto(pkt, (sr["broadcast"], 161))
                except OSError:
                    pass
            fim = time.time() + timeout
            while time.time() < fim:
                try:
                    data, addr = sock.recvfrom(4096)
                    if len(data) > 12:
                        achados.setdefault(addr[0], set()).add("SNMP-Bcast")
                except socket.timeout:
                    continue
                except OSError:
                    break
    except Exception:
        pass
    return achados


def _identificar_dispositivo(
    ip: str,
    origens: Set[str],
    community: str = "public",
    somente_lexmark: bool = True,
) -> Optional[Dict[str, Any]]:
    """Enriquece um IP candidato via SNMP (e fallback HTTP EWS se SNMP estiver fechado)."""
    def _sg(oid: str) -> str:
        try:
            return str(snmp_get(ip, oid, comunidade=community, timeout=0.9)).strip()
        except Exception:
            return ""

    desc = _sg("1.3.6.1.2.1.1.1.0")
    eh_impressora = False
    fabricante = "Outro"

    if desc:
        low = desc.lower()
        if "lexmark" in low:
            fabricante = "Lexmark"
            eh_impressora = True
        elif any(m in low for m in ("hp ", "hewlett", "brother", "epson", "ricoh", "kyocera", "xerox", "canon", "samsung", "konica", "sharp", "oki")):
            fabricante = desc.split()[0].capitalize()
            eh_impressora = True
        else:
            # Verifica se responde à Printer MIB (RFC 3805)
            pags_chk = _sg("1.3.6.1.2.1.43.10.2.1.4.1.1")
            if pags_chk.isdigit():
                eh_impressora = True
    else:
        # Fallback HTTP caso SNMP esteja bloqueado/com outra comunidade
        try:
            r = requests.get(f"http://{ip}/", timeout=1.2, verify=False)
            m_title = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
            titulo = re.sub(r"\s+", " ", m_title.group(1)).strip() if m_title else ""
            if "lexmark" in titulo.lower() or "lexmark" in r.text[:1500].lower():
                desc = titulo or "Lexmark (SNMP indisponível)"
                fabricante = "Lexmark"
                eh_impressora = True
                origens.add("HTTP")
        except Exception:
            pass

    if not eh_impressora:
        return None
    if somente_lexmark and fabricante != "Lexmark":
        return None

    modelo = desc.split(" version ")[0].strip() if " version " in desc else (desc[:48] or "Impressora")
    serial = _sg("1.3.6.1.2.1.43.5.1.1.17.1") or "N/D"
    paginas = _sg("1.3.6.1.2.1.43.10.2.1.4.1.1") or "N/D"
    lcd = _sg("1.3.6.1.2.1.43.16.5.1.2.1.1") or "N/D"

    toner_pct = None
    try:
        t_cur = int(_sg("1.3.6.1.2.1.43.11.1.1.9.1.1"))
        t_max = int(_sg("1.3.6.1.2.1.43.11.1.1.8.1.1"))
        if t_max > 0 and t_cur >= 0:
            toner_pct = max(0, min(100, round((t_cur / t_max) * 100)))
    except Exception:
        pass

    return {
        "ip": ip,
        "fabricante": fabricante,
        "modelo": modelo,
        "serial": serial,
        "paginas": paginas,
        "toner_pct": toner_pct,
        "lcd": lcd,
        "metodos": sorted(origens),
    }


def descobrir_impressoras_hibrido(
    ip_referencia: str = "",
    community: str = "public",
    somente_lexmark: bool = True,
) -> Dict[str, Any]:
    """
    Executa descoberta híbrida completa em todas as placas de rede ativas do PC:
    WSD (UDP 3702) + mDNS (UDP 5353) + SNMP Broadcast (UDP 161) + Varredura TCP 9100.
    """
    t0 = time.perf_counter()
    subredes = detectar_subredes_locais(ip_referencia=ip_referencia)

    candidatos: Dict[str, Set[str]] = {}

    def _mesclar(mapa: Dict[str, Set[str]]):
        for ip, tags in mapa.items():
            candidatos.setdefault(ip, set()).update(tags)

    # 1. Roda os 3 protocolos de Broadcast/Multicast em paralelo (~1.4s total!)
    with ThreadPoolExecutor(max_workers=3) as pool_proto:
        f_wsd = pool_proto.submit(descobrir_via_ws_discovery, 1.4)
        f_mdns = pool_proto.submit(descobrir_via_mdns, 1.4)
        f_bcast = pool_proto.submit(descobrir_via_snmp_broadcast, subredes, community, 1.3)
        _mesclar(f_wsd.result())
        _mesclar(f_mdns.result())
        _mesclar(f_bcast.result())

    # 2. Varredura TCP 9100 em paralelo nas sub-redes ativas (garante achar mesmo se multicast for bloqueado)
    alvos_tcp: List[str] = []
    for sr in subredes:
        pref = sr["prefixo"]
        alvos_tcp.extend(f"{pref}.{i}" for i in range(1, 255))

    def _probe_tcp(host: str) -> Optional[str]:
        try:
            with socket.create_connection((host, 9100), timeout=0.30):
                return host
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=64) as pool_tcp:
        for res in pool_tcp.map(_probe_tcp, alvos_tcp):
            if res:
                candidatos.setdefault(res, set()).add("TCP-9100")

    # 3. Enriquecimento e identificação de todos os candidatos únicos
    encontradas: List[Dict[str, Any]] = []
    if candidatos:
        with ThreadPoolExecutor(max_workers=24) as pool_id:
            futs = [
                pool_id.submit(_identificar_dispositivo, ip, set(tags), community, somente_lexmark)
                for ip, tags in candidatos.items()
            ]
            for f in as_completed(futs):
                item = f.result()
                if item:
                    encontradas.append(item)

    encontradas.sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))
    duracao = round(time.perf_counter() - t0, 2)
    redes_txt = ", ".join(f"{s['cidr']} ({s['interface']})" for s in subredes)

    linhas = [
        f"🔎 DESCOBERTA HÍBRIDA CONCLUÍDA EM {duracao}s — {len(encontradas)} impressora(s) encontrada(s)",
        f"• Redes analisadas: {redes_txt or 'Nenhuma'}",
        "• Protocolos      : WS-Discovery (3702) + mDNS (5353) + SNMP Broadcast (161) + TCP 9100",
    ]
    for it in encontradas:
        ton = f"{it['toner_pct']}%" if it["toner_pct"] is not None else "N/D"
        linhas.append(
            f"• {it['ip']:15} | {it['modelo']} | Serial: {it['serial']} | "
            f"Págs: {it['paginas']} | Toner: {ton} | Via: {', '.join(it['metodos'])}"
        )

    return {
        "ok": True,
        "duracao_seg": duracao,
        "subredes": subredes,
        "encontradas": encontradas,
        "resumo": "\n".join(linhas),
    }
