"use strict";

const element = (id) => document.getElementById(id);
const apiRoot = "/api/v1";
const terminal = new Set(["completed", "cancelled", "failed"]);
const qualityNames = {best: "Melhor disponível", 1080: "Até 1080p", 720: "Até 720p", 480: "Até 480p", mp3: "MP3"};
const statusNames = {queued: "Na fila", running: "Em andamento", cancelling: "Cancelando", cancelled: "Cancelado", completed: "Pronto", failed: "Falhou"};
const stageNames = {extract: "Consultando o site", download: "Baixando no PC", convert: "Preparando o arquivo"};
const rows = new Map();
let signedIn = false;
let refreshId = 0;
let authEpoch = 0;
let connectionLost = false;
let historySize = 0;

function message(text, isError = false) {
  const box = element("feedback");
  box.textContent = text;
  box.classList.toggle("error", isError);
}

async function api(path, {method = "GET", body} = {}) {
  const headers = {"X-VideoLivre": "1"};
  if (body) headers["Content-Type"] = "application/json";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  let response;
  try {
    response = await fetch(apiRoot + path, {
      method, headers, body: body && JSON.stringify(body), signal: controller.signal
    });
  } catch {
    throw new Error("PC indisponível. Confira se o VideoLivre Web está aberto e se a conexão está ativa.");
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = new Error(body?.error || "Não foi possível concluir a ação. Confira os dados e tente novamente.");
    error.status = response.status;
    throw error;
  }
  if (response.status !== 204) return response.json();
}

function changeSession(active) {
  signedIn = active;
  element("login").hidden = active;
  element("logout").hidden = !active;
  element("workspace").hidden = !active;
  if (!active) {
    authEpoch++;
    element("key").value = "";
    element("add-form").reset();
    rows.clear();
    element("jobs").replaceChildren();
  }
}

function showError(error) {
  if (error.status === 401 && signedIn) {
    changeSession(false);
    message("A sessão terminou. Entre novamente com a chave.", true);
  } else {
    message(error.message, true);
  }
}

async function refresh() {
  const request = ++refreshId;
  const epoch = authEpoch;
  try {
    const jobs = await api("/jobs");
    if (request !== refreshId || epoch !== authEpoch) return;
    if (connectionLost) {
      message("");
      connectionLost = false;
    }
    changeSession(true);
    render(jobs);
  } catch (error) {
    if (request !== refreshId || epoch !== authEpoch) return;
    if (error.status === 401 && !signedIn) {
      if (element("login").hidden) changeSession(false);
      return;
    }
    connectionLost = !error.status;
    showError(error);
  }
}

function make(tag, text, cssClass) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cssClass) node.className = cssClass;
  return node;
}

function action(label, handler) {
  const button = make("button", label);
  button.type = "button";
  button.addEventListener("click", () => withBusy(button, handler));
  return button;
}

async function withBusy(button, handler) {
  button.disabled = true;
  try {
    await handler();
  } catch (error) {
    showError(error);
  } finally {
    button.disabled = button.id === "clear" && historySize === 0;
  }
}

function draw(job, row) {
  const focused = row.contains(document.activeElement) && document.activeElement.textContent;
  const host = new URL(job.url).hostname;
  const name = job.filename || job.title || host;
  const info = make("div");
  info.append(make("h3", name));
  const stage = stageNames[job.stage] || statusNames[job.status];
  const credit = !job.filename && (job.credit || job.creator);
  info.append(make("p", [stage, qualityNames[job.quality], credit].filter(Boolean).join(" · "), "status"));
  if (job.error) info.append(make("p", job.error, "failure"));
  row.replaceChildren(info);

  const actions = make("div", null, "job-actions");
  if (job.status === "completed") {
    const link = make("a", "Baixar arquivo", "button primary");
    link.href = apiRoot + "/jobs/" + job.id + "/file";
    link.download = job.filename;
    actions.append(link);
    if (navigator.share && (!navigator.canShare || navigator.canShare({url: job.url}))) {
      actions.append(action("Compartilhar link", async () => {
        try {
          await navigator.share({url: job.url, title: job.title || "VideoLivre"});
        } catch (error) {
          if (error.name !== "AbortError") throw new Error("Não foi possível compartilhar o link original.");
        }
      }));
    }
  }
  if (["queued", "running"].includes(job.status)) {
    actions.append(action("Cancelar", () => changeJob(job.id, "cancel")));
  }
  if (["cancelled", "failed"].includes(job.status)) {
    actions.append(action(job.status === "cancelled" ? "Retomar" : "Tentar de novo", () => changeJob(job.id, "resume")));
  }
  if (actions.childElementCount) row.append(actions);
  if (focused) {
    const next = [...actions.children].find((control) => control.textContent === focused);
    next?.focus({preventScroll: true});
  }
  if (job.status === "running") {
    const progress = make("progress");
    progress.max = 100;
    progress.setAttribute("aria-label", "Progresso de " + name);
    const amount = make("span", null, "progress-text");
    amount.setAttribute("aria-hidden", "true");
    const group = make("div", null, "progress-row");
    group.append(progress, amount);
    row.append(group);
  }
}

