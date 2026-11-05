class AutoSave {
  constructor(onState, onSaved) {
    this.onState = onState;
    this.onSaved = onSaved;
    this.pending = new Map();
    this.failures = new Map();
    this.timer = null;
    this.retryTimer = null;
    this.running = null;
  }

  queue(key, patch, delay = 600) {
    this.pending.set(key, structuredClone(patch));
    this.failures.delete(key);
    this.update();
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), delay);
  }

  cancel(key) {
    this.pending.delete(key);
    this.failures.delete(key);
    this.update();
  }

  update() {
    if (this.running || this.pending.size) this.onState("saving");
    else if (this.failures.size)
      this.onState("error", [...this.failures.values()][0].message);
    else this.onState("saved");
  }

  async flush() {
    clearTimeout(this.timer);
    if (this.running) return this.running;
    this.running = this.drain();
    this.update();
    try {
      await this.running;
    } finally {
      this.running = null;
      this.update();
    }
    return this.failures.size === 0;
  }

  async drain() {
    while (this.pending.size) {
      const [key, patch] = this.pending.entries().next().value;
      this.pending.delete(key);
      try {
        const body = JSON.stringify(patch);
        const response = await fetch("/api/config", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body,
          keepalive: new Blob([body]).size < 60000,
        });
        const data = await response.json();
        if (!response.ok) {
          const error = new Error(data.error || "保存失败");
          error.retryable = response.status >= 500;
          throw error;
        }
        this.failures.delete(key);
        this.onSaved(key, patch, data);
      } catch (error) {
        if (!this.pending.has(key)) {
          this.failures.set(key, {
            patch,
            message: error.message || "保存失败",
            retryable: error.retryable !== false,
          });
        }
      }
    }
    if ([...this.failures.values()].some((failure) => failure.retryable)) {
      clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => {
        for (const [key, failure] of this.failures) {
          if (failure.retryable && !this.pending.has(key))
            this.pending.set(key, failure.patch);
        }
        this.flush();
      }, 5000);
    }
  }

  async settle() {
    clearTimeout(this.timer);
    while (this.running || this.pending.size) await this.flush();
    return this.failures.size === 0;
  }
}
