"""
============================================================
TERMINAL TI — AGENTE HÍBRIDO BLINDADO (ANTI-BRICK)
(core/agent.py)
============================================================

Arquitetura em 2 Motores:
- Motor A (Offline Local, 0% CPU, <5ms): interpreta comandos em português
  para operações de bancada diretamente via Whitelist fechada (safe_tools.py).
- Motor B (Gemini API na Nuvem, Opcional): acionado apenas quando o técnico
  configura uma chave API do Google AI Studio e faz perguntas complexas ou
  diagnósticos abertos. Também restrito ESTRITAMENTE à mesma Whitelist Anti-Brick.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import unicodedata

import requests

from core.safe_tools import BOTOES_HOME_ALIASES, SAFE_TOOL_REGISTRY

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT_DIR / "config_agente.json"

# Palavras-chave de zona proibida (Hard-Lock Anti-Brick)
TERMOS_BLOQUEADOS_ANTI_BRICK = [
    ("firmware", "Atualização de firmware (.fls/.bin) é bloqueada no Agente por segurança Anti-Brick."),
    (".fls", "Envio de arquivo .fls é bloqueado no Agente por segurança Anti-Brick."),
    (".bin", "Envio de binário de firmware é bloqueado no Agente por segurança Anti-Brick."),
    ("nvram", "Apagar/manipular NVRAM diretamente é bloqueado no Agente por segurança Anti-Brick."),
    ("wipe", "Limpeza de disco / Out-of-Service Wipe é bloqueada no Agente por segurança Anti-Brick."),
    ("fora de servico", "Modo Fora de Serviço (Wipe) é bloqueado no Agente por segurança Anti-Brick."),
    ("formatar disco", "Formatação de disco/flash é bloqueada no Agente por segurança Anti-Brick."),
    ("padrao de fabrica", "Restauração de padrões de fábrica é bloqueada no Agente (risco de perda de rede/IP)."),
    ("padroes de fabrica", "Restauração de padrões de fábrica é bloqueada no Agente (risco de perda de rede/IP)."),
    ("factory reset", "Factory reset é bloqueado no Agente por segurança."),
    ("reset de fabrica", "Reset de fábrica é bloqueado no Agente por segurança."),
    ("ip estatico", "Alteração de IP estático é bloqueada no Agente para evitar perda de acesso à impressora."),
    ("mudar ip", "Alteração de IP é bloqueada no Agente para evitar perda de acesso à impressora."),
    ("fsdelete", "Comandos de escrita/exclusão no sistema de arquivos PJL são bloqueados (Anti-Brick)."),
    ("fsdownload", "Comandos de escrita no sistema de arquivos PJL são bloqueados (Anti-Brick)."),
]


@dataclass
class AgentResponse:
    ok: bool
    motor: str  # "ANTI-BRICK" | "LOCAL-OFFLINE" | "GEMINI-CLOUD"
    acao: str
    mensagem: str
    dados: Optional[Dict[str, Any]] = None


def _normalizar(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def carregar_config_agente() -> Dict[str, Any]:
    padrao = {
        "usar_llm": False,
        "api_key": "",
        "modelo_gemini": "gemini-2.5-flash",
    }
    if CONFIG_PATH.is_file():
        try:
            dados = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                padrao.update(dados)
        except Exception:
            pass
    return padrao


def salvar_config_agente(api_key: str, usar_llm: bool, modelo_gemini: str = "gemini-2.5-flash") -> None:
    payload = {
        "usar_llm": bool(usar_llm),
        "api_key": str(api_key or "").strip(),
        "modelo_gemini": str(modelo_gemini or "gemini-2.5-flash").strip() or "gemini-2.5-flash",
    }
    CONFIG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _extrair_ip_alvo(texto_original: str, ip_padrao: str) -> str:
    # 1. IPv4 completo no texto
    m_full = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", texto_original)
    if m_full:
        return m_full.group(1)

    # 2. Abreviação do último octeto (ex.: "na 134", "da 134", "impressora 134", "ip 134")
    m_curto = re.search(r"\b(?:na|da|em|para|ip|impressora|maquina)\s+(\d{1,3})\b", _normalizar(texto_original))
    if m_curto and ip_padrao and ip_padrao.count(".") == 3:
        octeto = int(m_curto.group(1))
        if 1 <= octeto <= 254:
            prefixo = ".".join(ip_padrao.split(".")[:3])
            return f"{prefixo}.{octeto}"

    return ip_padrao


def _extrair_texto_aspas(texto_original: str) -> Optional[str]:
    m = re.search(r'["\']([^"\']{1,60})["\']', texto_original)
    if m:
        return m.group(1).strip()
    return None


def _texto_ajuda() -> str:
    return (
        "🤖 COMANDOS QUE EU ENTENDO (100% OFFLINE E ANTI-BRICK):\n"
        "• Diagnóstico completo : 'status', 'como está a 134?', 'quanto tem de toner?', 'contador de páginas'\n"
        "• Modo do Scanner (MFP): 'ver modo do scanner', 'desativar scanner', 'desativar adf', 'ativar scanner'\n"
        "• Visor LCD            : 'coloca \"MANUTENCAO TI\" no visor', 'limpar visor'\n"
        "• Tela Inicial (Botões): 'ver tela inicial', 'modo corporativo', 'modo smartphone',\n"
        "                         'ocultar fax', 'mostrar email', 'deixar só cópia e usb'\n"
        "• Relatório Zero-Driver: 'imprimir relatório de bancada', 'imprimir página de teste'\n"
        "• Impressão Segura     : 'papel A4', 'papel carta', 'ativar duplex', 'desativar duplex',\n"
        "                         'ligar modo eco', 'densidade 4'\n"
        "• Rede & Auditoria     : 'varrer rede', 'testar portas', 'variáveis pjl jam', 'limpar avisos'\n"
        "\n🛡️ Blindagem Anti-Brick: firmware, wipe, NVRAM, factory reset e troca de IP são bloqueados no agente."
    )


class TerminalTIAgent:
    """Orquestrador Híbrido (Motor A Local Offline + Motor B Gemini Cloud Opcional)."""

    def __init__(self):
        self.config = carregar_config_agente()

    def recarregar_config(self) -> Dict[str, Any]:
        self.config = carregar_config_agente()
        return self.config

    def _checar_anti_brick(self, norm: str) -> Optional[AgentResponse]:
        for termo, motivo in TERMOS_BLOQUEADOS_ANTI_BRICK:
            if termo in norm:
                return AgentResponse(
                    ok=False,
                    motor="ANTI-BRICK",
                    acao="BLOQUEADO",
                    mensagem=(
                        f"🛡️ AÇÃO BLOQUEADA PELA BLINDAGEM ANTI-BRICK\n"
                        f"• Motivo: {motivo}\n"
                        f"• Para proteger o equipamento contra brick ou perda de acesso na rede, "
                        f"o Agente só executa operações seguras e reversíveis da Whitelist.\n"
                        f"• Se realmente precisar dessa operação crítica, faça manualmente na aba correspondente."
                    ),
                )
        return None

    def _resolver_local(
        self,
        texto_original: str,
        ip: str,
        community: str,
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Motor A — Interpretador determinístico ultra-leve (0% CPU, 100% offline).
        Retorna (nome_ferramenta_whitelist, kwargs) ou None se não casar diretamente.
        """
        norm = _normalizar(texto_original)

        # 0. Ajuda
        if norm in ("ajuda", "help", "?", "comandos") or "o que voce faz" in norm or "quais comandos" in norm:
            return ("__ajuda__", {})

        # 1. Varredura de rede Lexmark
        if any(k in norm for k in ("varrer rede", "varre a rede", "buscar lexmark", "achar impressora", "achar lexmark", "descobrir impressora", "listar impressoras")):
            return ("escanear_rede_lexmark", {"ip_referencia": ip, "community": community})

        # 2. Verificar portas / ping
        if any(k in norm for k in ("testar porta", "escanear porta", "scan de porta", "ver portas", "portas abertas", "dar ping", "pingar", "ping ")):
            return ("verificar_portas", {"ip": ip})

        # 3. Relatório de bancada / Página de teste (Zero Driver 9100)
        if any(k in norm for k in ("imprim", "folha de teste", "pagina de teste", "relatorio de bancada", "relatorio tecnico")) and any(
            k in norm for k in ("relatorio", "teste", "bancada", "diagnostico", "folha")
        ):
            titulo = _extrair_texto_aspas(texto_original) or "RELATORIO DE BANCADA - TERMINAL TI"
            return ("imprimir_relatorio_bancada", {"ip": ip, "titulo": titulo, "community": community})

        # 4. Controle validado do Modo do Scanner (MFP)
        if "scanner" in norm or "adf" in norm:
            if any(k in norm for k in ("desativar adf", "desligar adf", "desabilitar adf", "sem adf", "so mesa plana", "somente mesa plana")):
                return ("definir_modo_scanner", {"ip": ip, "modo": "2"})
            if any(k in norm for k in ("desativar scanner", "desligar scanner", "desabilitar scanner", "sem scanner", "so impressora", "desativa o scanner", "desliga o scanner")):
                return ("definir_modo_scanner", {"ip": ip, "modo": "1"})
            if any(k in norm for k in ("ativar scanner", "ligar scanner", "habilitar scanner", "reativar scanner", "ativa o scanner", "liga o scanner", "ativar adf", "ligar adf")):
                return ("definir_modo_scanner", {"ip": ip, "modo": "0"})
            if any(k in norm for k in ("ver", "ler", "qual", "status", "estado", "modo", "checar", "verificar", "como esta")):
                return ("ler_modo_scanner", {"ip": ip})

        # 5. Visor LCD (RDYMSG DISPLAY)
        if any(k in norm for k in ("visor", "display", "mensagem")):
            if any(k in norm for k in ("limp", "restaur", "voltar pronto", "padrao", "apagar mensagem", "tirar mensagem")):
                return ("alterar_visor_lcd", {"ip": ip, "texto": ""})
            msg_aspas = _extrair_texto_aspas(texto_original)
            if msg_aspas is not None:
                return ("alterar_visor_lcd", {"ip": ip, "texto": msg_aspas})
            # Tenta capturar após "para ..." ou "como ..."
            m_para = re.search(r"(?:para|como|:)\s+(.+)$", texto_original, re.I)
            if m_para and any(k in norm for k in ("coloc", "escrev", "mud", "alter", "defin", "exib", "mostr", "bot")):
                candidato = m_para.group(1).strip().strip("\"'")
                if candidato:
                    return ("alterar_visor_lcd", {"ip": ip, "texto": candidato})

        # 6. Limpar avisos
        if "limpar aviso" in norm or "limpa aviso" in norm or "clear warning" in norm:
            return ("limpar_avisos_painel", {"ip": ip})

        # 7. Tela Inicial (botões / presets)
        if any(k in norm for k in ("tela inicial", "home", "botoes", "botao", "icone", "modo smartphone", "modo corporativo", "fax", "email", "e-mail", "pendrive")):
            if "smartphone" in norm:
                return ("configurar_tela_inicial", {"ip": ip, "preset": "smartphone"})
            if "corporativo" in norm:
                return ("configurar_tela_inicial", {"ip": ip, "preset": "corporativo"})
            if any(k in norm for k in ("mostrar todos", "ativar todos", "todos os botoes")):
                return ("configurar_tela_inicial", {"ip": ip, "preset": "todos"})
            if any(k in norm for k in ("ocultar todos", "esconder todos", "nenhum botao")):
                return ("configurar_tela_inicial", {"ip": ip, "preset": "nenhum"})

            # Detecta "deixar só X e Y"
            if any(k in norm for k in ("deixar so", "deixa so", "apenas ", "somente ")):
                encontrados = []
                for alias in sorted(BOTOES_HOME_ALIASES.keys(), key=len, reverse=True):
                    if re.search(rf"\b{re.escape(alias)}\b", norm):
                        encontrados.append(alias)
                if encontrados:
                    return ("configurar_tela_inicial", {"ip": ip, "manter_apenas": encontrados})

            # Detecta ocultar / mostrar botões específicos
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

        # 8. Configurações seguras de impressão (Papel / Duplex / Eco / Densidade)
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

        # 9. Variáveis PJL (somente leitura)
        if "variaveis pjl" in norm or "variavel pjl" in norm or "info variables" in norm:
            m_f = re.search(r"(?:pjl|variables)\s+([a-z0-9_]+)", norm)
            filtro = m_f.group(1) if m_f else ""
            return ("ler_variaveis_pjl", {"ip": ip, "filtro": filtro})

        # 10. Diagnóstico geral / status / toner / contador / serial
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
                "paginas",
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

        if nome not in SAFE_TOOL_REGISTRY:
            return AgentResponse(
                ok=False,
                motor="ANTI-BRICK",
                acao=nome,
                mensagem=f"🛡️ Ferramenta '{nome}' não pertence à Whitelist Anti-Brick e foi recusada.",
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
        Motor B — Consulta leve via REST HTTPS para Gemini na nuvem (zero CPU local).
        Só permite responder em texto OU escolher uma ferramenta da Whitelist fechada.
        """
        api_key = str(self.config.get("api_key") or "").strip()
        modelo = str(self.config.get("modelo_gemini") or "gemini-2.5-flash").strip()
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
FERRAMENTAS PERMITIDAS (WHITELIST ANTI-BRICK):
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
"""

        prompt_sistema = (
            "Você é o Agente Técnico do Terminal TI para impressoras Lexmark.\n"
            f"IP alvo atual: {ip} | Comunidade SNMP: {community}.\n"
            f"{ferramentas_desc}\n"
            "REGRA ESTRITA: Responda EXCLUSIVAMENTE um JSON válido sem markdown:\n"
            '- Para executar uma ferramenta da whitelist: {"tipo": "tool", "tool": "<nome>", "args": {...}}\n'
            '- Para apenas responder/orientar o técnico: {"tipo": "texto", "resposta": "<texto em português>"}\n'
            "NUNCA invente ferramentas fora da lista. NUNCA sugira comandos destrutivos."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
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
            r = requests.post(url, json=payload, timeout=20)
            r.raise_for_status()
            data = r.json()
            txt_json = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            parsed = json.loads(txt_json)
        except Exception as err:
            return AgentResponse(
                ok=False,
                motor="GEMINI-CLOUD",
                acao="erro_api",
                mensagem=f"❌ Falha ao consultar Gemini API na nuvem: {err}",
            )

        if parsed.get("tipo") == "tool":
            tool_name = str(parsed.get("tool") or "").strip()
            args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
            if "ip" not in args and tool_name != "escanear_rede_lexmark":
                args["ip"] = ip
            if tool_name == "escanear_rede_lexmark" and "ip_referencia" not in args:
                args["ip_referencia"] = ip
            return self._executar_ferramenta_whitelist(tool_name, args, motor="GEMINI-CLOUD")

        return AgentResponse(
            ok=True,
            motor="GEMINI-CLOUD",
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
        Ponto único de entrada para executar comandos escritos pelo técnico.
        Fluxo: Anti-Brick -> Motor A (Local Offline) -> Motor B (Gemini Cloud se ativo).
        """
        texto = str(texto_usuario or "").strip()
        if not texto:
            return AgentResponse(ok=False, motor="LOCAL-OFFLINE", acao="vazio", mensagem="Digite um comando (ex.: 'status' ou 'ajuda').")

        norm = _normalizar(texto)

        # 1. Camada Anti-Brick (sempre primeiro!)
        bloqueio = self._checar_anti_brick(norm)
        if bloqueio is not None:
            return bloqueio

        ip_alvo = _extrair_ip_alvo(texto, ip_padrao)

        # 2. Motor A (Local Offline, instantâneo)
        resolvido = self._resolver_local(texto, ip_alvo, community)
        if resolvido is not None:
            nome_tool, kwargs = resolvido
            return self._executar_ferramenta_whitelist(nome_tool, kwargs, motor="LOCAL-OFFLINE")

        # 3. Motor B (Gemini API na nuvem, se ativado e com chave)
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
                "• Ou ative o modo '☁️ Híbrido + Gemini API' para perguntas livres e raciocínio assistido."
            ),
        )
