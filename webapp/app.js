// СОКРАТ — мини-приложение MAX
let WebApp = null;
// Данные запуска MAX также приходят в адресе после # (WebAppData=...) — сохраняем их до смены маршрута
const launchHash = new URLSearchParams(location.hash.slice(1)).get("WebAppData") || "";
const initData = () => WebApp?.initData || launchHash;
const view = document.getElementById("view");
const state = { me: null, quiz: null };

const TOPICS = ["Квадратные уравнения", "Линейные функции", "Проценты", "Теорема Пифагора",
  "Системы уравнений", "Неравенства", "Степени и корни", "Тригонометрия"];

// ---------- API ----------
async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Init-Data": initData(),
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Ошибка сервера");
  return data;
}

// ---------- утилиты ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Markdown + формулы: прячем $...$ от marked, потом возвращаем и рендерим KaTeX
function md(text) {
  const math = [];
  const hidden = String(text ?? "").replace(/\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]/g,
    (m) => { math.push(m); return `@@M${math.length - 1}@@`; });
  let html = window.marked ? marked.parse(hidden, { breaks: true }) : esc(hidden).replace(/\n/g, "<br>");
  html = html.replace(/@@M(\d+)@@/g, (_, i) => esc(math[+i]));
  return window.DOMPurify ? DOMPurify.sanitize(html) : html;
}

function renderMath(el) {
  if (window.renderMathInElement) {
    renderMathInElement(el, {
      delimiters: [
        { left: "$$", right: "$$", display: true }, { left: "\\[", right: "\\]", display: true },
        { left: "$", right: "$", display: false }, { left: "\\(", right: "\\)", display: false },
      ],
      throwOnError: false,
    });
  }
}

function toast(text) {
  const t = document.getElementById("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 3500);
}

function haptic(type) {
  try { WebApp?.HapticFeedback?.notificationOccurred(type); } catch (_) { /* desktop */ }
}

function setView(html) {
  view.innerHTML = html;
  renderMath(view);
  window.scrollTo(0, 0);
}

function busy(button, on) {
  if (!button) return;
  if (on) {
    button.dataset.label = button.innerHTML;
    button.innerHTML = '<span class="spinner"></span>';
    button.disabled = true;
  } else {
    button.innerHTML = button.dataset.label || button.innerHTML;
    button.disabled = false;
  }
}

function ring(index) {
  const v = index ?? 0;
  return `<div class="ring" style="--p:${v}"><div>${index == null ? "—" : v}</div></div>`;
}

// ---------- экраны ----------
async function homeScreen() {
  setView('<div class="empty"><span class="spinner"></span></div>');
  const [me, spaces] = await Promise.all([api("/api/me"), api("/api/spaces")]);
  state.me = me;
  const s = me.stats;
  setView(`
    <p class="muted">Привет, ${esc(me.user.first_name || "друг")}!</p>
    <div class="card hero">
      ${ring(s.index)}
      <div class="grow">
        <b>Индекс самостоятельности</b>
        <p class="muted">${s.index == null
          ? "Реши первую задачу — и здесь появится твой результат."
          : "Насколько ты решаешь сам, без подсказок. Цель — 80+."}</p>
      </div>
    </div>
    <div class="stats">
      <div class="stat"><b>${s.solved}</b><span>решено</span></div>
      <div class="stat"><b>${s.solo}</b><span>без подсказок</span></div>
      <div class="stat"><b>${me.open_mistakes}</b><span>ошибок в работе</span></div>
    </div>
    ${me.ai_enabled ? "" : '<p class="muted" style="margin-top:10px">⚙️ Демо-режим: YandexGPT не подключён.</p>'}

    <h2>Новое пространство</h2>
    <form id="new-space" class="card stack">
      <div class="row">
        <input id="topic" class="grow" placeholder="Тема, например: квадратные уравнения" maxlength="120" required>
        <button type="submit">Начать</button>
      </div>
      <div class="chips">${TOPICS.map((t) => `<button type="button" class="chip">${esc(t)}</button>`).join("")}</div>
    </form>

    <h2>Мои пространства</h2>
    <div class="stack">
      ${spaces.length ? spaces.map((sp) => `
        <a class="card space-item" href="#/space/${sp.id}">
          <div class="badge">${sp.stats.index ?? "·"}</div>
          <div class="grow"><b>${esc(sp.topic)}</b>
            <div class="muted">Решено задач: ${sp.stats.solved}</div></div>
          <span class="muted">›</span>
        </a>`).join("") : '<div class="card empty">Пока пусто. Выбери тему выше — я подготовлю конспект и первую задачу.</div>'}
    </div>
  `);

  const form = document.getElementById("new-space");
  const input = document.getElementById("topic");
  form.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { input.value = c.textContent; }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    busy(btn, true);
    try {
      const { id } = await api("/api/spaces", { method: "POST", body: { topic: input.value } });
      location.hash = `#/space/${id}`;
    } catch (err) { toast(err.message); busy(btn, false); }
  });
}

