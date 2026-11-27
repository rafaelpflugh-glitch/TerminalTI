/* ============================================================
   TERMINAL TI v2.0 — FRONTEND MODERNO (app.js)
   Zero dependências externas, troca de tela em 0ms.
   ============================================================ */

const state = {
  homeButtons: [],
  homeValues: {},
  scannerMode: "0",
  pendingPin: null,
  logCount: 0,
  authHttps: false,
  agenteTemChave: false,
};

const $ = (id) => document.getElementById(id);

function currentIp() {
  return $("ip-input").value.trim();
}

function currentCommunity() {
  return $("snmp-community").value || "public";
}

function addLog(text) {
  const now = new Date().toTimeString().slice(0, 8);
  const el = $("console-log");
  el.textContent += `[${now}] ${text}\n`;
  el.scrollTop = el.scrollHeight;
  state.logCount += 1;
  $("console-toggle-label").textContent = `Console Técnico (${state.logCount})`;
}

function setStatus(text) {
  $("footer-status").textContent = text;
}

function toast(msg, isError = false) {
  const stack = $("toast-stack");
  const div = document.createElement("div");
  div.className = "toast" + (isError ? " err" : "");
  div.textContent = msg;
  stack.appendChild(div);
  setTimeout(() => div.remove(), 4200);
}

async function api(path, payload = {}, method = "POST") {
  setStatus(`Executando ${path}...`);
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (method !== "GET") {
    opts.body = JSON.stringify({ ip: currentIp(), community: currentCommunity(), ...payload });
  }
  const resp = await fetch(path, opts);
  const data = await resp.json();
  setStatus("Pronto");
  if (data.ok === false && data.erro) {
    addLog(`ERRO ${path}: ${data.erro}`);
    toast(data.erro, true);
    throw new Error(data.erro);
  }
  return data;
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function openModal(id) { $(id).classList.add("open"); }
function closeModal(id) { $(id).classList.remove("open"); }

/* ---------- NAVEGAÇÃO (0 ms) ---------- */
function switchView(viewId) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
  const target = $(`view-${viewId}`);
  if (target) target.classList.add("active");
  const btn = document.querySelector(`.nav-item[data-view="${viewId}"]`);
  if (btn) btn.classList.add("active");
}

/* ---------- INICIALIZAÇÃO ---------- */
async function init() {
  // Tema salvo
  const savedTheme = localStorage.getItem("terminalti_theme") || "light";
  if (savedTheme === "dark") document.documentElement.setAttribute("data-theme", "dark");
  updateThemeIcon();

  try {
    const data = await api("/api/state", {}, "GET");
    $("ip-input").value = data.ip_inicial || "192.168.14.134";
    updateIpHistory(data.historico_ips || []);
    $("inp-bkp-dir").value = data.backup_dir_padrao || "";
    updateAuthBadge(data.auth_ativa, data.auth_https);

    // Agente
    state.agenteTemChave = !!data.agente?.tem_chave;
    $("chk-agent-llm").checked = !!data.agente?.usar_llm;
    $("api-model-select").value = data.agente?.modelo_gemini || "gemini-flash-lite-latest";
    updateAgentLabel();

    // Catálogos
    state.homeButtons = data.catalogos.home_botoes || [];
    fillSelect("sel-origem", data.catalogos.origens);
    fillSelect("sel-tamanho", data.catalogos.tamanhos, "22");
    fillSelect("sel-tipo", data.catalogos.tipos, "0");
    renderHomeControls({ "2.system.17351": "1", "2.system.17252": "1" });

    addLog("Terminal TI v2.0 inicializado (Interface Desktop Minimalista).");
  } catch (err) {
    addLog("Erro ao carregar estado inicial: " + err.message);
  }
}

function fillSelect(id, items, defaultVal = null) {
  const sel = $(id);
  sel.innerHTML = "";
  items.forEach((it) => {
    const opt = document.createElement("option");
    opt.value = it.valor;
    opt.textContent = it.nome;
    if (defaultVal !== null && String(it.valor) === String(defaultVal)) opt.selected = true;
    sel.appendChild(opt);
  });
}

