const groupList = document.querySelector("#conversation-groups");
const conversationHeading = document.querySelector("#conversation-heading");
const conversationScroll = document.querySelector("#conversation-scroll");
const conversationContent = document.querySelector("#conversation-content");
const refreshButton = document.querySelector("#refresh-messages");

const conversation = {
  groups: [],
  groupsLoaded: false,
  names: new Map(),
  active: null,
  items: [],
  requests: new Map(),
  unanchored: [],
  nextBefore: null,
  loaded: false,
  generation: 0,
  busy: false,
};

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

function appendMessageImage(container, url) {
  const link = element("a", "message-image-link");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener";
  link.setAttribute("aria-label", "查看图片");
  const image = document.createElement("img");
  image.className = "message-image";
  image.src = url;
  image.alt = "图片";
  image.loading = "lazy";
  image.addEventListener("error", () =>
    link.replaceWith(element("span", "message-image-error", "[图片加载失败]")),
  );
  link.append(image);
  container.append(link);
}

function appendSummaryText(container, text, images) {
  let offset = 0;
  while (offset < text.length) {
    let next = null;
    for (const image of images) {
      const index = text.indexOf(image.marker, offset);
      if (index >= 0 && (!next || index < next.index))
        next = { ...image, index };
    }
    if (!next) break;
    if (next.index > offset)
      container.append(document.createTextNode(text.slice(offset, next.index)));
    appendMessageImage(container, next.url);
    offset = next.index + next.marker.length;
  }
  container.append(document.createTextNode(text.slice(offset)));
}

function groupName(group) {
  return conversation.names.get(group.id) || group.name || `群 ${group.id}`;
}

function renderGroups() {
  groupList.replaceChildren();
  if (!conversation.groups.length) {
    groupList.append(
      element("p", "conversation-placeholder", "还没有监听群聊"),
    );
    return;
  }
  for (const group of conversation.groups) {
    const name = groupName(group);
    const button = element("button", "conversation-group");
    button.type = "button";
    button.classList.toggle("active", group.id === conversation.active);
    button.setAttribute(
      "aria-pressed",
      String(group.id === conversation.active),
    );
    const details = element("span", "conversation-group-details");
    details.append(
      element("strong", "conversation-group-name", name),
      element(
        "span",
        "conversation-group-preview",
        group.latest?.text || "还没有消息",
      ),
    );
    button.append(groupAvatar(group.id, name), details);
    button.addEventListener("click", () => selectGroup(group.id));
    groupList.append(button);
  }
}

function renderHeading() {
  const group = conversation.groups.find(
    (item) => item.id === conversation.active,
  );
  conversationHeading.replaceChildren();
  if (!group) {
    conversationHeading.append(
      element("strong", "conversation-heading-name", "选择群聊"),
    );
    return;
  }
  const name = groupName(group);
  const identity = element("div", "conversation-heading-identity");
  identity.append(
    element("strong", "conversation-heading-name", name),
    element("span", "conversation-heading-id", group.id),
  );
  conversationHeading.append(groupAvatar(group.id, name), identity);
}

function messageRow(item, submitted = false) {
  const row = element("article", "chat-message");
  row.dataset.rowId = item.id;
  const name =
    item.sender_name || (item.user_id ? String(item.user_id) : "原消息未收集");
  const avatar = element("span", "chat-avatar", [...name.trim()][0] || "群");
  avatar.setAttribute("aria-hidden", "true");
  if (item.user_id > 0) {
    const image = document.createElement("img");
    image.alt = "";
    image.loading = "lazy";
    image.src = `https://q1.qlogo.cn/g?b=qq&nk=${item.user_id}&s=100`;
    image.addEventListener("error", () => image.remove());
    avatar.append(image);
  }
  const content = element("div", "chat-message-content");
  const meta = element("div", "chat-message-meta");
  meta.append(
    element("strong", "chat-sender", name),
    element("time", "chat-time", dateText(item.event_time)),
  );
  if (submitted) meta.append(element("span", "chat-submitted", "已提交"));
  const bubble = element("div", "chat-bubble");
  if (item.parts) {
    for (const part of item.parts) {
      if (part.type === "image") appendMessageImage(bubble, part.url);
      else bubble.append(document.createTextNode(part.text));
    }
  } else {
    bubble.textContent = item.text || "[非文字消息]";
  }
  content.append(meta, bubble);
  row.append(avatar, content);
  return row;
}

