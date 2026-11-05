// Веб-версия СОКРАТа: рабочее место ученика. Данные — из той же базы, что и у бота.
const app = document.getElementById("app");

const TOPICS = [
  ["📐", "Квадратные уравнения"], ["📈", "Линейные функции"], ["💯", "Проценты"],
  ["📏", "Теорема Пифагора"], ["🔗", "Системы уравнений"], ["√", "Степени и корни"],
  ["㏒", "Логарифмы"], ["📐", "Тригонометрия"],
];
const GRADES = [5, 6, 7, 8, 9, 10, 11];
const LETTERS = "АБВГ";

const state = {
  me: null,          // профиль и прогресс ученика
  view: "study",     // study | progress | quiz
  space: null,       // открытая тема с сообщениями
  mode: "ask",       // ask — вопрос наставнику, check — решение на проверку
  photo: "",         // прикреплённое фото (data URL)
  busy: false,       // ждём ответа ИИ
  pending: null,     // сообщение ученика, которое уже показали, но ответа ещё нет
  quiz: null,        // текущий тест
};

// ---------- вход и запросы к серверу ----------

const storage = {
  get: () => { try { return localStorage.getItem("sokrat_token") || ""; } catch (_) { return ""; } },
  set: (t) => { try { localStorage.setItem("sokrat_token", t); } catch (_) { /* приватный режим */ } },
  clear: () => { try { localStorage.removeItem("sokrat_token"); } catch (_) { /* приватный режим */ } },
};
// Внутри MAX мост передаёт подписанные данные ученика — тогда код вводить не нужно
const initData = () => window.WebApp?.initData || "";

async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${storage.get()}`, "X-Init-Data": initData() },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.detail || "Сервер не отвечает, попробуй ещё раз"), { status: res.status });
  return data;
}

// ---------- текст ответа → HTML ----------

// Экранируем всё, что пришло из базы: сообщение ученика не может вставить на страницу свой HTML
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");

// Мини-разметка ответов ИИ: заголовки, списки, **жирный**, абзацы
function md(text) {
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of String(text).split("\n")) {
    const line = raw.trim();
    let m;
    if (!line) { closeList(); continue; }
    if ((m = line.match(/^#{1,6}\s*(.+)$/))) { closeList(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
    if ((m = line.match(/^(?:[-•*]|\d+[.)])\s+(.+)$/))) {
      const kind = /^\d/.test(line) ? "ol" : "ul";
      if (list !== kind) { closeList(); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(m[1])}</li>`);
      continue;
    }
    closeList();
    out.push(`<p>${inline(line)}</p>`);
  }
  closeList();
  return out.join("");
}

// Как показать сообщение: служебные пометки для ИИ превращаем в понятные ярлыки
function messageView(m) {
  let text = m.text, tag = "", kind = m.role;
  if (m.role === "user") {
    if (text.startsWith("[Решение на проверку:]")) { tag = "Решение на проверку"; text = text.replace("[Решение на проверку:]", ""); }
    if (text.includes("[Ученик прислал фото. На нём:]")) {
      tag = tag ? tag + " · фото" : "Фото";
      text = text.replace("[Ученик прислал фото. На нём:]", "").replace("[Подпись ученика к фото:]", "\nПодпись:");
    }
  } else if (text.startsWith("💡")) kind = "hint";
  else if (text.startsWith("✅")) kind = "ok";
  else if (text.startsWith("⚠️")) kind = "bad";
  const body = (tag ? `<div class="tag">${esc(tag)}</div>` : "") + md(text.trim());
  if (m.role === "user") return `<div class="msg user"><div class="bubble">${body}</div></div>`;
  return `<div class="msg ${kind}"><div class="avatar">С</div><div class="bubble">${body}</div></div>`;
}

function toast(text) {
  const t = document.getElementById("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 4000);
}

const ring = (value, extra = "") =>
  `<div class="ring" style="--p:${value ?? 0};${extra}"><span>${value ?? "—"}</span></div>`;

// ---------- экран входа ----------

function loginScreen(error = "") {
  app.innerHTML = `
    <div class="login"><form class="login-card" id="login">
      <div class="logo-mark">С</div>
      <h1>СОКРАТ</h1>
      <p class="muted">Наставник по математике, который учит думать, а не списывать</p>
      <ol class="steps">
        <li>Открой бота СОКРАТ в MAX</li>
        <li>Нажми «📊 Мой прогресс» → «🌐 Веб-кабинет»</li>
        <li>Введи код из сообщения</li>
      </ol>
      <input class="code-input" id="code" inputmode="numeric" maxlength="6" placeholder="••••••" autocomplete="one-time-code" required>
      ${error ? `<div class="error-text">${esc(error)}</div>` : ""}
      <button class="btn block" type="submit">Войти</button>
    </form></div>`;
  const input = document.getElementById("code");
  input.focus();
  document.getElementById("login").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const { token } = await api("/api/login", "POST", { code: input.value });
      storage.set(token);
      start();
    } catch (err) { loginScreen(err.message); }
  });
}