function messageHtml(m) {
  let cls = m.role === "user" ? "user" : "";
  if (m.kind === "hint") cls = "hint";
  if (m.kind === "problem") cls = "problem-msg";
  if (m.kind === "check" && m.role === "assistant") cls = m.text.startsWith("✅") ? "ok" : "warn";
  const body = m.kind === "problem" ? `<b>Задача:</b> ${md(m.text)}` : md(m.text);
  return `<div class="msg ${cls}">${body}</div>`;
}

async function spaceScreen(id) {
  setView('<div class="empty"><span class="spinner"></span></div>');
  const data = await api(`/api/spaces/${id}`);
  let mode = "chat";

  const draw = () => {
    const p = data.problem;
    setView(`
      <div class="topbar">
        <button class="ghost" id="back">‹</button>
        <h1 class="grow">${esc(data.space.topic)}</h1>
        <div class="badge muted" title="Индекс по теме">${data.stats.index ?? "—"}</div>
      </div>
      ${data.space.summary ? `<details class="summary card"><summary>📘 Конспект темы</summary>
        <div style="margin-top:8px">${md(data.space.summary)}</div></details>` : ""}
      ${p ? `<div class="card problem"><div class="label">Задача · подсказок ${p.hint_level}/4</div>${md(p.text)}</div>`
          : `<div class="card empty">Задача решена 🎉 Возьми новую или спроси что-нибудь по теме.</div>`}
      <div class="chat" id="chat">${data.messages.filter((m) => m.kind !== "problem").map(messageHtml).join("")}</div>
      <div class="composer"><div class="inner">
        <div class="modes">
          <button class="secondary ${mode === "chat" ? "mode-on" : ""}" data-mode="chat">💬 Рассуждаю</button>
          <button class="secondary ${mode === "check" ? "mode-on" : ""}" data-mode="check" ${p ? "" : "disabled"}>✔ Проверить решение</button>
          <button class="secondary" id="hint" ${p && p.hint_level < 4 ? "" : "disabled"}>💡 Подсказка</button>
          <button class="secondary" id="new-problem">＋ Новая задача</button>
        </div>
        <form id="send" class="row">
          <textarea id="text" class="grow" rows="1" placeholder="${mode === "check"
            ? "Запиши решение по шагам и ответ" : "Твои мысли или вопрос по задаче"}"></textarea>
          <button type="submit">➤</button>
        </form>
      </div></div>
    `);
    bind();
    const last = document.getElementById("chat").lastElementChild;
    if (last) last.scrollIntoView({ block: "end" });
  };

  const push = (msgs) => {
    data.messages.push(...msgs);
    const chat = document.getElementById("chat");
    msgs.forEach((m) => chat.insertAdjacentHTML("beforeend", messageHtml(m)));
    renderMath(chat);
    chat.lastElementChild?.scrollIntoView({ block: "end", behavior: "smooth" });
  };

  const thinking = () => {
    const chat = document.getElementById("chat");
    chat.insertAdjacentHTML("beforeend", '<div class="typing" id="typing">СОКРАТ думает…</div>');
    chat.lastElementChild.scrollIntoView({ block: "end" });
    return () => document.getElementById("typing")?.remove();
  };

  const bind = () => {
    document.getElementById("back").onclick = () => (location.hash = "#/");
    document.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => { mode = b.dataset.mode; draw(); }));
    const text = document.getElementById("text");
    text.addEventListener("input", () => { text.style.height = "auto"; text.style.height = text.scrollHeight + "px"; });

    document.getElementById("send").onsubmit = async (e) => {
      e.preventDefault();
      const value = text.value.trim();
      if (!value) return;
      const btn = e.target.querySelector("button");
      busy(btn, true);
      const done = thinking();
      try {
        if (mode === "check") {
          const r = await api(`/api/spaces/${id}/check`, { method: "POST", body: { text: value } });
          done();
          data.stats = r.stats;
          if (r.verdict === "correct") {
            haptic("success");
            data.messages.push(...r.messages);
            data.problem = null;
            mode = "chat";
            draw();
            return;
          }
          haptic("warning");
          push(r.messages);
        } else {
          const r = await api(`/api/spaces/${id}/messages`, { method: "POST", body: { text: value } });
          done();
          push(r.messages);
        }
        text.value = "";
        text.style.height = "auto";
      } catch (err) { done(); toast(err.message); }
      busy(btn, false);
    };

    document.getElementById("hint").onclick = async (e) => {
      const level = data.problem.hint_level + 1;
      if (level === 4 && !confirm("Показать полное решение? Задача почти не добавит баллов к индексу.")) return;
      busy(e.currentTarget, true);
      const done = thinking();
      try {
        const r = await api(`/api/spaces/${id}/hint`, { method: "POST" });
        done();
        data.problem.hint_level = r.hint_level;
        data.messages.push(r.message);
        draw();
      } catch (err) { done(); toast(err.message); busy(e.currentTarget, false); }
    };

    document.getElementById("new-problem").onclick = async (e) => {
      const own = prompt("Вставь условие своей задачи или оставь пустым — я подберу задачу сам:", "");
      if (own === null) return;
      if (data.problem && data.messages.some((m) => m.problem_id === data.problem.id && m.role === "user")
          && !confirm("Текущая задача будет засчитана как нерешённая. Продолжить?")) return;
      busy(e.currentTarget, true);
      try {
        await api(`/api/spaces/${id}/problem`, { method: "POST", body: { text: own } });
        spaceScreen(id);
      } catch (err) { toast(err.message); busy(e.currentTarget, false); }
    };
  };

  draw();
}

