"""
============================================================
TERMINAL TI — CENTRAL DE ENGENHARIA E BANCADA LEXMARK
(interface/app_window.py)
============================================================
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import webbrowser

from core.agent import (
    TerminalTIAgent,
    carregar_config_agente,
    salvar_config_agente,
    testar_chave_gemini,
)
from core.catalog import (
    CONFIG_MF_OPCOES,
    DICIONARIO_COMANDOS,
    HIBERNACAO_OPCOES,
    ICONES_HOME_CAMPOS,
    IDIOMA_OPCOES,
    MIDIAS_PESO_CAMPOS,
    MIDIAS_TEXTURA_CAMPOS,
    MODO_ECO_OPCOES,
    MODO_SCANNER_OPCOES,
    ORIGEM_PADRAO_OPCOES,
    PESO_OPCOES,
    RECUPERACAO_ATOLAMENTO_OPCOES,
    RESOLUCAO_OPCOES,
    SUBSTITUIR_TAMANHO_OPCOES,
    TAMANHO_PAPEL_OPCOES,
    TEXTURA_OPCOES,
    TIPO_PAPEL_OPCOES,
    TONALIDADE_TONER_OPCOES,
)
from core.ews_client import EWSClientError, LexmarkEWSClient
from core.pjl_snmp_client import (
    enviar_pjl,
    escanear_portas_impressora,
    executar_ping,
    injetar_arquivo_raw,
    injetar_xml_vcc,
    snmp_get,
    snmp_set,
)
from core.safe_tools import definir_modo_scanner, imprimir_relatorio_bancada, ler_modo_scanner


def _chave_por_valor(mapa: dict, valor: str, padrao: str = "") -> str:
    for k, v in mapa.items():
        if str(v) == str(valor):
            return k
    return padrao or next(iter(mapa.keys()), "")


class ToolTip:
    """Tooltip informativo escuro exibido ao passar o mouse sobre botões e campos."""

    def __init__(self, widget, texto: str):
        self.widget = widget
        self.texto = texto
        self.tipwindow = None
        self.widget.bind("<Enter>", self._mostrar)
        self.widget.bind("<Leave>", self._esconder)

    def _mostrar(self, event=None):
        if self.tipwindow or not self.texto:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            tw,
            text=self.texto,
            justify="left",
            background="#161b22",
            foreground="#79c0ff",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9),
            padx=8,
            pady=5,
            wraplength=380,
        )
        lbl.pack()

    def _esconder(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class TerminalTIApp:
    """
    Interface Principal do Terminal TI (funciona tanto como aplicação
    standalone tk.Tk quanto como janela tk.Toplevel).
    """

    COR_FUNDO = "#0d1117"
    COR_PAINEL = "#161b22"
    COR_PAINEL_2 = "#21262d"
    COR_BORDA = "#30363d"
    COR_TEXTO = "#e6edf3"
    COR_TEXTO_SEC = "#8b949e"
    COR_DESTAQUE = "#58a6ff"
    COR_VERDE = "#3fb950"
    COR_AMARELO = "#d29922"
    COR_VERMELHO = "#f85149"

    def __init__(self, master=None, ip_inicial: str = "192.168.14.134"):
        if isinstance(master, str):
            ip_inicial = master
            master = None

        if master is None:
            self.root = tk.Tk()
            self.is_standalone = True
        else:
            self.root = tk.Toplevel(master)
            self.root.transient(master)
            self.is_standalone = False

        self.ip_alvo = ip_inicial
        self.root.title("Terminal TI — Central de Engenharia e Administração Remota Lexmark")
        self.root.geometry("1420x900")
        self.root.minsize(1150, 760)
        self.root.configure(background=self.COR_FUNDO)

        self._configurar_estilos()
        self._construir_interface()

    def mainloop(self):
        self.root.mainloop()

    # ========================================================
    # ESTILOS
    # ========================================================

    def _configurar_estilos(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TI.TFrame", background=self.COR_FUNDO)
        style.configure("TI.TLabel", background=self.COR_PAINEL, foreground=self.COR_TEXTO, font=("Segoe UI", 9))
        style.configure("TI.TNotebook", background=self.COR_FUNDO, borderwidth=0)
        style.configure(
            "TI.TNotebook.Tab",
            background=self.COR_PAINEL_2,
            foreground=self.COR_TEXTO_SEC,
            padding=[10, 6],
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TI.TNotebook.Tab",
            background=[("selected", self.COR_PAINEL)],
            foreground=[("selected", self.COR_DESTAQUE)],
        )

        style.configure(
            "TI.Primary.TButton",
            background="#1f6feb",
            foreground="#ffffff",
            bordercolor="#388bfd",
            padding=7,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TI.Primary.TButton",
            background=[("active", "#388bfd"), ("pressed", "#1158c7"), ("disabled", "#21262d")],
        )

        style.configure(
            "TI.Secondary.TButton",
            background="#21262d",
            foreground=self.COR_TEXTO,
            bordercolor=self.COR_BORDA,
            padding=6,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TI.Secondary.TButton",
            background=[("active", "#30363d"), ("pressed", "#161b22")],
        )

        style.configure(
            "TI.Danger.TButton",
            background="#da3633",
            foreground="#ffffff",
            bordercolor="#f85149",
            padding=7,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TI.Danger.TButton",
            background=[("active", "#f85149"), ("pressed", "#b62324")],
        )

        style.configure(
            "TI.TCombobox",
            fieldbackground=self.COR_PAINEL_2,
            background=self.COR_PAINEL_2,
            foreground=self.COR_TEXTO,
            arrowcolor=self.COR_TEXTO,
            bordercolor=self.COR_BORDA,
        )
        style.map(
            "TI.TCombobox",
            fieldbackground=[("readonly", self.COR_PAINEL_2)],
            foreground=[("readonly", self.COR_TEXTO)],
            selectbackground=[("readonly", "#1f6feb")],
            selectforeground=[("readonly", "#ffffff")],
        )

    # ========================================================
    # ESTRUTURA PRINCIPAL
    # ========================================================

    def _construir_interface(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # ----------------------------------------------------
        # BARRA SUPERIOR DE CONEXÃO E SINCRONIZAÇÃO
        # ----------------------------------------------------
        topo = tk.Frame(
            self.root,
            background=self.COR_PAINEL,
            padx=16,
            pady=10,
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
        )
        topo.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        topo.columnconfigure(6, weight=1)

        tk.Label(
            topo,
            text="⚡ TERMINAL TI",
            background=self.COR_PAINEL,
            foreground=self.COR_DESTAQUE,
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, padx=(0, 18))

        tk.Label(
            topo,
            text="IP do Equipamento:",
            background=self.COR_PAINEL,
            foreground=self.COR_TEXTO,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=1, padx=(0, 6))

        self.entry_ip = tk.Entry(
            topo,
            font=("Consolas", 11, "bold"),
            width=15,
            background=self.COR_PAINEL_2,
            foreground="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
        )
        self.entry_ip.insert(0, self.ip_alvo)
        self.entry_ip.grid(row=0, column=2, padx=(0, 14), ipady=3)
        ToolTip(self.entry_ip, "Endereço IPv4 da impressora na rede (ex: 192.168.14.134).")

        tk.Label(
            topo,
            text="Comunidade SNMP:",
            background=self.COR_PAINEL,
            foreground=self.COR_TEXTO_SEC,
            font=("Segoe UI", 9),
        ).grid(row=0, column=3, padx=(0, 6))

        self.combo_community = ttk.Combobox(
            topo,
            values=("public", "private", "admin"),
            width=9,
            state="readonly",
            style="TI.TCombobox",
        )
        self.combo_community.set("public")
        self.combo_community.grid(row=0, column=4, padx=(0, 14))
        ToolTip(self.combo_community, "Comunidade SNMPv2c usada nas consultas e gravações OID (porta 161 UDP).")

        self.btn_sincronizar = ttk.Button(
            topo,
            text="🔄 LER / SINCRONIZAR DA IMPRESSORA",
            command=self._sincronizar_tudo_da_maquina,
            style="TI.Primary.TButton",
        )
        self.btn_sincronizar.grid(row=0, column=5, padx=(0, 10))
        ToolTip(
            self.btn_sincronizar,
            "Conecta ao EWS da impressora via HTTP GET e carrega nas abas abaixo todas as configurações atuais "
            "(Bandejas, Ícones da Tela Inicial, Qualidade, Idioma, Tempos Limite e Rede).",
        )

        self.lbl_status_topo = tk.Label(
            topo,
            text="● Pronto para operar",
            background=self.COR_PAINEL,
            foreground=self.COR_VERDE,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.lbl_status_topo.grid(row=0, column=6, sticky="w", padx=8)

        btn_ews = ttk.Button(
            topo,
            text="🌐 Abrir EWS",
            command=lambda: webbrowser.open(f"http://{self._ip()}"),
            style="TI.Secondary.TButton",
        )
        btn_ews.grid(row=0, column=7, sticky="e", padx=(0, 6))
        ToolTip(btn_ews, "Abre a página web original da impressora no navegador padrão.")

        self.console_visivel = True
        self.btn_toggle_console = ttk.Button(
            topo,
            text="◀ Ocultar Console",
            command=self._toggle_console,
            style="TI.Secondary.TButton",
        )
        self.btn_toggle_console.grid(row=0, column=8, sticky="e")
        ToolTip(self.btn_toggle_console, "Oculta ou exibe o console lateral de logs para dar largura total aos cartões de configuração.")

        # ----------------------------------------------------
        # ÁREA CENTRAL: PANEDWINDOW (ABAS ESQUERDA + CONSOLE DIREITA)
        # ----------------------------------------------------
        corpo = tk.Frame(self.root, background=self.COR_FUNDO)
        corpo.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        corpo.columnconfigure(0, weight=1)
        corpo.rowconfigure(0, weight=1)

        self.paned = ttk.PanedWindow(corpo, orient="horizontal")
        self.paned.grid(row=0, column=0, sticky="nsew")

        # Container esquerdo para as abas
        self.frame_abas = tk.Frame(self.paned, background=self.COR_FUNDO)
        self.notebook = ttk.Notebook(self.frame_abas, style="TI.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        self._construir_aba_papel()
        self._construir_aba_tela_inicial()
        self._construir_aba_sistema_painel()
        self._construir_aba_motor_qualidade()
        self._construir_aba_rede_snmp()
        self._construir_aba_arquivos_dicionario()
        self._construir_aba_terminal_ews_raw()
        self._construir_aba_agente()

        # ----------------------------------------------------
        # CONSOLE EM TEMPO REAL COM EXPORTAÇÃO DE LOGS
        # ----------------------------------------------------
        self.console_card = tk.Frame(
            self.paned,
            background=self.COR_PAINEL,
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
        )
        self.console_card.columnconfigure(0, weight=1)
        self.console_card.rowconfigure(1, weight=1)

        barra_console = tk.Frame(self.console_card, background=self.COR_PAINEL, padx=12, pady=8)
        barra_console.grid(row=0, column=0, sticky="ew")
        barra_console.columnconfigure(0, weight=1)

        tk.Label(
            barra_console,
            text="🖥️ Console de Logs",
            background=self.COR_PAINEL,
            foreground=self.COR_TEXTO,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w")

        btn_exportar = ttk.Button(
            barra_console,
            text="💾 Salvar",
            command=self._exportar_log,
            style="TI.Secondary.TButton",
            width=8,
        )
        btn_exportar.grid(row=0, column=1, padx=(0, 4))
        ToolTip(btn_exportar, "Salva todo o histórico do console em um arquivo .txt para auditoria.")

        btn_limpar = ttk.Button(
            barra_console,
            text="🧹 Limpar",
            command=lambda: self.txt_console.delete("1.0", "end"),
            style="TI.Secondary.TButton",
            width=8,
        )
        btn_limpar.grid(row=0, column=2)

        self.txt_console = scrolledtext.ScrolledText(
            self.console_card,
            wrap="word",
            font=("Consolas", 9),
            background="#090c10",
            foreground="#3fb950",
            insertbackground="#ffffff",
            selectbackground="#1f6feb",
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=10,
        )
        self.txt_console.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self.paned.add(self.frame_abas, weight=7)
        self.paned.add(self.console_card, weight=3)

        self._log("============================================================")
        self._log(" TERMINAL TI — CENTRAL DE ENGENHARIA LEXMARK INICIADA")
        self._log(" Motores ativos: EWS HTTP/CGI + PJL RAW 9100 + SNMPv2c Nativo")
        self._log("============================================================")
        self._log(f"Alvo inicial configurado: {self.ip_alvo}")
        self._log("Dica: Clique em '🔄 LER / SINCRONIZAR DA IMPRESSORA' no topo para carregar o estado real da máquina.\n")

    # ========================================================
    # UTILITÁRIOS DE UI E LOG
    # ========================================================

    def _toggle_console(self):
        if self.console_visivel:
            self.paned.forget(self.console_card)
            self.console_visivel = False
            self.btn_toggle_console.config(text="▶ Exibir Console")
        else:
            self.paned.add(self.console_card, weight=3)
            self.console_visivel = True
            self.btn_toggle_console.config(text="◀ Ocultar Console")

    def _ip(self) -> str:
        return self.entry_ip.get().strip()

    def _ews(self) -> LexmarkEWSClient:
        return LexmarkEWSClient(self._ip())

    def _log(self, msg: str):
        agora = datetime.now().strftime("%H:%M:%S")
        self.txt_console.insert("end", f"[{agora}] {msg}\n")
        self.txt_console.see("end")

    def _status(self, texto: str, cor: Optional[str] = None):
        self.lbl_status_topo.config(text=texto, foreground=cor or self.COR_VERDE)

    def _exportar_log(self):
        conteudo = self.txt_console.get("1.0", "end").strip()
        if not conteudo:
            messagebox.showinfo("Exportar Log", "O console está vazio.", parent=self.root)
            return
        nome_padrao = f"TerminalTI_Log_{self._ip().replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        caminho = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salvar Log do Terminal TI",
            initialfile=nome_padrao,
            defaultextension=".txt",
            filetypes=[("Arquivo de Texto", "*.txt"), ("Todos os Arquivos", "*.*")],
        )
        if caminho:
            Path(caminho).write_text(conteudo, encoding="utf-8")
            self._log(f"✔ Log exportado com sucesso para: {caminho}")

    def _criar_aba_rolavel(self, titulo: str) -> tk.Frame:
        outer = ttk.Frame(self.notebook, style="TI.TFrame")
        self.notebook.add(outer, text=titulo)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, background=self.COR_FUNDO, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas, background=self.COR_FUNDO)

        win_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_frame_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(win_id, width=event.width)

        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        content.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        content.columnconfigure(0, weight=1)
        return content

    def _card(self, parent: tk.Widget, titulo: str, subtitulo: str = "") -> tk.Frame:
        card = tk.LabelFrame(
            parent,
            text=f"  {titulo}  ",
            background=self.COR_PAINEL,
            foreground=self.COR_DESTAQUE,
            font=("Segoe UI", 9, "bold"),
            padx=14,
            pady=12,
            relief="solid",
            bd=1,
        )
        card.pack(fill="x", padx=10, pady=7)
        if subtitulo:
            tk.Label(
                card,
                text=subtitulo,
                background=self.COR_PAINEL,
                foreground=self.COR_TEXTO_SEC,
                font=("Segoe UI", 8),
                anchor="w",
                justify="left",
            ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        return card

    def _executar_async(self, descricao: str, func_trabalho):
        self._status(f"⏳ Executando: {descricao}...", self.COR_AMARELO)
        self._log(f"▶ Iniciando: {descricao} ({self._ip()})...")

        def runner():
            try:
                res = func_trabalho()
                self.root.after(0, lambda: self._log(f"✔ CONCLUÍDO [{descricao}]: {res}\n"))
                self.root.after(0, lambda: self._status(f"● Concluído: {descricao}", self.COR_VERDE))
            except Exception as erro:
                self.root.after(0, lambda: self._log(f"✖ ERRO [{descricao}]: {erro}\n"))
                self.root.after(0, lambda: self._status("● Erro na operação (ver console)", self.COR_VERMELHO))

        threading.Thread(target=runner, daemon=True).start()

    # ========================================================
    # ABA 1: PAPEL, MÍDIA E BANDEJAS
    # ========================================================

    def _construir_aba_papel(self):
        aba = self._criar_aba_rolavel(" 📄 Papel ")

        # Card 1: Bandeja 1, Alimentador Manual e Origem Padrão (EWS HTTP POST + PJL)
        c_band = self._card(
            aba,
            "Bandejas, Tamanho e Tipo de Papel (Gravação Real EWS NVRAM + PJL)",
            "Altera diretamente o Menu Papel (/cgi-bin/posttest/printer/config/gen/papermenu.html) da impressora.",
        )
        c_band.columnconfigure(1, weight=1)
        c_band.columnconfigure(3, weight=1)

        tk.Label(c_band, text="Origem Padrão:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_origem_padrao = ttk.Combobox(c_band, values=list(ORIGEM_PADRAO_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_origem_padrao.set("Bandeja 1 (Cassete Principal)")
        self.cb_origem_padrao.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_band, text="Configurar Alimentador MF:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.cb_config_mf = ttk.Combobox(c_band, values=list(CONFIG_MF_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_config_mf.set("Primeiro (Prioridade MP Feeder)")
        self.cb_config_mf.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=4)

        tk.Label(c_band, text="Bandeja 1 — Tamanho:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.cb_b1_tamanho = ttk.Combobox(c_band, values=list(TAMANHO_PAPEL_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_b1_tamanho.set("A4 (210 x 297 mm)")
        self.cb_b1_tamanho.grid(row=2, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_band, text="Bandeja 1 — Tipo:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=2, column=2, sticky="w", pady=4)
        self.cb_b1_tipo = ttk.Combobox(c_band, values=list(TIPO_PAPEL_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_b1_tipo.set("Papel Comum (Plain)")
        self.cb_b1_tipo.grid(row=2, column=3, sticky="ew", padx=(6, 0), pady=4)

        tk.Label(c_band, text="Papel Manual — Tamanho:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=3, column=0, sticky="w", pady=4)
        self.cb_man_tamanho = ttk.Combobox(c_band, values=list(TAMANHO_PAPEL_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_man_tamanho.set("A4 (210 x 297 mm)")
        self.cb_man_tamanho.grid(row=3, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_band, text="Papel Manual — Tipo:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=3, column=2, sticky="w", pady=4)
        self.cb_man_tipo = ttk.Combobox(c_band, values=list(TIPO_PAPEL_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_man_tipo.set("Papel Comum (Plain)")
        self.cb_man_tipo.grid(row=3, column=3, sticky="ew", padx=(6, 0), pady=4)

        tk.Label(c_band, text="Substituição de Tamanho:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=4, column=0, sticky="w", pady=4)
        self.cb_subst_tam = ttk.Combobox(c_band, values=list(SUBSTITUIR_TAMANHO_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_subst_tam.set("Carta / A4")
        self.cb_subst_tam.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=4)

        def _salvar_menu_papel():
            alteracoes = {
                "0.system.48": ORIGEM_PADRAO_OPCOES[self.cb_origem_padrao.get()],
                "0.system.1088": CONFIG_MF_OPCOES[self.cb_config_mf.get()],
                "0.system.49": TAMANHO_PAPEL_OPCOES[self.cb_b1_tamanho.get()],
                "0.system.52": TIPO_PAPEL_OPCOES[self.cb_b1_tipo.get()],
                "0.system.51": TAMANHO_PAPEL_OPCOES[self.cb_man_tamanho.get()],
                "0.system.54": TIPO_PAPEL_OPCOES[self.cb_man_tipo.get()],
                "0.system.385": SUBSTITUIR_TAMANHO_OPCOES[self.cb_subst_tam.get()],
            }
            return self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/papermenu.html",
                alteracoes,
                "/cgi-bin/posttest/printer/config/gen/papermenu.html",
            )

        btn_salvar_papel = ttk.Button(
            c_band,
            text="⚡ GRAVAR CONFIGURAÇÃO DE BANDEJAS NA IMPRESSORA",
            command=lambda: self._executar_async("Gravar Menu Papel & Bandejas", _salvar_menu_papel),
            style="TI.Primary.TButton",
        )
        btn_salvar_papel.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ToolTip(btn_salvar_papel, "Envia HTTP POST para /cgi-bin/posttest/printer/config/gen/papermenu.html gravando na NVRAM.")

        # Card 2: Textura do Papel
        c_tex = self._card(
            aba,
            "Textura de Mídia (/config/paper/papertexture.html)",
            "Ajusta a velocidade e transferência para mídias lisas, normais ou rugosas.",
        )
        c_tex.columnconfigure(1, weight=1)
        c_tex.columnconfigure(3, weight=1)

        tk.Label(c_tex, text="Tipo de Mídia:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_midia_tex = ttk.Combobox(c_tex, values=list(MIDIAS_TEXTURA_CAMPOS.keys()), state="readonly", style="TI.TCombobox")
        self.cb_midia_tex.set("Papel Comum (Plain)")
        self.cb_midia_tex.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_tex, text="Textura Desejada:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.cb_valor_tex = ttk.Combobox(c_tex, values=list(TEXTURA_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_valor_tex.set("Normal")
        self.cb_valor_tex.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=4)

        def _salvar_textura(todas: bool = False):
            val_cod = TEXTURA_OPCOES[self.cb_valor_tex.get()]
            if todas:
                alt = {campo: val_cod for campo in MIDIAS_TEXTURA_CAMPOS.values()}
            else:
                campo = MIDIAS_TEXTURA_CAMPOS[self.cb_midia_tex.get()]
                alt = {campo: val_cod}
            return self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/paper/papertexture.html",
                alt,
                "/cgi-bin/posttest/printer/config/paper/papertexture.html",
            )

        ttk.Button(
            c_tex,
            text="⚡ Aplicar na Mídia Selecionada",
            command=lambda: self._executar_async("Aplicar Textura de Papel", lambda: _salvar_textura(False)),
            style="TI.Primary.TButton",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 6), pady=(8, 0))

        ttk.Button(
            c_tex,
            text="🔁 Aplicar Esta Textura em Todas as Mídias",
            command=lambda: self._executar_async("Aplicar Textura Global", lambda: _salvar_textura(True)),
            style="TI.Secondary.TButton",
        ).grid(row=2, column=2, columnspan=2, sticky="ew", pady=(8, 0))

        # Card 3: Gramatura / Peso do Papel
        c_peso = self._card(
            aba,
            "Gramatura / Peso do Papel (/config/paper/paperweight.html)",
            "Controla a temperatura do fusor para evitar toner solto ou ondulação do papel.",
        )
        c_peso.columnconfigure(1, weight=1)
        c_peso.columnconfigure(3, weight=1)

        tk.Label(c_peso, text="Tipo de Mídia:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_midia_peso = ttk.Combobox(c_peso, values=list(MIDIAS_PESO_CAMPOS.keys()), state="readonly", style="TI.TCombobox")
        self.cb_midia_peso.set("Papel Comum (Plain)")
        self.cb_midia_peso.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_peso, text="Peso / Gramatura:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.cb_valor_peso = ttk.Combobox(c_peso, values=list(PESO_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_valor_peso.set("Normal")
        self.cb_valor_peso.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=4)

        def _salvar_peso(todas: bool = False):
            val_cod = PESO_OPCOES[self.cb_valor_peso.get()]
            if todas:
                alt = {campo: val_cod for campo in MIDIAS_PESO_CAMPOS.values()}
            else:
                campo = MIDIAS_PESO_CAMPOS[self.cb_midia_peso.get()]
                alt = {campo: val_cod}
            return self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/paper/paperweight.html",
                alt,
                "/cgi-bin/posttest/printer/config/paper/paperweight.html",
            )

        ttk.Button(
            c_peso,
            text="⚡ Aplicar Peso na Mídia Selecionada",
            command=lambda: self._executar_async("Aplicar Peso do Papel", lambda: _salvar_peso(False)),
            style="TI.Primary.TButton",
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 6), pady=(8, 0))

        ttk.Button(
            c_peso,
            text="🔁 Aplicar Este Peso em Todas as Mídias",
            command=lambda: self._executar_async("Aplicar Peso Global", lambda: _salvar_peso(True)),
            style="TI.Secondary.TButton",
        ).grid(row=2, column=2, columnspan=2, sticky="ew", pady=(8, 0))

    # ========================================================
    # ABA 2: TELA INICIAL, ÍCONES (eSF) E WALLPAPER
    # ========================================================

    def _construir_aba_tela_inicial(self):
        aba = self._criar_aba_rolavel(" 🎨 Tela Inicial ")

        # Card 1: Ícones e Grade da Tela Inicial (Organização Estilo Celular)
        c_ico = self._card(
            aba,
            "Grade de Ícones da Tela Inicial do Visor LCD (/config/gen/sub/add_btns.html)",
            "Escolha quais botões aparecem, organize a ordem de exibição na grade como num celular e visualize a tela física em tempo real.",
        )
        c_ico.columnconfigure(0, weight=1)
        c_ico.columnconfigure(1, weight=1)

        # Mapa de metadados visuais para os ícones
        self.mapa_meta_icones = {
            "2.system.17351": {"icone": "📄", "nome": "Cópia"},
            "2.system.17254": {"icone": "📑", "nome": "Atalhos Cópia"},
            "2.system.17350": {"icone": "📠", "nome": "Fax"},
            "2.system.17257": {"icone": "📠", "nome": "Atalhos Fax"},
            "2.system.17352": {"icone": "✉️", "nome": "E-mail"},
            "2.system.17255": {"icone": "✉️", "nome": "Atalhos E-mail"},
            "2.system.17353": {"icone": "🌐", "nome": "FTP (Rede)"},
            "2.system.17256": {"icone": "🌐", "nome": "Atalhos FTP"},
            "2.system.17354": {"icone": "🔒", "nome": "Trabalhos Retidos"},
            "2.system.17348": {"icone": "🔍", "nome": "Buscar Retidos"},
            "2.system.17252": {"icone": "💾", "nome": "Unidade USB"},
            "2.system.17250": {"icone": "⚙️", "nome": "Perfis / Scan"},
            "2.system.17251": {"icone": "🔖", "nome": "Marcadores"},
            "2.system.17167": {"icone": "🌍", "nome": "Alterar Idioma"},
            "2.system.17253": {"icone": "👤", "nome": "Por Usuário"},
        }

        # Ordem de renderização na grade
        self.ordem_icones_home = [cid for cid, _, _ in ICONES_HOME_CAMPOS]

        self.vars_icones_home = {}
        for idx, (campo_id, rotulo, dica) in enumerate(ICONES_HOME_CAMPOS):
            var = tk.BooleanVar(value=campo_id in ("2.system.17351", "2.system.17354", "2.system.17252", "2.system.17250"))
            self.vars_icones_home[campo_id] = var
            chk = tk.Checkbutton(
                c_ico,
                text=rotulo,
                variable=var,
                command=lambda: self._atualizar_simulador_grade(),
                background=self.COR_PAINEL,
                foreground=self.COR_TEXTO,
                selectcolor=self.COR_PAINEL_2,
                activebackground=self.COR_PAINEL,
                activeforeground=self.COR_DESTAQUE,
                font=("Segoe UI", 9),
                anchor="w",
            )
            chk.grid(row=(idx // 2) + 1, column=idx % 2, sticky="w", padx=6, pady=2)
            ToolTip(chk, f"{dica} (Campo EWS: {campo_id})")

        linha_btns = (len(ICONES_HOME_CAMPOS) // 2) + 2
        f_presets = tk.Frame(c_ico, background=self.COR_PAINEL)
        f_presets.grid(row=linha_btns, column=0, columnspan=2, sticky="ew", pady=(8, 12))

        def _preset_smartphone():
            # 4 ícones grandes com toque facilitado
            for cid, v in self.vars_icones_home.items():
                v.set(cid in ("2.system.17351", "2.system.17354", "2.system.17252", "2.system.17250"))
            self._atualizar_simulador_grade()

        def _preset_corporativo():
            # 6 ícones corporativos
            for cid, v in self.vars_icones_home.items():
                v.set(cid in ("2.system.17351", "2.system.17354", "2.system.17252", "2.system.17250", "2.system.17352", "2.system.17254"))
            self._atualizar_simulador_grade()

        def _preset_todos():
            for v in self.vars_icones_home.values():
                v.set(True)
            self._atualizar_simulador_grade()

        def _preset_nenhum():
            for v in self.vars_icones_home.values():
                v.set(False)
            self._atualizar_simulador_grade()

        ttk.Button(
            f_presets,
            text="📱 Modo Smartphone (4 Ícones Grandes)",
            command=_preset_smartphone,
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            f_presets,
            text="✨ Preset Corporativo (6 Ícones)",
            command=_preset_corporativo,
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            f_presets,
            text="☑ Marcar Todos",
            command=_preset_todos,
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 6))

        ttk.Button(
            f_presets,
            text="⬜ Desmarcar",
            command=_preset_nenhum,
            style="TI.Secondary.TButton",
        ).pack(side="left")

        # Container Principal: Reordenação à Esquerda + Simulador de Tela LCD à Direita
        f_organizador = tk.Frame(c_ico, background=self.COR_PAINEL_2, padx=12, pady=12, highlightbackground=self.COR_BORDA, highlightthickness=1)
        f_organizador.grid(row=linha_btns + 1, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        f_organizador.columnconfigure(0, weight=1)
        f_organizador.columnconfigure(1, weight=1)

        # Lado Esquerdo: Lista de Reordenação
        f_ordem = tk.Frame(f_organizador, background=self.COR_PAINEL_2)
        f_ordem.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        f_ordem.columnconfigure(0, weight=1)

        tk.Label(
            f_ordem,
            text="📋 Ordem de Prioridade na Grade (Slot 1 ao Slot 8):",
            bg=self.COR_PAINEL_2,
            fg=self.COR_TEXTO,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        f_listbox_wrap = tk.Frame(f_ordem, background=self.COR_PAINEL_2)
        f_listbox_wrap.grid(row=1, column=0, sticky="nsew")
        f_listbox_wrap.columnconfigure(0, weight=1)

        self.listbox_ordem = tk.Listbox(
            f_listbox_wrap,
            height=7,
            bg="#161b22",
            fg=self.COR_TEXTO,
            selectbackground=self.COR_DESTAQUE,
            selectforeground="#ffffff",
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.COR_BORDA,
            font=("Segoe UI", 9),
            exportselection=False,
        )
        self.listbox_ordem.grid(row=0, column=0, sticky="nsew")

        scroll_ordem = ttk.Scrollbar(f_listbox_wrap, orient="vertical", command=self.listbox_ordem.yview)
        scroll_ordem.grid(row=0, column=1, sticky="ns")
        self.listbox_ordem.configure(yscrollcommand=scroll_ordem.set)

        # Botões de Reordenação (Cima / Baixo / Topo)
        f_btns_mov = tk.Frame(f_ordem, background=self.COR_PAINEL_2)
        f_btns_mov.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        def _mover_item_cima():
            sel = self.listbox_ordem.curselection()
            if not sel or sel[0] <= 0:
                return
            idx = sel[0]
            # Identifica os IDs ativos
            ativos = [cid for cid in self.ordem_icones_home if self.vars_icones_home.get(cid, tk.BooleanVar()).get()]
            cid_atual = ativos[idx]
            cid_anterior = ativos[idx - 1]
            # Troca na lista mestra
            i1 = self.ordem_icones_home.index(cid_atual)
            i2 = self.ordem_icones_home.index(cid_anterior)
            self.ordem_icones_home[i1], self.ordem_icones_home[i2] = self.ordem_icones_home[i2], self.ordem_icones_home[i1]
            self._atualizar_simulador_grade(selecionar_indice=idx - 1)

        def _mover_item_baixo():
            sel = self.listbox_ordem.curselection()
            if not sel:
                return
            idx = sel[0]
            ativos = [cid for cid in self.ordem_icones_home if self.vars_icones_home.get(cid, tk.BooleanVar()).get()]
            if idx >= len(ativos) - 1:
                return
            cid_atual = ativos[idx]
            cid_proximo = ativos[idx + 1]
            # Troca na lista mestra
            i1 = self.ordem_icones_home.index(cid_atual)
            i2 = self.ordem_icones_home.index(cid_proximo)
            self.ordem_icones_home[i1], self.ordem_icones_home[i2] = self.ordem_icones_home[i2], self.ordem_icones_home[i1]
            self._atualizar_simulador_grade(selecionar_indice=idx + 1)

        def _mover_item_topo():
            sel = self.listbox_ordem.curselection()
            if not sel or sel[0] <= 0:
                return
            idx = sel[0]
            ativos = [cid for cid in self.ordem_icones_home if self.vars_icones_home.get(cid, tk.BooleanVar()).get()]
            cid_atual = ativos[idx]
            self.ordem_icones_home.remove(cid_atual)
            self.ordem_icones_home.insert(0, cid_atual)
            self._atualizar_simulador_grade(selecionar_indice=0)

        def _restaurar_ordem_padrao():
            self.ordem_icones_home = [cid for cid, _, _ in ICONES_HOME_CAMPOS]
            self._atualizar_simulador_grade()

        ttk.Button(f_btns_mov, text="▲ Mover para Cima", command=_mover_item_cima, style="TI.Secondary.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(f_btns_mov, text="▼ Mover para Baixo", command=_mover_item_baixo, style="TI.Secondary.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(f_btns_mov, text="🔝 Topo (Slot 1)", command=_mover_item_topo, style="TI.Secondary.TButton").pack(side="left", padx=(0, 4))
        ttk.Button(f_btns_mov, text="🔄 Padrão", command=_restaurar_ordem_padrao, style="TI.Secondary.TButton").pack(side="left")

        # Lado Direito: Simulador da Tela Física LCD (800x480)
        f_lcd = tk.Frame(f_organizador, background="#0d1117", padx=8, pady=8, highlightbackground="#388bfd", highlightthickness=1)
        f_lcd.grid(row=0, column=1, sticky="nsew")
        f_lcd.columnconfigure(0, weight=1)

        # Topo do Visor LCD
        f_lcd_topo = tk.Frame(f_lcd, background="#161b22", padx=6, pady=3)
        f_lcd_topo.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(
            f_lcd_topo,
            text="🖥️ Visor Físico da Impressora (Painel eSF 7\" — 800x480)",
            bg="#161b22",
            fg="#79c0ff",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left")
        self.lbl_lcd_status = tk.Label(
            f_lcd_topo,
            text="● Pronto | Página 1",
            bg="#161b22",
            fg=self.COR_VERDE,
            font=("Segoe UI", 8),
        )
        self.lbl_lcd_status.pack(side="right")

        # Grade 2x4 dos Slots do LCD
        self.slots_lcd = []
        f_grade_slots = tk.Frame(f_lcd, background="#0d1117")
        f_grade_slots.grid(row=1, column=0, sticky="nsew")
        for c in range(4):
            f_grade_slots.columnconfigure(c, weight=1)

        for s_idx in range(8):
            r = s_idx // 4
            c = s_idx % 4
            f_slot = tk.Frame(f_grade_slots, background="#21262d", highlightbackground=self.COR_BORDA, highlightthickness=1, padx=4, pady=5)
            f_slot.grid(row=r, column=c, padx=3, pady=3, sticky="nsew")
            lbl_pos = tk.Label(f_slot, text=f"[{s_idx + 1}]", bg="#21262d", fg="#8b949e", font=("Segoe UI", 7, "bold"))
            lbl_pos.pack(anchor="w")
            lbl_ico = tk.Label(f_slot, text="📄", bg="#21262d", fg=self.COR_TEXTO, font=("Segoe UI", 12))
            lbl_ico.pack()
            lbl_nome = tk.Label(f_slot, text="Cópia", bg="#21262d", fg=self.COR_TEXTO, font=("Segoe UI", 7, "bold"), wraplength=70)
            lbl_nome.pack()
            self.slots_lcd.append({"frame": f_slot, "pos": lbl_pos, "ico": lbl_ico, "nome": lbl_nome})

        self.lbl_lcd_rodape = tk.Label(
            f_lcd,
            text="💡 Botões Maiores: Com 4 a 6 itens ativos, a impressora amplia a escala e a área de toque no visor.",
            bg="#0d1117",
            fg=self.COR_TEXTO_SEC,
            font=("Segoe UI", 8),
            justify="center",
        )
        self.lbl_lcd_rodape.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        # Método de atualização do simulador e da lista
        def _atualizar_simulador_grade(selecionar_indice=None):
            ativos = [cid for cid in self.ordem_icones_home if self.vars_icones_home.get(cid, tk.BooleanVar()).get()]

            # 1. Atualiza Listbox
            self.listbox_ordem.delete(0, "end")
            for idx, cid in enumerate(ativos, start=1):
                meta = self.mapa_meta_icones.get(cid, {"icone": "🔘", "nome": cid})
                slot_info = f" (Slot {idx})" if idx <= 8 else " (Página 2)"
                self.listbox_ordem.insert("end", f"{idx}. {meta['icone']} {meta['nome']}{slot_info}")

            if selecionar_indice is not None and 0 <= selecionar_indice < len(ativos):
                self.listbox_ordem.selection_set(selecionar_indice)
                self.listbox_ordem.activate(selecionar_indice)

            # 2. Atualiza Slots do Simulador LCD
            total_ativos = len(ativos)
            for slot_i, slot_widgets in enumerate(self.slots_lcd):
                if slot_i < total_ativos:
                    cid = ativos[slot_i]
                    meta = self.mapa_meta_icones.get(cid, {"icone": "🔘", "nome": cid})
                    slot_widgets["frame"].configure(background="#21262d", highlightbackground=self.COR_DESTAQUE)
                    slot_widgets["pos"].configure(text=f"[{slot_i + 1}]", bg="#21262d", fg=self.COR_DESTAQUE)
                    slot_widgets["ico"].configure(text=meta["icone"], bg="#21262d")
                    slot_widgets["nome"].configure(text=meta["nome"], bg="#21262d", fg=self.COR_TEXTO)
                else:
                    slot_widgets["frame"].configure(background="#161b22", highlightbackground=self.COR_BORDA)
                    slot_widgets["pos"].configure(text=f"[{slot_i + 1}]", bg="#161b22", fg="#484f58")
                    slot_widgets["ico"].configure(text="·", bg="#161b22", fg="#484f58")
                    slot_widgets["nome"].configure(text="(Livre)", bg="#161b22", fg="#484f58")

            # 3. Status e Dica de Tamanho de Ícone
            if total_ativos <= 6:
                self.lbl_lcd_status.configure(text=f"● {total_ativos} itens | Ícones Grandes (Layout Amplo)")
                self.lbl_lcd_rodape.configure(
                    text=f"✨ {total_ativos} botões ativos: a impressora renderiza os ícones em tamanho maior e com espaçamento otimizado para o toque.",
                    fg=self.COR_VERDE,
                )
            elif total_ativos <= 8:
                self.lbl_lcd_status.configure(text=f"● {total_ativos} itens | Matriz 2x4 Completa")
                self.lbl_lcd_rodape.configure(
                    text=f"📱 Matriz 2x4 preenchida: todos os {total_ativos} botões visíveis na 1ª página do visor.",
                    fg=self.COR_DESTAQUE,
                )
            else:
                excedente = total_ativos - 8
                self.lbl_lcd_status.configure(text=f"● 8 de {total_ativos} itens | Página 1 de 2")
                self.lbl_lcd_rodape.configure(
                    text=f"➡️ Há {excedente} botão(ões) adicional(is) que irão para a Página 2 no visor.",
                    fg="#d29922",
                )

        self._atualizar_simulador_grade = _atualizar_simulador_grade
        self._atualizar_simulador_grade()

        # Dica Explicativa sobre o Tamanho dos Ícones
        f_dica_tamanho = tk.Frame(c_ico, background=self.COR_PAINEL, pady=4)
        f_dica_tamanho.grid(row=linha_btns + 2, column=0, columnspan=2, sticky="ew")
        tk.Label(
            f_dica_tamanho,
            text=(
                "💡 Como funciona o tamanho dos ícones no LCD Lexmark: O framework gráfico eSF ajusta a escala e a área de toque dos botões "
                "conforme o total de itens ativos. Com 4 a 6 botões ativos, o sistema exibe ícones maiores e destacados (como numa tela inicial de celular). "
                "Com 8 botões, preenche a matriz 2x4 compacta."
            ),
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO_SEC,
            font=("Segoe UI", 8),
            justify="left",
            wraplength=980,
        ).pack(side="left")

        def _salvar_icones_home():
            alt = {cid: ("1" if var.get() else "0") for cid, var in self.vars_icones_home.items()}
            ativos = [cid for cid in self.ordem_icones_home if self.vars_icones_home.get(cid, tk.BooleanVar()).get()]
            nomes_ordem = [self.mapa_meta_icones.get(c, {}).get("nome", c) for c in ativos]
            
            res = self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html",
                alt,
                "/cgi-bin/posttest/printer/config/gen/sub/add_btns.html",
            )
            res["ordem_aplicada"] = " ➔ ".join(nomes_ordem) if nomes_ordem else "Nenhum botão ativo"
            return res

        ttk.Button(
            c_ico,
            text="⚡ GRAVAR ÍCONES E ORDEM DA GRADE NA IMPRESSORA",
            command=lambda: self._executar_async("Atualizar Ícones e Grade da Tela Inicial", _salvar_icones_home),
            style="TI.Primary.TButton",
        ).grid(row=linha_btns + 3, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # Card 2: Papel de Parede (Wallpaper LCD 800x414)
        c_wall = self._card(
            aba,
            "Papel de Parede Personalizado no Visor LCD (/config/gen/gen_custombackground.html)",
            "Converte e redimensiona automaticamente qualquer imagem (.jpg, .png, .gif) para 800x414 pixels (<128 KB) e aplica no painel.",
        )
        c_wall.columnconfigure(1, weight=1)

        tk.Label(c_wall, text="Imagem:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_wallpaper = tk.Entry(c_wall, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_wallpaper.grid(row=1, column=1, sticky="ew", padx=8, pady=4, ipady=3)

        def _escolher_wallpaper():
            arq = filedialog.askopenfilename(
                parent=self.root,
                title="Selecionar Imagem de Fundo para o LCD",
                filetypes=[("Imagens", "*.jpg *.jpeg *.png *.gif *.bmp"), ("Todos os arquivos", "*.*")],
            )
            if arq:
                self.entry_wallpaper.delete(0, "end")
                self.entry_wallpaper.insert(0, arq)

        ttk.Button(c_wall, text="📂 Procurar...", command=_escolher_wallpaper, style="TI.Secondary.TButton").grid(row=1, column=2, padx=(0, 8))
        ttk.Button(
            c_wall,
            text="🖼️ ENVIAR PAPEL DE PAREDE",
            command=lambda: self._executar_async(
                "Enviar Papel de Parede LCD",
                lambda: self._ews().enviar_papel_parede(self.entry_wallpaper.get().strip()),
            ),
            style="TI.Primary.TButton",
        ).grid(row=1, column=3)

        # Card 3: Gerador / Injetor de Atalho SMB / XML VCC e Backup UCF
        c_vcc = self._card(
            aba,
            "Atalhos de Rede (SMB / FTP) & Clonar Configurações (.UCF / XML VCC)",
            "Exporte ou importe o pacote de configurações/atalhos (.ucf) ou injete XML de configuração na porta 9100.",
        )
        c_vcc.columnconfigure(1, weight=1)
        c_vcc.columnconfigure(3, weight=1)

        tk.Label(c_vcc, text="Nome do Atalho:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_smb_nome = tk.Entry(c_vcc, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_smb_nome.insert(0, "Scan para PC")
        self.entry_smb_nome.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4, ipady=3)

        tk.Label(c_vcc, text="Caminho SMB (\\\\IP\\Pasta):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.entry_smb_path = tk.Entry(c_vcc, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_smb_path.insert(0, r"\\192.168.14.165\Digitalizacao")
        self.entry_smb_path.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=4, ipady=3)

        f_ucf_btns = tk.Frame(c_vcc, background=self.COR_PAINEL)
        f_ucf_btns.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))

        def _injetar_atalho_xml():
            nome = self.entry_smb_nome.get().strip() or "Scan_TI"
            caminho = self.entry_smb_path.get().strip()
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<Configuration>\n"
                '  <Setting name="ScanToNetwork.ShortcutName">' + nome + "</Setting>\n"
                '  <Setting name="ScanToNetwork.SharePath">' + caminho + "</Setting>\n"
                "</Configuration>"
            )
            enviados = injetar_xml_vcc(self._ip(), xml)
            return f"Pacote XML VCC ({enviados} bytes) enviado para {self._ip()}:9100"

        def _exportar_ucf(tipo_ucf: str):
            caminho_salvar = filedialog.asksaveasfilename(
                parent=self.root,
                title=f"Salvar {tipo_ucf}",
                initialfile=f"{self._ip().replace('.', '_')}_{tipo_ucf}",
                defaultextension=".ucf",
                filetypes=[("Lexmark UCF", "*.ucf"), ("Todos", "*.*")],
            )
            if not caminho_salvar:
                return
            def _trab():
                dados = self._ews().exportar_configuracao_ucf(tipo_ucf)
                Path(caminho_salvar).write_bytes(dados)
                return f"Arquivo salvo em {caminho_salvar} ({len(dados)} bytes)"
            self._executar_async(f"Exportar {tipo_ucf}", _trab)

        def _importar_ucf():
            arq = filedialog.askopenfilename(
                parent=self.root,
                title="Selecionar arquivo .ucf para importar na impressora",
                filetypes=[("Lexmark UCF", "*.ucf *.xml"), ("Todos", "*.*")],
            )
            if arq:
                self._executar_async("Importar Arquivo .UCF", lambda: self._ews().importar_configuracao_ucf(arq))

        ttk.Button(
            f_ucf_btns,
            text="📤 Injetar Atalho XML (Porta 9100)",
            command=lambda: self._executar_async("Injetar XML de Atalho", _injetar_atalho_xml),
            style="TI.Primary.TButton",
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            f_ucf_btns,
            text="⬇️ Exportar Config (.ucf)",
            command=lambda: _exportar_ucf("settingfile.ucf"),
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            f_ucf_btns,
            text="⬇️ Exportar Atalhos (.ucf)",
            command=lambda: _exportar_ucf("shortcuts.ucf"),
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            f_ucf_btns,
            text="⬆️ Importar Arquivo (.ucf)",
            command=_importar_ucf,
            style="TI.Secondary.TButton",
        ).pack(side="left")

    # ========================================================
    # ABA 3: SISTEMA, PAINEL FÍSICO, RELÓGIO E RESETS
    # ========================================================

    def _construir_aba_sistema_painel(self):
        aba = self._criar_aba_rolavel(" 🖥️ Sistema ")

        # Card 1: Mensagens no Visor LCD
        c_msg = self._card(
            aba,
            "Mensagens Customizadas no Visor LCD (PJL 9100)",
            "Escreve avisos de bancada/manutenção diretamente na tela da impressora ou restaura para 'Pronto'.",
        )
        c_msg.columnconfigure(1, weight=1)

        tk.Label(c_msg, text="Texto no Visor:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_msg_lcd = tk.Entry(
            c_msg,
            font=("Consolas", 10, "bold"),
            bg=self.COR_PAINEL_2,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
        )
        self.entry_msg_lcd.insert(0, "EM MANUTENCAO - TI")
        self.entry_msg_lcd.grid(row=1, column=1, sticky="ew", padx=8, pady=4, ipady=4)

        ttk.Button(
            c_msg,
            text="⚡ Escrever no Visor (RDYMSG)",
            command=lambda: self._executar_async(
                "Escrever Mensagem LCD",
                lambda: enviar_pjl(self._ip(), [f'RDYMSG DISPLAY="{self.entry_msg_lcd.get().strip()}"']),
            ),
            style="TI.Primary.TButton",
        ).grid(row=1, column=2, padx=(0, 6))

        ttk.Button(
            c_msg,
            text="🧹 Limpar Visor (Voltar ao Pronto)",
            command=lambda: self._executar_async(
                "Restaurar Visor Padrão",
                lambda: enviar_pjl(self._ip(), ['RDYMSG DISPLAY=""']),
            ),
            style="TI.Secondary.TButton",
        ).grid(row=1, column=3)

        # Card 2: Idioma, Brilho da Tela, Bipe ADF e Painel Remoto VNC
        c_painel = self._card(
            aba,
            "Idioma, Brilho do Painel, Áudio e Operador Remoto VNC (/config/gen/general.html)",
            "Configura idioma da máquina, brilho do display, bipe do scanner/ADF e ativa o espelhamento remoto do painel.",
        )
        c_painel.columnconfigure(1, weight=1)
        c_painel.columnconfigure(3, weight=1)

        tk.Label(c_painel, text="Idioma do Painel:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_idioma = ttk.Combobox(c_painel, values=list(IDIOMA_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_idioma.set("Português (Brasil)")
        self.cb_idioma.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_painel, text="Brilho do LCD (20 a 100%):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.spin_brilho_lcd = tk.Spinbox(
            c_painel, from_=20, to=100, increment=5, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, relief="flat", width=8
        )
        self.spin_brilho_lcd.delete(0, "end")
        self.spin_brilho_lcd.insert(0, "100")
        self.spin_brilho_lcd.grid(row=1, column=3, sticky="w", padx=(6, 0), pady=4)

        self.var_bipe_adf = tk.BooleanVar(value=True)
        tk.Checkbutton(
            c_painel,
            text="Bipe ao Carregar Papel no ADF (2.system.17245)",
            variable=self.var_bipe_adf,
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            selectcolor=self.COR_PAINEL_2,
            activebackground=self.COR_PAINEL,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        self.var_mostrar_estimativas = tk.BooleanVar(value=True)
        tk.Checkbutton(
            c_painel,
            text="Mostrar Estimativas de Suprimentos no Visor (0.system.5490)",
            variable=self.var_mostrar_estimativas,
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            selectcolor=self.COR_PAINEL_2,
            activebackground=self.COR_PAINEL,
        ).grid(row=2, column=2, columnspan=2, sticky="w", pady=4)

        def _salvar_painel_geral():
            alt = {
                "0.system.15": IDIOMA_OPCOES[self.cb_idioma.get()],
                "0.system.16720": str(self.spin_brilho_lcd.get()).strip(),
                "2.system.17245": "1" if self.var_bipe_adf.get() else "0",
                "0.system.5490": "1" if self.var_mostrar_estimativas.get() else "0",
                "0.system.16385": "1",  # DD-MM-AAAA
                "0.system.16713": "1",  # 24 horas
            }
            return self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/general.html",
                alt,
                "/cgi-bin/posttest/printer/config/gen/general.html",
            )

        ttk.Button(
            c_painel,
            text="⚡ APLICAR IDIOMA, BRILHO E PREFERÊNCIAS DO PAINEL",
            command=lambda: self._executar_async("Gravar Idioma e Painel", _salvar_painel_geral),
            style="TI.Primary.TButton",
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 6), pady=(8, 0))

        ttk.Button(
            c_painel,
            text="🔓 Ativar Painel Remoto VNC (Sem Senha)",
            command=lambda: self._executar_async(
                "Ativar Painel Remoto VNC",
                lambda: self._ews().gravar_campos_formulario(
                    "/cgi-bin/dynamic/printer/config/remote_oppanel_config.html",
                    {"2.system.12849": "1", "0.system.12850": "1"},
                    "/cgi-bin/posttest/printer/config/remote_oppanel_config.html",
                ),
            ),
            style="TI.Secondary.TButton",
        ).grid(row=3, column=2, columnspan=2, sticky="ew", pady=(8, 0))

        # Card 2B: Controle Validado do Modo do Scanner (MFP via UCF)
        c_scanner = self._card(
            aba,
            "🔬 Modo de Operação do Scanner MFP (Validado — mfp.scanner.scannerDisabled)",
            "Permite alternar multifuncionais Lexmark entre Ativado, Desativado (modo só impressora — bypass de erro 840.xx) ou ADF Desativado (só mesa plana) via mini-UCF seguro. Requer reinicialização da máquina para o ScanManager2 aplicar.",
        )
        c_scanner.columnconfigure(1, weight=1)

        tk.Label(c_scanner, text="Modo do Scanner:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_modo_scanner = ttk.Combobox(
            c_scanner,
            values=list(MODO_SCANNER_OPCOES.keys()),
            state="readonly",
            style="TI.TCombobox",
        )
        self.cb_modo_scanner.set(list(MODO_SCANNER_OPCOES.keys())[0])
        self.cb_modo_scanner.grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=4)

        def _ler_modo_scanner_ui():
            res = ler_modo_scanner(self._ip())
            cod = res.get("codigo")
            if cod is not None:
                chave_ui = _chave_por_valor(MODO_SCANNER_OPCOES, cod)
                self.root.after(0, lambda k=chave_ui: self.cb_modo_scanner.set(k))
            return res["resumo"]

        def _gravar_modo_scanner_ui():
            cod = MODO_SCANNER_OPCOES[self.cb_modo_scanner.get()]
            res = definir_modo_scanner(self._ip(), cod)
            return res["resumo"]

        ttk.Button(
            c_scanner,
            text="🔍 Ler Modo Atual",
            command=lambda: self._executar_async("Ler Modo do Scanner (UCF/ScanMgr)", _ler_modo_scanner_ui),
            style="TI.Secondary.TButton",
        ).grid(row=1, column=2, padx=(0, 6), pady=4)

        ttk.Button(
            c_scanner,
            text="⚡ GRAVAR MODO DO SCANNER",
            command=lambda: self._executar_async("Gravar Modo do Scanner (UCF Seguro)", _gravar_modo_scanner_ui),
            style="TI.Primary.TButton",
        ).grid(row=1, column=3, pady=4)

        # Card 3: Sincronização de Data e Hora
        c_relogio = self._card(
            aba,
            "Relógio Interno e Fuso Horário (/config/secure/datetime.html)",
            "Sincroniza a data e hora da placa lógica com o relógio deste computador e ajusta fuso para Brasília (UTC-03:00).",
        )
        c_relogio.columnconfigure(1, weight=1)

        tk.Label(c_relogio, text="Data/Hora (AAAA-MM-DD HH:MM):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_datahora = tk.Entry(c_relogio, font=("Consolas", 10), bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_datahora.insert(0, datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.entry_datahora.grid(row=1, column=1, sticky="ew", padx=8, pady=4, ipady=3)

        def _sincronizar_relogio_pc():
            agora_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.entry_datahora.delete(0, "end")
            self.entry_datahora.insert(0, agora_str)
            return self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/secure/datetime.html",
                {"1.system.4982": agora_str, "0.system.12360": "18"},
                "/cgi-bin/posttest/printer/config/secure/datetime.html",
            )

        ttk.Button(
            c_relogio,
            text="⏱️ SINCRONIZAR COM O PC AGORA (UTC-03:00 Brasília)",
            command=lambda: self._executar_async("Sincronizar Relógio da Impressora", _sincronizar_relogio_pc),
            style="TI.Primary.TButton",
        ).grid(row=1, column=2, padx=(4, 0))

        # Card 4: Limpeza de Fila, Alertas e Resets de Fábrica
        c_reset = self._card(
            aba,
            "Limpeza de Erros, Expurgo de Spooler e Central de Resets de Fábrica (NVRAM)",
            "Comandos imediatos para destravar impressora em bancada ou executar restauração parcial/total de fábrica.",
        )
        c_reset.columnconfigure(1, weight=1)

        f_rbtns = tk.Frame(c_reset, background=self.COR_PAINEL)
        f_rbtns.grid(row=1, column=0, columnspan=4, sticky="ew")

        ttk.Button(
            f_rbtns,
            text="🧹 Limpar Alertas (CLEAR WARNING)",
            command=lambda: self._executar_async("Limpar Alertas PJL", lambda: enviar_pjl(self._ip(), ["CLEAR WARNING"])),
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 8), pady=4)

        ttk.Button(
            f_rbtns,
            text="🗑️ Expurgar Fila / Initialize",
            command=lambda: self._executar_async("Expurgar Spooler PJL", lambda: enviar_pjl(self._ip(), ["INITIALIZE"])),
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 8), pady=4)

        ttk.Button(
            f_rbtns,
            text="🔄 Reiniciar Impressora (@PJL RESET)",
            command=lambda: self._executar_async("Reiniciar Impressora", lambda: enviar_pjl(self._ip(), ["RESET"], encapsular_job=False)),
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 8), pady=4)

        # Linha 2: Resets de Fábrica EWS
        f_fab = tk.Frame(c_reset, background=self.COR_PAINEL)
        f_fab.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        f_fab.columnconfigure(1, weight=1)

        opcoes_reset_fabrica = {
            "1. Restaurar Definições da Impressora (Preserva IP / Rede) [base]": "base",
            "2. Restaurar Definições de Rede (Zera TCP/IP para DHCP) [network]": "network",
            "3. Restaurar Apps e Soluções Incorporadas (eSF) [les]": "les",
            "4. Apagar Memória da Impressora (Limpa Definições + Apps + Trabalhos)": "erase_memory",
            "5. Wipe Completo 'Fora de Serviço' (Zera Volátil + NVRAM e volta ao Assistente Inicial)": "memwipe",
        }

        tk.Label(
            f_fab,
            text="Escopo do Reset de Fábrica:",
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)

        self.cb_escopo_reset = ttk.Combobox(
            f_fab,
            values=list(opcoes_reset_fabrica.keys()),
            state="readonly",
            style="TI.TCombobox",
        )
        self.cb_escopo_reset.set("1. Restaurar Definições da Impressora (Preserva IP / Rede) [base]")
        self.cb_escopo_reset.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=4)

        def _executar_reset_selecionado():
            rotulo = self.cb_escopo_reset.get()
            codigo = opcoes_reset_fabrica.get(rotulo, "base")
            if not messagebox.askyesno(
                "Confirmar Reset de Fábrica",
                f"Tem certeza que deseja executar na impressora {self._ip()}:\n\n"
                f"• {rotulo}\n\n"
                "A impressora poderá reiniciar automaticamente após o comando.",
                parent=self.root,
            ):
                return

            if codigo in ("base", "network", "les"):
                self._executar_async(
                    f"Reset de Fábrica ({codigo})",
                    lambda: self._ews().restaurar_padroes_fabrica(codigo),
                )
            elif codigo == "erase_memory":
                self._executar_async(
                    "Apagar Memória da Impressora",
                    lambda: self._ews().apagar_memoria_nvram(),
                )
            elif codigo == "memwipe":
                self._executar_async(
                    "Wipe Completo Fora de Serviço (NVRAM)",
                    lambda: self._ews().apagar_fora_de_servico_wipe(),
                )

        btn_exec_reset = ttk.Button(
            f_fab,
            text="⚠️ EXECUTAR RESET DE FÁBRICA",
            command=_executar_reset_selecionado,
            style="TI.Danger.TButton",
        )
        btn_exec_reset.grid(row=0, column=2, sticky="e", pady=4)
        ToolTip(
            btn_exec_reset,
            "Envia o comando HTTP POST oficial de restauração de fábrica para a controladora Lexmark.",
        )

    # ========================================================
    # ABA 4: MOTOR (ENGINE), QUALIDADE E ENERGIA
    # ========================================================

    def _construir_aba_motor_qualidade(self):
        aba = self._criar_aba_rolavel(" ⚙️ Qualidade ")

        # Card 1: Qualidade e Densidade do Toner
        c_qual = self._card(
            aba,
            "Qualidade de Impressão e Densidade do Toner (/config/gen/menu_quality.html)",
            "Regula tonalidade do toner (1 a 10), resolução nativa, brilho, contraste e nitidez de linhas finas.",
        )
        c_qual.columnconfigure(1, weight=1)
        c_qual.columnconfigure(3, weight=1)

        tk.Label(c_qual, text="Tonalidade / Densidade do Toner:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_tonalidade = ttk.Combobox(c_qual, values=list(TONALIDADE_TONER_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_tonalidade.set("Nível 8 (Padrão)")
        self.cb_tonalidade.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_qual, text="Resolução de Impressão:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=1, column=2, sticky="w", pady=4)
        self.cb_resolucao = ttk.Combobox(c_qual, values=list(RESOLUCAO_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_resolucao.set("600 ppp (Padrão Comercial)")
        self.cb_resolucao.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=4)

        tk.Label(c_qual, text="Brilho (-6 a +6):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=0, sticky="w", pady=4)
        self.spin_brilho_imp = tk.Spinbox(c_qual, from_=-6, to=6, width=8, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, relief="flat")
        self.spin_brilho_imp.delete(0, "end")
        self.spin_brilho_imp.insert(0, "0")
        self.spin_brilho_imp.grid(row=2, column=1, sticky="w", padx=(6, 16), pady=4)

        tk.Label(c_qual, text="Contraste (0 a 5):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=2, sticky="w", pady=4)
        self.spin_contraste_imp = tk.Spinbox(c_qual, from_=0, to=5, width=8, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, relief="flat")
        self.spin_contraste_imp.delete(0, "end")
        self.spin_contraste_imp.insert(0, "0")
        self.spin_contraste_imp.grid(row=2, column=3, sticky="w", padx=(6, 0), pady=4)

        self.var_linhas_finas = tk.BooleanVar(value=False)
        tk.Checkbutton(
            c_qual,
            text="Melhorar Linhas Finas (Fine Lines — 2.system.4547)",
            variable=self.var_linhas_finas,
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            selectcolor=self.COR_PAINEL_2,
            activebackground=self.COR_PAINEL,
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=4)

        def _salvar_qualidade():
            alt = {
                "0.system.2320": TONALIDADE_TONER_OPCOES[self.cb_tonalidade.get()],
                "0.system.2190": RESOLUCAO_OPCOES[self.cb_resolucao.get()],
                "0.system.776": str(self.spin_brilho_imp.get()).strip(),
                "0.system.777": str(self.spin_contraste_imp.get()).strip(),
                "2.system.4547": "1" if self.var_linhas_finas.get() else "0",
            }
            return self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/menu_quality.html",
                alt,
                "/cgi-bin/posttest/printer/config/gen/menu_quality.html",
            )

        ttk.Button(
            c_qual,
            text="⚡ GRAVAR QUALIDADE E DENSIDADE NA IMPRESSORA",
            command=lambda: self._executar_async("Gravar Menu Qualidade", _salvar_qualidade),
            style="TI.Primary.TButton",
        ).grid(row=4, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        # Card 2: Modo Econômico, Fusor/Sleep e Hibernação
        c_eco = self._card(
            aba,
            "Modo Econômico, Espera do Fusor e Hibernação (/config/gen/setupgen_timeouts.html)",
            "Controla economia de toner/energia e o tempo até desligar o aquecimento do fusor.",
        )
        c_eco.columnconfigure(1, weight=1)
        c_eco.columnconfigure(3, weight=1)

        tk.Label(c_eco, text="Modo Econômico:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_modo_eco = ttk.Combobox(c_eco, values=list(MODO_ECO_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_modo_eco.set("Desativado (Desempenho Máximo)")
        self.cb_modo_eco.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_eco, text="Limite de Hibernação:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.cb_hibernacao = ttk.Combobox(c_eco, values=list(HIBERNACAO_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_hibernacao.set("3 dias (Padrão)")
        self.cb_hibernacao.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=4)

        tk.Label(c_eco, text="Modo Espera (1–240 min):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=0, sticky="w", pady=4)
        self.entry_standby_min = tk.Entry(c_eco, width=10, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_standby_min.insert(0, "15")
        self.entry_standby_min.grid(row=2, column=1, sticky="w", padx=(6, 16), pady=4)

        tk.Label(c_eco, text="Suspensão Fusor / Sleep (1–240 min):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=2, sticky="w", pady=4)
        self.entry_sleep_min = tk.Entry(c_eco, width=10, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_sleep_min.insert(0, "15")
        self.entry_sleep_min.grid(row=2, column=3, sticky="w", padx=(6, 0), pady=4)

        def _salvar_energia_timeouts():
            ews = self._ews()
            ews.gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/gen_ecomode.html",
                {"0.system.4616": MODO_ECO_OPCOES[self.cb_modo_eco.get()]},
            )
            return ews.gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/setupgen_timeouts.html",
                {
                    "0.system.16928": self.entry_standby_min.get().strip(),
                    "0.system.16625": self.entry_sleep_min.get().strip(),
                    "0.system.5484": HIBERNACAO_OPCOES[self.cb_hibernacao.get()],
                },
                "/cgi-bin/posttest/printer/config/gen/setupgen_timeouts.html",
            )

        ttk.Button(
            c_eco,
            text="⚡ GRAVAR MODO ECONÔMICO E TEMPOS DE FUSOR/HIBERNAÇÃO",
            command=lambda: self._executar_async("Gravar Energia e Timeouts", _salvar_energia_timeouts),
            style="TI.Primary.TButton",
        ).grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        # Card 3: Recuperação de Atolamento (Jam Recovery)
        c_jam = self._card(
            aba,
            "Recuperação de Atolamento e Auto-Continue (/config/gen/setupgen_print_recovery.html)",
            "Define como o motor age após atolamento de papel ou erro de bandeja.",
        )
        c_jam.columnconfigure(1, weight=1)
        c_jam.columnconfigure(3, weight=1)

        tk.Label(c_jam, text="Recuperação de Atolamento:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_jam_rec = ttk.Combobox(c_jam, values=list(RECUPERACAO_ATOLAMENTO_OPCOES.keys()), state="readonly", style="TI.TCombobox")
        self.cb_jam_rec.set("Automática (Padrão)")
        self.cb_jam_rec.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4)

        tk.Label(c_jam, text="Continuar Automático (seg, 0=Desat.):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.entry_autocont = tk.Entry(c_jam, width=10, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_autocont.insert(0, "5")
        self.entry_autocont.grid(row=1, column=3, sticky="w", padx=(6, 0), pady=4)

        def _salvar_jam():
            return self._ews().gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/setupgen_print_recovery.html",
                {
                    "0.system.133": RECUPERACAO_ATOLAMENTO_OPCOES[self.cb_jam_rec.get()],
                    "0.system.78": self.entry_autocont.get().strip(),
                    "0.system.5486": "1",
                },
                "/cgi-bin/posttest/printer/config/gen/setupgen_print_recovery.html",
            )

        ttk.Button(
            c_jam,
            text="⚡ GRAVAR RECUPERAÇÃO DE ATOLAMENTO",
            command=lambda: self._executar_async("Gravar Jam Recovery", _salvar_jam),
            style="TI.Primary.TButton",
        ).grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))

    # ========================================================
    # ABA 5: REDE, SMTP, IDENTIDADE E DIAGNÓSTICO SNMP
    # ========================================================

    def _construir_aba_rede_snmp(self):
        aba = self._criar_aba_rolavel(" 🌐 Rede & SNMP ")

        # Card 1: Identidade do Equipamento (Hostname, Contato, Local, Ativo)
        c_id = self._card(
            aba,
            "Identidade na Placa: Hostname, Patrimônio, Contato e Localização",
            "Grava os dados de identificação diretamente via EWS (/config/gen/general.html e /config/net/ip.html).",
        )
        c_id.columnconfigure(1, weight=1)
        c_id.columnconfigure(3, weight=1)

        tk.Label(c_id, text="Hostname (Rede):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_hostname = tk.Entry(c_id, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_hostname.insert(0, "LEXMARK-TI")
        self.entry_hostname.grid(row=1, column=1, sticky="ew", padx=(6, 16), pady=4, ipady=3)

        tk.Label(c_id, text="Etiqueta de Ativo (Patrimônio):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=2, sticky="w", pady=4)
        self.entry_asset_tag = tk.Entry(c_id, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_asset_tag.grid(row=1, column=3, sticky="ew", padx=(6, 0), pady=4, ipady=3)

        tk.Label(c_id, text="Nome do Contato:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=0, sticky="w", pady=4)
        self.entry_contato = tk.Entry(c_id, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_contato.insert(0, "Suporte TI")
        self.entry_contato.grid(row=2, column=1, sticky="ew", padx=(6, 16), pady=4, ipady=3)

        tk.Label(c_id, text="Localização Física:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=2, sticky="w", pady=4)
        self.entry_localizacao = tk.Entry(c_id, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_localizacao.insert(0, "Bancada Técnica")
        self.entry_localizacao.grid(row=2, column=3, sticky="ew", padx=(6, 0), pady=4, ipady=3)

        def _salvar_identidade():
            ews = self._ews()
            ews.gravar_campos_formulario(
                "/cgi-bin/dynamic/printer/config/gen/general.html",
                {
                    "1.system.1876": self.entry_asset_tag.get().strip(),
                    "1.system.24586": self.entry_contato.get().strip(),
                    "1.system.24587": self.entry_localizacao.get().strip(),
                },
                "/cgi-bin/posttest/printer/config/gen/general.html",
            )
            return ews.gravar_campos_formulario(
                "/cgi-bin/dynamic/config/net/ip.html",
                {"vac.255.IPNAME": self.entry_hostname.get().strip()},
                "/cgi-bin/postpf/cgi-bin/dynamic/config/net/ip.html",
            )

        ttk.Button(
            c_id,
            text="⚡ GRAVAR IDENTIDADE, CONTATO E LOCALIZAÇÃO NA PLACA",
            command=lambda: self._executar_async("Gravar Identidade e Localização", _salvar_identidade),
            style="TI.Primary.TButton",
        ).grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        # Card 2: Modo IP (DHCP vs Estático) e SMTP
        c_ip = self._card(
            aba,
            "Configuração TCP/IP (DHCP / Estático) & Gateway SMTP (/config/net/email.html)",
            "Permite ativar DHCP, fixar IP estático ou configurar o servidor SMTP de disparo de e-mail.",
        )
        c_ip.columnconfigure(1, weight=1)
        c_ip.columnconfigure(3, weight=1)

        self.var_dhcp = tk.BooleanVar(value=True)
        tk.Checkbutton(
            c_ip,
            text="Ativar DHCP Automático (vac.255.IPDHCPENABLE)",
            variable=self.var_dhcp,
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            selectcolor=self.COR_PAINEL_2,
            activebackground=self.COR_PAINEL,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)

        ttk.Button(
            c_ip,
            text="⚡ Aplicar Modo DHCP",
            command=lambda: self._executar_async(
                "Atualizar DHCP",
                lambda: self._ews().gravar_campos_formulario(
                    "/cgi-bin/dynamic/config/net/ip.html",
                    {"vac.255.IPDHCPENABLE": "1" if self.var_dhcp.get() else "0"},
                    "/cgi-bin/postpf/cgi-bin/dynamic/config/net/ip.html",
                ),
            ),
            style="TI.Secondary.TButton",
        ).grid(row=1, column=2, columnspan=2, sticky="e", pady=4)

        tk.Label(c_ip, text="IP Estático:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=0, sticky="w", pady=4)
        self.entry_ip_fixo = tk.Entry(c_ip, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_ip_fixo.insert(0, self.ip_alvo)
        self.entry_ip_fixo.grid(row=2, column=1, sticky="ew", padx=(6, 16), pady=4, ipady=3)

        tk.Label(c_ip, text="Máscara:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=2, sticky="w", pady=4)
        self.entry_mask_fixo = tk.Entry(c_ip, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_mask_fixo.insert(0, "255.255.255.0")
        self.entry_mask_fixo.grid(row=2, column=3, sticky="ew", padx=(6, 0), pady=4, ipady=3)

        tk.Label(c_ip, text="Gateway Padrão:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=3, column=0, sticky="w", pady=4)
        self.entry_gw_fixo = tk.Entry(c_ip, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_gw_fixo.insert(0, "192.168.14.254")
        self.entry_gw_fixo.grid(row=3, column=1, sticky="ew", padx=(6, 16), pady=4, ipady=3)

        ttk.Button(
            c_ip,
            text="📌 Fixar IP Estático",
            command=lambda: self._executar_async(
                "Definir IP Estático",
                lambda: self._ews().gravar_ip_estatico(
                    self.entry_ip_fixo.get(), self.entry_mask_fixo.get(), self.entry_gw_fixo.get()
                ),
            ),
            style="TI.Secondary.TButton",
        ).grid(row=3, column=2, columnspan=2, sticky="ew", pady=4)

        tk.Label(c_ip, text="Gateway SMTP Primário:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=4, column=0, sticky="w", pady=4)
        self.entry_smtp_host = tk.Entry(c_ip, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_smtp_host.insert(0, "smtp.empresa.local")
        self.entry_smtp_host.grid(row=4, column=1, sticky="ew", padx=(6, 16), pady=4, ipady=3)

        tk.Label(c_ip, text="E-mail Remetente:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=4, column=2, sticky="w", pady=4)
        self.entry_smtp_from = tk.Entry(c_ip, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_smtp_from.insert(0, "impressora@empresa.local")
        self.entry_smtp_from.grid(row=4, column=3, sticky="ew", padx=(6, 0), pady=4, ipady=3)

        ttk.Button(
            c_ip,
            text="📧 Gravar Configuração SMTP",
            command=lambda: self._executar_async(
                "Gravar SMTP",
                lambda: self._ews().gravar_campos_formulario(
                    "/cgi-bin/dynamic/printer/config/net/email.html",
                    {
                        "1.system.16510": self.entry_smtp_host.get().strip(),
                        "0.system.16511": "25",
                        "1.system.16515": self.entry_smtp_from.get().strip(),
                    },
                    "/cgi-bin/posttest/printer/config/net/email.html",
                ),
            ),
            style="TI.Primary.TButton",
        ).grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        # Card 3: Diagnóstico de Rede, Ping e Telemetria SNMP Rápida
        c_diag = self._card(
            aba,
            "Diagnóstico de Rede (Ping / Portas) & Telemetria SNMPv2c em Tempo Real",
            "Consulta instantânea de portas abertas, hodômetro, uptime, seriais e texto atual do visor LCD via SNMP.",
        )

        f_db1 = tk.Frame(c_diag, background=self.COR_PAINEL)
        f_db1.grid(row=1, column=0, columnspan=4, sticky="ew")

        ttk.Button(
            f_db1,
            text="📡 Executar Ping ICMP",
            command=lambda: self._executar_async("Ping ICMP", lambda: "\n" + executar_ping(self._ip())),
            style="TI.Secondary.TButton",
        ).pack(side="left", padx=(0, 8), pady=4)

        ttk.Button(
            f_db1,
            text="🔍 Escanear Portas (80, 443, 161, 515, 631, 9100)",
            command=lambda: self._executar_async(
                "Scan de Portas",
                lambda: "\n" + "\n".join(f"  • {k}: {v}" for k, v in escanear_portas_impressora(self._ip()).items()),
            ),
            style="TI.Primary.TButton",
        ).pack(side="left", padx=(0, 8), pady=4)

        def _telemetria_snmp_completa():
            ip = self._ip()
            com = self.combo_community.get()
            oids = [
                ("Modelo / Firmware (sysDescr)", "1.3.6.1.2.1.1.1.0"),
                ("Hostname (sysName)", "1.3.6.1.2.1.1.5.0"),
                ("Localização (sysLocation)", "1.3.6.1.2.1.1.6.0"),
                ("Tempo Ligada (sysUpTime)", "1.3.6.1.2.1.1.3.0"),
                ("Serial Chassi", "1.3.6.1.2.1.43.5.1.1.17.1"),
                ("Hodômetro Total (Páginas)", "1.3.6.1.2.1.43.10.2.1.4.1.1"),
                ("Texto no Visor LCD", "1.3.6.1.2.1.43.16.5.1.2.1.1"),
                ("Toner Atual / Capacidade", "1.3.6.1.2.1.43.11.1.1.9.1.1"),
            ]
            linhas = [""]
            for nome, oid in oids:
                try:
                    val = snmp_get(ip, oid, comunidade=com)
                except Exception as e:
                    val = f"Erro ({e})"
                linhas.append(f"  • {nome:<28}: {val}")
            return "\n".join(linhas)

        ttk.Button(
            f_db1,
            text="📊 Ler Telemetria SNMP Completa",
            command=lambda: self._executar_async("Telemetria SNMPv2c", _telemetria_snmp_completa),
            style="TI.Primary.TButton",
        ).pack(side="left", pady=4)

    # ========================================================
    # ABA 6: INJEÇÃO DE ARQUIVOS E DICIONÁRIO PJL / SNMP LIVRE
    # ========================================================

    def _construir_aba_arquivos_dicionario(self):
        aba = self._criar_aba_rolavel(" 💾 Firmware & PJL ")

        # Card 1: Envio de Firmware (.fls / .bin) e Macros
        c_fw = self._card(
            aba,
            "Injeção de Firmware (.fls / .bin) e Macros de Bancada",
            "Envia arquivos de atualização/downgrade de firmware via HTTP Code Update ou streaming direto na porta RAW 9100.",
        )
        c_fw.columnconfigure(1, weight=1)

        tk.Label(c_fw, text="Arquivo (.fls / .bin / .pjl):", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_arq_fw = tk.Entry(c_fw, bg=self.COR_PAINEL_2, fg=self.COR_TEXTO, insertbackground="#ffffff", relief="flat")
        self.entry_arq_fw.grid(row=1, column=1, sticky="ew", padx=8, pady=4, ipady=3)

        def _procurar_fw():
            arq = filedialog.askopenfilename(
                parent=self.root,
                title="Selecionar Arquivo de Firmware ou Macro",
                filetypes=[("Firmware / PJL", "*.fls *.bin *.pjl *.prn *.ucf *.xml"), ("Todos os arquivos", "*.*")],
            )
            if arq:
                self.entry_arq_fw.delete(0, "end")
                self.entry_arq_fw.insert(0, arq)

        ttk.Button(c_fw, text="📂 Selecionar...", command=_procurar_fw, style="TI.Secondary.TButton").grid(row=1, column=2, padx=(0, 8))

        self.barra_progresso_fw = ttk.Progressbar(c_fw, maximum=100, value=0)
        self.barra_progresso_fw.grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)

        f_fw_btns = tk.Frame(c_fw, background=self.COR_PAINEL)
        f_fw_btns.grid(row=3, column=0, columnspan=3, sticky="ew")

        def _enviar_fw_raw9100():
            caminho = self.entry_arq_fw.get().strip()
            if not caminho:
                raise ValueError("Selecione um arquivo primeiro.")
            def _prog(enviados, total):
                pct = (enviados / total * 100) if total else 100
                self.root.after(0, lambda: self.barra_progresso_fw.configure(value=pct))
            total_b = injetar_arquivo_raw(self._ip(), caminho, progresso_cb=_prog)
            return f"Transmitidos {total_b:,} bytes via porta RAW 9100."

        ttk.Button(
            f_fw_btns,
            text="🚀 Enviar via Porta RAW 9100 (Stream Direto)",
            command=lambda: self._executar_async("Injeção RAW 9100", _enviar_fw_raw9100),
            style="TI.Primary.TButton",
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            f_fw_btns,
            text="🌐 Enviar Firmware via HTTP EWS (Code Update)",
            command=lambda: self._executar_async(
                "Upload HTTP Firmware",
                lambda: self._ews().enviar_firmware_http(self.entry_arq_fw.get().strip()),
            ),
            style="TI.Secondary.TButton",
        ).pack(side="left")

        # Card 2: Dicionário Categorizado e Editável PJL / SNMP
        c_dic = self._card(
            aba,
            "Dicionário Categorizado e Terminal Livre PJL / SNMP",
            "Selecione uma categoria e um comando pronto para carregar no editor, veja a explicação técnica e dispare.",
        )
        c_dic.columnconfigure(1, weight=1)

        tk.Label(c_dic, text="Categoria:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=1, column=0, sticky="w", pady=4)
        self.cb_cat_dic = ttk.Combobox(c_dic, values=list(DICIONARIO_COMANDOS.keys()), state="readonly", style="TI.TCombobox")
        self.cb_cat_dic.grid(row=1, column=1, sticky="ew", padx=8, pady=4)

        tk.Label(c_dic, text="Comando / OID:", bg=self.COR_PAINEL, fg=self.COR_TEXTO).grid(row=2, column=0, sticky="w", pady=4)
        self.cb_item_dic = ttk.Combobox(c_dic, state="readonly", style="TI.TCombobox")
        self.cb_item_dic.grid(row=2, column=1, sticky="ew", padx=8, pady=4)

        self.lbl_explicacao_dic = tk.Label(
            c_dic,
            text="Selecione um comando acima para ver o que ele faz.",
            bg=self.COR_PAINEL_2,
            fg="#79c0ff",
            font=("Segoe UI", 9),
            anchor="w",
            padx=10,
            pady=6,
        )
        self.lbl_explicacao_dic.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)

        tk.Label(c_dic, text="Comando / OID Editável:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=4, column=0, sticky="w", pady=4)
        self.entry_cmd_livre = tk.Entry(
            c_dic,
            font=("Consolas", 10, "bold"),
            bg=self.COR_PAINEL_2,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
        )
        self.entry_cmd_livre.insert(0, "INFO STATUS")
        self.entry_cmd_livre.grid(row=4, column=1, sticky="ew", padx=8, pady=4, ipady=4)

        self.var_encapsular_job = tk.BooleanVar(value=True)
        tk.Checkbutton(
            c_dic,
            text="Encapsular PJL com @PJL JOB / @PJL EOJ",
            variable=self.var_encapsular_job,
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            selectcolor=self.COR_PAINEL_2,
            activebackground=self.COR_PAINEL,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=2)

        def _ao_mudar_categoria(event=None):
            cat = self.cb_cat_dic.get()
            itens = DICIONARIO_COMANDOS.get(cat, [])
            self.cb_item_dic["values"] = [f"[{proto}] {cmd} — {desc[:45]}..." for cmd, proto, desc in itens]
            if itens:
                self.cb_item_dic.current(0)
                _ao_mudar_item()

        def _ao_mudar_item(event=None):
            cat = self.cb_cat_dic.get()
            itens = DICIONARIO_COMANDOS.get(cat, [])
            idx = self.cb_item_dic.current()
            if 0 <= idx < len(itens):
                cmd, proto, desc = itens[idx]
                self.entry_cmd_livre.delete(0, "end")
                self.entry_cmd_livre.insert(0, cmd)
                self.lbl_explicacao_dic.config(text=f"[{proto}] {desc}")

        self.cb_cat_dic.bind("<<ComboboxSelected>>", _ao_mudar_categoria)
        self.cb_item_dic.bind("<<ComboboxSelected>>", _ao_mudar_item)
        self.cb_cat_dic.current(0)
        _ao_mudar_categoria()

        f_disp = tk.Frame(c_dic, background=self.COR_PAINEL)
        f_disp.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Button(
            f_disp,
            text="⚡ Disparar como Comando PJL (Porta 9100)",
            command=lambda: self._executar_async(
                f"PJL: {self.entry_cmd_livre.get().strip()}",
                lambda: "\n" + enviar_pjl(
                    self._ip(),
                    [self.entry_cmd_livre.get().strip()],
                    encapsular_job=self.var_encapsular_job.get(),
                ),
            ),
            style="TI.Primary.TButton",
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            f_disp,
            text="🔍 Consultar como OID SNMP GET (Porta 161)",
            command=lambda: self._executar_async(
                f"SNMP GET {self.entry_cmd_livre.get().strip()}",
                lambda: snmp_get(self._ip(), self.entry_cmd_livre.get().strip(), comunidade=self.combo_community.get()),
            ),
            style="TI.Secondary.TButton",
        ).pack(side="left")

    # ========================================================
    # SINCRONIZAÇÃO COMPLETA DA IMPRESSORA -> INTERFACE
    # ========================================================

    def _sincronizar_tudo_da_maquina(self):
        """
        Lê os formulários atuais da impressora via HTTP GET e atualiza
        os campos de todas as abas na thread principal do Tkinter.
        """
        def _ler():
            ews = self._ews()
            dados_lidos = {}
            paginas = {
                "papel": "/cgi-bin/dynamic/printer/config/gen/papermenu.html",
                "icones": "/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html",
                "geral": "/cgi-bin/dynamic/printer/config/gen/general.html",
                "qualidade": "/cgi-bin/dynamic/printer/config/gen/menu_quality.html",
                "eco": "/cgi-bin/dynamic/printer/config/gen/gen_ecomode.html",
                "timeouts": "/cgi-bin/dynamic/printer/config/gen/setupgen_timeouts.html",
                "jam": "/cgi-bin/dynamic/printer/config/gen/setupgen_print_recovery.html",
            }
            for chave, path in paginas.items():
                try:
                    _, _, _, mapa = ews.ler_formulario(path)
                    dados_lidos[chave] = mapa
                except Exception as e:
                    dados_lidos[chave] = {"_erro": str(e)}

            def _aplicar_ui():
                # 1. Papel
                mp = dados_lidos.get("papel", {})
                if "0.system.48" in mp:
                    self.cb_origem_padrao.set(_chave_por_valor(ORIGEM_PADRAO_OPCOES, mp["0.system.48"], self.cb_origem_padrao.get()))
                if "0.system.1088" in mp:
                    self.cb_config_mf.set(_chave_por_valor(CONFIG_MF_OPCOES, mp["0.system.1088"], self.cb_config_mf.get()))
                if "0.system.49" in mp:
                    self.cb_b1_tamanho.set(_chave_por_valor(TAMANHO_PAPEL_OPCOES, mp["0.system.49"], self.cb_b1_tamanho.get()))
                if "0.system.52" in mp:
                    self.cb_b1_tipo.set(_chave_por_valor(TIPO_PAPEL_OPCOES, mp["0.system.52"], self.cb_b1_tipo.get()))
                if "0.system.51" in mp:
                    self.cb_man_tamanho.set(_chave_por_valor(TAMANHO_PAPEL_OPCOES, mp["0.system.51"], self.cb_man_tamanho.get()))
                if "0.system.54" in mp:
                    self.cb_man_tipo.set(_chave_por_valor(TIPO_PAPEL_OPCOES, mp["0.system.54"], self.cb_man_tipo.get()))
                if "0.system.385" in mp:
                    self.cb_subst_tam.set(_chave_por_valor(SUBSTITUIR_TAMANHO_OPCOES, mp["0.system.385"], self.cb_subst_tam.get()))

                # 2. Ícones Home
                mi = dados_lidos.get("icones", {})
                for cid, var in self.vars_icones_home.items():
                    if cid in mi:
                        var.set(mi[cid] == "1")
                if hasattr(self, "_atualizar_simulador_grade"):
                    self._atualizar_simulador_grade()

                # 3. Geral
                mg = dados_lidos.get("geral", {})
                if "0.system.15" in mg:
                    self.cb_idioma.set(_chave_por_valor(IDIOMA_OPCOES, mg["0.system.15"], self.cb_idioma.get()))
                if "0.system.16720" in mg:
                    self.spin_brilho_lcd.delete(0, "end")
                    self.spin_brilho_lcd.insert(0, mg["0.system.16720"])
                if "1.system.1876" in mg:
                    self.entry_asset_tag.delete(0, "end")
                    self.entry_asset_tag.insert(0, mg["1.system.1876"])
                if "1.system.24586" in mg:
                    self.entry_contato.delete(0, "end")
                    self.entry_contato.insert(0, mg["1.system.24586"])
                if "1.system.24587" in mg:
                    self.entry_localizacao.delete(0, "end")
                    self.entry_localizacao.insert(0, mg["1.system.24587"])

                # 4. Qualidade
                mq = dados_lidos.get("qualidade", {})
                if "0.system.2320" in mq:
                    self.cb_tonalidade.set(_chave_por_valor(TONALIDADE_TONER_OPCOES, mq["0.system.2320"], self.cb_tonalidade.get()))
                if "0.system.2190" in mq:
                    self.cb_resolucao.set(_chave_por_valor(RESOLUCAO_OPCOES, mq["0.system.2190"], self.cb_resolucao.get()))
                if "0.system.776" in mq:
                    self.spin_brilho_imp.delete(0, "end")
                    self.spin_brilho_imp.insert(0, mq["0.system.776"])
                if "0.system.777" in mq:
                    self.spin_contraste_imp.delete(0, "end")
                    self.spin_contraste_imp.insert(0, mq["0.system.777"])
                if "2.system.4547" in mq:
                    self.var_linhas_finas.set(mq["2.system.4547"] == "1")

                # 5. Eco e Timeouts
                me = dados_lidos.get("eco", {})
                if "0.system.4616" in me:
                    self.cb_modo_eco.set(_chave_por_valor(MODO_ECO_OPCOES, me["0.system.4616"], self.cb_modo_eco.get()))

                mt = dados_lidos.get("timeouts", {})
                if "0.system.16928" in mt:
                    self.entry_standby_min.delete(0, "end")
                    self.entry_standby_min.insert(0, mt["0.system.16928"])
                if "0.system.16625" in mt:
                    self.entry_sleep_min.delete(0, "end")
                    self.entry_sleep_min.insert(0, mt["0.system.16625"])
                if "0.system.5484" in mt:
                    self.cb_hibernacao.set(_chave_por_valor(HIBERNACAO_OPCOES, mt["0.system.5484"], self.cb_hibernacao.get()))

            self.root.after(0, _aplicar_ui)
            ok_count = sum(1 for v in dados_lidos.values() if "_erro" not in v)
            return f"{ok_count}/{len(paginas)} páginas de configuração EWS lidas e sincronizadas na interface."

        self._executar_async("Sincronizar Configurações Atuais da Máquina", _ler)

    # ========================================================
    # ABA 7: TERMINAL EWS, INSPETOR DE NVRAM & RAW DIRECT
    # ========================================================

    def _construir_aba_terminal_ews_raw(self):
        aba = self._criar_aba_rolavel(" ⚡ Terminal EWS & RAW ")

        # ----------------------------------------------------
        # CARD 1: INSPETOR E MODIFICADOR DE FORMULÁRIOS EWS (NVRAM)
        # ----------------------------------------------------
        c_ews = self._card(
            aba,
            "Inspetor e Modificador Direto de Formulários EWS (NVRAM Lexmark)",
            "Lê qualquer formulário web da impressora, lista todas as variáveis internas e permite alterar e gravar qualquer valor.",
        )
        c_ews.columnconfigure(1, weight=1)

        tk.Label(c_ews, text="Menu / Endpoint EWS:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=4)

        LISTA_ENDPOINTS_EWS = [
            ("Menu Papel (Tamanhos/Tipos)", "/cgi-bin/dynamic/printer/config/gen/papermenu.html"),
            ("Configurações Gerais (Validado)", "/cgi-bin/dynamic/printer/config/gen/general.html"),
            ("Tela Inicial / Botões Visor", "/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html"),
            ("Economia, Sleep e Timeouts", "/cgi-bin/dynamic/printer/config/gen/setupgen_timeouts.html"),
            ("Rede / Portas (Menu Principal)", "/cgi-bin/dynamic/config/net/network.html"),
            ("SNMP e Comunidades", "/cgi-bin/dynamic/config/net/snmp.html"),
            ("E-mail / FTP / Scan to Net", "/cgi-bin/dynamic/printer/config/gen/scan2net.html"),
            ("Configurações de Cópia", "/cgi-bin/dynamic/printer/config/gen/copy.html"),
            ("Configurações de Fax", "/cgi-bin/dynamic/printer/config/gen/faxmode.html"),
            ("Segurança e Autenticação", "/cgi-bin/dynamic/config/secure/security.html"),
            ("Menu de Engenharia SE (Validado)", "/cgi-bin/dynamic/se_index.html"),
            ("SE — ScanManager2 Debug (Scanner)", "/cgi-bin/script/printer/scanmgr"),
            ("SE — Tabela de Alertas NPAP", "/cgi-bin/npapalertpg"),
            ("Importar / Exportar UCF", "/cgi-bin/dynamic/printer/config/gen/importexport.html"),
            ("Informações do Dispositivo", "/cgi-bin/dynamic/printer/config/reports/deviceinfo.html"),
            ("Restaurar Padrões de Fábrica", "/cgi-bin/dynamic/printer/config/secure/printer_reset_options.html"),
        ]

        self.cb_endpoint_ews = ttk.Combobox(
            c_ews,
            values=[f"{nome} — {url}" for nome, url in LISTA_ENDPOINTS_EWS] + ["[Personalizado / Digite a URL abaixo]"],
            state="readonly",
            style="TI.TCombobox",
        )
        self.cb_endpoint_ews.set(f"{LISTA_ENDPOINTS_EWS[0][0]} — {LISTA_ENDPOINTS_EWS[0][1]}")
        self.cb_endpoint_ews.grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=4)

        self.entry_url_ews = tk.Entry(
            c_ews,
            font=("Consolas", 10),
            bg=self.COR_PAINEL_2,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
        )
        self.entry_url_ews.insert(0, LISTA_ENDPOINTS_EWS[0][1])
        self.entry_url_ews.grid(row=2, column=1, sticky="ew", padx=(6, 10), pady=4)

        def _ao_selecionar_endpoint(event=None):
            sel = self.cb_endpoint_ews.get()
            for nome, url in LISTA_ENDPOINTS_EWS:
                if url in sel:
                    self.entry_url_ews.delete(0, "end")
                    self.entry_url_ews.insert(0, url)
                    return

        self.cb_endpoint_ews.bind("<<ComboboxSelected>>", _ao_selecionar_endpoint)

        btn_ler_ews = ttk.Button(
            c_ews,
            text="🔍 Inspecionar Formulário e Variáveis da NVRAM",
            command=self._inspecionar_formulario_ews,
            style="TI.Primary.TButton",
        )
        btn_ler_ews.grid(row=2, column=0, sticky="w", pady=4)

        tree_frame = tk.Frame(c_ews, bg=self.COR_PAINEL)
        tree_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(8, 4))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("nvram_id", "valor_atual", "tipo")
        self.tree_vars_ews = ttk.Treeview(tree_frame, columns=cols, show="headings", height=8, selectmode="browse")
        self.tree_vars_ews.heading("nvram_id", text="Nome da Variável / NVRAM ID")
        self.tree_vars_ews.heading("valor_atual", text="Valor Atual Gravado")
        self.tree_vars_ews.heading("tipo", text="Tipo / Controle")
        self.tree_vars_ews.column("nvram_id", width=260, anchor="w")
        self.tree_vars_ews.column("valor_atual", width=220, anchor="w")
        self.tree_vars_ews.column("tipo", width=140, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_vars_ews.yview)
        self.tree_vars_ews.configure(yscrollcommand=tree_scroll.set)
        self.tree_vars_ews.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")

        edit_frame = tk.Frame(c_ews, bg=self.COR_PAINEL, pady=6)
        edit_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        edit_frame.columnconfigure(1, weight=1)
        edit_frame.columnconfigure(3, weight=1)

        tk.Label(edit_frame, text="Variável:", bg=self.COR_PAINEL, fg=self.COR_TEXTO_SEC, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.entry_edit_var_id = tk.Entry(edit_frame, font=("Consolas", 10), width=24, bg=self.COR_PAINEL_2, fg="#58a6ff", relief="flat")
        self.entry_edit_var_id.grid(row=0, column=1, sticky="ew", padx=(0, 14))

        tk.Label(edit_frame, text="Novo Valor:", bg=self.COR_PAINEL, fg=self.COR_TEXTO_SEC, font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.entry_edit_var_val = tk.Entry(edit_frame, font=("Consolas", 10), width=24, bg=self.COR_PAINEL_2, fg="#3fb950", relief="flat")
        self.entry_edit_var_val.grid(row=0, column=3, sticky="ew", padx=(0, 14))

        def _ao_clicar_item_tree(event=None):
            sel = self.tree_vars_ews.selection()
            if sel:
                vals = self.tree_vars_ews.item(sel[0], "values")
                if vals:
                    self.entry_edit_var_id.delete(0, "end")
                    self.entry_edit_var_id.insert(0, vals[0])
                    self.entry_edit_var_val.delete(0, "end")
                    self.entry_edit_var_val.insert(0, vals[1])

        self.tree_vars_ews.bind("<<TreeviewSelect>>", _ao_clicar_item_tree)

        btn_gravar_var = ttk.Button(
            edit_frame,
            text="⚡ Gravar Esta Variável na NVRAM",
            command=self._gravar_variavel_ews_individual,
            style="TI.Primary.TButton",
        )
        btn_gravar_var.grid(row=0, column=4, sticky="e")

        # ----------------------------------------------------
        # CARD 2: TERMINAL PJL RAW 9100 INTERATIVO
        # ----------------------------------------------------
        c_pjl = self._card(
            aba,
            "Terminal Interativo de Comandos PJL (Porta RAW 9100)",
            "Injeção direta de comandos @PJL no interpretador da controladora de impressão.",
        )
        c_pjl.columnconfigure(1, weight=1)

        quick_frame = tk.Frame(c_pjl, bg=self.COR_PAINEL)
        quick_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        comandos_rapidos = [
            ("INFO ID", "INFO ID"),
            ("INFO STATUS", "INFO STATUS"),
            ("INFO CONFIG", "INFO CONFIG"),
            ("INFO MEMORY", "INFO MEMORY"),
            ("INFO VARIABLES", "INFO VARIABLES"),
            ("PAGECOUNT", "INFO PAGECOUNT"),
            ("MENSAGEM LCD", 'RDYMSG DISPLAY="SUPORTE TI"'),
            ("LIMPAR LCD", 'RDYMSG DISPLAY=""'),
        ]

        def _definir_pjl_rapido(cmd):
            self.entry_pjl_cmd.delete(0, "end")
            self.entry_pjl_cmd.insert(0, cmd)
            self._enviar_comando_pjl_terminal()

        for idx, (label_btn, cmd_txt) in enumerate(comandos_rapidos):
            b = ttk.Button(
                quick_frame,
                text=label_btn,
                command=lambda c=cmd_txt: _definir_pjl_rapido(c),
                style="TI.Secondary.TButton",
            )
            b.pack(side="left", padx=(0, 5))

        tk.Label(c_pjl, text="Comando PJL:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.entry_pjl_cmd = tk.Entry(
            c_pjl,
            font=("Consolas", 11, "bold"),
            bg=self.COR_PAINEL_2,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
        )
        self.entry_pjl_cmd.insert(0, "INFO STATUS")
        self.entry_pjl_cmd.grid(row=2, column=1, sticky="ew", padx=(6, 10), pady=4)
        self.entry_pjl_cmd.bind("<Return>", lambda e: self._enviar_comando_pjl_terminal())

        btn_enviar_pjl = ttk.Button(
            c_pjl,
            text="⚡ Enviar PJL na Porta 9100",
            command=self._enviar_comando_pjl_terminal,
            style="TI.Primary.TButton",
        )
        btn_enviar_pjl.grid(row=2, column=2, sticky="e", pady=4)

        self.txt_pjl_resposta = scrolledtext.ScrolledText(
            c_pjl,
            wrap="word",
            font=("Consolas", 9),
            height=6,
            background="#090c10",
            foreground="#3fb950",
            relief="flat",
        )
        self.txt_pjl_resposta.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(6, 0))

        # ----------------------------------------------------
        # CARD 3: AUDITORIA E CONSULTA DIRETA SNMPv2c
        # ----------------------------------------------------
        c_snmp = self._card(
            aba,
            "Auditoria e Consulta Direta SNMPv2c (Porta UDP 161)",
            "Consulta e gravação de MIBs públicas e proprietárias Lexmark via protocolo puro UDP.",
        )
        c_snmp.columnconfigure(1, weight=1)

        tk.Label(c_snmp, text="OID:", bg=self.COR_PAINEL, fg=self.COR_TEXTO, font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=4)
        self.entry_snmp_oid = ttk.Combobox(
            c_snmp,
            values=[
                "1.3.6.1.2.1.1.1.0 (sysDescr)",
                "1.3.6.1.2.1.1.5.0 (sysName)",
                "1.3.6.1.2.1.1.6.0 (sysLocation)",
                "1.3.6.1.2.1.1.4.0 (sysContact)",
                "1.3.6.1.2.1.1.3.0 (sysUpTime)",
                "1.3.6.1.2.1.43.5.1.1.17.1 (prtGeneralSerialNumber)",
                "1.3.6.1.2.1.43.10.2.1.4.1.1 (prtMarkerLifeCount)",
                "1.3.6.1.2.1.43.16.5.1.2.1.1 (prtConsoleDisplayBufferText)",
            ],
            style="TI.TCombobox",
            font=("Consolas", 10),
        )
        self.entry_snmp_oid.set("1.3.6.1.2.1.1.1.0 (sysDescr)")
        self.entry_snmp_oid.grid(row=1, column=1, sticky="ew", padx=(6, 10), pady=4)

        botoes_snmp = tk.Frame(c_snmp, bg=self.COR_PAINEL)
        botoes_snmp.grid(row=1, column=2, sticky="e")

        btn_snmp_get = ttk.Button(
            botoes_snmp,
            text="🔍 SNMP GET",
            command=self._consultar_snmp_terminal,
            style="TI.Primary.TButton",
        )
        btn_snmp_get.pack(side="left", padx=(0, 5))

        btn_snmp_scanner = ttk.Button(
            botoes_snmp,
            text="📡 Scan de Portas",
            command=self._escanear_portas_terminal,
            style="TI.Secondary.TButton",
        )
        btn_snmp_scanner.pack(side="left")

        self.lbl_snmp_resultado = tk.Label(
            c_snmp,
            text="Resultado SNMP: Aguardando consulta...",
            bg=self.COR_PAINEL_2,
            fg=self.COR_TEXTO,
            font=("Consolas", 9),
            anchor="w",
            padx=10,
            pady=8,
            relief="solid",
            bd=1,
        )
        self.lbl_snmp_resultado.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

    # ========================================================
    # HANDLERS DO TERMINAL EWS, PJL E SNMP
    # ========================================================

    def _inspecionar_formulario_ews(self):
        url = self.entry_url_ews.get().strip()
        if not url:
            messagebox.showwarning("Terminal EWS", "Informe a URL ou selecione um endpoint.", parent=self.root)
            return

        def _tarefa():
            action, method, pares, mapa = self._ews().ler_formulario(url)
            def _aplicar():
                for item in self.tree_vars_ews.get_children():
                    self.tree_vars_ews.delete(item)
                for k, v in pares:
                    self.tree_vars_ews.insert("", "end", values=(k, v, "Input / Select"))
            self.root.after(0, _aplicar)
            return f"Formulário '{url}' lido com sucesso: {len(pares)} variáveis encontradas (Action: {action})."

        self._executar_async("Inspecionar Formulário EWS", _tarefa)

    def _gravar_variavel_ews_individual(self):
        url = self.entry_url_ews.get().strip()
        var_id = self.entry_edit_var_id.get().strip()
        var_val = self.entry_edit_var_val.get().strip()

        if not var_id:
            messagebox.showwarning("Gravar NVRAM", "Selecione uma variável na tabela ou digite o ID.", parent=self.root)
            return

        def _tarefa():
            res = self._ews().gravar_campos_formulario(url, {var_id: var_val})
            def _atualizar_tree():
                for item in self.tree_vars_ews.get_children():
                    vals = self.tree_vars_ews.item(item, "values")
                    if vals and vals[0] == var_id:
                        self.tree_vars_ews.item(item, values=(vals[0], var_val, vals[2]))
                        break
            self.root.after(0, _atualizar_tree)
            return f"Variável '{var_id}' alterada para '{var_val}' na NVRAM da impressora (HTTP {res.get('status_code', 200)})."

        self._executar_async(f"Gravar {var_id} = {var_val}", _tarefa)

    def _enviar_comando_pjl_terminal(self):
        cmd = self.entry_pjl_cmd.get().strip()
        if not cmd:
            return

        def _tarefa():
            resposta = enviar_pjl(self._ip(), [cmd], aguardar_resposta=True, timeout=5.0)
            def _atualizar():
                self.txt_pjl_resposta.delete("1.0", "end")
                self.txt_pjl_resposta.insert("end", resposta.strip() if resposta.strip() else "[Comando PJL enviado sem retorno textual do motor]")
            self.root.after(0, _atualizar)
            return f"PJL '{cmd}' enviado com sucesso."

        self._executar_async(f"Enviar PJL {cmd[:25]}", _tarefa)

    def _consultar_snmp_terminal(self):
        oid_raw = self.entry_snmp_oid.get().strip()
        bare_oid = oid_raw.split()[0].strip()
        comunidade = self.combo_community.get().strip() or "public"

        def _tarefa():
            val = snmp_get(self._ip(), bare_oid, comunidade=comunidade, timeout=3.5)
            def _atualizar():
                self.lbl_snmp_resultado.config(text=f"SNMP [{bare_oid}] = {val}", fg="#3fb950")
            self.root.after(0, _atualizar)
            return f"SNMP GET {bare_oid} = {val}"

        self._executar_async(f"SNMP GET {bare_oid}", _tarefa)

    def _escanear_portas_terminal(self):
        def _tarefa():
            portas = escanear_portas_impressora(self._ip())
            def _atualizar():
                res_txt = " | ".join(f"{p}: {st.split()[0]}" for p, st in portas.items())
                self.lbl_snmp_resultado.config(text=f"Portas ({self._ip()}): {res_txt}", fg="#58a6ff")
                for p, st in portas.items():
                    self._log(f"  • {p}: {st}")
            self.root.after(0, _atualizar)
            return f"{len(portas)} portas analisadas na impressora."

        self._executar_async("Scanner de Portas de Impressão", _tarefa)

    # ========================================================
    # ABA 8: AGENTE TI — COMANDOS EM LINGUAGEM NATURAL (ANTI-BRICK)
    # ========================================================

    def _construir_aba_agente(self):
        self.agente_ti = TerminalTIAgent()
        cfg = self.agente_ti.config

        outer = ttk.Frame(self.notebook, style="TI.TFrame")
        self.notebook.add(outer, text=" 🤖 Agente TI ")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        # 1. Banner Superior: Blindagem Anti-Brick + Modo Offline / Gemini Cloud
        topo_ag = tk.Frame(
            outer,
            background=self.COR_PAINEL,
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        topo_ag.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        topo_ag.columnconfigure(0, weight=1)

        tk.Label(
            topo_ag,
            text="🛡️ PROTEÇÃO EM 3 NÍVEIS — Seguras: diretas | Críticas (Firmware, Wipe, NVRAM, Fábrica, IP): Pré-Checagem + Alerta + PIN | FSDELETE: bloqueado",
            background=self.COR_PAINEL,
            foreground=self.COR_VERDE,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        self.var_agente_llm = tk.BooleanVar(value=bool(cfg.get("usar_llm", False)))
        chk_llm = tk.Checkbutton(
            topo_ag,
            text="☁️ Modo Híbrido: usar Gemini API na nuvem (0% CPU local) para perguntas livres",
            variable=self.var_agente_llm,
            command=self._alternar_modo_llm_agente,
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            selectcolor=self.COR_PAINEL_2,
            activebackground=self.COR_PAINEL,
            activeforeground=self.COR_TEXTO,
            font=("Segoe UI", 9),
        )
        chk_llm.grid(row=1, column=0, sticky="w")

        self.lbl_status_llm = tk.Label(
            topo_ag,
            text=self._texto_status_llm(),
            background=self.COR_PAINEL,
            foreground=self.COR_DESTAQUE,
            font=("Segoe UI", 8, "bold"),
        )
        self.lbl_status_llm.grid(row=1, column=1, padx=10, sticky="e")

        ttk.Button(
            topo_ag,
            text="🔑 Configurar API Key",
            command=self._abrir_config_api_agente,
            style="TI.Secondary.TButton",
        ).grid(row=1, column=2, sticky="e")

        # 2. Barra de Atalhos Rápidos de 1 Clique
        barra_chips = tk.Frame(outer, background=self.COR_FUNDO)
        barra_chips.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

        atalhos = [
            ("📊 Diagnóstico", "status completo"),
            ("🔬 Modo Scanner", "ver modo do scanner"),
            ("🎨 Ler Tela Inicial", "ver tela inicial"),
            ("🖨️ Relatório Bancada (9100)", "imprimir relatorio de bancada"),
            ("🔎 Varrer Rede Lexmark", "varrer rede"),
            ("❓ Ajuda", "ajuda"),
        ]
        for rotulo, cmd_txt in atalhos:
            ttk.Button(
                barra_chips,
                text=rotulo,
                command=lambda c=cmd_txt: self._enviar_comando_agente(c),
                style="TI.Secondary.TButton",
            ).pack(side="left", padx=(0, 6), pady=2)

        # 3. Área de Chat Dark Mode
        chat_box = tk.Frame(
            outer,
            background=self.COR_PAINEL,
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
            padx=8,
            pady=8,
        )
        chat_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 8))
        chat_box.columnconfigure(0, weight=1)
        chat_box.rowconfigure(0, weight=1)

        self.txt_chat_agente = scrolledtext.ScrolledText(
            chat_box,
            wrap="word",
            font=("Consolas", 10),
            background="#0b0f14",
            foreground=self.COR_TEXTO,
            insertbackground="#ffffff",
            relief="flat",
            padx=10,
            pady=10,
        )
        self.txt_chat_agente.grid(row=0, column=0, sticky="nsew")
        self.txt_chat_agente.tag_config("user", foreground="#58a6ff", font=("Consolas", 10, "bold"))
        self.txt_chat_agente.tag_config("meta", foreground="#8b949e", font=("Consolas", 8, "italic"))
        self.txt_chat_agente.tag_config("ok", foreground="#e6edf3")
        self.txt_chat_agente.tag_config("warn", foreground="#d29922")
        self.txt_chat_agente.tag_config("err", foreground="#f85149")

        self._escrever_chat_agente(
            "meta",
            "🤖 Agente TI pronto! Digite comandos em português abaixo ou clique em um atalho.\n"
            "Exemplos: 'como está a 134?', 'ver modo do scanner', 'coloca \"EM TESTE\" no visor', "
            "'ocultar fax', 'imprimir relatório de bancada', 'ajuda'.\n\n",
        )
        self.txt_chat_agente.configure(state="disabled")

        # 4. Caixa de Entrada de Comandos
        barra_input = tk.Frame(outer, background=self.COR_FUNDO)
        barra_input.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 10))
        barra_input.columnconfigure(0, weight=1)

        self.entry_agente_cmd = tk.Entry(
            barra_input,
            font=("Consolas", 11),
            background=self.COR_PAINEL_2,
            foreground="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
        )
        self.entry_agente_cmd.grid(row=0, column=0, sticky="ew", ipady=7, padx=(0, 8))
        self.entry_agente_cmd.bind("<Return>", lambda _e: self._enviar_comando_agente())

        self.btn_enviar_agente = ttk.Button(
            barra_input,
            text="▶ ENVIAR COMANDO",
            command=self._enviar_comando_agente,
            style="TI.Primary.TButton",
        )
        self.btn_enviar_agente.grid(row=0, column=1)

    def _texto_status_llm(self) -> str:
        cfg = self.agente_ti.recarregar_config()
        tem_chave = bool(cfg.get("api_key"))
        ativo = bool(cfg.get("usar_llm"))
        if ativo and tem_chave:
            return f"☁️ Gemini Ativo ({cfg.get('modelo_gemini', 'gemini-flash-lite-latest')})"
        if ativo and not tem_chave:
            return "⚠️ Sem API Key (rodando Offline)"
        return "⚡ Motor Local Offline (0% CPU)"

    def _alternar_modo_llm_agente(self):
        cfg = self.agente_ti.recarregar_config()
        salvar_config_agente(
            api_key=cfg.get("api_key", ""),
            usar_llm=self.var_agente_llm.get(),
            modelo_gemini=cfg.get("modelo_gemini", "gemini-flash-lite-latest"),
        )
        self.lbl_status_llm.config(text=self._texto_status_llm())

    def _abrir_config_api_agente(self):
        cfg = self.agente_ti.recarregar_config()
        win = tk.Toplevel(self.root)
        win.title("Configurar API Google Gemini (Nuvem — 0% CPU local)")
        win.geometry("580x360")
        win.configure(background=self.COR_FUNDO)
        win.transient(self.root)
        win.grab_set()

        frame = tk.Frame(win, background=self.COR_PAINEL, padx=16, pady=14)
        frame.pack(fill="both", expand=True, padx=12, pady=12)
        frame.columnconfigure(0, weight=1)

        tk.Label(
            frame,
            text="Chave API do Google AI Studio (processa na nuvem sem pesar em PCs fracos):",
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        ttk.Button(
            frame,
            text="🌐 Abrir Google AI Studio (Gerar Chave Grátis)",
            command=lambda: webbrowser.open("https://aistudio.google.com/apikey"),
            style="TI.Secondary.TButton",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        ent_key = tk.Entry(
            frame,
            show="*",
            font=("Consolas", 10),
            bg=self.COR_PAINEL_2,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            highlightbackground=self.COR_BORDA,
            highlightthickness=1,
        )
        ent_key.insert(0, cfg.get("api_key", ""))
        ent_key.grid(row=2, column=0, sticky="ew", ipady=5, pady=(0, 4))

        var_mostrar = tk.BooleanVar(value=False)
        tk.Checkbutton(
            frame,
            text="Mostrar chave",
            variable=var_mostrar,
            command=lambda: ent_key.configure(show="" if var_mostrar.get() else "*"),
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO_SEC,
            selectcolor=self.COR_PAINEL_2,
            activebackground=self.COR_PAINEL,
            font=("Segoe UI", 8),
        ).grid(row=3, column=0, sticky="w", pady=(0, 10))

        tk.Label(
            frame,
            text="Modelo Google Gemini (padrão rápido e com nível gratuito no AI Studio):",
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO_SEC,
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=4, column=0, sticky="w", pady=(0, 4))

        cb_mod = ttk.Combobox(
            frame,
            values=("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash", "gemini-pro-latest"),
            style="TI.TCombobox",
        )
        cb_mod.set(cfg.get("modelo_gemini", "gemini-flash-lite-latest"))
        cb_mod.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        lbl_teste = tk.Label(
            frame,
            text="Salvo localmente em config_agente.json (ignorado pelo Git).",
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO_SEC,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=520,
        )
        lbl_teste.grid(row=6, column=0, sticky="ew", pady=(0, 12))

        barra_btns = tk.Frame(frame, background=self.COR_PAINEL)
        barra_btns.grid(row=7, column=0, sticky="ew")

        def _testar():
            chave = ent_key.get().strip()
            modelo = cb_mod.get().strip() or "gemini-flash-lite-latest"
            lbl_teste.config(text="⏳ Testando conexão com Google Gemini...", fg=self.COR_AMARELO)

            def _w():
                ok, msg = testar_chave_gemini(chave, modelo)
                win.after(0, lambda: lbl_teste.config(text=msg, fg=self.COR_VERDE if ok else self.COR_VERMELHO))

            threading.Thread(target=_w, daemon=True).start()

        def _salvar():
            chave = ent_key.get().strip()
            modelo = cb_mod.get().strip() or "gemini-flash-lite-latest"
            usar = True if chave else False
            salvar_config_agente(chave, usar, modelo)
            self.var_agente_llm.set(usar)
            self.lbl_status_llm.config(text=self._texto_status_llm())
            self._log("🔑 Configuração da API Google Gemini atualizada (salva em config_agente.json).")
            win.destroy()

        ttk.Button(barra_btns, text="🧪 Testar Conexão", command=_testar, style="TI.Secondary.TButton").pack(side="left")
        ttk.Button(barra_btns, text="💾 Salvar e Ativar", command=_salvar, style="TI.Primary.TButton").pack(side="right")

    def _escrever_chat_agente(self, tag: str, texto: str):
        self.txt_chat_agente.configure(state="normal")
        self.txt_chat_agente.insert("end", texto, tag)
        self.txt_chat_agente.see("end")
        self.txt_chat_agente.configure(state="disabled")

    def _enviar_comando_agente(self, comando_forcado: Optional[str] = None):
        cmd = (comando_forcado if comando_forcado is not None else self.entry_agente_cmd.get()).strip()
        if not cmd:
            return
        if comando_forcado is None:
            self.entry_agente_cmd.delete(0, "end")

        agora = datetime.now().strftime("%H:%M:%S")
        ip_atual = self._ip()
        comunidade = self.combo_community.get().strip() or "public"

        self._escrever_chat_agente("user", f"[{agora}] Você ({ip_atual}) > {cmd}\n")
        self._status(f"🤖 Agente executando: {cmd[:40]}...", self.COR_AMARELO)
        self.btn_enviar_agente.configure(state="disabled")

        def _worker():
            resp = self.agente_ti.processar_comando(cmd, ip_padrao=ip_atual, community=comunidade)

            def _concluir():
                if resp.motor == "CONFIRMACAO-CRITICA":
                    tag_cor = "warn"
                elif resp.ok:
                    tag_cor = "ok"
                elif resp.motor == "ANTI-BRICK":
                    tag_cor = "warn"
                else:
                    tag_cor = "err"

                self._escrever_chat_agente(
                    "meta",
                    f"   [{resp.motor} | ação: {resp.acao}]\n",
                )
                self._escrever_chat_agente(tag_cor, f"{resp.mensagem}\n\n")
                self._log(f"🤖 Agente [{resp.motor}/{resp.acao}]: {'OK' if resp.ok else 'BLOQUEADO/ERRO'}")
                self._status("● Pronto para operar", self.COR_VERDE if resp.ok else self.COR_AMARELO)
                self.btn_enviar_agente.configure(state="normal")

                if resp.confirmacao_pendente is not None:
                    self._abrir_modal_confirmacao_critica(resp.confirmacao_pendente)

            self.root.after(0, _concluir)

        threading.Thread(target=_worker, daemon=True).start()

    def _abrir_modal_confirmacao_critica(self, pending):
        """
        Janela modal de alta visibilidade exibindo alvo SNMP, parâmetros,
        consequências detalhadas e exigindo digitação do PIN de 4 dígitos
        para destravar a execução de operações críticas.
        """
        win = tk.Toplevel(self.root)
        win.title("⚠️ CONFIRMAÇÃO DE OPERAÇÃO CRÍTICA — TERMINAL TI")
        win.geometry("620x440")
        win.configure(background="#1a0d0e")
        win.transient(self.root)
        win.grab_set()

        card = tk.Frame(
            win,
            background=self.COR_PAINEL,
            highlightbackground=self.COR_VERMELHO,
            highlightthickness=2,
            padx=18,
            pady=14,
        )
        card.pack(fill="both", expand=True, padx=14, pady=14)
        card.columnconfigure(0, weight=1)

        tk.Label(
            card,
            text=f"⚠️ OPERAÇÃO CRÍTICA: {pending.titulo}",
            bg=self.COR_PAINEL,
            fg=self.COR_VERMELHO,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
            wraplength=560,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        info_alvo = (
            f"Impressora Alvo : {pending.ip}\n"
            f"Modelo / Serial : {pending.modelo_detectado}  |  Serial: {pending.serial_detectado}\n"
            f"Parâmetros      : {pending.resumo_parametros}"
        )
        tk.Label(
            card,
            text=info_alvo,
            bg="#0b0f14",
            fg="#79c0ff",
            font=("Consolas", 9),
            anchor="w",
            justify="left",
            padx=10,
            pady=8,
            wraplength=540,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        tk.Label(
            card,
            text="CONSEQUÊNCIAS E ALERTAS DE SEGURANÇA:",
            bg=self.COR_PAINEL,
            fg=self.COR_AMARELO,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))

        riscos_txt = "\n".join(f"• {r}" for r in pending.riscos)
        tk.Label(
            card,
            text=riscos_txt,
            bg=self.COR_PAINEL,
            fg=self.COR_TEXTO,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=555,
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        tk.Label(
            card,
            text=f"Digite o PIN  {pending.token}  abaixo para destravar a execução (expira em {pending.segundos_restantes()}s):",
            bg=self.COR_PAINEL,
            fg=self.COR_VERDE,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 6))

        var_pin = tk.StringVar()
        ent_pin = tk.Entry(
            card,
            textvariable=var_pin,
            font=("Consolas", 13, "bold"),
            width=12,
            bg=self.COR_PAINEL_2,
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            justify="center",
        )
        ent_pin.grid(row=5, column=0, sticky="w", ipady=5, pady=(0, 14))

        botoes = tk.Frame(card, background=self.COR_PAINEL)
        botoes.grid(row=6, column=0, columnspan=2, sticky="ew")

        def _cancelar():
            win.destroy()
            self._enviar_comando_agente("CANCELAR")

        def _confirmar():
            pin = var_pin.get().strip()
            win.destroy()
            self._enviar_comando_agente(f"CONFIRMAR {pin}")

        btn_cancel = ttk.Button(
            botoes,
            text="❎ Cancelar (Seguro)",
            command=_cancelar,
            style="TI.Secondary.TButton",
        )
        btn_cancel.pack(side="left")

        btn_exec = tk.Button(
            botoes,
            text="⚠️ CONFIRMAR E EXECUTAR",
            command=_confirmar,
            state="disabled",
            bg="#6e2c2c",
            fg="#ffffff",
            activebackground="#da3633",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
        )
        btn_exec.pack(side="right")

        def _checar_pin(*_args):
            if var_pin.get().strip() == pending.token:
                btn_exec.configure(state="normal", bg="#da3633")
            else:
                btn_exec.configure(state="disabled", bg="#6e2c2c")

        var_pin.trace_add("write", _checar_pin)
        win.protocol("WM_DELETE_WINDOW", _cancelar)
        btn_cancel.focus_set()