// ---------- каркас страницы ----------

function render() {
  const me = state.me;
  const goal = me.goal ? me.goals[me.goal] : "уровень не выбран";
  const nav = (view, icon, label) =>
    `<button data-view="${view}" class="${state.view === view ? "active" : ""}">${icon} ${label}</button>`;
  app.innerHTML = `
    <div class="layout" id="layout">
      <aside class="sidebar">
        <div class="brand"><div class="logo-mark">С</div><div><b>СОКРАТ</b><span>наставник по математике</span></div></div>
        <div class="me-card" data-view="progress" title="Мой прогресс">
          ${ring(me.index)}
          <div><b>${esc(me.name || "Ученик")}</b><span class="muted small">${me.grade ? me.grade + " класс · " : ""}${esc(goal)}</span>
          <div class="small muted">Индекс самостоятельности</div></div>
        </div>
        <nav class="nav">
          ${nav("study", "💬", "Учёба")}
          ${nav("progress", "📊", "Мой прогресс")}
          ${nav("quiz", "📝", "Тест по ошибкам")}
          ${nav("class", "🏫", "Класс")}
        </nav>
        <div class="side-title"><span>Мои темы</span><button id="new-topic">＋ Новая</button></div>
        <div class="topics">
          ${me.spaces.length ? me.spaces.map((s) => `
            <button class="topic ${state.view === "study" && state.space?.id === s.id ? "active" : ""}" data-space="${s.id}">
              <span class="t-name">${esc(s.topic)}</span>${s.solved ? `<span class="t-count">✓ ${s.solved}</span>` : ""}
            </button>`).join("") : '<div class="side-empty">Тем пока нет — начни первую</div>'}
        </div>
        ${initData() ? "" : '<div class="nav" style="padding-bottom:14px"><button id="logout">↩ Выйти</button></div>'}
      </aside>
      <main class="main" id="main"></main>
    </div>`;

  app.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
  app.querySelectorAll("[data-space]").forEach((b) => b.addEventListener("click", () => openSpace(+b.dataset.space)));
  document.getElementById("new-topic").addEventListener("click", () => { state.space = null; go("study"); });
  document.getElementById("logout")?.addEventListener("click", () => { storage.clear(); loginScreen(); });

  if (state.view === "progress") renderProgress();
  else if (state.view === "quiz") renderQuiz();
  else if (state.view === "class") renderClass();
  else renderStudy();
}

function topbar(title, extra = "") {
  return `<div class="topbar"><button class="menu-btn" id="menu-btn" aria-label="Меню">☰</button>
    <h2>${title}</h2>${extra}</div>`;
}

function bindTopbar() {
  document.getElementById("menu-btn")?.addEventListener("click", () =>
    document.getElementById("layout").classList.toggle("drawer"));
  // нажатие на затемнённый фон закрывает выезжающее меню на телефоне
  document.getElementById("layout").addEventListener("click", (e) => {
    if (e.target.id === "layout") e.target.classList.remove("drawer");
  });
}

function go(view) {
  state.view = view;
  render();
}

// ---------- учёба: выбор темы и чат ----------

