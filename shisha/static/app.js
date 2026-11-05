const form = document.querySelector("#settings-form");
const toast = document.querySelector(".toast");
const clearedSecrets = new Set();
const groupList = document.querySelector("#group-list");
const groupCount = document.querySelector("#group-count");
const groupSearch = document.querySelector("#group-search");
const refreshGroups = document.querySelector("#refresh-groups");
const notificationSelect = form.elements.namedItem("filter.notification_group");
let selectedGroups = new Set();
let selectedNotification = "";
let availableGroups = [];
let groupMessage = "正在读取群列表…";
let groupError = "";
let groupRequest = 0;
let toastTimer;

function notice(message, error = false) {
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3000);
}

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

function updateOutputToggles() {
  notificationSelect.disabled = !form.elements.namedItem(
    "filter.notify_enabled",
  ).checked;
  const todoistEnabled = form.elements.namedItem("todoist.enabled").checked;
  for (const element of document.querySelectorAll(
    '#todoist input:not([name="todoist.enabled"]), #todoist .secret button',
  )) {
    element.disabled = !todoistEnabled;
  }
}

function renderConfig(config) {
  selectedGroups = new Set(config.filter.groups);
  selectedNotification = config.filter.notification_group;
  for (const input of form.querySelectorAll(
    "input[name], textarea[name], select[name]",
  )) {
    const [section, key] = input.name.split(".");
    const value = config[section][key];
    if (input.type === "radio") input.checked = input.value === value;
    else if (input.type === "checkbox") input.checked = value;
    else if (input === notificationSelect) continue;
    else input.value = Array.isArray(value) ? value.join("\n") : value;
    if (input.type === "password") {
      input.placeholder = config[section][`${key}_saved`]
        ? "已保存，留空则保留"
        : section === "snowluma"
          ? "可留空"
          : "输入令牌或密钥";
    }
  }
  clearedSecrets.clear();
  form.querySelectorAll("[data-clear]").forEach((button) => {
    button.classList.remove("active");
    button.textContent = "清除";
  });
  updateMode();
  updateOutputToggles();
  renderGroups();
}

function allGroups() {
  const groups = [...availableGroups];
  const known = new Set(groups.map((group) => group.id));
  for (const id of [...selectedGroups, selectedNotification]) {
    if (id && !known.has(id)) {
      groups.push({ id, name: `群 ${id}` });
      known.add(id);
    }
  }
  return groups;
}

function renderNotificationOptions(groups) {
  notificationSelect.replaceChildren(new Option("选择通知群聊", ""));
  for (const group of groups)
    notificationSelect.add(new Option(`${group.name} (${group.id})`, group.id));
  notificationSelect.value = selectedNotification;
}

function renderGroups() {
  groupList.replaceChildren();
  const groups = allGroups();
  renderNotificationOptions(groups);
  const query = groupSearch.value.trim().toLocaleLowerCase();
  const visible = groups.filter((group) =>
    `${group.name} ${group.id}`.toLocaleLowerCase().includes(query),
  );
  visible.sort(
    (a, b) =>
      Number(selectedGroups.has(b.id)) - Number(selectedGroups.has(a.id)),
  );
  groupCount.textContent = selectedGroups.size
    ? `已开启 ${selectedGroups.size} 个`
    : "选择要监听的群聊";
  if (groupError && groups.length) {
    const message = document.createElement("p");
    message.className = "group-empty";
    message.textContent = groupError;
    groupList.append(message);
  }
  if (!visible.length) {
    const message = document.createElement("p");
    message.className = "group-empty";
    message.textContent = query ? "没有匹配的群聊" : groupMessage;
    groupList.append(message);
    return;
  }
  for (const group of visible) {
    const row = document.createElement("label");
    row.className = "group-row";
    const meta = document.createElement("span");
    meta.className = "group-meta";
    const name = document.createElement("span");
    name.className = "group-name";
    name.textContent = group.name;
    const id = document.createElement("span");
    id.className = "group-id";
    id.textContent = group.id;
    meta.append(name, id);
    const toggle = document.createElement("span");
    toggle.className = "switch";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = selectedGroups.has(group.id);
    input.setAttribute("aria-label", `监听 ${group.name}`);
    input.addEventListener("change", () => {
      if (input.checked) selectedGroups.add(group.id);
      else selectedGroups.delete(group.id);
      renderGroups();
      groupList
        .querySelectorAll('input[type="checkbox"]')
        .forEach((checkbox) => {
          if (checkbox.getAttribute("aria-label") === `监听 ${group.name}`)
            checkbox.focus({ preventScroll: true });
        });
    });
    const track = document.createElement("span");
    track.className = "switch-track";
    toggle.append(input, track);
    row.append(groupAvatar(group.id, group.name), meta, toggle);
    groupList.append(row);
  }
}

