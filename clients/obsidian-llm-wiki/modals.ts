import { App, Modal, Notice } from "obsidian";
import { LlmWikiApiClient } from "./api-client";

export class UrlSubmitModal extends Modal {
  private client: LlmWikiApiClient;

  constructor(app: App, client: LlmWikiApiClient) {
    super(app);
    this.client = client;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "提交 URL 采集" });

    const urlInput = contentEl.createEl("input", {
      type: "url",
      placeholder: "https://example.com/article",
    });
    urlInput.className = "llm-wiki-input";
    urlInput.style.width = "100%";

    const toolbar = contentEl.createDiv({ cls: "llm-wiki-modal-actions" });
    toolbar.createEl("button", { text: "取消" }).addEventListener("click", () => this.close());
    toolbar.createEl("button", { text: "提交", cls: "mod-cta" }).addEventListener("click", () => {
      void this.submit(urlInput.value);
    });
  }

  private async submit(rawUrl: string): Promise<void> {
    const url = rawUrl.trim();
    if (!url) {
      new Notice("请输入 URL。");
      return;
    }
    const result = await this.client.submitUrl(url);
    if (!result) {
      new Notice("提交失败。请确认 serve 已启动。");
      return;
    }
    new Notice(`已入队：${result.job_id}`);
    this.close();
    if (result.links?.web) {
      window.open(result.links.web, "_blank");
    }
  }
}

export class PasteSubmitModal extends Modal {
  private client: LlmWikiApiClient;

  constructor(app: App, client: LlmWikiApiClient) {
    super(app);
    this.client = client;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "粘贴正文采集" });

    const titleInput = contentEl.createEl("input", {
      type: "text",
      placeholder: "标题",
    });
    titleInput.className = "llm-wiki-input";
    titleInput.style.width = "100%";

    const urlInput = contentEl.createEl("input", {
      type: "url",
      placeholder: "来源 URL（可选）",
    });
    urlInput.className = "llm-wiki-input";
    urlInput.style.width = "100%";

    const bodyArea = contentEl.createEl("textarea", {
      placeholder: "粘贴 Markdown 或纯文本正文…",
    });
    bodyArea.className = "llm-wiki-textarea";
    bodyArea.rows = 12;
    bodyArea.style.width = "100%";

    const toolbar = contentEl.createDiv({ cls: "llm-wiki-modal-actions" });
    toolbar.createEl("button", { text: "取消" }).addEventListener("click", () => this.close());
    toolbar.createEl("button", { text: "提交", cls: "mod-cta" }).addEventListener("click", () => {
      void this.submit(titleInput.value, bodyArea.value, urlInput.value);
    });
  }

  private async submit(title: string, body: string, sourceUrl: string): Promise<void> {
    if (!title.trim() || !body.trim()) {
      new Notice("标题和正文不能为空。");
      return;
    }
    const result = await this.client.submitPaste(title.trim(), body.trim(), sourceUrl.trim());
    if (!result) {
      new Notice("提交失败。请确认 serve 已启动。");
      return;
    }
    new Notice(`已入队：${result.job_id}`);
    this.close();
    if (result.links?.web) {
      window.open(result.links.web, "_blank");
    }
  }
}