function renderStudy() {
  const main = document.getElementById("main");
  if (!state.space) {
    main.innerHTML = topbar("Новая тема") + `
      <div class="page"><div class="welcome">
        <h1>Что разберём сегодня?</h1>
        <p class="muted">Я объясню тему под твой уровень и дам задачу. Решаешь ты, а я помогаю вопросами и подсказками.</p>
        <div class="topic-grid">
          ${TOPICS.map(([ico, name]) => `<button class="topic-card" data-topic="${esc(name)}"><span class="ico">${ico}</span><b>${esc(name)}</b></button>`).join("")}
        </div>
        <form class="custom-topic" id="custom-topic">
          <input id="topic-input" placeholder="Или напиши свою тему: например, «Показательные неравенства»" maxlength="200">
          <button class="btn" type="submit">Начать</button>
        </form>
        <div class="how">
          <div><b>💡 Подсказки</b><span class="muted">Не получается — сначала намёк, потом правило, потом похожий пример.</span></div>
          <div><b>✔ Проверка</b><span class="muted">Пришли решение или фото тетради — покажу, где ошибка.</span></div>
          <div><b>📊 Индекс</b><span class="muted">Чем больше задач решено без подсказок, тем он выше.</span></div>
        </div>
      </div></div>`;
    bindTopbar();
    main.querySelectorAll("[data-topic]").forEach((b) => b.addEventListener("click", () => newTopic(b.dataset.topic)));
    document.getElementById("custom-topic").addEventListener("submit", (e) => {
      e.preventDefault();
      const topic = document.getElementById("topic-input").value.trim();
      if (topic.length >= 2) newTopic(topic);
    });
    return;
  }

  const s = state.space;
  const hintsLeft = s.hints < s.max_hints;
  const messages = s.messages.map(messageView).join("") +
    (state.pending ? messageView({ role: "user", text: state.pending }) : "") +
    (state.busy ? '<div class="msg"><div class="avatar">С</div><div class="bubble"><span class="typing"><i></i><i></i><i></i></span></div></div>' : "");

  main.innerHTML = topbar(esc(s.topic), `<span class="muted small">Подсказок: ${s.hints}/${s.max_hints}</span>`) + `
    <div class="chat" id="chat"><div class="chat-inner">${messages}</div></div>
    <div class="composer"><div class="composer-inner">
      <div class="actions">
        <button class="chip hint-chip" id="hint" ${state.busy || !hintsLeft ? "disabled" : ""}>
          💡 ${hintsLeft ? `Подсказка ${s.hints + 1}/${s.max_hints}` : "Подсказки кончились"}</button>
        <button class="chip" id="next" ${state.busy ? "disabled" : ""}>➡️ Другая задача</button>
        <div class="segmented">
          <button data-mode="ask" class="${state.mode === "ask" ? "on" : ""}">💬 Вопрос</button>
          <button data-mode="check" class="${state.mode === "check" ? "on check" : ""}">✔ Проверить решение</button>
        </div>
      </div>
      ${state.photo ? `<div class="photo-preview"><img src="${state.photo}" alt="Прикреплённое фото"><span>Фото прикреплено</span><button id="drop-photo">✕</button></div>` : ""}
      <form class="input-row ${state.mode === "check" ? "check-mode" : ""}" id="composer">
        <label class="icon-btn" title="Прикрепить фото задачи или решения">📎<input type="file" accept="image/*" id="photo" hidden></label>
        <textarea id="text" rows="1" placeholder="${state.mode === "check"
          ? "Напиши решение по шагам и ответ — или прикрепи фото тетради"
          : "Напиши вопрос или свои мысли по задаче…"}" ${state.busy ? "disabled" : ""}></textarea>
        <button class="icon-btn send-btn" type="submit" title="Отправить" ${state.busy ? "disabled" : ""}>➤</button>
      </form>
    </div></div>`;

  bindTopbar();
  const chat = document.getElementById("chat");
  chat.scrollTop = chat.scrollHeight;
  const text = document.getElementById("text");
  if (!state.busy) text.focus();
  text.addEventListener("input", () => { text.style.height = "auto"; text.style.height = text.scrollHeight + "px"; });
  // Enter — отправить, Shift+Enter — новая строка
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); document.getElementById("composer").requestSubmit(); }
  });
  document.getElementById("composer").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(text.value); });
  document.getElementById("photo").addEventListener("change", (e) => attachPhoto(e.target.files[0]));
  document.getElementById("drop-photo")?.addEventListener("click", () => { state.photo = ""; renderStudy(); });
  document.getElementById("hint").addEventListener("click", () => act(`/api/spaces/${s.id}/hint`));
  document.getElementById("next").addEventListener("click", () => act(`/api/spaces/${s.id}/next`));
  main.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => { state.mode = b.dataset.mode; renderStudy(); }));
}

// Фото уменьшаем прямо в браузере: быстрее загрузка, а распознаванию хватает и 1600 пикселей
function attachPhoto(file) {
  if (!file) return;
  const img = new Image();
  img.onload = () => {
    const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    state.photo = canvas.toDataURL("image/jpeg", 0.88);
    URL.revokeObjectURL(img.src);
    renderStudy();
  };
  img.onerror = () => toast("Не получилось открыть картинку");
  img.src = URL.createObjectURL(file);
}

async function withBusy(promise) {
  state.busy = true;
  renderStudy();
  try {
    return await promise;
  } catch (err) {
    toast(err.message);
    return null;
  } finally {
    state.busy = false;
    state.pending = null;
  }
}