async function loadGroups() {
  const requestId = ++groupRequest;
  const currentMode = mode();
  refreshGroups.disabled = true;
  groupMessage = "正在读取群列表…";
  groupError = "";
  if (!availableGroups.length) renderGroups();
  try {
    const response = await fetch("/api/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: currentMode,
        url: form.elements
          .namedItem(`snowluma.${currentMode}_url`)
          .value.trim(),
        token: form.elements
          .namedItem(`snowluma.${currentMode}_token`)
          .value.trim(),
        clear_token: clearedSecrets.has(`snowluma.${currentMode}_token`),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "无法读取群列表");
    if (requestId !== groupRequest) return;
    availableGroups = data.groups;
    groupMessage = "当前账号没有群聊";
  } catch (error) {
    if (requestId !== groupRequest) return;
    availableGroups = [];
    groupMessage = error.message || "无法读取群列表";
    groupError = groupMessage;
  } finally {
    if (requestId === groupRequest) {
      refreshGroups.disabled = false;
      renderGroups();
    }
  }
}

refreshGroups.addEventListener("click", loadGroups);
groupSearch.addEventListener("input", renderGroups);
notificationSelect.addEventListener(
  "change",
  () => (selectedNotification = notificationSelect.value),
);
form.querySelectorAll('input[name="snowluma.mode"]').forEach((input) =>
  input.addEventListener("change", () => {
    updateMode();
    availableGroups = [];
    loadGroups();
  }),
);
form
  .querySelectorAll(
    'input[name="filter.notify_enabled"], input[name="todoist.enabled"]',
  )
  .forEach((input) => input.addEventListener("change", updateOutputToggles));

function splitItems(value) {
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function serialize() {
  const result = {
    snowluma: {},
    filter: {},
    ai: {},
    todoist: {},
    clear_secrets: [...clearedSecrets],
  };
  for (const input of form.querySelectorAll(
    "input[name], textarea[name], select[name]",
  )) {
    if (input.type === "radio" && !input.checked) continue;
    const [section, key] = input.name.split(".");
    let value = input.type === "checkbox" ? input.checked : input.value.trim();
    if (input.tagName === "TEXTAREA") value = splitItems(value);
    if (input.type === "number") value = Number(value);
    if (input === notificationSelect) value = selectedNotification;
    result[section][key] = value;
  }
  result.filter.groups = [...selectedGroups];
  return result;
}

form.querySelectorAll("[data-clear]").forEach((button) => {
  button.addEventListener("click", () => {
    const name = button.dataset.clear;
    const input = form.elements.namedItem(name);
    if (clearedSecrets.has(name)) {
      clearedSecrets.delete(name);
      button.classList.remove("active");
      button.textContent = "清除";
      input.placeholder = "已保存，留空则保留";
    } else {
      clearedSecrets.add(name);
      input.value = "";
      input.placeholder = "保存后清除";
      button.classList.add("active");
      button.textContent = "撤销";
    }
  });
});
form.querySelectorAll('input[type="password"]').forEach((input) =>
  input.addEventListener("input", () => {
    if (!input.value) return;
    clearedSecrets.delete(input.name);
    const button = form.querySelector(`[data-clear="${input.name}"]`);
    button.classList.remove("active");
    button.textContent = "清除";
  }),
);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const buttons = document.querySelectorAll('button[type="submit"]');
  buttons.forEach((button) => (button.disabled = true));
  try {
    const response = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(serialize()),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "保存失败");
    renderConfig(data.config);
    renderStatus(data.status);
    loadGroups();
    notice("设置已保存");
  } catch (error) {
    notice(error.message || "保存失败", true);
  } finally {
    buttons.forEach((button) => (button.disabled = false));
  }
});

(async () => {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error();
    const data = await response.json();
    renderConfig(data.config);
    renderStatus(data.status);
    loadGroups();
    setInterval(refreshStatus, 4000);
  } catch (_) {
    notice("无法读取设置", true);
  }
})();
