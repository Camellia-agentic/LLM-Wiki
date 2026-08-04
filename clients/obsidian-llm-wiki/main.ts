import { App, Notice, Plugin, PluginSettingTab, Setting, WorkspaceLeaf } from "obsidian";
import { LlmWikiApiClient } from "./api-client";
import { PasteSubmitModal, UrlSubmitModal } from "./modals";
import { LlmWikiSidebarView, SIDEBAR_VIEW_TYPE } from "./sidebar-view";

interface LlmWikiSettings {
  pollIntervalSeconds: number;
}

const DEFAULT_SETTINGS: LlmWikiSettings = {
  pollIntervalSeconds: 20,
};

export default class LlmWikiPlugin extends Plugin {
  settings: LlmWikiSettings = DEFAULT_SETTINGS;
  client: LlmWikiApiClient | null = null;
  statusEl: HTMLElement | null = null;

  async onload() {
    await this.loadSettings();
    this.client = new LlmWikiApiClient(this.app.vault.adapter.basePath);

    this.registerView(SIDEBAR_VIEW_TYPE, (leaf) => new LlmWikiSidebarView(leaf, this.client!));
    this.addRibbonIcon("layers", "LLM Wiki", () => this.activateSidebar());

    this.addCommand({
      id: "llm-wiki-open-console",
      name: "打开 LLM Wiki 控制中心",
      callback: () => this.openConsole(),
    });
    this.addCommand({
      id: "llm-wiki-open-sidebar",
      name: "打开 LLM Wiki 侧栏",
      callback: () => this.activateSidebar(),
    });
    this.addCommand({
      id: "llm-wiki-submit-url",
      name: "提交 URL 采集",
      callback: () => {
        if (!this.client) return;
        new UrlSubmitModal(this.app, this.client).open();
      },
    });
    this.addCommand({
      id: "llm-wiki-submit-paste",
      name: "粘贴正文采集",
      callback: () => {
        if (!this.client) return;
        new PasteSubmitModal(this.app, this.client).open();
      },
    });

    this.addSettingTab(new LlmWikiSettingTab(this.app, this));
    this.registerInterval(
      window.setInterval(() => this.refreshStatus(), this.settings.pollIntervalSeconds * 1000),
    );
    await this.refreshStatus();
  }

  onunload() {
    this.statusEl?.remove();
    this.app.workspace.detachLeavesOfType(SIDEBAR_VIEW_TYPE);
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  async activateSidebar() {
    const { workspace } = this.app;
    let leaf: WorkspaceLeaf | null = workspace.getLeavesOfType(SIDEBAR_VIEW_TYPE)[0] ?? null;
    if (!leaf) {
      const right = workspace.getRightLeaf(false);
      if (!right) return;
      await right.setViewState({ type: SIDEBAR_VIEW_TYPE, active: true });
      leaf = right;
    }
    workspace.revealLeaf(leaf);
  }

  async refreshStatus() {
    if (!this.client) return;
    const status = await this.client.getStatusSummary();
    const label = status
      ? `LLM Wiki · 草稿 ${status.drafts_pending} · 待办 ${status.facts_open + status.research_open}`
      : "LLM Wiki · 离线";
    if (!this.statusEl) {
      this.statusEl = this.addStatusBarItem();
    }
    this.statusEl.setText(label);
  }

  async openConsole() {
    if (!this.client) return;
    const caps = await this.client.getCapabilities();
    if (!caps?.routes?.console) {
      new Notice("LLM Wiki 服务未启动。请运行：python tools/wiki.py serve");
      return;
    }
    window.open(caps.routes.console, "_blank");
  }
}

class LlmWikiSettingTab extends PluginSettingTab {
  plugin: LlmWikiPlugin;

  constructor(app: App, plugin: LlmWikiPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "LLM Wiki" });
    new Setting(containerEl)
      .setName("状态轮询间隔（秒）")
      .setDesc("读取待办计数，不触发全库 lint。")
      .addText((text) =>
        text
          .setValue(String(this.plugin.settings.pollIntervalSeconds))
          .onChange(async (value) => {
            const parsed = Number(value);
            if (!Number.isFinite(parsed) || parsed < 10) return;
            this.plugin.settings.pollIntervalSeconds = parsed;
            await this.plugin.saveSettings();
          }),
      );
  }
}
