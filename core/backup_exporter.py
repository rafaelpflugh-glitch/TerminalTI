"""
============================================================
TERMINAL TI — EXPORTADOR & RESTAURADOR DE BACKUP (4 CATEGORIAS)
(core/backup_exporter.py)
============================================================

Organiza o backup completo da impressora Lexmark em 4 pastas claras:
  1. configuracoes/  -> settingfile.ucf, shortcuts.ucf, authfile.ucf
  2. embarcados/     -> settingfileesf.ucf, apps_instalados.json
  3. rede/           -> rede_somente.ucf (chaves network/ports/snmp/email), setup_rede.html
  4. arquivos/       -> deviceinfo.html, eventlog.html, scanmgr_debug.txt, resumo_snmp.json

Também suporta compactação automática em .zip e Importação Seletiva
(com filtro anti-sobrescrita de IP para clonar impressoras com segurança!).
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional
import zipfile

from core.esf_manager import listar_apps_embarcados
from core.ews_client import EWSClientError, LexmarkEWSClient
from core.pjl_snmp_client import snmp_get

PREFIXOS_REDE_UCF = (
    "network.",
    "ports.",
    "tcpip.",
    "snmp.",
    "dns.",
    "ip.",
    "eth.",
    "wifi.",
    "wlan.",
    "emailAlerts.",
    "smtp.",
    "hostname",
    "sysName",
)


def _sanitizar_nome_pasta(texto: str) -> str:
    limpo = re.sub(r"[^A-Za-z0-9._-]+", "_", str(texto or "").strip())
    return limpo.strip("_") or "Lexmark"


def filtrar_ucf_rede(conteudo_ucf: str, somente_rede: bool = True) -> str:
    """
    Separa chaves de rede das configurações gerais de um arquivo .ucf:
    - somente_rede=True  -> mantém apenas linhas de rede/portas/SNMP/email
    - somente_rede=False -> remove chaves de rede (ideal para clonar sem mudar o IP do destino!)
    """
    saida: List[str] = [
        f"// UCF Filtrado pelo Terminal TI v2 ({'SOMENTE REDE' if somente_rede else 'SEM CHAVES DE REDE - CLONAGEM SEGURA'})"
    ]
    for linha in conteudo_ucf.splitlines():
        st = linha.strip()
        if not st or st.startswith("//"):
            continue
        eh_rede = any(st.lower().startswith(p.lower()) for p in PREFIXOS_REDE_UCF)
        if somente_rede and eh_rede:
            saida.append(linha)
        elif (not somente_rede) and (not eh_rede):
            saida.append(linha)
    return "\r\n".join(saida) + "\r\n"


def exportar_backup_estruturado(
    ip: str,
    pasta_destino: str,
    incluir_configuracoes: bool = True,
    incluir_embarcados: bool = True,
    incluir_rede: bool = True,
    incluir_arquivos: bool = True,
    gerar_zip: bool = True,
    community: str = "public",
    progresso_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Exporta backup completo estruturado em 4 categorias:
    arquivos/ | embarcados/ | rede/ | configuracoes/
    """
    def _avisar(msg: str):
        if progresso_cb:
            progresso_cb(msg)

    ews = LexmarkEWSClient(ip, timeout=15)

    # Identificação SNMP para nomear a pasta com Modelo + Serial + Data
    def _snmp_opt(oid: str) -> str:
        try:
            return str(snmp_get(ip, oid, comunidade=community, timeout=1.8)).strip()
        except Exception:
            return "ND"

    _avisar("Coletando identificação do equipamento via SNMP...")
    sys_descr = _snmp_opt("1.3.6.1.2.1.1.1.0")
    modelo = sys_descr.split(" version ")[0].strip() if " version " in sys_descr else sys_descr[:35]
    serial = _snmp_opt("1.3.6.1.2.1.43.5.1.1.17.1")
    hostname = _snmp_opt("1.3.6.1.2.1.1.5.0")
    paginas = _snmp_opt("1.3.6.1.2.1.43.10.2.1.4.1.1")

    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_pacote = f"Backup_{_sanitizar_nome_pasta(modelo)}_{_sanitizar_nome_pasta(serial)}_{carimbo}"
    raiz = Path(pasta_destino) / nome_pacote
    raiz.mkdir(parents=True, exist_ok=True)

    salvos: List[str] = []
    avisos: List[str] = []
    settingfile_texto = ""

    def _baixar_ucf(tipo: str, destino_rel: str) -> Optional[bytes]:
        try:
            dados = ews.exportar_configuracao_ucf(tipo)
            p = raiz / destino_rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(dados)
            salvos.append(f"{destino_rel} ({len(dados)} bytes)")
            return dados
        except Exception as err:
            avisos.append(f"{destino_rel}: indisponível ({err})")
            return None

    def _baixar_pagina(endpoint: str, destino_rel: str) -> None:
        try:
            txt = ews.ler_pagina_texto(endpoint)
            p = raiz / destino_rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(txt, encoding="utf-8", errors="replace")
            salvos.append(f"{destino_rel} ({len(txt)} chars)")
        except Exception as err:
            avisos.append(f"{destino_rel}: indisponível ({err})")

    # 1. CONFIGURAÇÕES
    if incluir_configuracoes or incluir_rede:
        _avisar("Exportando configurações gerais (settingfile.ucf)...")
        raw_cfg = _baixar_ucf("settingfile.ucf", "configuracoes/settingfile.ucf")
        if raw_cfg:
            settingfile_texto = raw_cfg.decode("utf-8", errors="replace")
            if not incluir_configuracoes:
                (raiz / "configuracoes/settingfile.ucf").unlink(missing_ok=True)
                salvos = [s for s in salvos if not s.startswith("configuracoes/settingfile.ucf")]

    if incluir_configuracoes:
        _avisar("Exportando atalhos e segurança (shortcuts.ucf / authfile.ucf)...")
        _baixar_ucf("shortcuts.ucf", "configuracoes/shortcuts.ucf")
        _baixar_ucf("authfile.ucf", "configuracoes/authfile.ucf")
        if settingfile_texto:
            p_clone = raiz / "configuracoes/settingfile_sem_rede_clonagem.ucf"
            p_clone.parent.mkdir(parents=True, exist_ok=True)
            p_clone.write_text(filtrar_ucf_rede(settingfile_texto, somente_rede=False), encoding="utf-8")
            salvos.append("configuracoes/settingfile_sem_rede_clonagem.ucf")

    # 2. EMBARCADOS (eSF / NDD)
    if incluir_embarcados:
        _avisar("Exportando embarcados eSF / NDD (settingfileesf.ucf + lista de apps)...")
        _baixar_ucf("settingfileesf.ucf", "embarcados/settingfileesf.ucf")
        try:
            apps_res = listar_apps_embarcados(ip)
            p_apps = raiz / "embarcados/apps_instalados.json"
            p_apps.parent.mkdir(parents=True, exist_ok=True)
            p_apps.write_text(json.dumps(apps_res["apps"], indent=2, ensure_ascii=False), encoding="utf-8")
            salvos.append(f"embarcados/apps_instalados.json ({len(apps_res['apps'])} apps)")
        except Exception as err:
            avisos.append(f"embarcados/apps_instalados.json: {err}")

    # 3. REDE
    if incluir_rede:
        _avisar("Exportando configurações de rede...")
        if settingfile_texto:
            p_rede = raiz / "rede/rede_somente.ucf"
            p_rede.parent.mkdir(parents=True, exist_ok=True)
            p_rede.write_text(filtrar_ucf_rede(settingfile_texto, somente_rede=True), encoding="utf-8")
            salvos.append("rede/rede_somente.ucf")
        _baixar_pagina("/cgi-bin/dynamic/config/gen/setuppg.html", "rede/setup_rede.html")

    # 4. ARQUIVOS & RELATÓRIOS INTERNOS
    if incluir_arquivos:
        _avisar("Coletando arquivos internos, eventlog e telemetria...")
        _baixar_pagina("/cgi-bin/dynamic/printer/config/reports/deviceinfo.html", "arquivos/deviceinfo.html")
        _baixar_pagina("/cgi-bin/dynamic/printer/config/reports/eventlog.html", "arquivos/eventlog.html")
        _baixar_pagina("/cgi-bin/script/printer/scanmgr", "arquivos/scanmgr_debug.txt")
        p_meta = raiz / "arquivos/resumo_snmp.json"
        p_meta.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "ip": ip,
            "modelo": modelo,
            "sysDescr": sys_descr,
            "serial": serial,
            "hostname": hostname,
            "total_paginas": paginas,
            "exportado_em": datetime.now().isoformat(),
            "arquivos_salvos": salvos,
            "avisos": avisos,
        }
        p_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        salvos.append("arquivos/resumo_snmp.json")

    caminho_zip: Optional[str] = None
    if gerar_zip:
        _avisar("Compactando pacote .zip...")
        zip_path = Path(pasta_destino) / f"{nome_pacote}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in raiz.rglob("*"):
                if item.is_file():
                    zf.write(item, arcname=str(item.relative_to(raiz)))
        caminho_zip = str(zip_path)

    linhas = [
        f"📂 BACKUP ESTRUTURADO CONCLUÍDO — {ip} ({modelo})",
        f"• Pasta : {raiz}",
    ]
    if caminho_zip:
        linhas.append(f"• ZIP   : {caminho_zip}")
    linhas.append(f"• Arquivos exportados ({len(salvos)}):")
    for s in salvos:
        linhas.append(f"    ✔ {s}")
    if avisos:
        linhas.append(f"• Observações ({len(avisos)}):")
        for a in avisos:
            linhas.append(f"    ⚠️ {a}")

    return {
        "ok": len(salvos) > 0,
        "ip": ip,
        "pasta": str(raiz),
        "zip": caminho_zip,
        "salvos": salvos,
        "avisos": avisos,
        "resumo": "\n".join(linhas),
    }