function render(jobs) {
  const list = element("jobs");
  const live = jobs.filter((job) => !terminal.has(job.status));
  const past = jobs.filter((job) => terminal.has(job.status)).reverse();
  historySize = past.length;
  const order = [...live, ...past];
  const ids = new Set(order.map((job) => job.id));
  for (const [id, row] of rows) {
    if (!ids.has(id)) {
      row.remove();
      rows.delete(id);
    }
  }
  element("empty").hidden = order.length > 0;
  element("clear").disabled = past.length === 0;
  const summary = [live.length && (live.length === 1 ? "1 em andamento ou na fila" : live.length + " em andamento ou na fila"),
    past.length && (past.length === 1 ? "1 no histórico" : past.length + " no histórico")].filter(Boolean).join(" · ");
  if (element("summary").textContent !== summary) element("summary").textContent = summary;
  order.forEach((job, position) => {
    let row = rows.get(job.id);
    if (!row) {
      row = make("li", null, "job");
      rows.set(job.id, row);
    }
    const signature = JSON.stringify([job.status, job.stage, job.title, job.creator, job.filename, job.error]);
    if (row.dataset.signature !== signature) {
      row.dataset.signature = signature;
      draw(job, row);
    }
    const progress = row.querySelector("progress");
    if (progress) {
      const amount = row.querySelector(".progress-text");
      if (job.progress === null) {
        progress.removeAttribute("value");
        amount.textContent = "Em andamento";
      } else if (!progress.hasAttribute("value") || progress.value !== job.progress) {
        progress.value = job.progress;
        amount.textContent = job.progress + "%";
      }
    }
    if (list.children[position] !== row) list.insertBefore(row, list.children[position] || null);
  });
}

async function changeJob(id, command) {
  await api("/jobs/" + id + "/" + command, {method: "POST"});
  await refresh();
}

element("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  withBusy(event.submitter, async () => {
    await api("/session", {method: "POST", body: {key: element("key").value}});
    element("key").value = "";
    message("");
    await refresh();
    if (signedIn) element("url").focus();
    else message("Abra o serviço em localhost ou pelo endereço HTTPS para usar a sessão.", true);
  });
});

element("logout").addEventListener("click", (event) => withBusy(event.currentTarget, async () => {
  await api("/session", {method: "DELETE"});
  changeSession(false);
  message("Sessão encerrada.");
  element("key").focus();
}));

element("add-form").addEventListener("submit", (event) => {
  event.preventDefault();
  withBusy(event.submitter, async () => {
    const body = {
      url: element("url").value, quality: element("quality").value, credit: element("credit").value || null
    };
    await api("/jobs", {method: "POST", body});
    element("url").value = "";
    element("credit").value = "";
    message("Adicionado à fila.");
    await refresh();
    element("url").focus();
  });
});

element("paste").addEventListener("click", async () => {
  const url = element("url");
  url.focus();
  try {
    url.value = (await navigator.clipboard.readText()).trim();
    message("");
  } catch {
    message("Toque e segure no campo ou use Ctrl+V para colar o link.");
  }
});

const dialog = element("clear-dialog");
element("clear").addEventListener("click", () => {
  dialog.returnValue = "";
  dialog.showModal();
});
dialog.addEventListener("close", () => {
  if (dialog.returnValue !== "clear") return;
  withBusy(element("clear"), async () => {
    await api("/jobs", {method: "DELETE"});
    message("Histórico limpo. Os arquivos prontos continuam no PC.");
    await refresh();
  });
});

api("/info").then((info) => { element("version").textContent = "v" + info.version; }).catch(() => {});
(async function poll() {
  if (signedIn || element("login").hidden) await refresh();
  setTimeout(poll, signedIn ? 1800 : 4000);
})();
