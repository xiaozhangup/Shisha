const messageList = document.querySelector("#message-list");
const loadMore = document.querySelector("#load-more");
const refreshButton = document.querySelector("#refresh-messages");
const tabs = document.querySelectorAll("[data-kind]");
let activeKind = "messages";
let nextBefore = null;
let expanded = false;
let generation = 0;

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function dateText(timestamp) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp * 1000));
}

function messageCard(item) {
  const card = element("article", "message-card");
  const heading = element("div", "message-card-heading");
  const groupName = item.group_name || `群 ${item.group_id}`;
  const identity = element("div", "message-identity");
  const title = element(
    "strong",
    "message-name",
    item.sender_name || String(item.user_id),
  );
  const source = element(
    "span",
    "message-source",
    `${groupName}  ${item.group_id}`,
  );
  identity.append(title, source);
  heading.append(groupAvatar(item.group_id, groupName), identity);
  const right = element("div", "message-meta");
  if (item.sent_to_ai)
    right.append(element("span", "message-badge", "已提交 AI"));
  right.append(element("time", "message-time", dateText(item.event_time)));
  heading.append(right);
  card.append(
    heading,
    element("div", "message-body", item.text || "[非文字消息]"),
  );
  return card;
}

function aiCard(item) {
  const card = element("article", "message-card ai-card");
  const heading = element("div", "message-card-heading");
  const groupName = item.group_name || `群 ${item.group_id}`;
  const identity = element("div", "message-identity");
  identity.append(
    element("strong", "message-name", groupName),
    element("span", "message-source", String(item.group_id)),
  );
  heading.append(groupAvatar(item.group_id, groupName), identity);
  const right = element("div", "message-meta");
  const labels = {
    pending: "处理中",
    complete: "已完成",
    empty: "无任务",
    failed: "提取失败",
    interrupted: "已中断",
  };
  right.append(
    element("span", "message-badge", labels[item.status] || item.status),
  );
  right.append(element("time", "message-time", dateText(item.created_at)));
  heading.append(right);
  card.append(
    heading,
    element("div", "message-caption", "提交内容"),
    element("div", "message-body", item.text),
  );
  if (item.result && item.status === "complete") {
    card.append(
      element("div", "message-caption result-caption", "摘要结果"),
      element("div", "message-result", item.result),
    );
  }
  return card;
}

async function loadMessages(append = false, quiet = false) {
  const requestId = ++generation;
  const requestKind = activeKind;
  const params = new URLSearchParams({ kind: requestKind });
  if (append && nextBefore) params.set("before", nextBefore);
  if (!quiet) refreshButton.disabled = true;
  try {
    const response = await fetch(`/api/messages?${params}`);
    if (!response.ok) throw new Error("无法读取消息");
    const data = await response.json();
    if (requestId !== generation) return;
    if (!append) messageList.replaceChildren();
    for (const item of data.items)
      messageList.append(
        requestKind === "messages" ? messageCard(item) : aiCard(item),
      );
    if (!messageList.children.length) {
      const empty = element("div", "message-empty");
      empty.append(
        element(
          "strong",
          "empty-title",
          requestKind === "messages" ? "还没有群消息" : "还没有 AI 摘要",
        ),
      );
      empty.append(
        element(
          "span",
          "empty-detail",
          requestKind === "messages"
            ? "开启监听后，收到的消息会显示在这里。"
            : "提交给 AI 的内容会显示在这里。",
        ),
      );
      messageList.append(empty);
    }
    nextBefore = data.next_before;
    loadMore.hidden = !nextBefore;
    if (append) expanded = true;
  } catch (error) {
    if (requestId === generation && !quiet)
      messageList.replaceChildren(
        element("p", "message-empty", error.message || "无法读取消息"),
      );
  } finally {
    if (requestId === generation) refreshButton.disabled = false;
  }
}

tabs.forEach((button) =>
  button.addEventListener("click", () => {
    activeKind = button.dataset.kind;
    expanded = false;
    nextBefore = null;
    tabs.forEach((tab) => {
      const selected = tab === button;
      tab.classList.toggle("active", selected);
      tab.setAttribute("aria-selected", String(selected));
    });
    loadMessages();
  }),
);
refreshButton.addEventListener("click", () => {
  expanded = false;
  loadMessages();
});
loadMore.addEventListener("click", () => loadMessages(true));
loadMessages();
refreshStatus();
setInterval(() => {
  if (!expanded && !document.hidden) loadMessages(false, true);
}, 5000);
setInterval(refreshStatus, 4000);
