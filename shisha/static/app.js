const form = document.querySelector("#settings-form");
let config;

const saver = createPageSaver((key, patch, data) => {
  renderStatus(data.status);
  if (form.elements.namedItem(key).type === "password") {
    const [section, field] = key.split(".");
    const input = form.elements.namedItem(key);
    const value = patch[section][field];
    config[section][`${field}_saved`] = data.config[section][`${field}_saved`];
    if (input.value.trim() === value && document.activeElement !== input)
      input.value = "";
    input.placeholder = config[section][`${field}_saved`]
      ? "已保存，输入可替换"
      : "输入令牌或密钥";
  }
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
  }
}

function bindSettings() {
  for (const input of form.querySelectorAll("input[name]")) {
    const [section, key] = input.name.split(".");
    const value = config[section][key];
    if (input.type === "radio") input.checked = input.value === value;
    else input.value = value;
    if (input.type === "password") {
      input.placeholder = config[section][`${key}_saved`]
        ? "已保存，输入可替换"
        : "输入令牌或密钥";
      input.addEventListener("input", () =>
        saver.queue(
          input.name,
          { [section]: { [key]: input.value.trim() } },
          1200,
        ),
      );
      input.addEventListener("change", () =>
        saver.queue(
          input.name,
          { [section]: { [key]: input.value.trim() } },
          100,
        ),
      );
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          input.blur();
        }
      });
    } else {
      const eventName = input.type === "radio" ? "change" : "input";
      input.addEventListener(eventName, () => {
        if (input.type === "radio" && !input.checked) return;
        config[section][key] = input.value.trim();
        saver.queue(
          input.name,
          { [section]: { [key]: config[section][key] } },
          eventName === "change" ? 100 : 600,
        );
        if (input.name === "snowluma.mode") updateMode();
      });
      if (eventName === "input")
        input.addEventListener("change", () => saver.flush());
    }
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
  updateMode();
}

(async () => {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error();
    const data = await response.json();
    config = data.config;
    bindSettings();
    renderStatus(data.status);
    setInterval(refreshStatus, 4000);
  } catch (_) {
    document.querySelector(".toast").textContent = "无法读取设置";
    document.querySelector(".toast").classList.add("visible", "error");
  }
})();