function updateIpHistory(ips) {
  const dl = $("ip-history");
  dl.innerHTML = "";
  ips.forEach((ip) => {
    const opt = document.createElement("option");
    opt.value = ip;
    dl.appendChild(opt);
  });
}

function updateAuthBadge(ativa, https) {
  state.authHttps = !!https;
  const btn = $("btn-auth");
  const lbl = $("btn-auth-label");
  if (ativa) {
    btn.classList.add("btn-success-subtle");
    lbl.textContent = https ? "HTTPS + Auth" : "Autenticado";
  } else {
    btn.classList.remove("btn-success-subtle");
    lbl.textContent = "Login EWS";
  }
}

function updateAgentLabel() {
  const on = $("chk-agent-llm").checked;
  $("agent-mode-label").textContent = on
    ? (state.agenteTemChave ? `Gemini (${$("api-model-select").value})` : "Sem API Key")
    : "Modo Offline";
}

function updateThemeIcon() {
  const dark = document.documentElement.getAttribute("data-theme") === "dark";
  $("theme-icon").innerHTML = dark
    ? '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>'
    : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
}

/* ---------- DASHBOARD ---------- */
async function refreshDashboard() {
  try {
    addLog(`Lendo telemetria de ${currentIp()}...`);
    const data = await api("/api/dashboard");
    updateIpHistory(data.historico_ips || []);
    updateAuthBadge(data.auth_ativa, data.auth_https);

    const d = data.diag;
    const modShort = d.modelo.includes(" version ") ? d.modelo.split(" version ")[0] : d.modelo;

    $("top-device-label").textContent = `${modShort}`;
    $("top-device-dot").className = "dot online";

    $("dash-model").textContent = `${modShort} — ${d.ip}`;
    $("dash-fw").textContent = `${d.modelo} • Hostname: ${d.hostname} • Uptime: ${d.uptime}`;
    $("dash-serial").textContent = d.serial;
    $("dash-pages").textContent = `${d.total_paginas} págs`;

    const rel = data.relogio || {};
    $("dash-clock").textContent = rel.hora_impressora
      ? `${rel.hora_impressora}${rel.ntp_ativo ? " (NTP)" : ""}`
      : "N/D";

    const sc = d.scanner_info || {};
    $("dash-scanner").textContent = sc.modulo ? `${sc.modulo} (${sc.estado_ram || "OK"})` : "Impressora";

    const lcd = d.display_lcd || "—";
    $("dash-lcd").textContent = lcd;
    const lcdLow = lcd.toLowerCase();
    const isOk = (lcdLow.includes("pronto") || lcdLow.includes("ready")) && !lcdLow.includes("vazia") && !lcdLow.includes("empty");
    $("dash-lcd-dot").className = "dot " + (isOk ? "online" : "warn");

    // Suprimentos
    paintSupply(1, d.sup1_desc, d.sup1_pct, `IP ${d.ip}`);
    const s2 = data.sup2 || {};
    paintSupply(2, s2.desc || "Unidade de Imagem", s2.pct, s2.desc ? `Restante: ${s2.atual} / ${s2.max}` : "Não reportado via SNMP");

    addLog(d.resumo);
    toast(`Conectado a ${modShort}`);
  } catch (err) {
    $("top-device-dot").className = "dot error";
    $("top-device-label").textContent = "Falha de conexão";
  }
}

function paintSupply(idx, name, pct, sub) {
  $(`sup${idx}-name`).textContent = name || `Suprimento #${idx}`;
  $(`sup${idx}-sub`).textContent = sub;
  const bar = $(`sup${idx}-bar`);
  if (pct === null || pct === undefined) {
    $(`sup${idx}-pct`).textContent = "N/D";
    bar.style.width = "0%";
    bar.className = "progress-fill";
    return;
  }
  $(`sup${idx}-pct`).textContent = `${pct}%`;
  bar.style.width = `${pct}%`;
  bar.className = "progress-fill " + (pct >= 35 ? "ok" : pct >= 15 ? "warn" : "low");
}

