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
    const notification = document.querySelector("#notification-group");
    const groupMessage = document.querySelector("#group-message");
    const refresh = document.querySelector("#refresh-groups");

    function saveFilter(key, value, wait = 100) {
      config.filter[key] = value;
      saver.queue(`filter.${key}`, { filter: { [key]: value } }, wait);
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
    notification.disabled = !notify.checked;
    notify.addEventListener("change", () => {
      notification.disabled = !notify.checked;
      saveFilter("notify_enabled", notify.checked);
    });
    notification.addEventListener("change", () =>
      saveFilter("notification_group", notification.value),
    );

    async function loadGroups(force = false) {
      refresh.disabled = true;
      try {
        const groups = await getSnowGroups(config, force);
        notification.replaceChildren(new Option("选择通知群聊", ""));
        for (const group of groups)
          notification.add(new Option(`${group.name} (${group.id})`, group.id));
        if (
          config.filter.notification_group &&
          !groups.some((group) => group.id === config.filter.notification_group)
        )
          notification.add(
            new Option(
              `群 ${config.filter.notification_group}`,
              config.filter.notification_group,
            ),
          );
        notification.value = config.filter.notification_group;
        groupMessage.textContent = "";
      } catch (error) {
        if (
          config.filter.notification_group &&
          ![...notification.options].some(
            (option) => option.value === config.filter.notification_group,
          )
        )
          notification.add(
            new Option(
              `群 ${config.filter.notification_group}`,
              config.filter.notification_group,
            ),
          );
        notification.value = config.filter.notification_group;
        groupMessage.textContent = error.message || "无法读取群列表";
      } finally {
        refresh.disabled = false;
      }
    }
    refresh.addEventListener("click", () => loadGroups(true));
    renderKeywords();
    renderStatus(data.status);
    loadGroups();
    setInterval(refreshStatus, 4000);
  } catch (error) {
    label.classList.add("error");
    label.textContent = error.message || "无法读取设置";
  }
})();
