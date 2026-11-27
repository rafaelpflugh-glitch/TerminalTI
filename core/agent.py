"""
============================================================
TERMINAL TI — AGENTE HÍBRIDO COM PROTEÇÃO EM 3 NÍVEIS
(core/agent.py)
============================================================

Arquitetura de Segurança em 3 Camadas:
- Nível 0/1 (Operação Segura / Whitelist): executa diretamente (diagnóstico,
  visor LCD, tela inicial, modo scanner, relatório 9100, papel/eco/duplex, varredura).
- Nível 2 (Operação Crítica Controlada): Restaurar Padrões de Fábrica, Apagar NVRAM,
  Wipe Fora de Serviço, Mudar IP Estático e Atualizar Firmware (.fls).
  NUNCA executa direto — realiza pré-checagem técnica (modelo SNMP, sub-rede/máscara,
  integridade do .fls), alerta detalhadamente sobre as consequências e exige
  CONFIRMAÇÃO HUMANA EXPLÍCITA com PIN de 4 dígitos (validade de 60 segundos).
- Nível 3 (Hard-Lock Anti-Brick): comandos PJL crus de exclusão/escrita na flash
  (FSDELETE / FSDOWNLOAD) continuam bloqueados permanentemente.

Motores de Interpretação:
- Motor A (Offline Local, 0% CPU, <5 ms): comandos diretos em português.
- Motor B (Gemini API na Nuvem, Opcional): perguntas livres e raciocínio assistido,
  sempre preso às mesmas travas (o LLM NUNCA pode confirmar uma ação crítica).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import unicodedata

import requests

from core.safe_tools import (
    BOTOES_HOME_ALIASES,
    CRITICAL_TOOL_REGISTRY,
    IDIOMAS_MAPA,
    SAFE_TOOL_REGISTRY,
    identificar_alvo_rapido,
    validar_pre_voo_firmware,
    validar_pre_voo_ip_estatico,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config_agente.json"
EXPIRACAO_CONFIRMACAO_SEG = 60.0
MODELO_GEMINI_PADRAO = "gemini-flash-lite-latest"
MODELOS_GEMINI_FALLBACK = (
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.8-flash",
)

# Nível 3 — Hard-Lock permanente (comandos PJL crus destrutivos na flash sem validação)
TERMOS_HARD_LOCK = [
    ("fsdelete", "Comandos PJL crus de exclusão na partição flash (FSDELETE) podem corromper o sistema operacional da impressora."),
    ("fsdownload", "Comandos PJL crus de escrita direta na partição flash (FSDOWNLOAD) são bloqueados; use o envio oficial de firmware (.fls)."),
]


@dataclass
class PendingCriticalAction:
    token: str
    tool: str
    kwargs: Dict[str, Any]
    titulo: str
    ip: str
    modelo_detectado: str
    serial_detectado: str
    resumo_parametros: str
    riscos: List[str]
    criado_em: float

    def expirou(self) -> bool:
        return (time.time() - self.criado_em) > EXPIRACAO_CONFIRMACAO_SEG

    def segundos_restantes(self) -> int:
        return max(0, int(EXPIRACAO_CONFIRMACAO_SEG - (time.time() - self.criado_em)))


@dataclass
class AgentResponse:
    ok: bool
    motor: str  # "ANTI-BRICK" | "CONFIRMACAO-CRITICA" | "CRITICO-EXECUTADO" | "LOCAL-OFFLINE" | "GEMINI-CLOUD"
    acao: str
    mensagem: str
    dados: Optional[Dict[str, Any]] = None
    confirmacao_pendente: Optional[PendingCriticalAction] = None


def _normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def carregar_config_agente() -> Dict[str, Any]:
    padrao = {
        "usar_llm": False,
        "api_key": "",
        "modelo_gemini": MODELO_GEMINI_PADRAO,
    }
    if CONFIG_PATH.is_file():
        try:
            dados = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                padrao.update(dados)
        except Exception:
            pass

    # Migra automaticamente modelo legado descontinuado para novas chaves
    if str(padrao.get("modelo_gemini") or "").strip() == "gemini-2.5-flash":
        padrao["modelo_gemini"] = MODELO_GEMINI_PADRAO

    if not str(padrao.get("api_key") or "").strip():
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        if env_key.strip():
            padrao["api_key"] = env_key.strip()
    return padrao


def salvar_config_agente(api_key: str, usar_llm: bool, modelo_gemini: str = MODELO_GEMINI_PADRAO) -> None:
    payload = {
        "usar_llm": bool(usar_llm),
        "api_key": str(api_key or "").strip(),
        "modelo_gemini": str(modelo_gemini or MODELO_GEMINI_PADRAO).strip() or MODELO_GEMINI_PADRAO,
    }
    CONFIG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _post_gemini_com_fallback(
    api_key: str,
    modelo_preferido: str,
    payload: Dict[str, Any],
    timeout: int = 20,
) -> Tuple[str, Dict[str, Any]]:
    """
    Chama a API REST do Google Gemini enviando a chave APENAS no header 'x-goog-api-key'
    (nunca na URL, evitando vazamento em logs/erros), com fallback automático em 404/503/429.
    """
    candidatos: List[str] = []
    for m in (modelo_preferido, *MODELOS_GEMINI_FALLBACK):
        m_limpo = str(m or "").strip()
        if m_limpo and m_limpo not in candidatos:
            candidatos.append(m_limpo)

    headers = {
        "x-goog-api-key": str(api_key).strip(),
        "Content-Type": "application/json",
    }
    ultimo_erro = "Nenhum modelo Gemini respondeu."

    for mod in candidatos:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod}:generateContent"
        for tentativa in range(2):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            except Exception as err:
                ultimo_erro = f"Falha de rede ({mod}): {err}"
                break

            if r.status_code == 200:
                return mod, r.json()

            try:
                msg_api = r.json().get("error", {}).get("message", r.text[:220])
            except Exception:
                msg_api = r.text[:220]

            if r.status_code in (400, 401, 403):
                raise RuntimeError(f"Chave API inválida ou sem permissão (HTTP {r.status_code}): {msg_api}")

            ultimo_erro = f"Modelo {mod} indisponível (HTTP {r.status_code}): {msg_api}"
            if r.status_code == 503 and tentativa == 0:
                time.sleep(1.2)
                continue
            if r.status_code in (404, 429, 503):
                break
            raise RuntimeError(ultimo_erro)

    raise RuntimeError(ultimo_erro)


def testar_chave_gemini(api_key: str, modelo: str = MODELO_GEMINI_PADRAO) -> Tuple[bool, str]:
    """
    Faz uma chamada mínima à API REST do Google Gemini (sem bibliotecas pesadas)
    para validar chave, modelo e conectividade.
    """
    chave = str(api_key or "").strip()
    mod = str(modelo or MODELO_GEMINI_PADRAO).strip() or MODELO_GEMINI_PADRAO
    if not chave:
        return False, "Informe uma API Key do Google AI Studio antes de testar."

    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Responda apenas: OK"}]}],
        "generationConfig": {"maxOutputTokens": 8, "temperature": 0.0},
    }
    try:
        mod_usado, data = _post_gemini_com_fallback(chave, mod, payload, timeout=15)
        txt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        extra = f" (fallback de {mod})" if mod_usado != mod else ""
        return True, f"✅ Conectado ao Google Gemini ({mod_usado}{extra})! Resposta: {txt}"
    except Exception as err:
        return False, f"❌ {err}"


def _extrair_ip_alvo(texto_original: str, ip_padrao: str) -> str:
    # Em comandos de troca de IP ("mudar ip para X"), o IP alvo é o IP ATUAL (ip_padrao), não o novo!
    norm = _normalizar(texto_original)
    if any(k in norm for k in ("mudar ip", "alterar ip", "ip estatico", "definir ip", "trocar ip")):
        m_da = re.search(r"\b(?:da|na|em)\s+(\d{1,3}(?:\.\d{1,3}){3})\b", texto_original, re.I)
        if m_da:
            return m_da.group(1)
        m_curto = re.search(r"\b(?:na|da|em|impressora|maquina)\s+(\d{1,3})\b", norm)
        if m_curto and ip_padrao and ip_padrao.count(".") == 3:
            octeto = int(m_curto.group(1))
            if 1 <= octeto <= 254:
                return f"{'.'.join(ip_padrao.split('.')[:3])}.{octeto}"
        return ip_padrao

    m_full = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", texto_original)
    if m_full:
        return m_full.group(1)

    m_curto = re.search(r"\b(?:na|da|em|para|ip|impressora|maquina)\s+(\d{1,3})\b", norm)
    if m_curto and ip_padrao and ip_padrao.count(".") == 3:
        octeto = int(m_curto.group(1))
        if 1 <= octeto <= 254:
            prefixo = ".".join(ip_padrao.split(".")[:3])
            return f"{prefixo}.{octeto}"

    return ip_padrao


def _extrair_texto_aspas(texto_original: str) -> Optional[str]:
    m = re.search(r'["\']([^"\']{1,260})["\']', texto_original)
    if m:
        return m.group(1).strip()
    return None


def _texto_ajuda() -> str:
    return (
        "🤖 COMANDOS QUE EU ENTENDO (100% OFFLINE):\n"
        "\n🟢 OPERAÇÕES SEGURAS (execução imediata):\n"
        "• Diagnóstico completo : 'status', 'como está a 134?', 'quanto tem de toner?', 'contador de páginas'\n"
        "• Modo do Scanner (MFP): 'ver modo do scanner', 'desativar scanner', 'desativar adf', 'ativar scanner'\n"
        "• Visor LCD            : 'coloca \"MANUTENCAO TI\" no visor', 'limpar visor'\n"
        "• Idioma / NTP / VNC   : 'mude o idioma para português', 'sincronizar hora de brasília',\n"
        "                         'ativar ntp oficial', 'brilho 80%', 'desligar bipe do adf', 'ativar vnc'\n"
        "• Embarcados & Backup  : 'listar embarcados' (eSF/NDD), 'fazer backup completo'\n"
        "• Tela Inicial (Botões): 'ver tela inicial', 'modo corporativo', 'modo smartphone',\n"
        "                         'ocultar fax', 'mostrar email', 'deixar só cópia e usb'\n"
        "• Relatório Zero-Driver: 'imprimir relatório de bancada', 'imprimir página de teste'\n"
        "• Impressão Segura     : 'papel A4', 'papel carta', 'ativar duplex', 'ligar modo eco', 'densidade 4'\n"
        "• Rede & Auditoria     : 'varrer rede', 'testar portas', 'variáveis pjl jam', 'limpar avisos'\n"
        "\n🟠 OPERAÇÕES CRÍTICAS CONTROLADAS (pré-checagem + alerta + confirmação com PIN):\n"
        "• Padrões de Fábrica   : 'restaurar padrões de fábrica' (ou '... rede' / '... apps')\n"
        "• Limpar NVRAM         : 'apagar nvram'\n"
        "• Wipe Fora de Serviço : 'wipe fora de serviço'\n"
        "• IP Estático          : 'mudar ip estático para 192.168.14.200 mascara 255.255.255.0 gateway 192.168.14.254'\n"
        "• Firmware (.fls)      : 'atualizar firmware \"C:\\caminho\\arquivo.fls\"'\n"
        "• Confirmar / Cancelar : 'CONFIRMAR <PIN>' ou 'CANCELAR'\n"
        "\n🔴 BLOQUEIO PERMANENTE: comandos PJL crus destrutivos na flash (FSDELETE / FSDOWNLOAD)."
    )


class TerminalTIAgent:
    """Orquestrador Híbrido com Proteção em 3 Níveis."""

    def __init__(self):
        self.config = carregar_config_agente()
        self.acao_pendente: Optional[PendingCriticalAction] = None

    def recarregar_config(self) -> Dict[str, Any]:
        self.config = carregar_config_agente()
        return self.config

    def cancelar_acao_pendente(self) -> AgentResponse:
        if self.acao_pendente is None:
            return AgentResponse(
                ok=True,
                motor="LOCAL-OFFLINE",
                acao="cancelar",
                mensagem="ℹ️ Não há nenhuma operação crítica aguardando confirmação.",
            )
        titulo = self.acao_pendente.titulo
        self.acao_pendente = None
        return AgentResponse(
            ok=True,
            motor="LOCAL-OFFLINE",
            acao="cancelado",
            mensagem=f"❎ Operação crítica '{titulo}' CANCELADA com segurança. Nada foi alterado na impressora.",
        )

    def _checar_hard_lock(self, norm: str) -> Optional[AgentResponse]:
        for termo, motivo in TERMOS_HARD_LOCK:
            if termo in norm:
                return AgentResponse(
                    ok=False,
                    motor="ANTI-BRICK",
                    acao="BLOQUEADO",
                    mensagem=(
                        f"🔴 AÇÃO BLOQUEADA PERMANENTEMENTE (HARD-LOCK ANTI-BRICK)\n"
                        f"• Motivo: {motivo}"
                    ),
                )
        return None

    def _preparar_confirmacao_critica(
        self,
        tool: str,
        kwargs: Dict[str, Any],
        titulo: str,
        ip: str,
        resumo_parametros: str,
        riscos: List[str],
        community: str,
    ) -> AgentResponse:
        if tool not in CRITICAL_TOOL_REGISTRY:
            return AgentResponse(
                ok=False,
                motor="ANTI-BRICK",
                acao="recusado",
                mensagem=f"🛡️ Ferramenta crítica '{tool}' não reconhecida.",
            )

        # Identifica o equipamento ao vivo via SNMP para o técnico ter 100% de certeza do alvo
        alvo = identificar_alvo_rapido(ip, community=community)
        token = f"{random.randint(1000, 9999)}"
        pending = PendingCriticalAction(
            token=token,
            tool=tool,
            kwargs=kwargs,
            titulo=titulo,
            ip=ip,
            modelo_detectado=alvo["modelo"],
            serial_detectado=alvo["serial"],
            resumo_parametros=resumo_parametros,
            riscos=riscos,
            criado_em=time.time(),
        )
        self.acao_pendente = pending

        linhas_riscos = "\n".join(f"  ⚠️ {r}" for r in riscos)
        msg = (
            f"🟠 CONFIRMAÇÃO OBRIGATÓRIA — OPERAÇÃO CRÍTICA\n"
            f"• Operação        : {titulo}\n"
            f"• Impressora Alvo : {ip} ({alvo['modelo']} | Serial: {alvo['serial']})\n"
            f"• Parâmetros      : {resumo_parametros}\n"
            f"\nCONSEQUÊNCIAS E ALERTAS:\n{linhas_riscos}\n"
            f"\n🔐 Para autorizar, digite:  CONFIRMAR {token}   (expira em {int(EXPIRACAO_CONFIRMACAO_SEG)}s)\n"
            f"❎ Para abortar, digite:    CANCELAR"
        )
        return AgentResponse(
            ok=True,
            motor="CONFIRMACAO-CRITICA",
            acao=f"aguardando_pin:{tool}",
            mensagem=msg,
            confirmacao_pendente=pending,
        )

    def _executar_acao_confirmada(self, pin_informado: str) -> AgentResponse:
        pending = self.acao_pendente
        if pending is None:
            return AgentResponse(
                ok=False,
                motor="CONFIRMACAO-CRITICA",
                acao="sem_pendencia",
                mensagem="ℹ️ Não existe nenhuma operação crítica pendente para confirmar.",
            )

        if pending.expirou():
            self.acao_pendente = None
            return AgentResponse(
                ok=False,
                motor="CONFIRMACAO-CRITICA",
                acao="expirado",
                mensagem=(
                    f"⏱️ O pedido de confirmação para '{pending.titulo}' EXPIROU (passaram-se mais de "
                    f"{int(EXPIRACAO_CONFIRMACAO_SEG)}s). Por segurança, solicite o comando novamente."
                ),
            )

        if str(pin_informado).strip() != pending.token:
            return AgentResponse(
                ok=False,
                motor="CONFIRMACAO-CRITICA",
                acao="pin_incorreto",
                mensagem=(
                    f"❌ PIN incorreto ('{pin_informado}'). Operação NÃO executada.\n"
                    f"Digite exatamente 'CONFIRMAR {pending.token}' ou 'CANCELAR'."
                ),
            )

        # Consome a pendência antes de executar (uso único — evita dupla execução!)
        self.acao_pendente = None
        func = CRITICAL_TOOL_REGISTRY[pending.tool]
        try:
            res = func(**pending.kwargs)
            return AgentResponse(
                ok=bool(res.get("ok", True)),
                motor="CRITICO-EXECUTADO",
                acao=pending.tool,
                mensagem=res.get("resumo", str(res)),
                dados=res,
            )
        except Exception as err:
            return AgentResponse(
                ok=False,
                motor="CRITICO-EXECUTADO",
                acao=pending.tool,
                mensagem=f"❌ Erro ao executar operação crítica '{pending.titulo}': {err}",
            )

    def _resolver_critico_local(
        self,
        texto_original: str,
        ip: str,
        community: str,
    ) -> Optional[AgentResponse]:
        """
        Detecta pedidos de Nível 2 (Operações Críticas Controladas), executa pré-checagem
        rígida e SEMPRE exige confirmação humana com PIN + alerta de consequências.
        """
        norm = _normalizar(texto_original)

        # 1. Wipe / Fora de Serviço
        if any(k in norm for k in ("wipe", "fora de servico", "formatar disco", "apagar tudo")):
            return self._preparar_confirmacao_critica(
                tool="critico_wipe_fora_de_servico",
                kwargs={"ip": ip},
                titulo="Wipe Fora de Serviço (Memória Volátil + NVRAM + Disco)",
                ip=ip,
                resumo_parametros="Endpoint oficial /memwipe.html",
                riscos=[
                    "APAGA IRREVERSIVELMENTE todas as configurações, atalhos, certificados, senhas e trabalhos salvos.",
                    "A impressora perderá configurações de rede personalizadas e reiniciará no assistente inicial de fábrica.",
                    "NÃO desligue a energia durante o procedimento de limpeza.",
                ],
                community=community,
            )

        # 2. Apagar Memória NVRAM
        if "nvram" in norm or "apagar memoria" in norm or "limpar memoria" in norm:
            return self._preparar_confirmacao_critica(
                tool="critico_apagar_nvram",
                kwargs={"ip": ip},
                titulo="Limpeza de Memória NVRAM",
                ip=ip,
                resumo_parametros="Endpoint oficial /erase_printer_memory.html",
                riscos=[
                    "Apaga configurações salvas na memória não volátil da impressora.",
                    "A impressora será reiniciada automaticamente e poderá perder ajustes de bandeja/tela inicial.",
                    "Recomendado exportar backup settingfile.ucf antes de prosseguir.",
                ],
                community=community,
            )

        # 3. Restaurar Padrões de Fábrica
        if any(k in norm for k in ("padrao de fabrica", "padroes de fabrica", "factory reset", "reset de fabrica", "restaurar fabrica")):
            if any(k in norm for k in ("rede", "network", "ip")):
                escopo = "network"
                escopo_desc = "network (Apenas configurações de Rede/TCP-IP)"
                riscos = [
                    "RESETA A PLACA DE REDE para DHCP/padrão de fábrica!",
                    "A impressora VAI PERDER O IP ESTÁTICO ATUAL e ficará inacessível neste IP até descobrir o novo IP.",
                    "Se estiver acessando remotamente, você perderá a conexão com a máquina imediatamente.",
                ]
            elif any(k in norm for k in ("app", "les", "esf", "soluc")):
                escopo = "les"
                escopo_desc = "les (Aplicativos embarcados eSF / Soluções)"
                riscos = [
                    "Restaura todos os aplicativos eSF (Scan to Network, atalhos e soluções) ao padrão.",
                    "Configurações de rede e IP são mantidas, mas integrações eSF precisarão ser reconfiguradas.",
                ]
            else:
                escopo = "base"
                escopo_desc = "base (Definições gerais da impressora — mantém IP de rede)"
                riscos = [
                    "Apaga todas as configurações locais da impressora (bandejas, idioma, tela inicial, qualidade e atalhos).",
                    "A impressora pode reiniciar automaticamente durante o processo.",
                ]

            return self._preparar_confirmacao_critica(
                tool="critico_restaurar_fabrica",
                kwargs={"ip": ip, "escopo": escopo},
                titulo=f"Restaurar Padrões de Fábrica ({escopo})",
                ip=ip,
                resumo_parametros=f"Escopo: {escopo_desc}",
                riscos=riscos,
                community=community,
            )

        # 4. Mudar IP Estático
        if any(k in norm for k in ("mudar ip", "alterar ip", "ip estatico", "definir ip", "trocar ip")):
            ips_encontrados = re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", texto_original)
            # Se o usuário citou "da 192.168.14.134 para 192.168.14.200 ...", ignora o primeiro se igual ao ip alvo
            if len(ips_encontrados) >= 4 and ips_encontrados[0] == ip:
                ips_encontrados = ips_encontrados[1:]

            if len(ips_encontrados) < 3:
                return AgentResponse(
                    ok=False,
                    motor="CONFIRMACAO-CRITICA",
                    acao="parametros_incompletos",
                    mensagem=(
                        "⚠️ Para alterar o IP estático com segurança, informe IP, Máscara e Gateway completos.\n"
                        "Exemplo:\n"
                        "  mudar ip estático para 192.168.14.200 mascara 255.255.255.0 gateway 192.168.14.254"
                    ),
                )

            novo_ip, mascara, gateway = ips_encontrados[0], ips_encontrados[1], ips_encontrados[2]
            try:
                val = validar_pre_voo_ip_estatico(novo_ip, mascara, gateway)
            except ValueError as err:
                return AgentResponse(
                    ok=False,
                    motor="CONFIRMACAO-CRITICA",
                    acao="pre_voo_falhou",
                    mensagem=f"❌ Pré-checagem de rede BLOQUEOU a troca de IP:\n• {err}",
                )

            return self._preparar_confirmacao_critica(
                tool="critico_mudar_ip_estatico",
                kwargs={
                    "ip": ip,
                    "novo_ip": val["novo_ip"],
                    "mascara": val["mascara"],
                    "gateway": val["gateway"],
                },
                titulo="Alterar IP Estático da Impressora",
                ip=ip,
                resumo_parametros=(
                    f"IP Atual: {ip}  ➜  Novo IP: {val['novo_ip']} | "
                    f"Máscara: {val['mascara']} | Gateway: {val['gateway']} (Sub-rede {val['rede']})"
                ),
                riscos=[
                    f"A impressora deixará de responder em {ip} e passará a responder em {val['novo_ip']}.",
                    "Certifique-se de que o IP escolhido NÃO está em uso por outro equipamento na rede (conflito de IP).",
                    "Se o endereço estiver fora da faixa da rede do cliente/bancada, será necessário reconfigurar no painel físico.",
                ],
                community=community,
            )

        # 5. Atualizar Firmware (.fls / .bin)
        if any(k in norm for k in ("firmware", ".fls", "atualizar codigo", "flash ")):
            caminho = _extrair_texto_aspas(texto_original)
            if not caminho:
                m_path = re.search(r"([A-Za-z]:\\[^\s]+\.(?:fls|bin))", texto_original, re.I)
                if m_path:
                    caminho = m_path.group(1)

            if not caminho:
                return AgentResponse(
                    ok=False,
                    motor="CONFIRMACAO-CRITICA",
                    acao="parametros_incompletos",
                    mensagem=(
                        "⚠️ Para atualizar o firmware com segurança, informe o caminho completo do arquivo .fls entre aspas.\n"
                        'Exemplo:\n  atualizar firmware "C:\\Firmwares\\MX611_NH7.fls"'
                    ),
                )

            try:
                info_fw = validar_pre_voo_firmware(caminho)
            except ValueError as err:
                return AgentResponse(
                    ok=False,
                    motor="CONFIRMACAO-CRITICA",
                    acao="pre_voo_falhou",
                    mensagem=f"❌ Pré-checagem de firmware BLOQUEOU o envio:\n• {err}",
                )

            aviso_assinatura = (
                "Cabeçalho compatível com container PJL/Lexmark detectado."
                if info_fw["assinatura_lexmark"]
                else "ATENÇÃO EXTRA: cabeçalho PJL/Lexmark não identificado nos primeiros 512 bytes — confira 2x se este arquivo é mesmo um firmware oficial!"
            )
            return self._preparar_confirmacao_critica(
                tool="critico_atualizar_firmware",
                kwargs={"ip": ip, "caminho_fls": info_fw["caminho"]},
                titulo="Atualização de Firmware via HTTP (EWS)",
                ip=ip,
                resumo_parametros=f"Arquivo: {info_fw['nome']} ({info_fw['tamanho_mb']} MB) — {aviso_assinatura}",
                riscos=[
                    "RISCO DE BRICK SE O ARQUIVO NÃO FOR EXATAMENTE DA FAMÍLIA/MODELO DESTA IMPRESSORA!",
                    "NUNCA DESLIGUE A ENERGIA OU O CABO DE REDE durante o envio e a gravação na flash (3 a 8 minutos).",
                    "Confira acima se o Modelo detectado via SNMP corresponde ao firmware escolhido antes de digitar o PIN.",
                ],
                community=community,
            )

        return None

    def _resolver_local(
        self,
        texto_original: str,
        ip: str,
        community: str,
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Motor A — Operações Seguras Nível 0/1 (Offline Local, 0% CPU)."""
        norm = _normalizar(texto_original)

        if norm in ("ajuda", "help", "?", "comandos") or "o que voce faz" in norm or "quais comandos" in norm:
            return ("__ajuda__", {})

        # Idioma do equipamento (antes de Tela Inicial para não conflitar com botão "Alterar Idioma")
        if not any(k in norm for k in ("botao", "botoes", "icone", "tela inicial", "ocultar", "esconder")):
            tem_gatilho_idioma = any(k in norm for k in ("idioma", "lingua", "linguagem", "language", "mudar para", "mude para", "colocar em", "trocar para"))
            for alvo_lang in sorted(IDIOMAS_MAPA.keys(), key=len, reverse=True):
                if len(alvo_lang) <= 2 and not tem_gatilho_idioma:
                    continue
                if re.search(rf"\b{re.escape(alvo_lang)}\b", norm):
                    if tem_gatilho_idioma or len(alvo_lang) >= 5:
                        return ("alterar_idioma", {"ip": ip, "idioma": alvo_lang})

        # Relógio / Data e Hora (NTP Oficial de Brasília — a.st1.ntp.br)
        if any(k in norm for k in ("ativar ntp", "configurar ntp", "ntp nativo", "ntp oficial", "ntp brasil")):
            return ("sincronizar_relogio", {"ip": ip, "ativar_ntp_nativo": True})
        if any(k in norm for k in ("sincronizar relogio", "acertar relogio", "ajustar relogio", "acertar hora", "ajustar hora", "sincronizar hora", "hora de brasilia", "data e hora", "hora do pc")):
            return ("sincronizar_relogio", {"ip": ip, "ativar_ntp_nativo": False})

        # Embarcados (eSF / NDD)
        if any(k in norm for k in ("embarcado", "embarcados", "listar apps", "ver apps", "quais apps", "apps instalados", "esf", "ndd")):
            return ("listar_embarcados_seguro", {"ip": ip})

        # Backup completo 4 categorias
        if any(k in norm for k in ("fazer backup", "exportar backup", "backup completo", "exportar configurac")):
            return ("exportar_backup_rapido", {"ip": ip, "community": community})

        # Painel Geral: Brilho LCD, Bipe ADF, VNC
        kwargs_painel: Dict[str, Any] = {}
        if "brilho" in norm:
            m_b = re.search(r"(\d{2,3})\s*%?", norm)
            if m_b:
                kwargs_painel["brilho"] = int(m_b.group(1))
        if "bipe" in norm or "beep" in norm:
            if any(k in norm for k in ("deslig", "desativ", "tirar", "tira", "sem ", "silenci", "off")):
                kwargs_painel["bipe_adf"] = False
            elif any(k in norm for k in ("lig", "ativ", "habilit", "on", "com ")):
                kwargs_painel["bipe_adf"] = True
        if any(k in norm for k in ("ativar vnc", "ligar vnc", "habilitar vnc", "painel remoto", "espelhamento")):
            kwargs_painel["ativar_vnc"] = True
        if kwargs_painel:
            kwargs_painel["ip"] = ip
            return ("configurar_painel_geral", kwargs_painel)

        if any(k in norm for k in ("varrer rede", "varre a rede", "buscar lexmark", "achar impressora", "achar lexmark", "descobrir impressora", "listar impressoras")):
            return ("escanear_rede_lexmark", {"ip_referencia": ip, "community": community})

        if any(k in norm for k in ("testar porta", "escanear porta", "scan de porta", "ver portas", "portas abertas", "dar ping", "pingar", "ping ")):
            return ("verificar_portas", {"ip": ip})

        # Relatórios nativos do firmware Lexmark (PJL LPRINT*)
        if any(k in norm for k in ("imprim", "pagina de", "lista de")):
            if any(k in norm for k in ("configuracoes de menu", "configuracao de menu", "pagina de menu", "lprintmenus", "menus da impressora")):
                return ("imprimir_relatorio_nativo", {"ip": ip, "tipo": "menus"})
            if any(k in norm for k in ("diretorio", "lprintdirectory")):
                return ("imprimir_relatorio_nativo", {"ip": ip, "tipo": "diretorio"})
            if "fontes pcl" in norm or "lista de fontes pcl" in norm:
                return ("imprimir_relatorio_nativo", {"ip": ip, "tipo": "fontes_pcl"})
            if "fontes ps" in norm or "fontes postscript" in norm:
                return ("imprimir_relatorio_nativo", {"ip": ip, "tipo": "fontes_ps"})

        if any(k in norm for k in ("imprim", "folha de teste", "pagina de teste", "relatorio de bancada", "relatorio tecnico")) and any(
            k in norm for k in ("relatorio", "teste", "bancada", "diagnostico", "folha", "demonstracao", "ativo")
        ):
            titulo = _extrair_texto_aspas(texto_original) or "RELATORIO DE BANCADA - TERMINAL TI"
            return ("imprimir_relatorio_bancada", {"ip": ip, "titulo": titulo, "community": community})

        # Cópia física / Digitalização física (explica uso via Painel Remoto VNC)
        if any(k in norm for k in ("fazer copia", "tirar copia", "iniciar copia", "digitalizar pagina", "digitalizar documento", "escanear pagina", "escanear documento")):
            return ("__aviso_copia_scan__", {"ip": ip})

        if "scanner" in norm or "adf" in norm:
            if any(k in norm for k in ("desativar adf", "desligar adf", "desabilitar adf", "sem adf", "so mesa plana", "somente mesa plana")):
                return ("definir_modo_scanner", {"ip": ip, "modo": "2"})
            if any(k in norm for k in ("desativar scanner", "desligar scanner", "desabilitar scanner", "sem scanner", "so impressora", "desativa o scanner", "desliga o scanner")):
                return ("definir_modo_scanner", {"ip": ip, "modo": "1"})
            if any(k in norm for k in ("ativar scanner", "ligar scanner", "habilitar scanner", "reativar scanner", "ativa o scanner", "liga o scanner", "ativar adf", "ligar adf")):
                return ("definir_modo_scanner", {"ip": ip, "modo": "0"})
            if any(k in norm for k in ("ver", "ler", "qual", "status", "estado", "modo", "checar", "verificar", "como esta")):
                return ("ler_modo_scanner", {"ip": ip})

        if any(k in norm for k in ("visor", "display", "mensagem")):
            if any(k in norm for k in ("limp", "restaur", "voltar pronto", "padrao", "apagar mensagem", "tirar mensagem")):
                return ("alterar_visor_lcd", {"ip": ip, "texto": ""})
            msg_aspas = _extrair_texto_aspas(texto_original)
            if msg_aspas is not None:
                return ("alterar_visor_lcd", {"ip": ip, "texto": msg_aspas})
            m_para = re.search(r"(?:para|como|:)\s+(.+)$", texto_original, re.I)
            if m_para and any(k in norm for k in ("coloc", "escrev", "mud", "alter", "defin", "exib", "mostr", "bot")):
                candidato = m_para.group(1).strip().strip("\"'")
                if candidato:
                    return ("alterar_visor_lcd", {"ip": ip, "texto": candidato})

        if "limpar aviso" in norm or "limpa aviso" in norm or "clear warning" in norm:
            return ("limpar_avisos_painel", {"ip": ip})

        if any(k in norm for k in ("tela inicial", "home", "botoes", "botao", "icone", "modo smartphone", "modo corporativo", "fax", "email", "e-mail", "pendrive")):
            if "smartphone" in norm:
                return ("configurar_tela_inicial", {"ip": ip, "preset": "smartphone"})
            if "corporativo" in norm:
                return ("configurar_tela_inicial", {"ip": ip, "preset": "corporativo"})
            if any(k in norm for k in ("mostrar todos", "ativar todos", "todos os botoes")):
                return ("configurar_tela_inicial", {"ip": ip, "preset": "todos"})
            if any(k in norm for k in ("ocultar todos", "esconder todos", "nenhum botao")):
                return ("configurar_tela_inicial", {"ip": ip, "preset": "nenhum"})

            if any(k in norm for k in ("deixar so", "deixa so", "apenas ", "somente ")):
                encontrados = []
                for alias in sorted(BOTOES_HOME_ALIASES.keys(), key=len, reverse=True):
                    if re.search(rf"\b{re.escape(alias)}\b", norm):
                        encontrados.append(alias)
                if encontrados:
                    return ("configurar_tela_inicial", {"ip": ip, "manter_apenas": encontrados})

            eh_ocultar = any(k in norm for k in ("ocultar", "oculta", "esconder", "esconde", "tirar", "tira", "remover", "remove", "desativar botao"))
            eh_mostrar = any(k in norm for k in ("mostrar", "mostra", "exibir", "exibe", "ativar botao", "adicionar", "colocar botao"))
            if eh_ocultar or eh_mostrar:
                encontrados = []
                for alias in sorted(BOTOES_HOME_ALIASES.keys(), key=len, reverse=True):
                    if re.search(rf"\b{re.escape(alias)}\b", norm):
                        encontrados.append(alias)
                if encontrados:
                    return (
                        "configurar_tela_inicial",
                        {
                            "ip": ip,
                            "ocultar": encontrados if eh_ocultar else None,
                            "mostrar": encontrados if (eh_mostrar and not eh_ocultar) else None,
                        },
                    )

            if any(k in norm for k in ("ver", "ler", "listar", "quais", "mostrar", "status")):
                return ("ler_tela_inicial", {"ip": ip})

        kwargs_imp: Dict[str, Any] = {}
        if "papel a4" in norm or "tamanho a4" in norm or "para a4" in norm:
            kwargs_imp["papel"] = "A4"
        elif "papel carta" in norm or "letter" in norm:
            kwargs_imp["papel"] = "LETTER"
        elif "oficio" in norm or "legal" in norm:
            kwargs_imp["papel"] = "LEGAL"

        if "duplex" in norm or "frente e verso" in norm:
            if any(k in norm for k in ("desativ", "deslig", "off", "sem ")):
                kwargs_imp["duplex"] = False
            elif any(k in norm for k in ("ativ", "lig", "on", "com ")):
                kwargs_imp["duplex"] = True

        if "modo eco" in norm or "economia de toner" in norm or "economode" in norm:
            if any(k in norm for k in ("desativ", "deslig", "off")):
                kwargs_imp["eco"] = False
            elif any(k in norm for k in ("ativ", "lig", "on")):
                kwargs_imp["eco"] = True

        m_dens = re.search(r"(?:densidade|tonalidade)\s*(?:nivel|para|=)?\s*([1-5])\b", norm)
        if m_dens:
            kwargs_imp["densidade"] = int(m_dens.group(1))

        if kwargs_imp:
            kwargs_imp["ip"] = ip
            return ("configurar_impressao_segura", kwargs_imp)

        if "variaveis pjl" in norm or "variavel pjl" in norm or "info variables" in norm:
            m_f = re.search(r"(?:pjl|variables)\s+([a-z0-9_]+)", norm)
            filtro = m_f.group(1) if m_f else ""
            return ("ler_variaveis_pjl", {"ip": ip, "filtro": filtro})

        if any(
            k in norm
            for k in (
                "status",
                "diagnostico",
                "saude",
                "como esta",
                "como ta",
                "toner",
                "cilindro",
                "suprimento",
                "contador",
                "total de paginas",
                "quantas paginas",
                "serial",
                "modelo",
                "informacoes",
                "auditoria",
                "resumo",
                "checar",
                "verificar",
            )
        ):
            return ("diagnostico_completo", {"ip": ip, "community": community})

        return None

    def _executar_ferramenta_whitelist(self, nome: str, kwargs: Dict[str, Any], motor: str) -> AgentResponse:
        if nome == "__ajuda__":
            return AgentResponse(ok=True, motor=motor, acao="ajuda", mensagem=_texto_ajuda())

        if nome == "__aviso_copia_scan__":
            ip_alvo = kwargs.get("ip", "")
            return AgentResponse(
                ok=True,
                motor=motor,
                acao="orientacao_vnc",
                mensagem=(
                    f"ℹ️ O firmware Lexmark não possui comando PJL/HTTP direto para disparar Cópia ou Digitalização física.\n"
                    f"• Para clicar remotamente em 'Cópia' ou 'Digitalizar' na tela da {ip_alvo}:\n"
                    f"  1) Digite 'ativar vnc' aqui no Agente.\n"
                    f"  2) Abra o Painel Remoto em: http://{ip_alvo}/cgi-bin/dynamic/printer/config/remote_oppanel.html"
                ),
            )

        if nome not in SAFE_TOOL_REGISTRY:
            return AgentResponse(
                ok=False,
                motor="ANTI-BRICK",
                acao=nome,
                mensagem=f"🛡️ Ferramenta '{nome}' não pertence à Whitelist Segura e não pode ser executada sem confirmação.",
            )

        func = SAFE_TOOL_REGISTRY[nome]
        try:
            res = func(**kwargs)
            return AgentResponse(
                ok=bool(res.get("ok", True)),
                motor=motor,
                acao=nome,
                mensagem=res.get("resumo", str(res)),
                dados=res,
            )
        except Exception as err:
            return AgentResponse(
                ok=False,
                motor=motor,
                acao=nome,
                mensagem=f"❌ Erro ao executar '{nome}': {err}",
            )

    def _chamar_gemini_cloud(self, texto_usuario: str, ip: str, community: str) -> AgentResponse:
        """
        Motor B — Gemini na nuvem (0% CPU local).
        Restrito à Whitelist Segura; jamais pode auto-confirmar ações críticas.
        """
        api_key = str(self.config.get("api_key") or "").strip()
        modelo = str(self.config.get("modelo_gemini") or MODELO_GEMINI_PADRAO).strip()
        if not api_key:
            return AgentResponse(
                ok=False,
                motor="GEMINI-CLOUD",
                acao="sem_chave",
                mensagem=(
                    "☁️ Modo Gemini na Nuvem ativado, mas nenhuma API Key está configurada.\n"
                    "Clique em '🔑 Configurar API Key' ou use um comando direto do modo Offline (digite 'ajuda')."
                ),
            )

        ferramentas_desc = """
FERRAMENTAS SEGURAS PERMITIDAS (execução direta):
1. diagnostico_completo(ip, community)
2. ler_modo_scanner(ip)
3. definir_modo_scanner(ip, modo) -> modo: "0" (Ativado), "1" (Desativado), "2" (ADF Desativado)
4. alterar_visor_lcd(ip, texto) -> texto vazio "" restaura 'Pronto'
5. limpar_avisos_painel(ip)
6. ler_tela_inicial(ip)
7. configurar_tela_inicial(ip, preset, mostrar, ocultar, manter_apenas)
8. configurar_impressao_segura(ip, papel, duplex, eco, densidade)
9. imprimir_relatorio_bancada(ip, titulo, community)
10. verificar_portas(ip)
11. ler_variaveis_pjl(ip, filtro)
12. escanear_rede_lexmark(ip_referencia, community)
13. alterar_idioma(ip, idioma) -> idioma: "portugues", "ingles", "espanhol", "frances", "alemao", "italiano", "turco", "russo", "japones", "coreano", "chines", "polones", "holandes", "sueco", "dinamarques", "noruegues", "finlandes", "tcheco", "hungaro", "grego"
14. sincronizar_relogio(ip, ativar_ntp_nativo) -> usa Horário Oficial de Brasília (a.st1.ntp.br)
15. configurar_painel_geral(ip, brilho, bipe_adf, ativar_vnc)
16. imprimir_relatorio_nativo(ip, tipo) -> tipo: "menus" (@PJL LPRINTMENUS), "diretorio", "fontes_pcl", "fontes_ps"
17. listar_embarcados_seguro(ip) -> lista aplicativos embarcados eSF / NDD instalados
18. exportar_backup_rapido(ip, community) -> exporta backup 4 categorias + .zip
"""

        prompt_sistema = (
            "Você é o Agente Técnico do Terminal TI para impressoras Lexmark.\n"
            f"IP alvo atual: {ip} | Comunidade SNMP: {community}.\n"
            f"{ferramentas_desc}\n"
            "REGRA ESTRITA: Responda EXCLUSIVAMENTE um JSON válido sem markdown:\n"
            '- Para executar uma ferramenta segura da lista: {"tipo": "tool", "tool": "<nome>", "args": {...}}\n'
            '- Para responder/orientar o técnico: {"tipo": "texto", "resposta": "<texto em português>"}\n'
            "NUNCA invente ferramentas fora da lista. Operações críticas (firmware, wipe, nvram, fábrica, IP) "
            "exigem comando direto com pré-checagem e confirmação humana por PIN."
        )

        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": f"{prompt_sistema}\n\nPEDIDO DO TÉCNICO: {texto_usuario}"}]}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        try:
            mod_usado, data = _post_gemini_com_fallback(api_key, modelo, payload, timeout=20)
            txt_json = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            parsed = json.loads(txt_json)
        except Exception as err:
            return AgentResponse(
                ok=False,
                motor="GEMINI-CLOUD",
                acao="erro_api",
                mensagem=f"❌ Falha ao consultar Gemini API na nuvem: {err}",
            )

        motor_tag = f"GEMINI-CLOUD ({mod_usado})"
        if parsed.get("tipo") == "tool":
            tool_name = str(parsed.get("tool") or "").strip()
            args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
            if "ip" not in args and tool_name != "escanear_rede_lexmark":
                args["ip"] = ip
            if tool_name == "escanear_rede_lexmark" and "ip_referencia" not in args:
                args["ip_referencia"] = ip
            return self._executar_ferramenta_whitelist(tool_name, args, motor=motor_tag)

        return AgentResponse(
            ok=True,
            motor=motor_tag,
            acao="resposta_ia",
            mensagem=str(parsed.get("resposta") or txt_json),
        )

    def processar_comando(
        self,
        texto_usuario: str,
        ip_padrao: str,
        community: str = "public",
    ) -> AgentResponse:
        """
        Fluxo de execução:
        1. CONFIRMAR <PIN> / CANCELAR (para ações críticas pendentes)
        2. Hard-Lock permanente (FSDELETE / FSDOWNLOAD)
        3. Nível 2 — Ações Críticas Controladas (pré-checagem + alerta + PIN, sem executar direto!)
        4. Nível 0/1 — Motor A (Local Offline)
        5. Motor B — Gemini Cloud (opcional)
        """
        texto = str(texto_usuario or "").strip()
        if not texto:
            return AgentResponse(ok=False, motor="LOCAL-OFFLINE", acao="vazio", mensagem="Digite um comando (ex.: 'status' ou 'ajuda').")

        norm = _normalizar(texto)

        # 1. Confirmação ou cancelamento de ação crítica pendente
        if norm in ("cancelar", "abortar", "nao", "cancel"):
            return self.cancelar_acao_pendente()

        m_conf = re.match(r"^confirmar\s+(\d{4})$", norm)
        if m_conf:
            return self._executar_acao_confirmada(m_conf.group(1))
        if norm == "confirmar":
            if self.acao_pendente and not self.acao_pendente.expirou():
                return AgentResponse(
                    ok=False,
                    motor="CONFIRMACAO-CRITICA",
                    acao="falta_pin",
                    mensagem=f"⚠️ Por segurança, digite o PIN junto: CONFIRMAR {self.acao_pendente.token}",
                )
            return AgentResponse(ok=False, motor="CONFIRMACAO-CRITICA", acao="sem_pendencia", mensagem="ℹ️ Não há operação crítica pendente.")

        # 2. Hard-Lock permanente (FSDELETE / FSDOWNLOAD)
        bloqueio = self._checar_hard_lock(norm)
        if bloqueio is not None:
            return bloqueio

        ip_alvo = _extrair_ip_alvo(texto, ip_padrao)

        # 3. Nível 2 — Operações Críticas Controladas (nunca executam sem PIN!)
        critico_resp = self._resolver_critico_local(texto, ip_alvo, community)
        if critico_resp is not None:
            return critico_resp

        # 4. Nível 0/1 — Motor A (Local Offline, instantâneo)
        resolvido = self._resolver_local(texto, ip_alvo, community)
        if resolvido is not None:
            nome_tool, kwargs = resolvido
            return self._executar_ferramenta_whitelist(nome_tool, kwargs, motor="LOCAL-OFFLINE")

        # 5. Motor B (Gemini API na nuvem, se ativado e com chave)
        self.recarregar_config()
        if self.config.get("usar_llm") and self.config.get("api_key"):
            return self._chamar_gemini_cloud(texto, ip_alvo, community)

        return AgentResponse(
            ok=False,
            motor="LOCAL-OFFLINE",
            acao="nao_reconhecido",
            mensagem=(
                f"🤔 Não reconheci o comando '{texto}' no modo Offline.\n"
                "• Digite 'ajuda' para ver todos os comandos diretos suportados.\n"
                "• Ou ative o modo '☁️ Híbrido + Gemini API' para perguntas livres."
            ),
        )
