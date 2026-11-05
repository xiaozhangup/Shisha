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
    ? status.configured
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
