"""
============================================================
TERMINAL TI — CATÁLOGO DE VARIÁVEIS EWS, PJL E SNMP LEXMARK
(core/catalog.py)
============================================================
"""

# ------------------------------------------------------------
# 1. PAPEL, MÍDIA E BANDEJAS (/cgi-bin/dynamic/printer/config/gen/papermenu.html)
# ------------------------------------------------------------

ORIGEM_PADRAO_OPCOES = {
    "Bandeja 1 (Cassete Principal)": "1",
    "Alimentador Manual (Papel)": "128",
    "Alimentador Manual (Envelope)": "129",
}

TAMANHO_PAPEL_OPCOES = {
    "A4 (210 x 297 mm)": "22",
    "Carta / Letter (8.5 x 11 pol)": "1",
    "Ofício / Legal (8.5 x 14 pol)": "7",
    "Ofício México": "232",
    "A5 (148 x 210 mm)": "23",
    "A6 (105 x 148 mm)": "24",
    "Executivo": "9",
    "Folio": "230",
    "Statement (US)": "231",
    "JIS B5": "117",
    "Universal": "254",
}

TIPO_PAPEL_OPCOES = {
    "Papel Comum (Plain)": "0",
    "Cartões / Cardstock": "3",
    "Etiquetas (Labels)": "4",
    "Encorpado (Heavy Plain)": "7",
    "Comum Gramatura Maior": "16",
    "Papel Leve (Light)": "15",
    "Transparência": "2",
    "Reciclado": "18",
    "Timbrado (Letterhead)": "5",
    "Pré-impresso": "6",
    "Papel Colorido": "1",
    "Áspero / Algodão (Rough/Cotton)": "17",
}

CONFIG_MF_OPCOES = {
    "Primeiro (Prioridade MP Feeder)": "2",
    "Cassete (Igual à Bandeja)": "0",
    "Manual": "1",
}

SUBSTITUIR_TAMANHO_OPCOES = {
    "Tudo Listado (Carta <-> A4 / Statement <-> A5)": "99",
    "Carta / A4": "1",
    "Statement (US) / A5": "3",
    "Desativar Substituição": "0",
}

# ------------------------------------------------------------
# 2. TEXTURA E GRAMATURA (/config/paper/papertexture.html & paperweight.html)
# ------------------------------------------------------------

MIDIAS_TEXTURA_CAMPOS = {
    "Papel Comum (Plain)": "0.system.1825",
    "Cartões (Cardstock)": "0.system.1833",
    "Etiquetas (Labels)": "0.system.1835",
    "Encorpado (Bond/Heavy)": "0.system.1839",
    "Transparência": "0.system.1831",
    "Reciclado": "0.system.4620",
    "Envelope": "0.system.1843",
    "Timbrado": "0.system.1837",
    "Pré-impresso": "0.system.1841",
    "Colorido": "0.system.1829",
    "Papel Leve": "0.system.4596",
    "Papel Pesado": "0.system.4603",
}

TEXTURA_OPCOES = {
    "Suave (Smooth)": "0",
    "Normal": "1",
    "Áspero (Rough)": "2",
}

MIDIAS_PESO_CAMPOS = {
    "Papel Comum (Plain)": "0.system.1824",
    "Cartões (Cardstock)": "0.system.1832",
    "Etiquetas (Labels)": "0.system.1834",
    "Encorpado (Bond/Heavy)": "0.system.1838",
    "Transparência": "0.system.1830",
    "Reciclado": "0.system.4619",
    "Envelope": "0.system.1842",
    "Timbrado": "0.system.1836",
    "Pré-impresso": "0.system.1840",
    "Colorido": "0.system.1828",
    "Áspero / Algodão": "0.system.1826",
}

PESO_OPCOES = {
    "Leve (Light)": "0",
    "Normal": "1",
    "Pesado (Heavy)": "2",
}

# ------------------------------------------------------------
# 3. ÍCONES DA TELA INICIAL (/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html)
# ------------------------------------------------------------

