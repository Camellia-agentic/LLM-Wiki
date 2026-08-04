import { ItemView, WorkspaceLeaf } from "obsidian";
import { LlmWikiApiClient, PageContext } from "./api-client";

export const SIDEBAR_VIEW_TYPE = "llm-wiki-sidebar";

export class LlmWikiSidebarView extends ItemView {
  client: LlmWikiApiClient;
  private container: HTMLElement | null = null;
  private currentPageId: string | null = null;

  constructor(leaf: WorkspaceLeaf, client: LlmWikiApiClient) {
    super(leaf);
    this.client = client;
  }

  getViewType(): string {
    return SIDEBAR_VIEW_TYPE;
  }

  getDisplayText(): string {
    return "LLM Wiki";
  }

  getIcon(): string {
    return "layers";
  }

  async onOpen(): Promise<void> {
    this.container = this.contentEl.createDiv({ cls: "llm-wiki-sidebar" });
    this.container.createEl("p", { text: "加载中…", cls: "llm-wiki-muted" });
    this.registerEvent(
      this.app.workspace.on("active-leaf-change", () => {
        void this.refresh();
      }),
    );
    await this.refresh();
  }

  async onClose(): Promise<void> {
    this.container = null;
  }

  wikiPageIdFromPath(filePath: string): string | null {
    const normalized = filePath.replace(/\\/g, "/");
    const marker = "/wiki/";
    const idx = normalized.indexOf(marker);
    if (idx < 0) return null;
    const relative = normalized.slice(idx + marker.length);
    if (!relative.endsWith(".md")) return null;
    return relative.slice(0, -3);
  }

  async refresh(): Promise<void> {
    if (!this.container) return;
    const file = this.app.workspace.getActiveFile();
    const pageId = file ? this.wikiPageIdFromPath(file.path) : null;
    this.currentPageId = pageId;
    this.container.empty();

    if (!pageId) {
      this.container.createEl("p", {
        text: "打开 wiki/ 下的页面以查看来源与链接。",
        cls: "llm-wiki-muted",
      });
      return;
    }

    const ctx = await this.client.getPageContext(pageId);
    if (!ctx) {
      this.container.createEl("p", {
        text: "LLM Wiki 服务未启动。请运行：python tools/wiki.py serve",
        cls: "llm-wiki-error",
      });
      return;
    }

    this.renderContext(ctx);
  }

  private renderContext(ctx: PageContext): void {
    if (!this.container) return;
    this.container.createEl("h3", { text: ctx.id });

    this.renderList(this.container, "来源", ctx.sources);
    this.renderList(this.container, "入链", ctx.backlinks);
    this.renderList(this.container, "出链", ctx.outlinks);

    const actions = this.container.createDiv({ cls: "llm-wiki-actions" });
    if (ctx.links?.web) {
      const web = actions.createEl("a", { text: "Web 详情", href: ctx.links.web });
      web.setAttr("target", "_blank");
    }
    if (ctx.links?.graph) {
      const graph = actions.createEl("a", { text: "局部图", href: ctx.links.graph });
      graph.setAttr("target", "_blank");
    }
  }

  private renderList(parent: HTMLElement, label: string, items: string[]): void {
    const section = parent.createDiv({ cls: "llm-wiki-section" });
    section.createEl("h4", { text: `${label} (${items.length})` });
    if (!items.length) {
      section.createEl("p", { text: "无", cls: "llm-wiki-muted" });
      return;
    }
    const list = section.createEl("ul");
    for (const item of items.slice(0, 20)) {
      list.createEl("li", { text: item });
    }
    if (items.length > 20) {
      section.createEl("p", { text: `…还有 ${items.length - 20} 项`, cls: "llm-wiki-muted" });
    }
  }
}
