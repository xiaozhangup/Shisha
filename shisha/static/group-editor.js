class GroupEditor {
  constructor(form, state, saver, notice) {
    this.form = form;
    this.state = state;
    this.saver = saver;
    this.notice = notice;
    this.groupList = document.querySelector("#group-list");
    this.groupCount = document.querySelector("#group-count");
    this.search = document.querySelector("#group-search");
    this.refresh = document.querySelector("#refresh-groups");
    this.notification = form.elements.namedItem("filter.notification_group");
    this.targets = document.querySelector("#todoist-groups");
    this.refreshTodoist = document.querySelector("#refresh-todoist");
    this.dialog = document.querySelector("#create-dialog");
    this.createForm = document.querySelector("#create-form");
    this.createName = document.querySelector("#create-name");
    this.createError = document.querySelector("#create-error");
    this.availableGroups = [];
    this.catalog = { projects: [], sections: [] };
    this.groupMessage = "正在读取群列表…";
    this.groupError = "";
    this.catalogError = "";
    this.groupRequest = 0;
    this.catalogRequest = 0;
    this.dialogContext = null;
    this.bind();
  }

  bind() {
    this.search.addEventListener("input", () => this.renderGroups());
    this.refresh.addEventListener("click", () => this.loadGroups());
    this.refreshTodoist.addEventListener("click", () => this.loadCatalog());
    document
      .querySelector("#add-group")
      .addEventListener("click", () => this.openDialog("group"));
    this.notification.addEventListener("change", () => {
      this.state.filter.notification_group = this.notification.value;
      this.saver.queue(
        "filter.notification_group",
        { filter: { notification_group: this.notification.value } },
        100,
      );
    });
    document
      .querySelector("#create-cancel")
      .addEventListener("click", () => this.dialog.close());
    this.createForm.addEventListener("submit", (event) => this.create(event));
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
    for (const entry of this.state.todoist.groups) ids.push(...entry.group_ids);
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
      this.state.todoist.groups.find((entry) => entry.group_ids.includes(id)) ||
      this.state.todoist.groups.find((entry) => entry.id === "default")
    );
  }

  assign(id, targetId) {
    for (const entry of this.state.todoist.groups)
      entry.group_ids = entry.group_ids.filter((member) => member !== id);
    this.state.todoist.groups
      .find((entry) => entry.id === targetId)
      .group_ids.push(id);
  }

  renderNotification(groups) {
    this.notification.replaceChildren(new Option("选择通知群聊", ""));
    for (const group of groups)
      this.notification.add(
        new Option(`${group.name} (${group.id})`, group.id),
      );
    this.notification.value = this.state.filter.notification_group;
    this.notification.disabled = !this.state.filter.notify_enabled;
  }

  renderGroups() {
    const groups = this.allGroups();
    this.renderNotification(groups);
    const selected = new Set(this.state.filter.groups);
    const query = this.search.value.trim().toLocaleLowerCase();
    const visible = groups.filter((group) =>
      `${group.name} ${group.id}`.toLocaleLowerCase().includes(query),
    );
    visible.sort(
      (a, b) => Number(selected.has(b.id)) - Number(selected.has(a.id)),
    );
    this.groupCount.textContent = selected.size
      ? `已开启 ${selected.size} 个`
      : "选择要监听的群聊";
    this.groupList.replaceChildren();
    if (this.groupError && groups.length) {
      const error = document.createElement("p");
      error.className = "group-empty";
      error.textContent = this.groupError;
      this.groupList.append(error);
    }
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.className = "group-empty";
      empty.textContent = query ? "没有匹配的群聊" : this.groupMessage;
      this.groupList.append(empty);
      return;
    }
    for (const group of visible) {
      const row = document.createElement("div");
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
      const assignment = document.createElement("select");
      assignment.className = "group-assignment";
      assignment.setAttribute("aria-label", `${group.name} 所属分组`);
      for (const entry of this.state.todoist.groups)
        assignment.add(
          new Option(
            entry.id === "default" ? "default（默认）" : entry.name,
            entry.id,
          ),
        );
      assignment.value = this.assigned(group.id).id;
      assignment.disabled = !selected.has(group.id);
      assignment.addEventListener("change", () => {
        this.assign(group.id, assignment.value);
        this.saveRouting();
        this.renderTargets();
      });
      const toggle = document.createElement("label");
      toggle.className = "switch";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selected.has(group.id);
      checkbox.setAttribute("aria-label", `监听 ${group.name}`);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          if (!this.state.filter.groups.includes(group.id))
            this.state.filter.groups.push(group.id);
          if (
            !this.state.todoist.groups.some((entry) =>
              entry.group_ids.includes(group.id),
            )
          )
            this.assign(group.id, "default");
        } else {
          this.state.filter.groups = this.state.filter.groups.filter(
            (id) => id !== group.id,
          );
        }
        this.saveRouting();
        this.renderGroups();
        this.renderTargets();
        this.groupList
          .querySelectorAll('input[type="checkbox"]')
          .forEach((input) => {
            if (input.getAttribute("aria-label") === `监听 ${group.name}`)
              input.focus({ preventScroll: true });
          });
      });
      const track = document.createElement("span");
      track.className = "switch-track";
      toggle.append(checkbox, track);
      row.append(groupAvatar(group.id, group.name), meta, assignment, toggle);
      this.groupList.append(row);
    }
  }

  async loadGroups() {
    const requestId = ++this.groupRequest;
    const mode = this.form.querySelector(
      'input[name="snowluma.mode"]:checked',
    ).value;
    this.refresh.disabled = true;
    this.groupMessage = "正在读取群列表…";
    this.groupError = "";
    if (!this.availableGroups.length) this.renderGroups();
    try {
      const response = await fetch("/api/groups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          url: this.form.elements
            .namedItem(`snowluma.${mode}_url`)
            .value.trim(),
          token: this.form.elements
            .namedItem(`snowluma.${mode}_token`)
            .value.trim(),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "无法读取群列表");
      if (requestId !== this.groupRequest) return;
      this.availableGroups = data.groups;
      this.groupMessage = "当前账号没有群聊";
    } catch (error) {
      if (requestId !== this.groupRequest) return;
      this.availableGroups = [];
      this.groupError = error.message || "无法读取群列表";
      this.groupMessage = this.groupError;
    } finally {
      if (requestId === this.groupRequest) {
        this.refresh.disabled = false;
        this.renderGroups();
        this.renderTargets();
      }
    }
  }

  async loadCatalog() {
    const requestId = ++this.catalogRequest;
    this.refreshTodoist.disabled = true;
    try {
      await this.saver.flush();
      if (this.saver.failures.has("todoist.token"))
        throw new Error("Todoist 令牌尚未保存");
      const response = await fetch("/api/todoist/catalog");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "无法读取 Todoist 项目");
      if (requestId !== this.catalogRequest) return;
      this.catalog = data;
      this.catalogError = "";
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
      if (requestId !== this.catalogRequest) return;
      this.catalogError = error.message || "无法读取 Todoist 项目";
    } finally {
      if (requestId === this.catalogRequest) {
        this.refreshTodoist.disabled = false;
        this.renderTargets();
      }
    }
  }

  renderTargets() {
    this.targets.replaceChildren();
    if (this.catalogError) {
      const warning = document.createElement("p");
      warning.className = "catalog-message";
      warning.textContent = this.catalogError;
      this.targets.append(warning);
    }
    for (const group of this.state.todoist.groups) {
      const card = document.createElement("div");
      card.className = "target-card";
      const header = document.createElement("div");
      header.className = "target-header";
      const title = document.createElement("div");
      title.className = "target-title";
      if (group.id === "default") {
        const name = document.createElement("strong");
        name.textContent = "default";
        title.append(name, document.createTextNode("（默认）"));
      } else {
        const name = document.createElement("input");
        name.className = "target-name";
        name.value = group.name;
        name.maxLength = 120;
        name.setAttribute("aria-label", "分组名称");
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
          this.renderGroups();
        });
        name.addEventListener("blur", () => {
          if (name.getAttribute("aria-invalid") === "true") {
            name.value = group.name;
            name.setAttribute("aria-invalid", "false");
          }
        });
        title.append(name);
      }
      const count = document.createElement("small");
      const active = group.group_ids.filter((id) =>
        this.state.filter.groups.includes(id),
      ).length;
      count.textContent = `${active} 个群聊`;
      title.append(count);
      header.append(title);
      if (group.id !== "default") {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove-group";
        remove.textContent = "删除";
        remove.setAttribute("aria-label", `删除分组 ${group.name}`);
        remove.addEventListener("click", () => {
          const defaultGroup = this.state.todoist.groups.find(
            (entry) => entry.id === "default",
          );
          defaultGroup.group_ids.push(...group.group_ids);
          this.state.todoist.groups = this.state.todoist.groups.filter(
            (entry) => entry.id !== group.id,
          );
          this.saveRouting();
          this.renderGroups();
          this.renderTargets();
          this.notice("群聊已移至 default");
        });
        header.append(remove);
      }
      card.append(header);
      const members = group.group_ids.filter((id) =>
        this.state.filter.groups.includes(id),
      );
      if (members.length) {
        const list = document.createElement("div");
        list.className = "target-members";
        const names = new Map(
          this.allGroups().map((item) => [item.id, item.name]),
        );
        for (const id of members.slice(0, 6)) {
          const chip = document.createElement("span");
          chip.textContent = names.get(id) || `群 ${id}`;
          list.append(chip);
        }
        if (members.length > 6) {
          const more = document.createElement("span");
          more.textContent = `+${members.length - 6}`;
          list.append(more);
        }
        card.append(list);
      }
      const fields = document.createElement("div");
      fields.className = "target-fields";
      const project = this.targetSelect(
        "项目",
        group.id,
        "project",
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
        this.renderTargets();
      });
      project.button.addEventListener("click", () =>
        this.openDialog("project", group.id),
      );
      const sections = this.catalog.sections.filter(
        (item) => item.project_id === group.project_id,
      );
      const section = this.targetSelect(
        "板块",
        group.id,
        "section",
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
        this.openDialog("section", group.id),
      );
      fields.append(project.container, section.container);
      card.append(fields);
      this.targets.append(card);
    }
  }

  targetSelect(label, groupId, kind, value, items, emptyLabel) {
    const container = document.createElement("label");
    container.className = "field target-field";
    const title = document.createElement("span");
    title.textContent = label;
    const control = document.createElement("span");
    control.className = "target-control";
    const select = document.createElement("select");
    select.setAttribute(
      "aria-label",
      `${this.state.todoist.groups.find((item) => item.id === groupId).name} ${label}`,
    );
    select.add(new Option(emptyLabel, ""));
    for (const item of items) select.add(new Option(item.name, item.id));
    if (value && !items.some((item) => item.id === value))
      select.add(new Option(`已保存的${label} (${value})`, value));
    select.value = value;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "target-create";
    button.setAttribute("aria-label", `新建${label}`);
    button.textContent = "+";
    control.append(select, button);
    container.append(title, control);
    return { container, select, button };
  }

  openDialog(kind, groupId = null) {
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
        : kind === "group"
          ? "把群聊归入分组，为它们选择同一个 Todoist 位置。"
          : "在 Todoist 中创建项目。";
    this.createName.value = "";
    this.createError.textContent = "";
    this.dialog.showModal();
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
        });
        this.saveRouting();
        this.renderGroups();
        this.renderTargets();
      } else {
        await this.saver.flush();
        if (this.saver.failures.has("todoist.token"))
          throw new Error("Todoist 令牌尚未保存");
        const group = this.state.todoist.groups.find(
          (entry) => entry.id === groupId,
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
        this.saveRouting();
        this.renderTargets();
      }
      this.dialog.close();
    } catch (error) {
      this.createError.textContent = error.message || "创建失败";
    } finally {
      button.disabled = false;
    }
  }
}