ICONES_HOME_CAMPOS = [
    ("2.system.17351", "Cópia", "Exibe ou oculta o ícone principal de Cópia na tela inicial."),
    ("2.system.17254", "Atalhos de Cópia", "Exibe ou oculta o botão de Atalhos rápidos de Cópia."),
    ("2.system.17350", "Fax", "Exibe ou oculta o ícone de Fax no visor (útil desmarcar quando não há linha)."),
    ("2.system.17257", "Atalhos de Fax", "Exibe ou oculta o botão de Atalhos de Fax."),
    ("2.system.17352", "E-mail", "Exibe ou oculta o ícone de Digitalizar para E-mail."),
    ("2.system.17255", "Atalhos de E-mail", "Exibe ou oculta o botão de Atalhos de E-mail."),
    ("2.system.17353", "FTP (Rede)", "Exibe ou oculta o ícone de Digitalizar para FTP."),
    ("2.system.17256", "Atalhos de FTP", "Exibe ou oculta o botão de Atalhos de FTP."),
    ("2.system.17354", "Trabalhos Retidos (Held Jobs)", "Exibe ou oculta a fila de Trabalhos Retidos / Confidenciais."),
    ("2.system.17348", "Pesquisar Trabalhos Retidos", "Exibe ou oculta a busca de Trabalhos Retidos."),
    ("2.system.17252", "Unidade USB (Pendrive)", "Exibe ou oculta o ícone de impressão/scan via USB frontal."),
    ("2.system.17250", "Perfis (Profiles)", "Exibe ou oculta o ícone de Perfis e Soluções (Scan to PC / eSF)."),
    ("2.system.17251", "Marcadores (Bookmarks)", "Exibe ou oculta o ícone de Marcadores no visor."),
    ("2.system.17167", "Alterar Idioma", "Exibe ou oculta o botão de troca rápida de idioma na tela inicial."),
]

# ------------------------------------------------------------
# 4. QUALIDADE, MOTOR E ENERGIA
# ------------------------------------------------------------

RESOLUCAO_OPCOES = {
    "300 ppp (Rascunho Rápido)": "0",
    "600 ppp (Padrão Comercial)": "1",
    "1200 ppp (Alta Definição Real)": "3",
    "1200 Image Quality (QI 1200)": "2",
    "2400 Image Quality (QI 2400)": "9",
}

TONALIDADE_TONER_OPCOES = {
    f"Nível {i} {'(Mais Claro)' if i == 1 else '(Padrão)' if i == 8 else '(Máximo Escuro)' if i == 10 else ''}": str(i - 1)
    for i in range(1, 11)
}

MODO_ECO_OPCOES = {
    "Desativado (Desempenho Máximo)": "0",
    "Economia de Energia": "1",
    "Economia de Energia + Papel (Duplex)": "2",
    "Economia de Papel (Duplex)": "3",
}

HIBERNACAO_OPCOES = {
    "Desativado": "0",
    "20 minutos": "11",
    "1 hora": "1",
    "2 horas": "2",
    "3 horas": "3",
    "6 horas": "4",
    "1 dia": "5",
    "2 dias": "6",
    "3 dias (Padrão)": "7",
    "1 semana": "8",
    "2 semanas": "9",
    "1 mês": "10",
}

RECUPERACAO_ATOLAMENTO_OPCOES = {
    "Automática (Padrão)": "2",
    "Ativada (Sempre reimprimir página atolada)": "1",
    "Desativada (Nunca reimprimir)": "0",
}

IDIOMA_OPCOES = {
    "Português (Brasil)": "16",
    "English (US)": "0",
    "Español": "4",
    "Français": "2",
    "Deutsch": "1",
    "Italiano": "5",
}

# ------------------------------------------------------------
# 5. DICIONÁRIO CATEGORIZADO DE COMANDOS PJL E SNMP
# ------------------------------------------------------------

