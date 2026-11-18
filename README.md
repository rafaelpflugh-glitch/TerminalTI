# 🖥️ Terminal TI — Engenharia & Painel Operacional Lexmark

Aplicação desktop independente desenvolvida para engenharia reversa, diagnóstico de bancada e controle operacional de impressoras multifuncionais corporativas **Lexmark** (com foco nas famílias MX/MS, eSF e painéis LCD 800x480).

---

## 🚀 Principais Recursos

### 1. 🎨 Gerenciador de Tela Inicial (Home Screen & eSF)
- **Organização estilo "Celular":** Reordenação intuitiva dos botões do visor LCD através de slots (Slot 1 ao 8 na página principal, com suporte à página 2).
- **Simulador Físico LCD em Tempo Real (800x480):** Preview gráfico bidirecional em matriz 2x4 com badges numéricos, rótulos e emojis representativos.
- **Presets de 1 Clique:**
  - *Modo Smartphone:* 4 botões essenciais em tamanho expandido.
  - *Modo Corporativo:* Layout padrão de 6 botões para escritórios.
  - *Todos / Nenhum:* Marcação em massa rápida.
- **Injeção EWS Direta:** Aplicação instantânea via HTTP POST no endpoint nativo `/cgi-bin/dynamic/printer/config/gen/sub/add_btns.html`.

### 2. 🖨️ Injeção de Comandos PJL & Porta RAW 9100
- Envio direto de comandos `@PJL` em socket TCP RAW (porta 9100).
- Consulta de `INFO STATUS`, `INFO CONFIG`, `INFO ID`, variáveis de ambiente e reset de subsistemas.

### 3. 🔍 Diagnóstico e SNMPv2c
- Leitura e manipulação de MIBs públicas e proprietárias Lexmark via SNMP.
- Consulta instantânea de contadores de páginas, serial, status de suprimentos e identificadores de hardware.

### 4. 🌐 EWS Web Scraping & VNC Remoto
- Conexão e automação direta com o servidor web interno (Embedded Web Server).
- Abertura de sessões de painel remoto / VNC para controle à distância da tela do operador.

---

## 📂 Estrutura do Projeto

```text
TerminalTI/
│
├── core/
│   ├── catalog.py           # Catálogo de comandos PJL, OIDs SNMP e rotas EWS
│   ├── ews_client.py        # Cliente HTTP de alta performance para o EWS da Lexmark
│   └── pjl_snmp_client.py   # Driver de comunicação TCP RAW 9100 e SNMPv2c
│
├── interface/
│   └── app_window.py        # Janela principal Tkinter com Dark UI e abas operacionais
│
├── .gitignore
├── Iniciar_Terminal_TI.bat  # Script de inicialização rápida para técnicos de bancada
├── main.py                  # Ponto de entrada da aplicação
└── README.md
```

---

## 🛠️ Como Executar

### Pré-requisitos
- Python 3.10 ou superior
- Bibliotecas: `pysnmp` (opcional para modo SNMP avançado), `requests`, `tkinter` (nativo do Python)

### Execução Direta
Dê um duplo clique no script:
```bat
Iniciar_Terminal_TI.bat
```

Ou execute via linha de comando informando o IP da impressora alvo:
```bash
python main.py 192.168.14.134
```

---

## 📄 Licença
Projeto interno para suporte técnico e engenharia de hardware.