async function sendMessage(text) {
  text = text.trim();
  if ((!text && !state.photo) || state.busy) return;
  const check = state.mode === "check";
  state.pending = (check ? "[Решение на проверку:]\n" : "") + (state.photo ? "[Ученик прислал фото. На нём:]\n📷 распознаю…\n" : "") + text;
  const photo = state.photo;
  state.photo = "";
  const space = await withBusy(api(`/api/spaces/${state.space.id}/messages`, "POST", { text, photo, check }));
  if (space) {
    state.space = space;
    if (check) state.mode = "ask";        // решение проверили — возвращаемся к обычному режиму
    if (space.verdict) await refreshMe(); // проверка меняет индекс и счётчики тем
  }
  render();
}

async function act(path) {
  const space = await withBusy(api(path, "POST"));
  if (space) state.space = space;
  renderStudy();
}

async function newTopic(topic) {
  state.space = { id: 0, topic, hints: 0, max_hints: 3, messages: [] };
  const space = await withBusy(api("/api/spaces", "POST", { topic }));
  state.space = space;
  if (space) await refreshMe();
  render();
}

async function openSpace(id) {
  state.view = "study";
  document.getElementById("layout")?.classList.remove("drawer");
  try {
    state.space = await api(`/api/spaces/${id}`);
    state.mode = "ask";
  } catch (err) { toast(err.message); }
  render();
}

// ---------- прогресс ----------

