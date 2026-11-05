const form = document.querySelector("#settings-form");
const toast = document.querySelector(".toast");
const saveState = document.querySelector("[data-save-state]");
const keywordList = document.querySelector("#keyword-list");
const keywordInput = document.querySelector("#keyword-input");
let state;
let editor;
let toastTimer;

function notice(message, error = false) {
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3000);
}

function showSaveState(status, message) {
  saveState.classList.toggle("error", status === "error");
  saveState.textContent =
    status === "saving"
      ? "正在保存…"
      : status === "error"
        ? `未保存：${message}`
        : "已自动保存";
}

const saver = new AutoSave(showSaveState, (key, patch, data) => {
  renderStatus(data.status);
  if (key.includes(".token") || key === "ai.api_key") {
    const [section, field] = key.split(".");
    const input = form.elements.namedItem(key);
    const value = patch[section][field];
    state[section][`${field}_saved`] = data.config[section][`${field}_saved`];
    if (input.value.trim() === value && document.activeElement !== input)
      input.value = "";
    input.placeholder = state[section][`${field}_saved`]
      ? "已保存，输入可替换"
      : "输入令牌或密钥";
  }
  if (key.startsWith("snowluma.")) setTimeout(() => editor.loadGroups(), 0);
  if (key === "todoist.token") setTimeout(() => editor.loadCatalog(), 0);
});

function mode() {
  return form.querySelector('input[name="snowluma.mode"]:checked').value;
}

function updateMode() {
  for (const section of document.querySelectorAll("[data-connection]")) {
    const active = section.dataset.connection === mode();
    section.hidden = !active;
    section
      .querySelectorAll("input, button")
      .forEach((input) => (input.disabled = !active));
    section.querySelector('input[type="url"]').required = active;
  }
}

function saveField(section, key, value, delay = 600) {
  state[section][key] = value;
  saver.queue(`${section}.${key}`, { [section]: { [key]: value } }, delay);
}

function renderKeywords() {
  keywordList.replaceChildren();
  for (const keyword of state.filter.keywords) {
    const bubble = document.createElement("span");
    bubble.className = "keyword-bubble";
    const text = document.createElement("span");
    text.textContent = keyword;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `删除关键词 ${keyword}`);
    remove.addEventListener("click", () => {
      state.filter.keywords = state.filter.keywords.filter(
        (item) => item !== keyword,
      );
      saver.queue(
        "filter.keywords",
        { filter: { keywords: state.filter.keywords } },
        100,
      );
      renderKeywords();
    });
    bubble.append(text, remove);
    keywordList.append(bubble);
  }
}

function renderConfig(config) {
  state = config;
  for (const input of form.querySelectorAll("input[name], select[name]")) {
    const [section, key] = input.name.split(".");
    const value = config[section][key];
    if (input.type === "radio") input.checked = input.value === value;
    else if (input.type === "checkbox") input.checked = value;
    else if (input.name === "filter.notification_group") continue;
    else input.value = value;
    if (input.type === "password")
      input.placeholder = config[section][`${key}_saved`]
        ? "已保存，输入可替换"
        : "输入令牌或密钥";
  }
  updateMode();
  renderKeywords();
  editor = new GroupEditor(form, state, saver, notice);
  editor.renderGroups();
  editor.renderTargets();
}

function bindSettings() {
  for (const input of form.querySelectorAll("input[name], select[name]")) {
    if (input.name === "filter.notification_group") continue;
    const [section, key] = input.name.split(".");
    if (input.type === "password") {
      input.addEventListener("input", () => {
        saver.queue(
          input.name,
          { [section]: { [key]: input.value.trim() } },
          1200,
        );
      });
      input.addEventListener("change", () => {
        const value = input.value.trim();
        saver.queue(input.name, { [section]: { [key]: value } }, 100);
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          input.blur();
        }
      });
      continue;
    }
    const eventName =
      ["radio", "checkbox"].includes(input.type) || input.tagName === "SELECT"
        ? "change"
        : "input";
    input.addEventListener(eventName, () => {
      if (input.type === "radio" && !input.checked) return;
      let value =
        input.type === "checkbox" ? input.checked : input.value.trim();
      if (input.type === "number") value = Number(value);
      saveField(section, key, value, eventName === "change" ? 100 : 600);
      if (input.name === "snowluma.mode") {
        updateMode();
        editor.availableGroups = [];
        editor.loadGroups();
      }
      if (input.name === "filter.notify_enabled") editor.renderGroups();
    });
    if (eventName === "input")
      input.addEventListener("change", () => saver.flush());
  }
  form.querySelectorAll("[data-clear]").forEach((button) =>
    button.addEventListener("click", () => {
      const name = button.dataset.clear;
      const input = form.elements.namedItem(name);
      const [section, key] = name.split(".");
      input.value = "";
      saver.queue(name, { [section]: { [key]: "" } }, 100);
    }),
  );
  form.addEventListener("submit", (event) => event.preventDefault());
  window.addEventListener("pagehide", () => saver.flush());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) saver.flush();
  });
  keywordInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const keyword = keywordInput.value.trim();
      if (keyword && !state.filter.keywords.includes(keyword)) {
        state.filter.keywords.push(keyword);
        saver.queue(
          "filter.keywords",
          { filter: { keywords: state.filter.keywords } },
          100,
        );
        renderKeywords();
      }
      keywordInput.value = "";
    } else if (
      event.key === "Backspace" &&
      !keywordInput.value &&
      state.filter.keywords.length
    ) {
      state.filter.keywords.pop();
      saver.queue(
        "filter.keywords",
        { filter: { keywords: state.filter.keywords } },
        100,
      );
      renderKeywords();
    }
  });
  document
    .querySelectorAll('a[href="/messages"], a[href="/"]')
    .forEach((link) =>
      link.addEventListener("click", async (event) => {
        if (!saver.pending.size && !saver.running && !saver.failures.size)
          return;
        event.preventDefault();
        if (await saver.settle()) window.location.href = link.href;
        else notice("请先修正未保存的设置", true);
      }),
    );
}

(async () => {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error();
    const data = await response.json();
    renderConfig(data.config);
    renderStatus(data.status);
    bindSettings();
    editor.loadGroups();
    editor.loadCatalog();
    setInterval(refreshStatus, 4000);
  } catch (_) {
    notice("无法读取设置", true);
  }
})();