DICIONARIO_COMANDOS = {
    "Diagnóstico e Leitura (PJL INFO)": [
        ("INFO STATUS", "PJL", "Lê o estado atual do painel, código de status e prontidão da máquina."),
        ("INFO ID", "PJL", "Retorna a string de identificação do modelo e versão de firmware."),
        ("INFO PAGECOUNT", "PJL", "Consulta o contador total de páginas impressas pelo motor."),
        ("INFO CONFIG", "PJL", "Lista bandejas instaladas, memória RAM, duplexador e opcionais de hardware."),
        ("INFO VARIABLES", "PJL", "Despeja TODAS as variáveis de ambiente PJL e NVRAM suportadas pela placa."),
        ("INFO MEMORY", "PJL", "Exibe a memória livre e total alocada para jobs na controladora."),
    ],
    "Painel, Display e Alertas (PJL)": [
        ('RDYMSG DISPLAY="MANUTENCAO TI"', "PJL", "Escreve 'MANUTENCAO TI' na linha de status do visor LCD."),
        ('RDYMSG DISPLAY=""', "PJL", "Limpa a mensagem customizada e restaura o texto 'Pronto' original."),
        ('OPMSG DISPLAY="NAO DESLIGAR"', "PJL", "Exibe mensagem de operador no visor aguardando confirmação."),
        ("CLEAR WARNING", "PJL", "Limpa avisos e alertas não críticos pendentes no painel."),
        ("INITIALIZE", "PJL", "Reinicializa as variáveis de sessão PJL para os padrões de fábrica."),
        ("RESET", "PJL", "Executa um reset lógico da controladora de impressão."),
    ],
    "Papel, Mídia e Motor (PJL DEFAULT)": [
        ("DEFAULT PAPER=A4", "PJL", "Define o tamanho de papel padrão PJL para A4."),
        ("DEFAULT PAPER=LETTER", "PJL", "Define o tamanho de papel padrão PJL para Carta (Letter)."),
        ("DEFAULT DUPLEX=ON", "PJL", "Ativa a impressão frente e verso por padrão."),
        ("DEFAULT DUPLEX=OFF", "PJL", "Desativa a impressão frente e verso por padrão."),
        ("DEFAULT ECONOMODE=ON", "PJL", "Ativa o modo de economia de toner via PJL."),
        ("DEFAULT ECONOMODE=OFF", "PJL", "Desativa o modo de economia de toner via PJL."),
        ("DEFAULT DENSITY=4", "PJL", "Ajusta a densidade PJL para nível 4."),
        ("DEFAULT JAMRECOVERY=ON", "PJL", "Força a reimpressão de páginas após atolamento."),
        ("DEFAULT POWERSAVE=ON", "PJL", "Habilita o gerenciamento de economia de energia."),
        ("DEFAULT POWERSAVETIME=15", "PJL", "Define o tempo de entrada em modo de espera para 15 minutos."),
    ],
    "Auditoria e Identidade (SNMP OIDs)": [
        ("1.3.6.1.2.1.1.1.0", "SNMP_GET", "sysDescr — Modelo completo, revisão de hardware e versão de firmware."),
        ("1.3.6.1.2.1.1.5.0", "SNMP_GET", "sysName — Nome de host (Hostname) configurado na placa de rede."),
        ("1.3.6.1.2.1.1.6.0", "SNMP_GET", "sysLocation — Localização física gravada na NVRAM."),
        ("1.3.6.1.2.1.1.4.0", "SNMP_GET", "sysContact — Nome/ramal de contato do responsável técnico."),
        ("1.3.6.1.2.1.1.3.0", "SNMP_GET", "sysUpTime — Tempo de atividade contínuo desde o último boot."),
        ("1.3.6.1.2.1.43.5.1.1.17.1", "SNMP_GET", "prtGeneralSerialNumber — Número de série oficial do chassi."),
        ("1.3.6.1.2.1.43.10.2.1.4.1.1", "SNMP_GET", "prtMarkerLifeCount — Contador vitalício de páginas impressas."),
        ("1.3.6.1.2.1.43.11.1.1.6.1.1", "SNMP_GET", "Descrição do Suprimento #1 (Toner)."),
        ("1.3.6.1.2.1.43.11.1.1.9.1.1", "SNMP_GET", "Nível atual do Suprimento #1 (Toner)."),
        ("1.3.6.1.2.1.43.11.1.1.8.1.1", "SNMP_GET", "Capacidade máxima do Suprimento #1 (Toner)."),
        ("1.3.6.1.2.1.43.11.1.1.9.1.2", "SNMP_GET", "Nível atual do Suprimento #2 (Unidade de Imagem)."),
        ("1.3.6.1.2.1.43.16.5.1.2.1.1", "SNMP_GET", "prtConsoleDisplayBufferText — Texto exibido atualmente na linha 1 do visor LCD!"),
    ],
}
