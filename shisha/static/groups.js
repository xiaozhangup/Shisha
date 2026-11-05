class GroupBoard {
  constructor(state, saver) {
    this.state = state;
    this.saver = saver;
    this.availableGroups = [];
    this.catalog = { projects: [], sections: [] };
    this.groupMessage = "正在读取群列表…";
    this.groupError = "";
    this.list = document.querySelector("#group-list");
    this.board = document.querySelector("#group-board");
    this.layout = document.querySelector(".groups-board");
    this.columnOptions = document.querySelectorAll(
      "#columns-switch [data-columns]",
    );
    this.search = document.querySelector("#group-search");
    this.memberFilter = document.querySelector("#member-filter");
    this.memberFilterError = document.querySelector("#member-filter-error");
    this.createDialog = document.querySelector("#create-dialog");
    this.createName = document.querySelector("#create-name");
    this.createError = document.querySelector("#create-error");
    this.moveDialog = document.querySelector("#move-dialog");
    this.bind();
  }

  bind() {
    this.search.addEventListener("input", () => this.renderLibrary());
    this.memberFilter.addEventListener("input", () => this.renderLibrary());
    this.columnOptions.forEach((button) =>
      button.addEventListener("click", () => {
        const columns = Number(button.dataset.columns);
        this.state.ui.group_columns = columns;
        this.renderColumns();
        this.saver.queue(
          "ui.group_columns",
          { ui: { group_columns: columns } },
          100,
        );
      }),
    );
    this.renderColumns();
    document
      .querySelector("#refresh-groups")
      .addEventListener("click", () => this.loadGroups(true));
    document
      .querySelector("#refresh-todoist")
      .addEventListener("click", () => this.loadCatalog());
    document
      .querySelector("#add-group")
      .addEventListener("click", () => this.openCreate("group"));
    document
      .querySelector("#create-cancel")
      .addEventListener("click", () => this.createDialog.close());
    document
      .querySelector("#create-form")
      .addEventListener("submit", (event) => this.create(event));
    document
      .querySelector("#move-cancel")
      .addEventListener("click", () => this.moveDialog.close());
  }

  renderColumns() {
    const columns = this.state.ui.group_columns;
    this.layout.dataset.columns = String(columns);
    this.columnOptions.forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(Number(button.dataset.columns) === columns),
      ),
    );
  }

  saveRouting() {
    this.saver.queue(
      "routing",
      {
        filter: { groups: this.state.filter.groups },
        todoist: { groups: this.state.todoist.groups },
      },
      150,
    );
  }

  allGroups() {
    const groups = [...this.availableGroups];
    const known = new Set(groups.map((group) => group.id));
    const ids = [
      ...this.state.filter.groups,
      this.state.filter.notification_group,
    ];
    for (const group of this.state.todoist.groups) ids.push(...group.group_ids);
    for (const id of ids) {
      if (id && !known.has(id)) {
        groups.push({ id, name: `群 ${id}` });
        known.add(id);
      }
    }
    return groups;
  }

  assigned(id) {
    return (
      this.state.todoist.groups.find((group) => group.group_ids.includes(id)) ||
      this.state.todoist.groups.find((group) => group.id === "default")
    );
  }

  assign(id, targetId) {
    for (const group of this.state.todoist.groups)
      group.group_ids = group.group_ids.filter((member) => member !== id);
    this.state.todoist.groups
      .find((group) => group.id === targetId)
      .group_ids.push(id);
    if (!this.state.filter.groups.includes(id))
      this.state.filter.groups.push(id);
    this.saveRouting();
    this.render();
  }

  unassign(id) {
    for (const group of this.state.todoist.groups)
      group.group_ids = group.group_ids.filter((member) => member !== id);
    this.state.filter.groups = this.state.filter.groups.filter(
      (member) => member !== id,
    );
    this.saveRouting();
    this.render();
  }

  render() {
    this.renderLibrary();
    this.renderBoard();
  }

  renderLibrary() {
    const groups = this.allGroups();
    const selected = new Set(this.state.filter.groups);
    const query = this.search.value.trim().toLocaleLowerCase();
    const expression = this.memberFilter.value.trim();
    const match = expression.match(/^(>=|<=|>|<|=|≥|≤)?\s*(\d+)$/u);
    const invalid = Boolean(expression && !match);
    this.memberFilter.setAttribute("aria-invalid", String(invalid));
    this.memberFilterError.hidden = !invalid;
    const visible = groups.filter((group) => {
      if (!`${group.name} ${group.id}`.toLocaleLowerCase().includes(query))
        return false;
      if (!match) return true;
      const count = group.member_count;
      if (!Number.isInteger(count) || count <= 0) return false;
      const limit = Number(match[2]);
      switch (match[1]) {
        case ">":
          return count > limit;
        case ">=":
        case "≥":
          return count >= limit;
        case "<":
          return count < limit;
        case "<=":
        case "≤":
          return count <= limit;
        default:
          return count === limit;
      }
    });
    visible.sort(
      (a, b) => Number(selected.has(b.id)) - Number(selected.has(a.id)),
    );
    document.querySelector("#group-count").textContent =
      `已监听 ${selected.size} 个`;
    this.list.replaceChildren();
    if (this.groupError && groups.length) {
      const message = document.createElement("p");
      message.className = "group-empty";
      message.textContent = this.groupError;
      this.list.append(message);
    }
    if (!visible.length) {
      const message = document.createElement("p");
      message.className = "group-empty";
      message.textContent =
        query || match ? "没有匹配的群聊" : this.groupMessage;
      this.list.append(message);
      return;
    }
    for (const group of visible) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "library-card";
      card.classList.toggle("listening", selected.has(group.id));
      card.dataset.listId = group.id;
      this.makeDraggable(card, group.id);
      const meta = document.createElement("span");
      meta.className = "group-meta";
      const name = document.createElement("span");
      name.className = "group-name";
      name.textContent = group.name;
      const detail = document.createElement("span");
      detail.className = "group-id";
      detail.textContent = selected.has(group.id)
        ? this.displayName(this.assigned(group.id))
        : "未监听";
      const memberCount = document.createElement("span");
      memberCount.className = "group-member-count";
      memberCount.textContent =
        Number.isInteger(group.member_count) && group.member_count > 0
          ? `${group.member_count} 人`
          : "人数未知";
      const info = document.createElement("span");
      info.className = "group-info";
      info.append(detail, memberCount);
      meta.append(name, info);
      card.setAttribute(
        "aria-label",
        `${group.name}，${detail.textContent}，${memberCount.textContent}`,
      );
      card.setAttribute("aria-haspopup", "dialog");
      card.addEventListener("click", () => this.openMove(group));
      card.append(groupAvatar(group.id, group.name), meta);
      this.list.append(card);
    }
  }

  displayName(group) {
    return group.id === "default" ? "default（默认）" : group.name;
  }

  makeDraggable(element, id, member = false) {
    element.draggable = true;
    element.addEventListener("dragstart", (event) => {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", id);
      if (member) this.startMemberDrag(id);
      element.classList.add("dragging");
    });
    element.addEventListener("dragend", () => {
      element.classList.remove("dragging");
      this.endMemberDrag();
    });
  }

  startMemberDrag(id) {
    const overlay = document.createElement("div");
    overlay.className = "drag-remove-overlay";
    const hint = document.createElement("span");
    hint.textContent = "拖到分组外，松开后停止监听";
    overlay.append(hint);
    overlay.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
    });
    overlay.addEventListener("drop", (event) => {
      event.preventDefault();
      this.endMemberDrag();
      this.unassign(id);
    });
    this.dragOverlay = overlay;
    document.body.classList.add("member-dragging");
    document.body.append(overlay);
  }

  endMemberDrag() {
    this.dragOverlay?.remove();
    this.dragOverlay = null;
    document.body.classList.remove("member-dragging");
    this.board
      .querySelectorAll(".drag-over")
      .forEach((target) => target.classList.remove("drag-over"));
  }

  renderBoard() {
    if (this.dragOverlay) this.endMemberDrag();
    this.board.replaceChildren();
    const names = new Map(
      this.allGroups().map((group) => [group.id, group.name]),
    );
    const active = new Set(this.state.filter.groups);
    for (const group of this.state.todoist.groups) {
      const card = document.createElement("article");
      card.className = "board-card";
      card.dataset.groupId = group.id;
      const header = document.createElement("div");
      header.className = "target-header";
      const title = document.createElement("div");
      title.className = "target-title";
      if (group.id === "default") {
        const name = document.createElement("strong");
        name.textContent = "default（默认）";
        title.append(name);
      } else {
        const name = document.createElement("input");
        name.className = "target-name";
        name.value = group.name;
        name.maxLength = 120;
        name.setAttribute("aria-label", `重命名分组 ${group.name}`);
        name.addEventListener("input", () => {
          const value = name.value.trim();
          const duplicate = this.state.todoist.groups.some(
            (item) =>
              item.id !== group.id &&
              item.name.toLocaleLowerCase() === value.toLocaleLowerCase(),
          );
          name.setAttribute("aria-invalid", String(!value || duplicate));
          if (!value || duplicate) return;
          group.name = value;
          this.saveRouting();
          this.renderLibrary();
        });
        name.addEventListener("blur", () => {
          if (name.getAttribute("aria-invalid") === "true") {
            name.value = group.name;
            name.setAttribute("aria-invalid", "false");
          }
        });
        title.append(name);
      }
      const members = group.group_ids.filter((id) => active.has(id));
      const count = document.createElement("small");
      count.textContent = `${members.length} 个群聊`;
      title.append(count);
      header.append(title);
      if (group.id !== "default") {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove-group";
        remove.textContent = "删除";
        remove.setAttribute("aria-label", `删除分组 ${group.name}`);
        remove.title = "删除分组并停止监听其中的群聊";
        remove.addEventListener("click", () => {
          const members = new Set(group.group_ids);
          this.state.filter.groups = this.state.filter.groups.filter(
            (id) => !members.has(id),
          );
          this.state.todoist.groups = this.state.todoist.groups.filter(
            (item) => item.id !== group.id,
          );
          this.saveRouting();
          this.render();
        });
        header.append(remove);
      }
      const dropzone = document.createElement("div");
      dropzone.className = "group-dropzone";
      dropzone.dataset.dropGroup = group.id;
      dropzone.addEventListener("dragover", (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        dropzone.classList.add("drag-over");
      });
      dropzone.addEventListener("dragleave", (event) => {
        if (!dropzone.contains(event.relatedTarget))
          dropzone.classList.remove("drag-over");
      });
      dropzone.addEventListener("drop", (event) => {
        event.preventDefault();
        event.stopPropagation();
        dropzone.classList.remove("drag-over");
        const id = event.dataTransfer.getData("text/plain");
        this.endMemberDrag();
        if (this.allGroups().some((item) => item.id === id))
          this.assign(id, group.id);
      });
      if (!members.length) {
        const empty = document.createElement("span");
        empty.className = "drop-placeholder";
        empty.textContent = "拖入群聊";
        dropzone.append(empty);
      }
      for (const id of members) {
        const member = document.createElement("div");
        member.className = "member-chip";
        this.makeDraggable(member, id, true);
        const name = names.get(id) || `群 ${id}`;
        const text = document.createElement("span");
        text.textContent = name;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove-member";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `停止监听 ${name}`);
        remove.addEventListener("click", () => this.unassign(id));
        member.append(groupAvatar(id, name), text, remove);
        dropzone.append(member);
      }
      const output = document.createElement("label");
      output.className = "group-output";
      const outputText = document.createElement("span");
      outputText.textContent = "写入 Todoist";
      const toggle = document.createElement("span");
      toggle.className = "switch";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = group.todoist_enabled;
      checkbox.setAttribute(
        "aria-label",
        `${this.displayName(group)} 写入 Todoist`,
      );
      const destinations = this.renderDestinations(group);
      destinations.hidden = !group.todoist_enabled;
      checkbox.addEventListener("change", () => {
        group.todoist_enabled = checkbox.checked;
        destinations.hidden = !checkbox.checked;
        this.updateCatalogMessage();
        this.saveRouting();
      });
      const track = document.createElement("span");
      track.className = "switch-track";
      toggle.append(checkbox, track);
      output.append(outputText, toggle);
      card.append(header, dropzone, output, destinations);
      this.board.append(card);
    }
    this.updateCatalogMessage();
  }

  updateCatalogMessage() {
    document.querySelector("#catalog-message").hidden =
      !this.state.todoist.groups.some((group) => group.todoist_enabled);
  }

  renderDestinations(group) {
    const fields = document.createElement("div");
    fields.className = "target-fields";
    const project = this.targetSelect(
      "项目",
      group,
      group.project_id,
      this.catalog.projects,
      "收件箱",
    );
    if (group.legacy_section) {
      project.select.add(
        new Option(`原配置：${group.legacy_section}`, "__legacy__"),
      );
      project.select.value = "__legacy__";
    }
    project.select.addEventListener("change", () => {
      group.project_id = project.select.value;
      group.section_id = "";
      group.legacy_section = "";
      this.saveRouting();
      this.renderBoard();
    });
    project.button.addEventListener("click", () =>
      this.openCreate("project", group.id),
    );
    const sections = this.catalog.sections.filter(
      (item) => item.project_id === group.project_id,
    );
    const section = this.targetSelect(
      "板块",
      group,
      group.section_id,
      sections,
      "不指定板块",
    );
    section.select.disabled = !group.project_id;
    section.button.disabled = !group.project_id;
    section.select.addEventListener("change", () => {
      group.section_id = section.select.value;
      group.legacy_section = "";
      this.saveRouting();
    });
    section.button.addEventListener("click", () =>
      this.openCreate("section", group.id),
    );
    fields.append(project.container, section.container);
    return fields;
  }

  targetSelect(label, group, value, items, emptyLabel) {
    const container = document.createElement("label");
    container.className = "field target-field";
    const title = document.createElement("span");
    title.textContent = `Todoist ${label}`;
    const control = document.createElement("span");
    control.className = "target-control";
    const select = document.createElement("select");
    select.setAttribute("aria-label", `${this.displayName(group)} ${label}`);
    select.add(new Option(emptyLabel, ""));
    for (const item of items) select.add(new Option(item.name, item.id));
    if (value && !items.some((item) => item.id === value))
      select.add(new Option(`已保存的${label} (${value})`, value));
    select.value = value;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "target-create";
    button.setAttribute(
      "aria-label",
      `为 ${this.displayName(group)} 新建${label}`,
    );
    button.textContent = "+";
    control.append(select, button);
    container.append(title, control);
    return { container, select, button };
  }

  async loadGroups(force = false) {
    const refresh = document.querySelector("#refresh-groups");
    refresh.disabled = true;
    this.groupMessage = "正在读取群列表…";
    this.groupError = "";
    try {
      this.availableGroups = await getSnowGroups(this.state, force);
      this.groupMessage = "当前账号没有群聊";
    } catch (error) {
      this.groupError = error.message || "无法读取群列表";
      this.groupMessage = this.groupError;
    } finally {
      refresh.disabled = false;
      this.render();
    }
  }

  async loadCatalog() {
    const refresh = document.querySelector("#refresh-todoist");
    const message = document.querySelector("#catalog-message");
    refresh.disabled = true;
    try {
      const response = await fetch("/api/todoist/catalog");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "无法读取 Todoist 项目");
      this.catalog = data;
      message.textContent = "";
      let migrated = false;
      for (const group of this.state.todoist.groups) {
        if (!group.legacy_section) continue;
        const matches = data.sections.filter((section) => {
          const project = data.projects.find(
            (item) => item.id === section.project_id,
          );
          return (
            project &&
            `${project.name}.${section.name}` === group.legacy_section
          );
        });
        if (matches.length === 1) {
          group.project_id = matches[0].project_id;
          group.section_id = matches[0].id;
          group.legacy_section = "";
          migrated = true;
        }
      }
      if (migrated) this.saveRouting();
    } catch (error) {
      message.textContent = error.message || "无法读取 Todoist 项目";
    } finally {
      refresh.disabled = false;
      this.renderBoard();
    }
  }

  openMove(group) {
    document.querySelector("#move-dialog h2").textContent =
      this.state.filter.groups.includes(group.id) ? "移动群聊" : "加入分组";
    document.querySelector("#move-description").textContent =
      `选择 ${group.name} 的分组`;
    const options = document.querySelector("#move-options");
    options.replaceChildren();
    for (const target of this.state.todoist.groups) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = this.displayName(target);
      button.addEventListener("click", () => {
        this.assign(group.id, target.id);
        this.moveDialog.close();
        this.list
          .querySelector(`[data-list-id="${group.id}"]`)
          ?.focus({ preventScroll: true });
      });
      options.append(button);
    }
    this.moveDialog.showModal();
  }

  openCreate(kind, groupId = null) {
    this.dialogContext = { kind, groupId };
    const titles = {
      group: "新建分组",
      project: "新建项目",
      section: "新建板块",
    };
    document.querySelector("#create-title").textContent = titles[kind];
    const group = this.state.todoist.groups.find((item) => item.id === groupId);
    const project =
      group &&
      this.catalog.projects.find((item) => item.id === group.project_id);
    document.querySelector("#create-description").textContent =
      kind === "section"
        ? `添加到 ${project?.name || "当前项目"}`
        : kind === "project"
          ? "在 Todoist 中创建项目。"
          : "为群聊设置共同的 Todoist 位置。";
    this.createName.value = "";
    this.createError.textContent = "";
    this.createDialog.showModal();
    this.createName.focus();
  }

  async create(event) {
    event.preventDefault();
    const name = this.createName.value.trim();
    if (!name) return;
    const { kind, groupId } = this.dialogContext;
    const button = document.querySelector("#create-submit");
    button.disabled = true;
    this.createError.textContent = "";
    try {
      if (kind === "group") {
        if (
          this.state.todoist.groups.some(
            (group) =>
              group.name.toLocaleLowerCase() === name.toLocaleLowerCase(),
          )
        )
          throw new Error("分组名称已存在");
        this.state.todoist.groups.push({
          id: crypto.randomUUID(),
          name,
          group_ids: [],
          project_id: "",
          section_id: "",
          legacy_section: "",
          todoist_enabled: false,
        });
      } else {
        const group = this.state.todoist.groups.find(
          (item) => item.id === groupId,
        );
        const payload =
          kind === "section"
            ? { name, project_id: group.project_id }
            : { name };
        const response = await fetch(
          `/api/todoist/${kind === "project" ? "projects" : "sections"}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
        );
        const item = await response.json();
        if (!response.ok) throw new Error(item.error || "创建失败");
        if (kind === "project") {
          this.catalog.projects.push(item);
          group.project_id = item.id;
          group.section_id = "";
        } else {
          this.catalog.sections.push(item);
          group.section_id = item.id;
        }
        group.legacy_section = "";
      }
      this.saveRouting();
      this.render();
      this.createDialog.close();
    } catch (error) {
      this.createError.textContent = error.message || "创建失败";
    } finally {
      button.disabled = false;
    }
  }
}

(async () => {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("无法读取设置");
    const data = await response.json();
    const saver = createPageSaver((key, patch, result) =>
      renderStatus(result.status),
    );
    const board = new GroupBoard(data.config, saver);
    renderStatus(data.status);
    board.render();
    board.loadGroups();
    board.loadCatalog();
    setInterval(refreshStatus, 4000);
  } catch (error) {
    document.querySelector("[data-save-state]").textContent =
      error.message || "无法读取设置";
  }
})();
