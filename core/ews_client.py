"""
============================================================
TERMINAL TI — MOTOR EWS HTTP/CGI LEXMARK (core/ews_client.py)
============================================================

Responsável por ler e gravar configurações reais na NVRAM da
impressora Lexmark usando os mesmos formulários HTTP/CGI do EWS
(/cgi-bin/dynamic/... e /cgi-bin/posttest/... ou /cgi-bin/postpf/...),
sem depender apenas da porta 9100.
"""

from __future__ import annotations

from html.parser import HTMLParser
import io
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests


class _EWSHTMLFormParser(HTMLParser):
    """
    Parser HTML nativo (biblioteca padrão Python, sem depender de BeautifulSoup/bs4)
    para extrair o primeiro <form>, seus atributos action/method e todos os
    campos <input>, <select>/<option> e <textarea>.
    """

    def __init__(self):
        super().__init__()
        self.in_form = False
        self.form_found = False
        self.action = ""
        self.method = "POST"
        self.pares: List[Tuple[str, str]] = []
        self.mapa_valores: Dict[str, str] = {}

        self._cur_select_name: Optional[str] = None
        self._cur_select_options: List[Tuple[str, bool]] = []
        self._in_textarea: Optional[str] = None
        self._textarea_buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        t = tag.lower()
        attr_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        attr_names = {k.lower() for k, _ in attrs}

        if t == "form" and not self.form_found:
            self.in_form = True
            self.form_found = True
            self.action = attr_dict.get("action", "").strip()
            self.method = (attr_dict.get("method") or "POST").upper()
            return

        if not self.in_form:
            return

        if t == "select":
            name = attr_dict.get("name", "").strip()
            if name:
                self._cur_select_name = name
                self._cur_select_options = []

        elif t == "option" and self._cur_select_name:
            val = attr_dict.get("value", "")
            selected = "selected" in attr_names
            self._cur_select_options.append((val, selected))

        elif t == "textarea":
            name = attr_dict.get("name", "").strip()
            if name:
                self._in_textarea = name
                self._textarea_buf = []

        elif t == "input":
            name = attr_dict.get("name", "").strip()
            if not name:
                return
            itype = (attr_dict.get("type") or "text").lower()
            if itype in ("submit", "reset", "button", "file", "image"):
                return
            val_in = attr_dict.get("value", "")
            if itype == "checkbox":
                checked = "checked" in attr_names
                if checked:
                    self.pares.append((name, val_in or "1"))
                    self.mapa_valores[name] = "1"
                else:
                    if name not in self.mapa_valores:
                        self.mapa_valores[name] = "0"
            elif itype == "radio":
                if "checked" in attr_names:
                    self.pares.append((name, val_in))
                    self.mapa_valores[name] = val_in
            else:
                self.pares.append((name, val_in))
                if itype != "hidden" or name not in self.mapa_valores:
                    self.mapa_valores[name] = val_in

    def handle_data(self, data: str):
        if self._in_textarea is not None:
            self._textarea_buf.append(data)

    def handle_endtag(self, tag: str):
        t = tag.lower()
        if t == "form" and self.in_form:
            self.in_form = False
        elif t == "select" and self._cur_select_name:
            val_sel = ""
            for val, is_sel in self._cur_select_options:
                if is_sel:
                    val_sel = val
                    break
            if not val_sel and self._cur_select_options:
                val_sel = self._cur_select_options[0][0]
            self.pares.append((self._cur_select_name, val_sel))
            self.mapa_valores[self._cur_select_name] = val_sel
            self._cur_select_name = None
            self._cur_select_options = []
        elif t == "textarea" and self._in_textarea is not None:
            texto = "".join(self._textarea_buf)
            self.pares.append((self._in_textarea, texto))
            self.mapa_valores[self._in_textarea] = texto
            self._in_textarea = None
            self._textarea_buf = []


class EWSClientError(Exception):
    """Erro controlado na comunicação HTTP/EWS com a impressora."""
    pass