function summaryCard(request) {
  const card = element("article", "summary-card");
  const heading = element("div", "summary-card-heading");
  const labels = {
    pending: "处理中",
    complete: "已完成",
    empty: "未提取到任务",
    failed: "提取失败",
    interrupted: "已中断",
  };
  heading.append(
    element("strong", "summary-title", "AI 摘要"),
    element("span", "summary-status", labels[request.status] || request.status),
  );
  card.append(
    heading,
    element("time", "summary-time", dateText(request.created_at)),
  );
  if (request.status === "complete" && request.result) {
    const body = element("div", "summary-body");
    appendSummaryText(body, request.result, request.images || []);
    card.append(body);
  } else if (
    request.status === "failed" &&
    (request.result?.startsWith("图片读取失败：") ||
      request.result?.startsWith("AI "))
  ) {
    card.append(element("div", "summary-body", request.result));
  }
  return card;
}

function rangeBlock(items, batches) {
  const block = element("section", "summary-range");
  block.setAttribute("aria-label", "提交给 AI 的消息范围");
  block.classList.toggle(
    "starts-here",
    batches.some((batch) => batch.first_message_row === items[0].id),
  );
  block.classList.toggle(
    "ends-here",
    batches.some((batch) => batch.last_message_row === items.at(-1).id),
  );
  const messages = element("div", "summary-messages");
  const summaries = element("div", "summary-side");
  const included = new Set(batches.flatMap((batch) => batch.message_rows));
  const rows = [];
  for (const item of items) {
    const row = messageRow(item, included.has(item.id));
    row.classList.toggle(
      "range-start",
      batches.some((batch) => batch.first_message_row === item.id),
    );
    row.classList.toggle(
      "range-end",
      batches.some((batch) => batch.last_message_row === item.id),
    );
    rows.push(row);
    messages.append(row);
  }
  for (const batch of batches) {
    const card = summaryCard(batch);
    if (batches.length > 1) {
      card.tabIndex = 0;
      card.title = "聚焦时突出显示对应消息";
      const mark = (active) => {
        block.classList.toggle("has-focused-summary", active);
        rows.forEach((row, index) => {
          const id = items[index].id;
          row.classList.toggle(
            "focused-range",
            active &&
              id >= batch.first_message_row &&
              id <= batch.last_message_row,
          );
          row.classList.toggle(
            "focused-message",
            active && batch.message_rows.includes(id),
          );
          row.classList.toggle(
            "focused-start",
            active && id === batch.first_message_row,
          );
          row.classList.toggle(
            "focused-end",
            active && id === batch.last_message_row,
          );
        });
      };
      card.addEventListener("mouseenter", () => mark(true));
      card.addEventListener("mouseleave", () => mark(false));
      card.addEventListener("focus", () => mark(true));
      card.addEventListener("blur", () => mark(false));
    }
    summaries.append(card);
  }
  block.append(messages, summaries);
  return block;
}

function unanchoredBlock(request) {
  const block = element(
    "section",
    "summary-range unanchored-range starts-here ends-here",
  );
  block.setAttribute("aria-label", "原消息未收集的摘要");
  const messages = element("div", "summary-messages");
  const row = messageRow(
    {
      id: `request-${request.id}`,
      sender_name: "原消息未收集",
      event_time: request.created_at,
      text: request.text,
    },
    true,
  );
  row.classList.add("range-start", "range-end");
  messages.append(row);
  const summaries = element("div", "summary-side");
  summaries.append(summaryCard(request));
  block.append(messages, summaries);
  return block;
}

