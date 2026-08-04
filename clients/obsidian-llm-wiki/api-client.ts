import * as fs from "fs";
import * as path from "path";

export interface ControlFile {
  vault_id: string;
  api_token: string;
  base_url: string;
  api_version: string;
}

export interface StatusSummary {
  revision: number;
  drafts_pending: number;
  facts_open: number;
  research_open: number;
  jobs_failed: number;
  jobs_pending: number;
  model_ready: boolean;
}

export interface Capabilities {
  api_version: string;
  vault_id: string;
  routes: Record<string, string>;
}

export interface PageContext {
  id: string;
  sources: string[];
  backlinks: string[];
  outlinks: string[];
  links?: {
    web?: string;
    obsidian?: string;
    graph?: string;
  };
}

export interface AcquisitionResult {
  job_id: string;
  acquisition_id?: string;
  links?: {
    web?: string;
  };
}

export class LlmWikiApiClient {
  private controlPath: string;
  private vaultRoot: string;

  constructor(vaultRoot: string) {
    this.vaultRoot = vaultRoot;
    this.controlPath = path.join(vaultRoot, ".llm-wiki", "control.json");
  }

  readControl(): ControlFile | null {
    try {
      const raw = JSON.parse(fs.readFileSync(this.controlPath, "utf-8")) as ControlFile & { token?: string };
      if (!raw.api_token && raw.token) raw.api_token = raw.token;
      return raw;
    } catch {
      return null;
    }
  }

  private async request<T>(route: string, init: RequestInit = {}): Promise<T | null> {
    const control = this.readControl();
    if (!control) return null;
    const headers: Record<string, string> = {
      ...(init.headers as Record<string, string> | undefined),
      "X-LLM-Wiki-Token": control.api_token,
    };
    try {
      const response = await fetch(`${control.base_url}${route}`, { ...init, headers });
      if (!response.ok) return null;
      return (await response.json()) as T;
    } catch {
      return null;
    }
  }

  async getCapabilities(): Promise<Capabilities | null> {
    const control = this.readControl();
    if (!control) return null;
    try {
      const response = await fetch(`${control.base_url}/api/capabilities`);
      if (!response.ok) return null;
      return (await response.json()) as Capabilities;
    } catch {
      return null;
    }
  }

  async getStatusSummary(): Promise<StatusSummary | null> {
    return this.request<StatusSummary>("/api/v1/status/summary");
  }

  async getPageContext(pageId: string): Promise<PageContext | null> {
    const encoded = encodeURIComponent(pageId).replace(/%2F/g, "/");
    return this.request<PageContext>(`/api/v1/pages/${encoded}/context`);
  }

  async submitUrl(url: string): Promise<AcquisitionResult | null> {
    return this.request<AcquisitionResult>("/api/v1/acquisitions/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
  }

  async submitPaste(title: string, body: string, sourceUrl = ""): Promise<AcquisitionResult | null> {
    const payload: Record<string, string> = { title, body };
    if (sourceUrl) payload.source_url = sourceUrl;
    return this.request<AcquisitionResult>("/api/v1/acquisitions/paste", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }
}
