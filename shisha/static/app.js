const form = document.querySelector("#settings-form");
const toast = document.querySelector(".toast");
const clearedSecrets = new Set();
const groupList = document.querySelector("#group-list");
const groupCount = document.querySelector("#group-count");
const refreshGroups = document.querySelector("#refresh-groups");
let selectedGroups = new Set();
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

function renderStatus(status) {
  const label = !status.configured
    ? "等待配置"
    : status.connected
      ? "已连接"
      : "连接中";
  const detail = !status.configured
    ? "完成设置后开始监听"
    : status.connected
      ? "正在监听群消息"
      : status.error || "正在连接 SnowLuma";
  document
    .querySelectorAll("[data-status]")
    .forEach((node) => (node.textContent = label));
  document
    .querySelectorAll("[data-status-detail]")
    .forEach((node) => (node.textContent = detail));
  document.querySelectorAll("[data-status-dot]").forEach((node) => {
    node.classList.toggle("online", status.connected);
    node.classList.toggle("error", Boolean(status.error));
  });
}

function renderConfig(config) {
  selectedGroups = new Set(config.filter.groups);
  for (const input of form.querySelectorAll("input[name], textarea[name]")) {
    const [section, key] = input.name.split(".");
    const value = config[section][key];
    input.value = Array.isArray(value) ? value.join("\n") : value;
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
  renderGroups();
}

function renderGroups() {
  groupList.replaceChildren();
  const groups = [...availableGroups];
  const known = new Set(groups.map((group) => group.id));
  for (const id of selectedGroups) {
    if (!known.has(id)) groups.push({ id, name: `群 ${id}` });
  }
  groupCount.textContent = selectedGroups.size
    ? `已开启 ${selectedGroups.size} 个`
    : "选择要监听的群聊";
  if (groupError && groups.length) {
    const message = document.createElement("p");
    message.className = "group-empty";
    message.textContent = groupError;
    groupList.append(message);
  }
  if (!groups.length) {
    const message = document.createElement("p");
    message.className = "group-empty";
    message.textContent = groupMessage;
    groupList.append(message);
    return;
  }
  for (const group of groups) {
    const row = document.createElement("label");
    row.className = "group-row";
    const avatar = document.createElement("span");
    avatar.className = "group-avatar";
    avatar.textContent = [...group.name.trim()][0] || "群";
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
      groupCount.textContent = selectedGroups.size
        ? `已开启 ${selectedGroups.size} 个`
        : "选择要监听的群聊";
    });
    const track = document.createElement("span");
    track.className = "switch-track";
    toggle.append(input, track);
    row.append(avatar, meta, toggle);
    groupList.append(row);
  }
}

async function loadGroups() {
  const requestId = ++groupRequest;
  refreshGroups.disabled = true;
  groupMessage = "正在读取群列表…";
  groupError = "";
  if (!availableGroups.length) renderGroups();
  try {
    const response = await fetch("/api/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        http_url: form.elements.namedItem("snowluma.http_url").value.trim(),
        http_token: form.elements.namedItem("snowluma.http_token").value.trim(),
        clear_token: clearedSecrets.has("snowluma.http_token"),
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
  for (const input of form.querySelectorAll("input[name], textarea[name]")) {
    const [section, key] = input.name.split(".");
    let value = input.value.trim();
    if (input.tagName === "TEXTAREA") value = splitItems(value);
    if (input.type === "number") value = Number(value);
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

form.querySelectorAll('input[type="password"]').forEach((input) => {
  input.addEventListener("input", () => {
    if (!input.value) return;
    clearedSecrets.delete(input.name);
    const button = form.querySelector(`[data-clear="${input.name}"]`);
    button.classList.remove("active");
    button.textContent = "清除";
  });
});

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

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    if (response.ok) renderStatus(await response.json());
  } catch (_) {
    renderStatus({
      configured: true,
      connected: false,
      error: "配置服务已断开",
    });
  }
}

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
