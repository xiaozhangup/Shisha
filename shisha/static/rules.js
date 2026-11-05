(async () => {
  const label = document.querySelector("[data-save-state]");
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("无法读取设置");
    const data = await response.json();
    const config = data.config;
    const saver = createPageSaver((key, patch, result) =>
      renderStatus(result.status),
    );
    const keywords = document.querySelector("#keyword-list");
    const keywordInput = document.querySelector("#keyword-input");
    const delay = document.querySelector("#debounce-seconds");
    const notify = document.querySelector("#notify-enabled");
    const sender = document.querySelector("#notification-sender");
    const connectionHint = document.querySelector("#notification-connection-hint");
    const notification = document.querySelector("#notification-group");
    const groupMessage = document.querySelector("#group-message");
    const refresh = document.querySelector("#refresh-groups");
    let groupRequest = 0;

    function saveFilter(key, value, wait = 100) {
      config.filter[key] = value;
      saver.queue(`filter.${key}`, { filter: { [key]: value } }, wait);
    }

    function saveNotification(key, value) {
      config.notification[key] = value;
      saver.queue(`notification.${key}`, { notification: { [key]: value } }, 100);
    }

    function selectedGroup() {
      return sender.value === "other"
        ? config.notification.group_id
        : config.filter.notification_group;
    }

    function updateNotificationControls() {
      sender.disabled = !notify.checked;
      notification.disabled = !notify.checked;
      refresh.disabled = !notify.checked;
      connectionHint.hidden = !notify.checked || sender.value !== "other";
    }

    function renderKeywords() {
      keywords.replaceChildren();
      for (const value of config.filter.keywords) {
        const bubble = document.createElement("span");
        bubble.className = "keyword-bubble";
        const text = document.createElement("span");
        text.textContent = value;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `删除关键词 ${value}`);
        remove.addEventListener("click", () => {
          saveFilter(
            "keywords",
            config.filter.keywords.filter((keyword) => keyword !== value),
          );
          renderKeywords();
        });
        bubble.append(text, remove);
        keywords.append(bubble);
      }
    }

    keywordInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) return;
      event.preventDefault();
      const value = keywordInput.value.trim();
      if (value && !config.filter.keywords.includes(value)) {
        saveFilter("keywords", [...config.filter.keywords, value]);
        renderKeywords();
      }
      keywordInput.value = "";
    });
    delay.value = config.filter.debounce_seconds;
    delay.addEventListener("input", () => {
      const value = Number(delay.value);
      if (delay.value && Number.isInteger(value) && value >= 1 && value <= 300)
        saveFilter("debounce_seconds", value, 600);
    });
    delay.addEventListener("change", () => saver.flush());
    notify.checked = config.filter.notify_enabled;
    sender.value = config.notification.sender;
    updateNotificationControls();
    notify.addEventListener("change", () => {
      saveFilter("notify_enabled", notify.checked);
      updateNotificationControls();
      if (notify.checked) loadGroups();
      else groupRequest++;
    });
    sender.addEventListener("change", () => {
      saveNotification("sender", sender.value);
      updateNotificationControls();
      loadGroups();
    });
    notification.addEventListener("change", () => {
      if (sender.value === "other")
        saveNotification("group_id", notification.value);
      else saveFilter("notification_group", notification.value);
    });

    async function loadGroups(force = false) {
      const request = ++groupRequest;
      const source = sender.value;
      refresh.disabled = true;
      notification.replaceChildren(new Option("选择通知群聊", ""));
      try {
        const groups =
          source === "other"
            ? await getNotificationGroups(force)
            : await getSnowGroups(config, force);
        if (request !== groupRequest) return;
        for (const group of groups)
          notification.add(new Option(`${group.name} (${group.id})`, group.id));
        const selected = selectedGroup();
        if (selected && !groups.some((group) => group.id === selected))
          notification.add(
            new Option(`群 ${selected}`, selected),
          );
        notification.value = selected;
        groupMessage.textContent = "";
      } catch (error) {
        if (request !== groupRequest) return;
        const selected = selectedGroup();
        if (selected) notification.add(new Option(`群 ${selected}`, selected));
        notification.value = selected;
        groupMessage.textContent = error.message || "无法读取群列表";
      } finally {
        if (request === groupRequest) refresh.disabled = !notify.checked;
      }
    }
    refresh.addEventListener("click", () => loadGroups(true));
    renderKeywords();
    renderStatus(data.status);
    if (notify.checked) loadGroups();
    setInterval(refreshStatus, 4000);
  } catch (error) {
    label.classList.add("error");
    label.textContent = error.message || "无法读取设置";
  }
})();