async function quizScreen() {
  if (!state.quiz) {
    setView(`
      <h1>Тест по моим ошибкам</h1>
      <p class="muted">Я соберу 5 вопросов именно по тем местам, где ты ошибался. Если наберёшь 4 из 5 и больше,
        эти ошибки будут считаться проработанными.</p>
      <div class="card stack" style="margin-top:16px">
        <button id="start">Собрать тест</button>
      </div>`);
    document.getElementById("start").onclick = async (e) => {
      busy(e.currentTarget, true);
      try {
        state.quiz = { ...(await api("/api/quiz", { method: "POST" })), picked: [], result: null };
        quizScreen();
      } catch (err) { toast(err.message); busy(e.currentTarget, false); }
    };
    return;
  }

  const q = state.quiz;
  setView(`
    <h1>Тест по моим ошибкам</h1>
    <p class="muted">${q.based_on ? `Основан на ${q.based_on} твоих ошибках` : "По твоим темам"}</p>
    ${q.result ? `<div class="card" style="margin-top:12px"><b>Результат: ${q.result.score} из ${q.result.total}</b>
      <p class="muted">${q.result.score / q.result.total >= 0.8 ? "Отлично! Ошибки отмечены как проработанные." : "Разбери пояснения и попробуй ещё раз."}</p></div>` : ""}
    ${q.questions.map((item, i) => `
      <div class="card" style="margin-top:12px">
        <b>${i + 1}. </b>${md(item.question)}
        ${item.options.map((o, j) => {
          let cls = q.picked[i] === j ? "picked" : "";
          if (q.result) {
            const r = q.result.results[i];
            cls = j === r.correct ? "right" : (j === r.given ? "wrong" : "");
          }
          return `<button class="option ${cls}" data-q="${i}" data-o="${j}" ${q.result ? "disabled" : ""}>${md(o)}</button>`;
        }).join("")}
        ${q.result ? `<p class="muted" style="margin-top:8px">${md(q.result.results[i].explanation)}</p>` : ""}
      </div>`).join("")}
    <div style="margin:16px 0" class="row">
      ${q.result ? '<button id="again" class="grow">Новый тест</button>'
                 : `<button id="submit" class="grow" ${q.picked.filter((x) => x != null).length < q.questions.length ? "disabled" : ""}>Проверить</button>`}
    </div>`);

  view.querySelectorAll(".option").forEach((b) => (b.onclick = () => {
    q.picked[+b.dataset.q] = +b.dataset.o;
    const y = window.scrollY;
    quizScreen();
    window.scrollTo(0, y);
  }));
  document.getElementById("submit")?.addEventListener("click", async (e) => {
    busy(e.currentTarget, true);
    try {
      q.result = await api(`/api/quiz/${q.id}/submit`, { method: "POST", body: { answers: q.picked } });
      haptic(q.result.score / q.result.total >= 0.8 ? "success" : "warning");
      quizScreen();
    } catch (err) { toast(err.message); busy(e.currentTarget, false); }
  });
  document.getElementById("again")?.addEventListener("click", () => { state.quiz = null; quizScreen(); });
}