function chart(history) {
  if (history.length < 2) {
    return `<p class="muted">График появится, когда решишь хотя бы две задачи с проверкой.</p>`;
  }
  const w = 600, h = 170, pad = 24;
  const x = (i) => pad + (i * (w - 2 * pad)) / (history.length - 1);
  const y = (v) => h - pad - (v * (h - 2 * pad)) / 100;
  const points = history.map((p, i) => `${x(i)},${y(p.index)}`).join(" ");
  const grid = [0, 50, 100].map((v) =>
    `<line x1="${pad}" x2="${w - pad}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/>
     <text x="0" y="${y(v) + 4}" font-size="11" fill="var(--muted)">${v}</text>`).join("");
  const dots = history.map((p, i) =>
    `<circle cx="${x(i)}" cy="${y(p.index)}" r="4" fill="var(--brand)"><title>${esc(p.date)} · ${esc(p.topic)}: задача ${p.score}, индекс ${p.index}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Изменение индекса самостоятельности">
    ${grid}<polyline points="${points}" fill="none" stroke="var(--brand)" stroke-width="2.5" stroke-linejoin="round"/>${dots}</svg>`;
}

function renderProgress() {
  const me = state.me;
  const main = document.getElementById("main");
  const maxMistakes = Math.max(1, ...me.mistakes.map((m) => m.count));
  main.innerHTML = topbar("Мой прогресс", `<button class="btn ghost" id="level">🎓 Мой уровень</button>`) + `
    <div class="page"><div class="page-inner">
      <div class="grid-2">
        <div class="card index-card">
          ${ring(me.index)}
          <div><h3 style="margin-bottom:6px">Индекс самостоятельности</h3>
          <p class="muted small" style="margin:0">${me.index === null
            ? "Появится после первой задачи, отправленной на проверку."
            : "Задача решена с первой проверки без подсказок — 100 баллов. Каждая неудачная проверка −20, каждая подсказка −15. Среднее за последние 10 задач."}</p></div>
        </div>
        <div class="card chart"><h3>Как менялся индекс</h3>${chart(me.history)}</div>
      </div>
      <div class="tiles">
        <div class="tile"><b>${me.solved}</b><span>задач решено</span></div>
        <div class="tile"><b>${me.first_try}</b><span>с первой попытки без подсказок</span></div>
        <div class="tile"><b>${me.spaces.length}</b><span>тем изучено</span></div>
      </div>
      <div class="grid-2">
        <div class="card"><h3>Над чем поработать</h3>
          ${me.mistakes.length ? me.mistakes.map((m) => `
            <div class="bar-row"><span>${esc(m.type)}</span><b>${m.count}</b></div>
            <div class="bar"><div style="width:${(100 * m.count) / maxMistakes}%"></div></div>`).join("") +
            `<button class="btn block" data-view="quiz">📝 Пройти тест по этим ошибкам</button>`
            : '<p class="muted">Открытых ошибок нет 👏</p>'}
        </div>
        <div class="card"><h3>Тесты по ошибкам</h3>
          ${me.quizzes.length ? `<table class="table"><tr><th>Дата</th><th class="num">Результат</th></tr>
            ${me.quizzes.map((q) => `<tr><td>${esc(q.date)}</td><td class="num"><b>${q.score}</b> из ${q.total}</td></tr>`).join("")}</table>`
            : '<p class="muted">Тестов пока не было.</p>'}
        </div>
      </div>
      <div class="card" style="margin-top:16px"><h3>Темы</h3>
        ${me.spaces.length ? `<table class="table"><tr><th>Тема</th><th>Начата</th><th class="num">Решено</th><th class="num">Ошибок</th></tr>
          ${me.spaces.map((s) => `<tr class="click" data-space="${s.id}"><td>${esc(s.topic)}</td><td class="muted">${s.created}</td>
            <td class="num">${s.solved}</td><td class="num">${s.mistakes}</td></tr>`).join("")}</table>`
          : '<p class="muted">Тем пока нет.</p>'}
      </div>
      <div class="card" style="margin-top:16px"><h3>Мои данные</h3>
        <p class="muted small">Храним имя из MAX, класс и цель, переписку по темам, проверки, ошибки и тесты —
          для индекса и чтобы помнить, на чём ты остановился. Телефон, фамилию и школу не собираем.
          Фото после распознавания сразу удаляется.</p>
        <button class="btn ghost" id="delete-me">🗑 Удалить все мои данные</button>
      </div>
    </div></div>`;
  bindTopbar();
  main.querySelectorAll("[data-space]").forEach((r) => r.addEventListener("click", () => openSpace(+r.dataset.space)));
  main.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
  document.getElementById("level").addEventListener("click", () => levelModal());
  document.getElementById("delete-me").addEventListener("click", () => deleteModal());
}

// Подтверждение удаления — своим окном: системный confirm() внутри MAX может не работать
function deleteModal() {
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal">
    <h3>Удалить все данные?</h3>
    <p class="muted">Переписка, темы, ошибки, тесты и индекс будут удалены навсегда. Вернуть их будет нельзя.</p>
    <button class="btn block" id="confirm-delete" style="background:var(--bad);color:#fff">Да, удалить всё</button>
    <button class="btn ghost block" id="cancel-delete">Отмена</button>
  </div>`;
  back.querySelector("#cancel-delete").addEventListener("click", () => back.remove());
  back.addEventListener("click", (e) => { if (e.target === back) back.remove(); });
  back.querySelector("#confirm-delete").addEventListener("click", async () => {
    try {
      await api("/api/me", "DELETE");
      back.remove();
      storage.clear();
      app.innerHTML = `<div class="login"><div class="login-card"><div class="logo-mark">С</div>
        <h1>Данные удалены</h1><p class="muted">Если захочешь вернуться — просто напиши боту /start.</p></div></div>`;
    } catch (err) { toast(err.message); }
  });
  document.body.appendChild(back);
}

// ---------- класс: ученик и кабинет учителя ----------

async function renderClass() {
  const main = document.getElementById("main");
  main.innerHTML = topbar("Класс") + '<div class="page"><div class="page-inner"><p class="muted">Загрузка…</p></div></div>';
  bindTopbar();
  let data;
  try { data = await api("/api/classes"); } catch (err) { toast(err.message); return; }
  if (state.view !== "class") return;          // пока грузили, ученик ушёл на другой экран

  const student = data.student;
  const studentCard = student ? `
    <div class="card"><h3>🏫 Мой класс: ${esc(student.name)}</h3>
      ${student.teacher ? `<p class="muted small" style="margin-top:-8px">Учитель: ${esc(student.teacher)}</p>` : ""}
      ${student.assignments.length ? `<table class="table"><tr><th>Задание</th><th>Выдано</th><th>Статус</th><th></th></tr>
        ${student.assignments.map((a) => `<tr><td><b>${esc(a.topic)}</b>${a.note ? `<div class="muted small">${esc(a.note)}</div>` : ""}</td>
          <td class="muted">${a.created}</td>
          <td>${a.solved ? `✅ решено ${a.solved}` : a.started ? "▶️ начато" : "🆕 новое"}</td>
          <td class="num"><button class="btn ghost" data-assign="${a.id}">${a.started ? "Продолжить" : "Начать"}</button></td></tr>`).join("")}</table>`
        : '<p class="muted">Заданий пока нет — когда учитель выдаст тему, она появится здесь и придёт в MAX.</p>'}
      <button class="btn ghost" id="leave-class" style="margin-top:12px">Выйти из класса</button>
    </div>` : `
    <div class="card"><h3>🔑 Вступить в класс</h3>
      <p class="muted small" style="margin-top:-8px">Код даёт учитель. Тогда он сможет выдавать тебе задания.</p>
      <form class="custom-topic" id="join-form" style="margin-top:0">
        <input id="join-code" placeholder="Код класса, например K7M2QX" maxlength="12" autocomplete="off">
        <button class="btn" type="submit">Вступить</button>
      </form>
    </div>`;

  const teachingCard = data.teaching.length ? `
    <div class="card" style="margin-top:16px"><h3>👩‍🏫 Мои классы как учителя</h3>
      <table class="table">${data.teaching.map((c) => `<tr class="click" data-class="${c.id}">
        <td><b>${esc(c.name)}</b></td><td>код <b>${esc(c.code)}</b></td><td class="num">${c.students} уч.</td><td class="num">›</td></tr>`).join("")}</table>
    </div>` : "";

  main.querySelector(".page-inner").innerHTML = studentCard + teachingCard + `
    <div class="card" style="margin-top:16px"><h3>Я учитель — создать класс</h3>
      <p class="muted small" style="margin-top:-8px">Получите код для учеников, сводку ошибок класса и выдачу заданий.</p>
      <form class="custom-topic" id="class-form" style="margin-top:0">
        <input id="class-name" placeholder="Название, например «9 Б, алгебра»" maxlength="100">
        <button class="btn" type="submit">Создать</button>
      </form>
    </div>`;

  main.querySelectorAll("[data-assign]").forEach((b) => b.addEventListener("click", () => startAssignment(+b.dataset.assign)));
  main.querySelectorAll("[data-class]").forEach((r) => r.addEventListener("click", () => renderTeacher(+r.dataset.class)));
  document.getElementById("leave-class")?.addEventListener("click", async () => {
    try { await api("/api/classes/leave", "POST"); renderClass(); } catch (err) { toast(err.message); }
  });
  document.getElementById("join-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/classes/join", "POST", { code: document.getElementById("join-code").value });
      toast(`Ты в классе «${r.name}» 🎉`);
      renderClass();
    } catch (err) { toast(err.message); }
  });
  document.getElementById("class-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("class-name").value.trim();
    if (!name) return;
    try {
      const r = await api("/api/classes", "POST", { name });
      renderTeacher(r.id);
    } catch (err) { toast(err.message); }
  });
}

async function startAssignment(id) {
  state.view = "study";
  state.space = { id: 0, topic: "Задание", hints: 0, max_hints: 3, messages: [] };
  const space = await withBusy(api(`/api/assignments/${id}/start`, "POST"));
  state.space = space;
  if (space) await refreshMe();
  render();
}

async function renderTeacher(classId) {
  const main = document.getElementById("main");
  let c;
  try { c = await api(`/api/classes/${classId}`); } catch (err) { toast(err.message); return; }
  const presets = TOPICS.map(([, name]) => `<option value="${esc(name)}">`).join("");
  main.innerHTML = topbar(esc(c.name), `<button class="btn ghost" id="back-class">← Классы</button>`) + `
    <div class="page"><div class="page-inner">
      <div class="tiles">
        <div class="tile"><span>Код для учеников</span><b style="letter-spacing:.08em">${esc(c.code)}</b></div>
        <div class="tile"><span>Учеников</span><b>${c.students.length}</b></div>
        <div class="tile"><span>Средний индекс класса</span><b>${c.class_index ?? "—"}</b></div>
      </div>

      <div class="grid-2">
        <div class="card"><h3>Типичные ошибки класса</h3>
          ${c.common_mistakes.length ? c.common_mistakes.map((m) => `
            <div class="bar-row"><span>${esc(m.type)}</span><b>${m.share}% класса</b></div>
            <div class="bar"><div style="width:${m.share}%"></div></div>`).join("")
            : '<p class="muted">Пока нет данных: ошибки появятся, когда ученики начнут проверять решения.</p>'}
        </div>
        <div class="card"><h3>Темы, где больше всего ошибок</h3>
          ${c.weak_topics.length ? `<table class="table">${c.weak_topics.map((t) =>
            `<tr><td>${esc(t.topic)}</td><td class="num"><b>${t.errors}</b> ошиб.</td></tr>`).join("")}</table>`
            : '<p class="muted">Пока нет данных.</p>'}
        </div>
      </div>

      <div class="card" style="margin-top:16px"><h3>Выдать задание</h3>
        <form id="assign-form">
          <div class="custom-topic" style="margin-top:0">
            <input id="assign-topic" list="topic-presets" placeholder="Тема, например «Логарифмы»" maxlength="200" required>
            <datalist id="topic-presets">${presets}</datalist>
          </div>
          <div class="custom-topic">
            <input id="assign-note" placeholder="Комментарий для учеников (необязательно): например, «реши 3 задачи до пятницы»" maxlength="1000">
            <button class="btn" type="submit">Выдать</button>
          </div>
        </form>
        <p class="muted small" style="margin:10px 0 0">Каждому ученику класса придёт сообщение в MAX с кнопкой «Начать задание».</p>
      </div>

      <div class="card" style="margin-top:16px"><h3>Задания</h3>
        ${c.assignments.length ? `<table class="table"><tr><th>Тема</th><th>Выдано</th><th class="num">Начали</th><th class="num">Решили задачу</th></tr>
          ${c.assignments.map((a) => `<tr><td><b>${esc(a.topic)}</b>${a.note ? `<div class="muted small">${esc(a.note)}</div>` : ""}</td>
            <td class="muted">${a.created}</td><td class="num">${a.started} из ${a.total}</td><td class="num">${a.solved} из ${a.total}</td></tr>`).join("")}</table>`
          : '<p class="muted">Заданий ещё не было.</p>'}
      </div>

      <div class="card" style="margin-top:16px"><h3>Ученики</h3>
        ${c.students.length ? `<table class="table"><tr><th>Ученик</th><th class="num">Индекс</th><th class="num">Решено</th>
            <th class="num">С 1-й попытки</th><th class="num">Ошибок в работе</th><th class="num">Активность</th></tr>
          ${c.students.map((s) => `<tr><td>${esc(s.name)}</td><td class="num"><b>${s.index ?? "—"}</b></td><td class="num">${s.solved}</td>
            <td class="num">${s.first_try}</td><td class="num">${s.open_mistakes}</td><td class="num muted">${s.last_active ?? "—"}</td></tr>`).join("")}</table>`
          : `<p class="muted">Пока никто не вступил. Продиктуйте ученикам код <b>${esc(c.code)}</b>:
              в боте «🏫 Мой класс» → «Вступить по коду».</p>`}
      </div>
    </div></div>`;
  bindTopbar();
  document.getElementById("back-class").addEventListener("click", () => renderClass());
  document.getElementById("assign-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    button.disabled = true;
    try {
      const r = await api(`/api/classes/${classId}/assignments`, "POST", {
        topic: document.getElementById("assign-topic").value, note: document.getElementById("assign-note").value,
      });
      toast(`Задание выдано: уведомление получили ${r.notified} из ${r.students} учеников`);
      renderTeacher(classId);
    } catch (err) { toast(err.message); button.disabled = false; }
  });
}

// ---------- тест по ошибкам ----------

async function renderQuiz() {
  const main = document.getElementById("main");
  const q = state.quiz;
  if (!q) {
    const count = state.me.mistakes.reduce((a, m) => a + m.count, 0);
    main.innerHTML = topbar("Тест по ошибкам") + `
      <div class="page"><div class="quiz card" style="text-align:center">
        <div style="font-size:40px">📝</div>
        <h3 style="font-size:20px;margin:8px 0">Тест по твоим ошибкам</h3>
        <p class="muted">${count
          ? `Соберу 5 вопросов именно на те места, где были ошибки (${count}). Наберёшь 4 из 5 — ошибки будут считаться проработанными.`
          : "Ошибок для теста пока нет. Реши задачу и отправь её на проверку — если ошибёшься, тест соберётся на это место."}</p>
        <button class="btn block" id="start-quiz" ${count ? "" : "disabled"}>Собрать тест</button>
      </div></div>`;
    bindTopbar();
    document.getElementById("start-quiz").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = "Собираю вопросы… около 20 секунд";
      try {
        const quiz = await api("/api/quiz", "POST");
        state.quiz = { ...quiz, index: 0, answers: [], last: null, score: 0 };
      } catch (err) { toast(err.message); }
      renderQuiz();
    });
    return;
  }

  if (q.finished) {
    main.innerHTML = topbar("Тест по ошибкам") + `
      <div class="page"><div class="quiz card" style="text-align:center">
        <div style="font-size:44px">${q.passed ? "🏆" : "📚"}</div>
        <h3 style="font-size:22px;margin:8px 0">${q.score} из ${q.questions.length}</h3>
        <p class="muted">${q.passed ? "Отлично! Эти ошибки отмечены как проработанные." : "Разбери пояснения и попробуй ещё раз — ошибки пока остаются в работе."}</p>
        <button class="btn block" id="quiz-done">Готово</button>
      </div></div>`;
    bindTopbar();
    document.getElementById("quiz-done").addEventListener("click", async () => { state.quiz = null; await refreshMe(); go("progress"); });
    return;
  }

  const item = q.questions[q.index];
  const last = q.last;   // ответ на текущий вопрос, если уже ответили
  main.innerHTML = topbar("Тест по ошибкам", `<span class="muted small">Вопрос ${q.index + 1} из ${q.questions.length}</span>`) + `
    <div class="page"><div class="quiz">
      <div class="quiz-progress"><div style="width:${(100 * q.index) / q.questions.length}%"></div></div>
      <div class="card">
        <div class="bubble" style="box-shadow:none;border:0;padding:0">${md(item.question)}</div>
        ${item.options.map((o, j) => {
          let cls = "";
          if (last) cls = j === last.correct ? "right" : (j === last.chosen ? "wrong" : "");
          return `<button class="option ${cls}" data-option="${j}" ${last ? "disabled" : ""}><span class="letter">${LETTERS[j]}</span><span>${inline(o)}</span></button>`;
        }).join("")}
        ${last ? `<div class="explain">${last.ok ? "✅ <b>Верно!</b>" : "❌ <b>Не совсем.</b>"} ${inline(last.explanation)}</div>
          <button class="btn block" id="quiz-next">${q.index + 1 < q.questions.length ? "Следующий вопрос" : "Посмотреть результат"}</button>` : ""}
      </div>
    </div></div>`;
  bindTopbar();
  main.querySelectorAll("[data-option]").forEach((b) => b.addEventListener("click", async () => {
    const option = +b.dataset.option;
    try {
      const r = await api(`/api/quiz/${q.id}/answer`, "POST", { index: q.index, option });
      q.last = { ...r, chosen: option };
      if (r.finished) Object.assign(q, { score: r.score, passed: r.passed, done: true });
    } catch (err) { toast(err.message); }
    renderQuiz();
  }));
  document.getElementById("quiz-next")?.addEventListener("click", () => {
    if (q.done) q.finished = true;
    else { q.index += 1; q.last = null; }
    renderQuiz();
  });
}

// ---------- знакомство: класс и цель ----------

function levelModal() {
  const me = state.me;
  let grade = me.grade, goal = me.goal;
  const back = document.createElement("div");
  back.className = "modal-back";
  const draw = () => {
    back.innerHTML = `<div class="modal">
      <h3>${me.grade ? "Мой уровень" : "Давай знакомиться 👋"}</h3>
      <p class="muted">От этого зависит, как подробно я объясняю и какие задачи даю.</p>
      <label>Класс</label>
      <div class="pick">${GRADES.map((g) => `<button data-grade="${g}" class="${g === grade ? "on" : ""}">${g}</button>`).join("")}</div>
      <label>Цель</label>
      <div class="pick col">${Object.entries(me.goals).map(([k, v]) =>
        `<button data-goal="${k}" class="${k === goal ? "on" : ""}">${esc(v[0].toUpperCase() + v.slice(1))}</button>`).join("")}</div>
      <button class="btn block" id="save-level" ${grade && goal ? "" : "disabled"}>Сохранить</button>
    </div>`;
    back.querySelectorAll("[data-grade]").forEach((b) => b.addEventListener("click", () => { grade = +b.dataset.grade; draw(); }));
    back.querySelectorAll("[data-goal]").forEach((b) => b.addEventListener("click", () => { goal = b.dataset.goal; draw(); }));
    back.querySelector("#save-level").addEventListener("click", async () => {
      try {
        await api("/api/me", "PUT", { grade, goal });
        back.remove();
        await refreshMe();
        render();
        toast("Уровень сохранён ✅");
      } catch (err) { toast(err.message); }
    });
  };
  draw();
  // Закрыть можно, только если уровень уже был выбран раньше
  back.addEventListener("click", (e) => { if (e.target === back && me.grade) back.remove(); });
  document.body.appendChild(back);
}

// ---------- запуск ----------

async function refreshMe() {
  state.me = await api("/api/me");
}

async function start() {
  try {
    await refreshMe();
  } catch (err) {
    if (err.status === 401) return loginScreen();
    app.innerHTML = `<div class="login"><div class="login-card"><p class="error-text">${esc(err.message)}</p></div></div>`;
    return;
  }
  // Открываем тему, на которой ученик остановился (в боте или на сайте)
  if (state.me.current_space_id && state.me.spaces.some((s) => s.id === state.me.current_space_id)) {
    try { state.space = await api(`/api/spaces/${state.me.current_space_id}`); } catch (_) { state.space = null; }
  }
  render();
  if (!state.me.grade || !state.me.goal) levelModal();
}

// Даём мосту MAX до 3 секунд загрузиться (вне MAX его нет — тогда просто идём дальше)
async function waitForBridge() {
  if (!location.hash.includes("WebAppData")) return;   // MAX передаёт данные запуска в адресе после #
  for (let i = 0; i < 30 && !window.WebApp; i++) await new Promise((r) => setTimeout(r, 100));
}

window.addEventListener("DOMContentLoaded", async () => {
  await waitForBridge();
  try { window.WebApp?.ready?.(); } catch (_) { /* вне MAX */ }
  start();
});
