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
  document.querySelectorAll("[data-status]").forEach((node) => {
    node.textContent = label;
    node.title = detail;
  });
  document.querySelectorAll("[data-status-dot]").forEach((node) => {
    node.classList.toggle("online", status.connected);
    node.classList.toggle("error", Boolean(status.error));
  });
  const metrics = {
    groups:
      status.group_count == null
        ? "—"
        : `${status.group_count.toLocaleString("zh-CN")} 个`,
    messages:
      status.message_count == null
        ? "—"
        : `${status.message_count.toLocaleString("zh-CN")} 条`,
    memory:
      status.memory_bytes == null
        ? "—"
        : `${(status.memory_bytes / 1_000_000).toFixed(1)} MB`,
  };
  for (const [key, value] of Object.entries(metrics)) {
    document
      .querySelectorAll(`[data-status-${key}]`)
      .forEach((node) => (node.textContent = value));
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error("无法读取状态");
    renderStatus(await response.json());
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
  const statusCard = `
    <section class="status-card" aria-label="运行状态">
      <div class="status-card-heading">
        <span>运行状态</span>
        <div class="status-card-connection"><span class="status-dot" data-status-dot></span><strong data-status>等待配置</strong></div>
      </div>
      <dl class="status-card-metrics">
        <div><dt>监听群聊</dt><dd data-status-groups>—</dd></div>
        <div><dt>已收消息</dt><dd data-status-messages>—</dd></div>
        <div><dt>内存占用</dt><dd data-status-memory>—</dd></div>
      </dl>
    </section>`;
  sidebar.innerHTML = `
    <a class="brand" href="/" aria-label="Shisha 首页">
      <span class="brand-mark" aria-hidden="true"><img src="/static/shisha.png" alt="" /></span>
      <span class="brand-name">Shisha</span>
    </a>
    <nav class="navigation primary-nav" aria-label="页面导航">
      <a href="/">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
          <path d="M19.4 13.5a7.8 7.8 0 0 0 0-3l1.5-1.2-1.5-2.6-1.9.6a7.7 7.7 0 0 0-2.6-1.5l-.4-2h-3l-.4 2a7.7 7.7 0 0 0-2.6 1.5l-1.9-.6-1.5 2.6 1.5 1.2a7.8 7.8 0 0 0 0 3l-1.5 1.2 1.5 2.6 1.9-.6a7.7 7.7 0 0 0 2.6 1.5l.4 2h3l.4-2a7.7 7.7 0 0 0 2.6-1.5l1.9.6 1.5-2.6-1.5-1.2Z" transform="translate(-1 0)" />
        </svg>
        <span>设置</span>
      </a>
      <a href="/groups">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
          <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
          <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
          <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
        </svg>
        <span>分组</span>
      </a>
      <a href="/rules">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="m4 7 1.6 1.6L8 6.2M11 7.5h9M4 16l1.6 1.6L8 15.2M11 16.5h9" />
        </svg>
        <span>规则</span>
      </a>
      <a href="/messages">
        <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <g transform="translate(0 -0.5)">
            <path d="M5 4.5h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-8l-4.5 3v-3H5a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z" />
            <path d="M7.5 9.5h9M7.5 13h6" />
          </g>
        </svg>
        <span>消息</span>
      </a>
    </nav>
    <div class="side-footer">${statusCard}</div>`;
  document.querySelector(".mobile-status").innerHTML = statusCard;
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