function renderConversation(position = "keep") {
  const oldHeight = conversationScroll.scrollHeight;
  const oldTop = conversationScroll.scrollTop;
  const nearBottom = oldHeight - oldTop - conversationScroll.clientHeight < 80;
  conversationContent.replaceChildren();
  if (!conversation.active) {
    conversationContent.append(
      element("p", "conversation-empty", "选择一个群聊查看消息。"),
    );
    return;
  }
  if (conversation.nextBefore) {
    const older = element("button", "conversation-older", "加载更早消息");
    older.type = "button";
    older.addEventListener("click", loadOlder);
    conversationContent.append(older);
  }
  if (conversation.unanchored.length) {
    conversationContent.append(
      element("p", "unanchored-heading", "未收集原消息的摘要"),
    );
    for (const request of conversation.unanchored) {
      conversationContent.append(unanchoredBlock(request));
    }
  }
  if (!conversation.items.length && !conversation.unanchored.length) {
    conversationContent.append(
      element("p", "conversation-empty", "还没有群消息"),
    );
  }

  const items = conversation.items;
  const intervals = [];
  for (const batch of conversation.requests.values()) {
    const start = items.findIndex(
      (item) =>
        item.id >= batch.first_message_row && item.id <= batch.last_message_row,
    );
    if (start < 0) continue;
    let end = start;
    while (
      end + 1 < items.length &&
      items[end + 1].id <= batch.last_message_row
    )
      end++;
    intervals.push({ start, end, batch });
  }
  intervals.sort(
    (a, b) => a.start - b.start || a.end - b.end || a.batch.id - b.batch.id,
  );
  const ranges = [];
  for (const interval of intervals) {
    const previous = ranges.at(-1);
    if (previous && interval.start <= previous.end) {
      previous.end = Math.max(previous.end, interval.end);
      previous.batches.push(interval.batch);
    } else {
      ranges.push({
        start: interval.start,
        end: interval.end,
        batches: [interval.batch],
      });
    }
  }
  let index = 0;
  for (const range of ranges) {
    while (index < range.start)
      conversationContent.append(messageRow(items[index++]));
    conversationContent.append(
      rangeBlock(items.slice(range.start, range.end + 1), range.batches),
    );
    index = range.end + 1;
  }
  while (index < items.length)
    conversationContent.append(messageRow(items[index++]));

  if (position === "older") {
    conversationScroll.scrollTop =
      oldTop + conversationScroll.scrollHeight - oldHeight;
  } else if (position === "bottom" || nearBottom) {
    conversationScroll.scrollTop = conversationScroll.scrollHeight;
  } else {
    conversationScroll.scrollTop = oldTop;
  }
}

function mergeRequests(requests) {
  for (const request of requests)
    conversation.requests.set(request.id, request);
}

async function fetchConversation(params = {}) {
  const query = new URLSearchParams(params);
  const response = await fetch(
    `/api/conversations/${encodeURIComponent(conversation.active)}?${query}`,
  );
  if (!response.ok) throw new Error("无法读取群消息");
  return response.json();
}

async function loadInitial() {
  if (!conversation.active || conversation.busy) return;
  const generation = conversation.generation;
  conversation.busy = true;
  try {
    const data = await fetchConversation();
    if (generation !== conversation.generation) return;
    const changed =
      !conversation.loaded ||
      JSON.stringify([conversation.items, conversation.unanchored]) !==
        JSON.stringify([data.items, data.unanchored]);
    const position = conversation.loaded ? "keep" : "bottom";
    conversation.items = data.items;
    conversation.requests = new Map();
    mergeRequests(data.requests);
    conversation.unanchored = data.unanchored;
    conversation.nextBefore = data.next_before;
    conversation.loaded = true;
    if (changed) renderConversation(position);
  } catch (error) {
    if (generation === conversation.generation) {
      conversationContent.replaceChildren(
        element("p", "conversation-empty", error.message || "无法读取群消息"),
      );
    }
  } finally {
    if (generation === conversation.generation) conversation.busy = false;
  }
}