async function profileScreen() {
  setView('<div class="empty"><span class="spinner"></span></div>');
  const me = await api("/api/me");
  const max = Math.max(1, ...me.mistakes_by_type.map((m) => m.count));
  setView(`
    <h1>${esc(me.user.first_name)} ${esc(me.user.last_name || "")}</h1>
    <div class="card row" style="margin-top:12px">
      <label class="grow" for="grade">Класс</label>
      <select id="grade" style="width:auto">
        <option value="">—</option>
        ${[5, 6, 7, 8, 9, 10, 11].map((g) => `<option ${me.user.grade === g ? "selected" : ""}>${g}</option>`).join("")}
      </select>
    </div>

    <h2>Индекс самостоятельности</h2>
    <div class="card hero">${ring(me.stats.index)}
      <p class="muted grow">Задача, решённая сама с первой попытки, даёт 100 баллов. Каждая ступень подсказки
        и каждая лишняя проверка снижают вклад. Полное решение даёт почти 0.</p></div>

    <h2>Над чем поработать</h2>
    <div class="card stack">
      ${me.mistakes_by_type.length ? me.mistakes_by_type.map((m) => `
        <div><div class="row"><span class="grow">${esc(m.label)}</span><b>${m.count}</b></div>
        <div class="bar"><div style="width:${(100 * m.count) / max}%"></div></div></div>`).join("")
        : '<p class="muted">Открытых ошибок нет 👏</p>'}
    </div>
    ${me.weak_topics.length ? `<h2>Слабые темы</h2><div class="chips">${me.weak_topics
      .map((t) => `<span class="chip">${esc(t.topic)} · ${t.count}</span>`).join("")}</div>` : ""}
  `);
  document.getElementById("grade").onchange = async (e) => {
    await api("/api/me", { method: "PATCH", body: { grade: e.target.value ? +e.target.value : null } });
    toast("Сохранено");
  };
}

// ---------- роутер ----------
async function route() {
  const hash = location.hash.startsWith("#/") ? location.hash : "#/";
  const tab = hash.startsWith("#/quiz") ? "quiz" : hash.startsWith("#/profile") ? "profile" : "home";
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  const sub = hash !== "#/";
  try {
    if (sub) { WebApp?.BackButton?.show(); } else { WebApp?.BackButton?.hide(); }
  } catch (_) { /* старые клиенты */ }

  try {
    const m = hash.match(/^#\/space\/(\d+)/);
    if (m) await spaceScreen(+m[1]);
    else if (tab === "quiz") await quizScreen();
    else if (tab === "profile") await profileScreen();
    else await homeScreen();
  } catch (err) {
    setView(`<div class="card empty">${esc(err.message)}</div>`);
  }
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", async () => {
  await window.maxBridge;
  WebApp = window.WebApp || null;
  try {
    WebApp?.ready?.();
    WebApp?.BackButton?.onClick(() => history.back());
  } catch (_) { /* вне MAX */ }
  route();
});