/* ---------- TELA INICIAL & PREVIEW LCD ---------- */
function renderHomeControls(valuesMap) {
  state.homeValues = {};
  const wrap = $("home-toggles");
  wrap.innerHTML = "";
  state.homeButtons.forEach((btn) => {
    const active = String(valuesMap[btn.key] || "0") === "1";
    state.homeValues[btn.key] = active;
    const lbl = document.createElement("label");
    lbl.className = "toggle-item";
    lbl.title = btn.desc;
    lbl.innerHTML = `<input type="checkbox" ${active ? "checked" : ""} /> <span>${btn.nome}</span>`;
    lbl.querySelector("input").addEventListener("change", (e) => {
      state.homeValues[btn.key] = e.target.checked;
      renderLcdPreview();
    });
    wrap.appendChild(lbl);
  });
  renderLcdPreview();
}

function renderLcdPreview() {
  const grid = $("lcd-preview");
  grid.innerHTML = "";
  const actives = state.homeButtons.filter((b) => state.homeValues[b.key]);
  $("lcd-count").textContent = `${actives.length} ícones ativos`;
  if (!actives.length) {
    grid.innerHTML = '<div class="muted" style="grid-column:1/-1; text-align:center; padding:32px; color:#64748b;">Nenhum botão selecionado na Tela Inicial.</div>';
    return;
  }
  actives.slice(0, 8).forEach((b, i) => {
    const tile = document.createElement("div");
    tile.className = "lcd-tile";
    tile.innerHTML = `<span class="lcd-tile-slot">SLOT ${i + 1}</span><span>${b.nome}</span>`;
    grid.appendChild(tile);
  });
}