def importar_ucf_seguro(
    ip: str,
    caminho_ucf: str,
    ignorar_chaves_rede: bool = True,
) -> Dict[str, Any]:
    """
    Importa um arquivo .ucf para a impressora.
    Com ignorar_chaves_rede=True (padrão seguro para clonagem), remove chaves
    de rede/IP antes do envio para não derrubar a máquina da rede do cliente!
    """
    arq = Path(caminho_ucf)
    if not arq.is_file():
        raise EWSClientError(f"Arquivo UCF não encontrado: {arq}")

    ews = LexmarkEWSClient(ip, timeout=20)
    if ignorar_chaves_rede and arq.name.lower().startswith("settingfile") and "esf" not in arq.name.lower():
        conteudo_str = arq.read_text(encoding="utf-8", errors="replace")
        filtrado = filtrar_ucf_rede(conteudo_str, somente_rede=False).encode("utf-8")
        res = ews.importar_ucf_bytes(filtrado, nome_arquivo=f"safe_{arq.name}")
        nota = " (chaves de rede/IP preservadas — clonagem segura)"
    else:
        endpoint = "importdests.html" if "shortcut" in arq.name.lower() else "importsettings.html"
        res = ews.importar_configuracao_ucf(str(arq), endpoint=endpoint)
        nota = ""

    return {
        "ok": True,
        "ip": ip,
        "arquivo": arq.name,
        "resumo": f"✅ Arquivo '{arq.name}' importado com sucesso em {ip}{nota} (HTTP {res.get('status_code')}).",
    }