class LexmarkEWSClient:
    """
    Cliente HTTP/CGI para leitura e gravação direta nas páginas de
    configuração EWS das impressoras Lexmark (famílias MS/MX/CS/CX).
    """

    def __init__(self, ip: str, timeout: int = 12):
        self.ip = str(ip).strip()
        self.base_url = f"http://{self.ip}"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "TerminalTI-Engineering/2.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return urljoin(self.base_url + "/", path.lstrip("/"))

    @staticmethod
    def _decodificar(resp: requests.Response) -> str:
        raw = resp.content
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("iso-8859-1", errors="replace")

    def ler_formulario(self, dynamic_path: str) -> Tuple[str, str, List[Tuple[str, str]], Dict[str, str]]:
        """
        Faz GET na página dinâmica do EWS, extrai o <form>, seu action,
        a lista ordenada de pares (name, value) atuais e um dicionário
        {name: current_value} para sincronizar a interface.
        """
        url = self._url(dynamic_path)
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as erro:
            raise EWSClientError(f"Falha ao acessar {url}: {erro}") from erro

        html = self._decodificar(resp)
        parser = _EWSHTMLFormParser()
        parser.feed(html)
        if not parser.form_found:
            raise EWSClientError(f"Nenhum formulário encontrado em {dynamic_path}")

        action_raw = (parser.action or dynamic_path).strip()
        action_url = urljoin(url, action_raw)
        method = parser.method

        return action_url, method, parser.pares, parser.mapa_valores

    def gravar_campos_formulario(
        self,
        dynamic_path: str,
        alteracoes: Dict[str, str],
        post_fallback_path: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Lê o formulário atual da impressora em `dynamic_path`, mescla as
        `alteracoes` (preservando os demais campos da página para não zerar nada)
        e envia o POST para a controladora.
        """
        try:
            action_url, method, pares_atuais, _ = self.ler_formulario(dynamic_path)
        except Exception:
            action_url = self._url(post_fallback_path or dynamic_path)
            method = "POST"
            pares_atuais = []

        # Reconstrói o payload tratando checkboxes Lexmark (hidden 0 + checkbox 1)
        nomes_alterados = set(alteracoes.keys())
        novo_payload: List[Tuple[str, str]] = []
        ja_inseridos = set()

        for nome, valor in pares_atuais:
            if nome in nomes_alterados:
                if nome not in ja_inseridos:
                    novo_val = str(alteracoes[nome])
                    if nome.startswith("2.system."):
                        novo_payload.append((nome, "0"))
                        if novo_val in ("1", "true", "True", "on"):
                            novo_payload.append((nome, "1"))
                    else:
                        novo_payload.append((nome, novo_val))
                    ja_inseridos.add(nome)
            else:
                novo_payload.append((nome, valor))

        for nome, valor in alteracoes.items():
            if nome not in ja_inseridos:
                novo_val = str(valor)
                if nome.startswith("2.system."):
                    novo_payload.append((nome, "0"))
                    if novo_val in ("1", "true", "True", "on"):
                        novo_payload.append((nome, "1"))
                else:
                    novo_payload.append((nome, novo_val))
                ja_inseridos.add(nome)

        try:
            if method == "GET":
                resp = self.session.get(action_url, params=novo_payload, timeout=self.timeout)
            else:
                resp = self.session.post(action_url, data=novo_payload, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as erro:
            raise EWSClientError(f"Erro ao gravar em {action_url}: {erro}") from erro

        return {
            "url": action_url,
            "status_code": str(resp.status_code),
            "campos_gravados": ", ".join(f"{k}={v}" for k, v in alteracoes.items()),
        }

    def gravar_ip_estatico(self, novo_ip: str, mascara: str, gateway: str) -> Dict[str, str]:
        """
        Envia a configuração de IP estático no formato esperado por
        /cgi-bin/postpf/cgi-bin/dynamic/config/net/ipsettings.html
        (onde cada octeto é enviado como campo 'A').
        """
        def _octetos(endereco: str) -> List[str]:
            partes = [p.strip() for p in endereco.strip().split(".")]
            if len(partes) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in partes):
                raise EWSClientError(f"Endereço IPv4 inválido: {endereco}")
            return partes

        ip_oct = _octetos(novo_ip)
        mask_oct = _octetos(mascara)
        gw_oct = _octetos(gateway)

        payload: List[Tuple[str, str]] = [
            ("PT_IPADDR", ""),
            ("vac.255.IPADDRESS", ""),
            ("A", "0"), ("A", "0"), ("A", "0"), ("A", "0"),
            ("PT_IPADDR", ""),
            ("vac.255.IPADDRESS", ""),
            ("A", ip_oct[0]), ("A", ip_oct[1]), ("A", ip_oct[2]), ("A", ip_oct[3]),
            ("PT_IPADDR", ""),
            ("vac.255.IPNETMASK", ""),
            ("A", mask_oct[0]), ("A", mask_oct[1]), ("A", mask_oct[2]), ("A", mask_oct[3]),
            ("PT_IPADDR", ""),
            ("vac.255.IPGATEWAY", ""),
            ("A", gw_oct[0]), ("A", gw_oct[1]), ("A", gw_oct[2]), ("A", gw_oct[3]),
        ]

        url = self._url("/cgi-bin/postpf/cgi-bin/dynamic/config/net/ipsettings.html")
        try:
            resp = self.session.post(url, data=payload, timeout=self.timeout)
            resp.raise_for_status()
            return {"url": url, "status_code": str(resp.status_code)}
        except Exception as erro:
            raise EWSClientError(f"Erro ao definir IP estático: {erro}") from erro

    def enviar_papel_parede(self, caminho_imagem: str, redimensionar: bool = True) -> Dict[str, str]:
        """
        Envia uma imagem de fundo (Wallpaper) para o LCD da impressora
        via /cgi-bin/dynamic/printer/config/gen/gen_custombackground.html.
        Redimensiona automaticamente para 800x414 (<= 128 KB) como Baseline RGB
        (progressive=False, subsampling=0), preservando proporções e canal alfa.
        """
        arq = Path(caminho_imagem)
        if not arq.is_file():
            raise EWSClientError(f"Arquivo de imagem não encontrado: {arq}")

        nome_envio = arq.name
        conteudo_bytes = arq.read_bytes()
        mime_type = "image/jpeg"

        if redimensionar:
            try:
                from PIL import Image
                src = Image.open(arq)
                target_w, target_h = 800, 414

                # Cria tela 800x414 com fundo branco (ou neutro) para evitar fundo preto em PNGs transparentes
                canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))

                # Redimensiona mantendo proporção original (aspect ratio)
                scale = min((target_w - 40) / src.width, (target_h - 40) / src.height)
                nw = max(1, int(src.width * scale))
                nh = max(1, int(src.height * scale))
                resized = src.resize((nw, nh), getattr(Image, "Resampling", Image).LANCZOS)

                offset_x = (target_w - nw) // 2
                offset_y = (target_h - nh) // 2

                if resized.mode in ("RGBA", "LA") or (resized.mode == "P" and "transparency" in resized.info):
                    rgba_img = resized.convert("RGBA")
                    canvas.paste(rgba_img, (offset_x, offset_y), mask=rgba_img.split()[-1])
                else:
                    canvas.paste(resized.convert("RGB"), (offset_x, offset_y))

                buf = io.BytesIO()
                qualidade = 90
                while qualidade >= 35:
                    buf.seek(0)
                    buf.truncate(0)
                    # Baseline JPEG estrito: progressive=False, subsampling=0
                    canvas.save(buf, format="JPEG", quality=qualidade, progressive=False, subsampling=0, optimize=True)
                    if buf.tell() <= 125 * 1024:
                        break
                    qualidade -= 10

                conteudo_bytes = buf.getvalue()
                nome_envio = arq.stem + "_800x414.jpeg"
            except ImportError:
                pass

        url = self._url("/cgi-bin/dynamic/printer/config/gen/gen_custombackground.html")
        try:
            # 1. GET preparatório na sessão para inicializar cookies e conexão
            self.session.get(url, timeout=self.timeout)

            # 2. Upload multipart do arquivo.
            # Nota técnica: a controladora Lexmark NÃO aceita campos textuais como 'Background.Add'
            # no corpo do formulário multipart simultaneamente ao arquivo (retorna 'Tipo de imagem inválido').
            files = {
                "input_file": (nome_envio, conteudo_bytes, mime_type),
            }
            resp = self.session.post(url, files=files, timeout=30)
            resp.raise_for_status()

            if "Form Error" in resp.text:
                m_err = re.search(r'<H2>(.*?)</H2>', resp.text, re.DOTALL | re.IGNORECASE)
                msg_err = m_err.group(1).strip() if m_err else "Arquivo rejeitado pelo painel"
                raise EWSClientError(f"A impressora rejeitou a imagem: {msg_err}")

            if "Arquivo recebido" not in resp.text and "<img" not in resp.text:
                raise EWSClientError("Resposta inesperada da impressora ao enviar imagem de fundo.")

            return {
                "url": url,
                "status_code": str(resp.status_code),
                "bytes": str(len(conteudo_bytes)),
                "arquivo": nome_envio,
                "resultado": "Arquivo recebido e instalado com sucesso no painel",
            }
        except Exception as erro:
            raise EWSClientError(f"Falha ao enviar papel de parede: {erro}") from erro

    def exportar_configuracao_ucf(self, tipo: str = "settingfile.ucf") -> bytes:
        """
        Exporta o pacote de configuração (.ucf) da impressora:
        - settingfile.ucf (Configurações gerais)
        - shortcuts.ucf (Atalhos)
        - settingfileesf.ucf (Soluções incorporadas / eSF)
        """
        url_page = self._url("/cgi-bin/dynamic/printer/config/gen/importexport.html")
        csrf_val = ""
        try:
            r_page = self.session.get(url_page, timeout=self.timeout)
            m = re.search(r'name="csrf_token"\s+value="([^"]*)"', r_page.text, re.I)
            if m:
                csrf_val = m.group(1)
        except Exception:
            pass

        url_export = self._url(f"/cgi-bin/exportfile/printer/config/secure/{tipo}")
        try:
            resp = self.session.post(
                url_export,
                data={"csrf_token": csrf_val} if csrf_val else {},
                timeout=25,
            )
            resp.raise_for_status()
            return resp.content
        except Exception as erro:
            raise EWSClientError(f"Não foi possível exportar {tipo}: {erro}") from erro

    def importar_configuracao_ucf(self, caminho_ucf: str, endpoint: str = "importsettings.html") -> Dict[str, str]:
        """
        Importa um arquivo .ucf ou .xml de configuração/atalhos para a impressora.
        """
        arq = Path(caminho_ucf)
        if not arq.is_file():
            raise EWSClientError(f"Arquivo não encontrado: {arq}")

        url = self._url(f"/cgi-bin/dynamic/printer/config/secure/{endpoint}")
        csrf_val = ""
        try:
            r_get = self.session.get(url, timeout=self.timeout)
            m = re.search(r'name="csrf_token"\s+value="([^"]*)"', r_get.text, re.I)
            if m:
                csrf_val = m.group(1)
        except Exception:
            pass

        files = {
            "input_file": (arq.name, arq.read_bytes(), "application/octet-stream"),
        }
        data = {"csrf_token": csrf_val}
        try:
            resp = self.session.post(url, files=files, data=data, timeout=60)
            resp.raise_for_status()
            return {"url": url, "status_code": str(resp.status_code), "arquivo": arq.name}
        except Exception as erro:
            raise EWSClientError(f"Falha ao importar arquivo {arq.name}: {erro}") from erro

    def enviar_firmware_http(self, caminho_fls: str) -> Dict[str, str]:
        """
        Envia arquivo de atualização de firmware (.fls / .bin) pelo endpoint HTTP
        oficial do EWS (/cgi-bin/postpf/cgi-bin/dynamicpf/pf/config/gen/code_update.html).
        """
        arq = Path(caminho_fls)
        if not arq.is_file():
            raise EWSClientError(f"Arquivo de firmware não encontrado: {arq}")

        url = self._url("/cgi-bin/postpf/cgi-bin/dynamicpf/pf/config/gen/code_update.html")
        with open(arq, "rb") as fp:
            files = {"code_update": (arq.name, fp, "application/octet-stream")}
            try:
                resp = self.session.post(url, files=files, timeout=300)
                resp.raise_for_status()
                return {"url": url, "status_code": str(resp.status_code), "arquivo": arq.name}
            except Exception as erro:
                raise EWSClientError(f"Erro no envio HTTP de firmware: {erro}") from erro

    def restaurar_padroes_fabrica(self, escopo: str = "base") -> Dict[str, str]:
        """
        Restaura padrões de fábrica via EWS:
        escopo: 'base' (Definições da impressora), 'network' (Rede), 'les' (Apps)
        """
        url = self._url("/cgi-bin/dynamic/printer/config/secure/restore_factory_settings.html")
        try:
            resp = self.session.post(url, data={"option": escopo}, timeout=self.timeout)
            resp.raise_for_status()
            return {"url": url, "status_code": str(resp.status_code), "escopo": escopo}
        except Exception as erro:
            raise EWSClientError(f"Falha ao restaurar padrões ({escopo}): {erro}") from erro

    def apagar_memoria_nvram(self) -> Dict[str, str]:
        """
        Aciona limpeza de memória da impressora (/cgi-bin/dynamic/printer/config/secure/erase_printer_memory.html).
        """
        url = self._url("/cgi-bin/dynamic/printer/config/secure/erase_printer_memory.html")
        try:
            resp = self.session.post(url, data={"confirm": "confirm"}, timeout=self.timeout)
            resp.raise_for_status()
            return {"url": url, "status_code": str(resp.status_code)}
        except Exception as erro:
            raise EWSClientError(f"Falha ao acionar limpeza de memória: {erro}") from erro

    def apagar_fora_de_servico_wipe(self) -> Dict[str, str]:
        """
        Aciona o 'Apagar fora de serviço' (/cgi-bin/dynamic/printer/config/secure/memwipe.html):
        limpa memória volátil e não volátil (NVRAM completa) e reinicia no assistente de fábrica.
        """
        url = self._url("/cgi-bin/dynamic/printer/config/secure/memwipe.html")
        try:
            resp = self.session.post(url, data={"confirm": "confirm"}, timeout=self.timeout)
            resp.raise_for_status()
            return {"url": url, "status_code": str(resp.status_code)}
        except Exception as erro:
            raise EWSClientError(f"Falha ao acionar Wipe Fora de Serviço: {erro}") from erro
