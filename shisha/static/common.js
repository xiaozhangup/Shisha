function groupAvatar(id, name) {
  const avatar = document.createElement("span");
  avatar.className = "group-avatar";
  avatar.textContent = [...String(name).trim()][0] || "群";
  if (/^\d+$/.test(String(id))) {
    const image = document.createElement("img");
    image.alt = "";
    image.loading = "lazy";
    image.src = `https://p.qlogo.cn/gh/${id}/${id}/100`;
    image.addEventListener("error", () => image.remove());
    avatar.append(image);
  }
  return avatar;
}

function renderStatus(status) {
  const label = status.connected
    ? "已连接"
    : status.error
      ? "连接中断"
      : status.configured
        ? "连接中"
        : "等待配置";
  const detail = status.connected
    ? !status.listening
      ? "暂无监听群聊"
      : status.configured
        ? "正在监听群消息"
        : "群消息收集中，待完成摘要配置"
    : status.error ||
      (status.configured ? "正在连接 SnowLuma" : "完成设置后开始监听");
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

function initNavigation() {
  const sidebar = document.querySelector("[data-navigation]");
  if (!sidebar) return;
  sidebar.innerHTML = `<a class="brand" href="/" aria-label="Shisha 首页"><span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 36 36" fill="none"><path d="M22.8 9.2c-1.8-1.3-4.1-1.9-6.3-1.4-2.2.4-3.7 1.8-3.7 3.6 0 4.7 10.2 2.6 10.2 8 0 2.2-2 3.9-4.8 4.2-2.5.3-5-.5-6.8-2" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><path d="M12 28h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity=".55"/></svg></span><span class="brand-name">Shisha</span></a><div class="side-label">菜单</div><nav class="navigation primary-nav" aria-label="页面导航"><a href="/">设置</a><a href="/groups">分组</a><a href="/rules">规则</a><a href="/messages">消息</a></nav><div class="side-footer"><span class="status-dot" data-status-dot></span><div><strong data-status>等待配置</strong><span data-status-detail>完成设置后开始监听</span></div></div>`;
  for (const link of sidebar.querySelectorAll(".primary-nav a")) {
    if (new URL(link.href).pathname === window.location.pathname) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
  }
}

function createPageSaver(onSaved = () => {}) {
  const label = document.querySelector("[data-save-state]");
  const saver = new AutoSave((status, message) => {
    label.classList.toggle("error", status === "error");
    label.textContent =
      status === "saving"
        ? "正在保存…"
        : status === "error"
          ? `未保存：${message}`
          : "已自动保存";
  }, onSaved);
  window.addEventListener("pagehide", () => saver.flush());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) saver.flush();
  });
  document.addEventListener("click", async (event) => {
    const link = event.target.closest("a[href]");
    if (
      !link ||
      link.origin !== window.location.origin ||
      link.pathname === window.location.pathname
    )
      return;
    if (!saver.pending.size && !saver.running && !saver.failures.size) return;
    event.preventDefault();
    if (await saver.settle()) window.location.href = link.href;
  });
  return saver;
}

async function getSnowGroups(config, refresh = false) {
  const connection = config.snowluma;
  const mode = connection.mode;
  const response = await fetch("/api/groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode,
      url: connection[`${mode}_url`],
      token: "",
      refresh,
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "无法读取群列表");
  return data.groups;
}

async function getNotificationGroups(refresh = false) {
  const response = await fetch("/api/groups", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "notification", refresh }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "无法读取群列表");
  return data.groups;
}

initNavigation();