/* ---------- AGENTE TI & MODAL PIN ---------- */
function appendChat(role, text, meta = "", cls = "") {
  const box = $("chat-messages");
  const div = document.createElement("div");
  div.className = `msg ${role === "user" ? "msg-user" : "msg-bot " + cls}`;
  if (meta) {
    const m = document.createElement("div");
    m.className = "msg-meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  div.appendChild(document.createTextNode(text));
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

async function sendAgentCommand(cmdText, echoUser = true) {
  const cmd = (cmdText || "").trim();
  if (!cmd) return;
  if (echoUser) appendChat("user", cmd);
  $("btn-agent-send").disabled = true;
  try {
    const res = await api("/api/agent/command", { comando: cmd });
    const cls = res.motor === "CONFIRMACAO-CRITICA" || res.motor === "ANTI-BRICK" ? "warn" : (res.ok ? "" : "err");
    appendChat("bot", res.mensagem, `${res.motor} • ${res.acao}`, cls);
    addLog(`Agente [${res.motor}/${res.acao}]: ${res.ok ? "OK" : "ALERTA"}`);
    if (res.confirmacao_pendente) {
      openPinModal(res.confirmacao_pendente);
    }
  } finally {
    $("btn-agent-send").disabled = false;
  }
}

function openPinModal(pend) {
  state.pendingPin = pend;
  $("pin-title").textContent = pend.titulo;
  $("pin-target").textContent = `Alvo       : ${pend.ip}\nEquipamento: ${pend.modelo}  |  Serial: ${pend.serial}\nParâmetros : ${pend.parametros}`;
  const ul = $("pin-risks");
  ul.innerHTML = "";
  (pend.riscos || []).forEach((r) => {
    const li = document.createElement("li");
    li.textContent = r;
    li.style.marginBottom = "4px";
    ul.appendChild(li);
  });
  $("pin-prompt-label").textContent = `Digite o PIN  ${pend.token}  para destravar (expira em ${pend.segundos}s):`;
  $("pin-input").value = "";
  $("btn-pin-confirm").disabled = true;
  openModal("modal-pin");
}

/* ---------- EMBARCADOS (eSF / NDD) ---------- */
async function refreshEsf() {
  const res = await api("/api/esf/list");
  addLog(res.resumo);
  const tbody = $("esf-tbody");
  tbody.innerHTML = "";
  if (!res.apps || !res.apps.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="muted" style="text-align:center; padding:18px;">Nenhum aplicativo embarcado encontrado.</td></tr>';
    return;
  }
  res.apps.forEach((a) => {
    const tr = document.createElement("tr");
    const acao = a.acao_toggle || (a.ativo ? "Desativar" : "Ativar");
    tr.innerHTML = `
      <td><strong>${a.nome}</strong> ${a.eh_ndd ? '<span class="badge badge-accent">NDD</span>' : ""}</td>
      <td class="mono">${a.app_id}</td>
      <td class="mono">${a.versao}</td>
      <td>${a.licenca}</td>
      <td><span class="badge ${a.ativo ? "badge-ok" : "badge-muted"}">${a.ativo ? "Ativo" : "Parado"}</span></td>
      <td style="text-align:right;">
        <button class="btn btn-sm esf-toggle">${acao}</button>
        ${a.pode_desinstalar ? '<button class="btn btn-sm btn-danger-outline esf-del">Desinstalar</button>' : ""}
      </td>
    `;
    tr.querySelector(".esf-toggle").addEventListener("click", async () => {
      const r = await api("/api/esf/toggle", { app_id: a.app_id, acao });
      addLog(r.resumo);
      toast(`${acao}: ${a.nome}`);
      refreshEsf();
    });
    const delBtn = tr.querySelector(".esf-del");
    if (delBtn) {
      delBtn.addEventListener("click", async () => {
        if (!confirm(`Confirma desinstalar "${a.nome}" (${a.app_id}) de ${currentIp()}?`)) return;
        const r = await api("/api/esf/uninstall", { app_id: a.app_id, nome: a.nome });
        addLog(r.resumo);
        toast(`Desinstalado: ${a.nome}`);
        refreshEsf();
      });
    }
    tbody.appendChild(tr);
  });
}

/* ---------- EVENT LISTENERS ---------- */
document.addEventListener("DOMContentLoaded", () => {
  init();

  // Navegação sidebar
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.addEventListener("click", () => switchView(b.dataset.view));
  });

  // Fechar modais
  document.querySelectorAll("[data-close]").forEach((b) => {
    b.addEventListener("click", () => closeModal(b.dataset.close));
  });

  // Tema
  $("btn-theme").addEventListener("click", () => {
    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    if (isDark) {
      document.documentElement.removeAttribute("data-theme");
      localStorage.setItem("terminalti_theme", "light");
    } else {
      document.documentElement.setAttribute("data-theme", "dark");
      localStorage.setItem("terminalti_theme", "dark");
    }
    updateThemeIcon();
  });

  // Topbar
  $("btn-connect").addEventListener("click", () => { switchView("dashboard"); refreshDashboard(); });
  $("btn-refresh-dash").addEventListener("click", refreshDashboard);
  $("ip-input").addEventListener("keydown", (e) => { if (e.key === "Enter") { switchView("dashboard"); refreshDashboard(); } });
  $("btn-open-ews").addEventListener("click", () => {
    const proto = state.authHttps ? "https" : "http";
    window.open(`${proto}://${currentIp()}`, "_blank");
  });

  // Console Drawer
  $("btn-console-toggle").addEventListener("click", () => {
    $("console-body").classList.toggle("open");
  });
  $("btn-log-clear").addEventListener("click", () => {
    $("console-log").textContent = "";
    state.logCount = 0;
    $("console-toggle-label").textContent = "Console Técnico (0)";
  });
  $("btn-log-download").addEventListener("click", () => {
    const blob = new Blob([$("console-log").textContent], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `TerminalTI_${currentIp().replace(/\./g, "_")}.txt`;
    a.click();
  });

  // Modal Auth
  $("btn-auth").addEventListener("click", () => { $("auth-feedback").textContent = ""; openModal("modal-auth"); });
  $("btn-auth-test").addEventListener("click", async () => {
    $("auth-feedback").textContent = "Testando acesso...";
    try {
      const r = await api("/api/auth/test", {
        usuario: $("auth-user").value,
        senha: $("auth-pass").value,
        pin: $("auth-pin").value,
        usar_https: $("auth-https").checked,
      });
      $("auth-feedback").textContent = r.mensagem;
      addLog(r.mensagem);
    } catch (e) { $("auth-feedback").textContent = e.message; }
  });
  $("btn-auth-save").addEventListener("click", async () => {
    const https = $("auth-https").checked;
    const r = await api("/api/auth/set", {
      usuario: $("auth-user").value,
      senha: $("auth-pass").value,
      pin: $("auth-pin").value,
      usar_https: https,
    });
    const ativa = !!($("auth-user").value || $("auth-pass").value || $("auth-pin").value || https);
    updateAuthBadge(ativa, https);
    toast(r.mensagem);
    closeModal("modal-auth");
  });
  $("btn-auth-clear").addEventListener("click", async () => {
    $("auth-user").value = ""; $("auth-pass").value = ""; $("auth-pin").value = ""; $("auth-https").checked = false;
    const r = await api("/api/auth/clear");
    updateAuthBadge(false, false);
    toast(r.mensagem);
    closeModal("modal-auth");
  });

  // Modal Descobrir Rede
  $("btn-discover").addEventListener("click", async () => {
    openModal("modal-discover");
    $("discover-status").textContent = `Varrendo sub-rede de ${currentIp()} (porta 9100 + SNMP)...`;
    $("discover-tbody").innerHTML = "";
    try {
      const res = await api("/api/discover");
      const list = res.encontradas || [];
      $("discover-status").textContent = `${list.length} impressora(s) Lexmark encontrada(s).`;
      if (!list.length) {
        $("discover-tbody").innerHTML = '<tr><td colspan="5" class="muted" style="text-align:center;">Nenhuma Lexmark encontrada nesta sub-rede.</td></tr>';
        return;
      }
      list.forEach((item) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td class="mono"><strong>${item.ip}</strong></td><td>${item.modelo}</td><td class="mono">${item.serial}</td><td class="mono">${item.paginas}</td><td style="text-align:right;"><button class="btn btn-sm btn-primary">Usar</button></td>`;
        tr.querySelector("button").addEventListener("click", () => {
          $("ip-input").value = item.ip;
          closeModal("modal-discover");
          switchView("dashboard");
          refreshDashboard();
        });
        $("discover-tbody").appendChild(tr);
      });
    } catch (e) { $("discover-status").textContent = e.message; }
  });

  // Ações Rápidas (Dashboard)
  $("qa-ntp").addEventListener("click", async () => {
    const r = await api("/api/ntp/sync", { ativar_ntp_nativo: false });
    addLog(r.resumo); toast(`Relógio sincronizado (${r.data_hora_brt} BRT)`);
  });
  $("qa-ptbr").addEventListener("click", async () => {
    const r = await api("/api/system/language", { idioma: "portugues" });
    addLog(r.resumo); toast("Idioma definido para Português (Brasil)");
  });
  $("qa-bench").addEventListener("click", async () => {
    const r = await api("/api/reports/bench");
    addLog(r.resumo); toast("Relatório de bancada enviado na porta 9100");
  });
  $("qa-menu").addEventListener("click", async () => {
    const r = await api("/api/reports/native", { tipo: "menus" });
    addLog(r.resumo); toast("Página de menu nativa enviada (@PJL LPRINTMENUS)");
  });
  $("qa-backup").addEventListener("click", () => switchView("backup"));
  $("qa-vnc").addEventListener("click", async () => {
    const r = await api("/api/system/panel", { ativar_vnc: true });
    addLog(r.resumo);
    window.open(`http://${currentIp()}/cgi-bin/dynamic/printer/config/remote_oppanel.html`, "_blank");
    toast("Painel remoto VNC ativado");
  });

  // Agente TI
  $("btn-agent-send").addEventListener("click", () => {
    const txt = $("agent-input").value; $("agent-input").value = "";
    sendAgentCommand(txt);
  });
  $("agent-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { const txt = $("agent-input").value; $("agent-input").value = ""; sendAgentCommand(txt); }
  });
  document.querySelectorAll(".agent-chip").forEach((b) => {
    b.addEventListener("click", () => sendAgentCommand(b.dataset.cmd));
  });
  $("chk-agent-llm").addEventListener("change", async () => {
    await api("/api/agent/config", { usar_llm: $("chk-agent-llm").checked, manter_chave_atual: true, modelo_gemini: $("api-model-select").value });
    updateAgentLabel();
  });
  $("btn-agent-api").addEventListener("click", () => { $("api-feedback").textContent = ""; openModal("modal-api"); });
  $("btn-api-test").addEventListener("click", async () => {
    $("api-feedback").textContent = "Testando conexão com Google Gemini...";
    const r = await api("/api/agent/test_key", { api_key: $("api-key-input").value, modelo_gemini: $("api-model-select").value });
    $("api-feedback").textContent = r.mensagem;
  });
  $("btn-api-save").addEventListener("click", async () => {
    const key = $("api-key-input").value.trim();
    const r = await api("/api/agent/config", {
      api_key: key,
      manter_chave_atual: !key,
      usar_llm: true,
      modelo_gemini: $("api-model-select").value,
    });
    state.agenteTemChave = !!r.agente?.tem_chave;
    $("chk-agent-llm").checked = !!r.agente?.usar_llm;
    updateAgentLabel();
    toast(r.mensagem);
    closeModal("modal-api");
  });

  // Modal PIN
  $("pin-input").addEventListener("input", () => {
    const ok = state.pendingPin && $("pin-input").value.trim() === state.pendingPin.token;
    $("btn-pin-confirm").disabled = !ok;
  });
  $("btn-pin-cancel").addEventListener("click", () => {
    closeModal("modal-pin");
    state.pendingPin = null;
    sendAgentCommand("CANCELAR", false);
  });
  $("btn-pin-confirm").addEventListener("click", () => {
    const pin = $("pin-input").value.trim();
    closeModal("modal-pin");
    state.pendingPin = null;
    sendAgentCommand(`CONFIRMAR ${pin}`, false);
  });

  // Tela Inicial & Papel
  $("btn-home-read").addEventListener("click", async () => {
    const r = await api("/api/home/read");
    renderHomeControls(r.valores || {});
    addLog(r.resumo);
    toast("Botões da Tela Inicial carregados");
  });
  document.querySelectorAll("[data-preset]").forEach((b) => {
    b.addEventListener("click", async () => {
      const r = await api("/api/home/preset", { preset: b.dataset.preset });
      const rd = await api("/api/home/read");
      renderHomeControls(rd.valores || {});
      addLog(r.resumo);
      toast(`Preset "${b.textContent}" aplicado`);
    });
  });
  $("btn-home-apply").addEventListener("click", async () => {
    const r = await api("/api/home/apply", { valores: state.homeValues });
    addLog(r.resumo);
    toast("Botões aplicados no painel LCD");
  });
  $("btn-paper-apply").addEventListener("click", async () => {
    const tamText = $("sel-tamanho").options[$("sel-tamanho").selectedIndex].text;
    const papelPjl = tamText.includes("A4") ? "A4" : (tamText.includes("Carta") ? "LETTER" : null);
    const r = await api("/api/paper/apply", {
      origem: $("sel-origem").value,
      tamanho: $("sel-tamanho").value,
      tipo: $("sel-tipo").value,
      papel_pjl: papelPjl,
      duplex: $("chk-duplex").checked,
      eco: $("chk-eco").checked,
    });
    addLog(r.resumo);
    toast("Configurações de papel aplicadas");
  });
  $("btn-wallpaper-upload").addEventListener("click", async () => {
    const file = $("file-wallpaper").files[0];
    if (!file) return toast("Selecione uma imagem primeiro", true);
    const b64 = await readFileAsBase64(file);
    const r = await api("/api/wallpaper/upload", { nome: file.name, conteudo_b64: b64 });
    addLog(r.resumo);
    toast("Papel de parede atualizado no visor");
  });

  // Sistema & Scanner
  $("btn-ntp-read").addEventListener("click", async () => {
    const r = await api("/api/ntp/read");
    const rel = r.relogio;
    $("ntp-status-text").textContent = `Relógio atual: ${rel.hora_impressora} | NTP: ${rel.ntp_ativo ? "Ativo (" + rel.servidor_ntp + ")" : "Desativado"}`;
    if (rel.servidor_ntp) $("inp-ntp-server").value = rel.servidor_ntp;
    toast("Relógio lido da impressora");
  });
  $("btn-ntp-now").addEventListener("click", async () => {
    const r = await api("/api/ntp/sync", { ativar_ntp_nativo: false, servidor_ntp: $("inp-ntp-server").value });
    $("ntp-status-text").textContent = `Atualizado: ${r.depois.hora_impressora} (${r.fonte})`;
    addLog(r.resumo); toast(`Sincronizado via ${r.fonte}`);
  });
  $("btn-ntp-native").addEventListener("click", async () => {
    const r = await api("/api/ntp/sync", { ativar_ntp_nativo: true, servidor_ntp: $("inp-ntp-server").value });
    $("ntp-status-text").textContent = `NTP Nativo ATIVO ➜ ${r.depois.servidor_ntp} | Hora: ${r.depois.hora_impressora}`;
    addLog(r.resumo); toast("NTP nativo ativado na impressora");
  });
  $("seg-scanner").querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => {
      $("seg-scanner").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.scannerMode = b.dataset.val;
    });
  });
  $("btn-scanner-read").addEventListener("click", async () => {
    const r = await api("/api/scanner/read");
    addLog(r.resumo);
    if (r.codigo !== null && r.codigo !== undefined) {
      state.scannerMode = String(r.codigo);
      $("seg-scanner").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.val === state.scannerMode));
      $("scanner-status-text").textContent = `Estado atual na NVRAM: ${r.modo_nome}`;
    } else {
      $("scanner-status-text").textContent = r.resumo;
    }
    toast("Modo do scanner lido");
  });
  $("btn-scanner-apply").addEventListener("click", async () => {
    const r = await api("/api/scanner/set", { modo: state.scannerMode });
    $("scanner-status-text").textContent = `Gravado: ${r.modo_nome}. Reinicie a impressora para o ScanManager2 aplicar.`;
    addLog(r.resumo);
    toast("Modo do scanner gravado na NVRAM");
  });
  $("inp-brilho").addEventListener("input", () => { $("lbl-brilho").textContent = $("inp-brilho").value; });
  $("btn-lang-apply").addEventListener("click", async () => {
    const r = await api("/api/system/language", { idioma: $("sel-lang").value });
    addLog(r.resumo); toast(`Idioma alterado para ${r.idioma}`);
  });
  $("btn-lcd-apply").addEventListener("click", async () => {
    const r = await api("/api/system/display", { texto: $("inp-lcd-msg").value });
    addLog(r.resumo); toast("Mensagem gravada no visor LCD");
  });
  $("btn-panel-apply").addEventListener("click", async () => {
    const r = await api("/api/system/panel", { brilho: Number($("inp-brilho").value), bipe_adf: $("chk-bipe").checked, ativar_vnc: true });
    addLog(r.resumo); toast("Preferências de painel aplicadas");
  });

  // Embarcados (NDD / eSF)
  $("btn-esf-refresh").addEventListener("click", refreshEsf);
  $("btn-esf-install").addEventListener("click", async () => {
    const appFile = $("file-esf-app").files[0];
    if (!appFile) return toast("Selecione o arquivo .fls ou .lic primeiro", true);
    const appB64 = await readFileAsBase64(appFile);
    let cfgB64 = null, cfgNome = null;
    const cfgFile = $("file-esf-cfg").files[0];
    if (cfgFile) { cfgB64 = await readFileAsBase64(cfgFile); cfgNome = cfgFile.name; }
    const r = await api("/api/esf/install", {
      nome: appFile.name,
      conteudo_b64: appB64,
      cfg_nome: cfgNome,
      cfg_b64: cfgB64,
      sincronizar_hora: $("chk-esf-ntp").checked,
    });
    addLog(r.resumo);
    toast(`Embarcado "${appFile.name}" enviado`);
    refreshEsf();
  });

  // Backup 4 Categorias
  document.querySelectorAll(".bkp-card input").forEach((inp) => {
    inp.addEventListener("change", () => inp.closest(".bkp-card").classList.toggle("checked", inp.checked));
  });
  $("btn-bkp-pick").addEventListener("click", async () => {
    const r = await api("/api/backup/pick_folder", { inicial: $("inp-bkp-dir").value });
    if (r.pasta) $("inp-bkp-dir").value = r.pasta;
  });
  $("btn-bkp-export").addEventListener("click", async () => {
    const r = await api("/api/backup/export", {
      pasta: $("inp-bkp-dir").value,
      arquivos: $("bkp-arq").checked,
      embarcados: $("bkp-emb").checked,
      rede: $("bkp-red").checked,
      configuracoes: $("bkp-cfg").checked,
      gerar_zip: $("bkp-zip").checked,
    });
    $("bkp-output").style.display = "block";
    $("bkp-output").textContent = r.resumo;
    addLog(r.resumo);
    toast(`Backup concluído (${r.salvos.length} arquivos)`);
  });
  $("btn-bkp-import").addEventListener("click", async () => {
    const file = $("file-ucf-import").files[0];
    if (!file) return toast("Selecione um arquivo .ucf primeiro", true);
    const b64 = await readFileAsBase64(file);
    const r = await api("/api/backup/import", {
      nome: file.name,
      conteudo_b64: b64,
      preservar_ip: $("chk-keep-ip").checked,
    });
    addLog(r.resumo);
    toast(`UCF "${file.name}" importado`);
  });

  // Engenharia & Zona Crítica
  $("btn-eng-pjl").addEventListener("click", async () => {
    const r = await api("/api/engineering/pjl", { comando: $("inp-pjl").value });
    $("eng-output").textContent = r.resumo;
    addLog(`PJL: ${$("inp-pjl").value}`);
  });
  $("btn-eng-snmp").addEventListener("click", async () => {
    const r = await api("/api/engineering/snmp", { oid: $("inp-snmp").value });
    $("eng-output").textContent = r.resumo;
    addLog(r.resumo);
  });
  $("btn-eng-ports").addEventListener("click", async () => {
    const r = await api("/api/engineering/ports");
    $("eng-output").textContent = r.resumo;
    addLog("Scan de portas concluído.");
  });
  document.querySelectorAll(".eng-se").forEach((b) => {
    b.addEventListener("click", async () => {
      const r = await api("/api/engineering/ews", { endpoint: b.dataset.ep });
      $("eng-output").textContent = r.resumo;
      addLog(`Leitura EWS/SE: ${b.dataset.ep}`);
    });
  });
  document.querySelectorAll(".crit-btn").forEach((b) => {
    b.addEventListener("click", () => sendAgentCommand(b.dataset.cmd, false));
  });
  $("btn-crit-fw").addEventListener("click", async () => {
    const file = $("file-fw").files[0];
    if (!file) return toast("Selecione um arquivo .fls ou .bin", true);
    const b64 = await readFileAsBase64(file);
    const r = await api("/api/critical/prepare_firmware", { nome: file.name, conteudo_b64: b64 });
    addLog(r.mensagem);
    if (r.confirmacao_pendente) {
      openPinModal(r.confirmacao_pendente);
    } else {
      toast(r.mensagem, true);
    }
  });
});