async function loadOlder(event) {
  if (!conversation.nextBefore || conversation.busy) return;
  const generation = conversation.generation;
  const button = event.currentTarget;
  conversation.busy = true;
  button.disabled = true;
  try {
    const data = await fetchConversation({ before: conversation.nextBefore });
    if (generation !== conversation.generation) return;
    conversation.items = [...data.items, ...conversation.items];
    mergeRequests(data.requests);
    conversation.unanchored = data.unanchored;
    conversation.nextBefore = data.next_before;
    renderConversation("older");
  } catch (error) {
    if (generation === conversation.generation) {
      button.textContent = error.message || "加载失败";
      button.disabled = false;
    }
  } finally {
    if (generation === conversation.generation) conversation.busy = false;
  }
}

async function updateConversation() {
  if (!conversation.active || conversation.busy) return;
  if (!conversation.items.length) return loadInitial();
  const generation = conversation.generation;
  conversation.busy = true;
  let changed = false;
  try {
    let more = true;
    while (more && generation === conversation.generation) {
      const data = await fetchConversation({
        after: conversation.items.at(-1).id,
        range_start: conversation.items[0].id,
      });
      if (generation !== conversation.generation) return;
      const before = JSON.stringify([
        Array.from(conversation.requests.values()),
        conversation.unanchored,
      ]);
      conversation.items.push(...data.items);
      mergeRequests(data.requests);
      conversation.unanchored = data.unanchored;
      changed ||=
        data.items.length > 0 ||
        before !==
          JSON.stringify([
            Array.from(conversation.requests.values()),
            conversation.unanchored,
          ]);
      more = Boolean(data.next_after);
    }
  } catch (_) {
    // 保留已加载的消息，下次刷新时重试。
  } finally {
    if (generation === conversation.generation) {
      conversation.busy = false;
      if (changed) renderConversation();
    }
  }
}

function selectGroup(id) {
  if (conversation.active === id) return;
  conversation.generation++;
  conversation.active = id;
  conversation.items = [];
  conversation.requests = new Map();
  conversation.unanchored = [];
  conversation.nextBefore = null;
  conversation.loaded = false;
  conversation.busy = false;
  renderGroups();
  renderHeading();
  if (id) {
    conversationContent.replaceChildren(
      element("p", "conversation-empty", "正在读取…"),
    );
    loadInitial();
  } else {
    renderConversation();
  }
}

async function loadGroups() {
  try {
    const response = await fetch("/api/conversations");
    if (!response.ok) throw new Error("无法读取群聊");
    const groups = (await response.json()).groups;
    const changed =
      !conversation.groupsLoaded ||
      JSON.stringify(groups) !== JSON.stringify(conversation.groups);
    conversation.groups = groups;
    conversation.groupsLoaded = true;
    if (
      !conversation.groups.some((group) => group.id === conversation.active)
    ) {
      selectGroup(conversation.groups[0]?.id || null);
    }
    if (changed) {
      renderGroups();
      renderHeading();
    }
  } catch (error) {
    conversation.groupsLoaded = false;
    groupList.replaceChildren(
      element("p", "conversation-placeholder", error.message || "无法读取群聊"),
    );
  }
}

async function loadGroupNames() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) return;
    const groups = await getSnowGroups((await response.json()).config);
    conversation.names = new Map(groups.map((group) => [group.id, group.name]));
    renderGroups();
    renderHeading();
  } catch (_) {
    // 离线时继续显示本地记录中的群名。
  }
}

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  await Promise.all([loadGroups(), updateConversation()]);
  refreshButton.disabled = false;
  loadGroupNames();
});
loadGroups();
loadGroupNames();
refreshStatus();
setInterval(() => {
  if (!document.hidden) {
    loadGroups();
    updateConversation();
  }
}, 5000);
setInterval(refreshStatus, 4000);
