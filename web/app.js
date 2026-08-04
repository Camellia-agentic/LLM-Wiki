(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const token = $('meta[name="llm-wiki-token"]').content;

  const STAGE_LABELS = {
    queued: "排队中",
    acquiring: "采集中",
    archived: "已归档",
    chunking: "分块中",
    analyzing: "分析中",
    merging: "合并中",
    drafting: "生成草稿",
    awaiting_review: "待审阅",
    applied: "已应用",
    failed: "失败",
  };

  const state = {
    workspace: "collect",
    pendingFilter: "all",
    kview: "list",
    currentPageId: null,
    activeReviewId: null,
    graphView: null,
  };

  function esc(text) {
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function notice(text, bad) {
    const el = $("#notice");
    el.textContent = text;
    el.className = bad ? "notice bad" : "notice";
  }

  async function api(path, opt) {
    opt = opt || {};
    opt.headers = Object.assign({}, opt.headers || {}, { "X-LLM-Wiki-Token": token });
    const resp = await fetch(path, opt);
    let data;
    try {
      data = await resp.json();
    } catch (_) {
      data = {};
    }
    if (!resp.ok) throw new Error(data.error || data.message || "请求失败");
    return data;
  }

  function obsidianLink(absPath) {
    return absPath ? "obsidian://open?path=" + encodeURIComponent(absPath) : "#";
  }

  function renderMarkdown(text) {
    let html = esc(text);
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, label, url) {
      const safe = esc(url);
      if (/^https?:\/\//i.test(url)) {
        return '<a href="' + safe + '" target="_blank" rel="noopener">' + esc(label) + "</a>";
      }
      return esc(label);
    });
    html = html.replace(/\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]/g, function (_, target) {
      const id = target.trim().replace(/^wiki\//, "").replace(/\.md$/, "");
      return '<a href="#/knowledge/' + encodeURIComponent(id) + '" class="wikilink">' + esc(id) + "</a>";
    });
    html = html.split(/\n{2,}/).map(function (block) {
      if (/^#{1,3}\s/.test(block)) {
        const m = block.match(/^(#{1,3})\s+(.*)$/s);
        if (m) {
          const level = m[1].length;
          return "<h" + level + ">" + m[2].replace(/\n/g, " ") + "</h" + level + ">";
        }
      }
      return "<p>" + block.replace(/\n/g, "<br>") + "</p>";
    }).join("");
    return html;
  }

  function emptyRow(text) {
    const el = document.createElement("div");
    el.className = "empty";
    el.textContent = text;
    return el;
  }

  function makeRow(cells, actions, opts) {
    opts = opts || {};
    const row = document.createElement("div");
    row.className = "row" + (opts.clickable ? " clickable" : "");
    if (opts.onClick) row.onclick = opts.onClick;

    cells.forEach(function (cell, i) {
      const div = document.createElement("div");
      if (typeof cell === "string") {
        div.textContent = cell;
        if (i > 0) div.className = "muted";
      } else if (cell && cell.nodeType) {
        div.appendChild(cell);
      } else if (cell && cell.html) {
        div.innerHTML = cell.html;
      } else {
        div.textContent = String(cell ?? "");
      }
      if (i === 0) div.className = (div.className ? div.className + " " : "") + "primary-text";
      row.appendChild(div);
    });

    const act = document.createElement("div");
    act.className = "actions";
    (actions || []).forEach(function (action) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = action.label;
      btn.className = "btn" + (action.cls ? " " + action.cls : "");
      btn.onclick = function (e) {
        e.stopPropagation();
        action.run();
      };
      act.appendChild(btn);
    });
    row.appendChild(act);
    return row;
  }

  function badge(text, kind) {
    return { html: '<span class="badge ' + esc(kind) + '">' + esc(text) + "</span>" };
  }

  function spreadChildren(parent, nodes) {
    const list = Array.isArray(nodes) ? nodes : [nodes];
    parent.replaceChildren.apply(parent, list);
  }

  function updateModelPill(summary, llmConfig) {
    const pill = $("#model-pill");
    const text = $("#model-pill-text");
    if (!pill || !text) return;
    const ready = summary && summary.model_ready;
    pill.classList.toggle("ready", !!ready);
    if (ready) {
      const label = (summary.model_label || "模型") + " · " + (summary.model_name || "");
      text.innerHTML = "<strong>已连接</strong> " + esc(label);
    } else if (llmConfig && llmConfig.configured) {
      const active = llmConfig.active || {};
      text.innerHTML = "待密钥 · " + esc(active.label || active.profile || "已配置");
    } else {
      text.textContent = "未配置 config.toml";
    }
  }

  async function refreshModelConfig() {
    const box = $("#config-status");
    if (!box) return;
    try {
      const cfg = await api("/api/v1/config/llm");
      const active = cfg.active;
      if (!cfg.configured || !active) {
        box.innerHTML = "<p class='bad'>未找到有效配置。请复制 <code>config.toml.example</code> 为 <code>config.toml</code>。</p>";
        return;
      }
      box.innerHTML =
        "<p><strong>" + esc(active.label || active.profile) + "</strong> · <code>" + esc(active.model) + "</code></p>" +
        "<p>端点：<code>" + esc(active.endpoint_host || "") + "</code></p>" +
        "<p>密钥：" + (active.api_key_set ? "<span class='good'>已设置环境变量</span>" : "<span class='bad'>未检测到环境变量</span>") + "</p>" +
        (cfg.source ? "<p class='muted'>配置文件：" + esc(cfg.source) + "</p>" : "");
    } catch (err) {
      box.innerHTML = "<p class='bad'>" + esc(err.message) + "</p>";
    }
  }

  function setWorkspace(name) {
    state.workspace = name;
    $$(".main-nav button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.workspace === name);
    });
    $$(".workspace").forEach(function (ws) {
      ws.classList.toggle("active", ws.id === "ws-" + name);
    });
  }

  function parseRoute() {
    const hash = location.hash.replace(/^#/, "") || "/collect";
    const qIdx = hash.indexOf("?");
    const pathPart = qIdx >= 0 ? hash.slice(0, qIdx) : hash;
    const query = qIdx >= 0 ? hash.slice(qIdx + 1) : "";
    const params = new URLSearchParams(query);
    const parts = pathPart.split("/").filter(Boolean);
    return { parts: parts, params: params };
  }

  async function navigateFromHash() {
    const route = parseRoute();
    const head = route.parts[0] || "collect";

    if (head === "jobs" && route.parts[1]) {
      setWorkspace("collect");
      await showJobDetail(route.parts[1]);
      return;
    }
    if (head === "drafts" && route.parts[1]) {
      setWorkspace("pending");
      state.pendingFilter = "drafts";
      syncPendingFilters();
      await refreshPending();
      await showDraftDiff(route.parts[1]);
      return;
    }
    if (head === "reviews" && route.parts[1]) {
      setWorkspace("pending");
      await openReviewDetail(route.parts[1]);
      return;
    }
    if (head === "graph") {
      setWorkspace("knowledge");
      const focus = route.params.get("focus") || state.currentPageId;
      if (focus) {
        setKview("graph");
        await loadGraph(focus);
      }
      return;
    }
    if (head === "knowledge") {
      setWorkspace("knowledge");
      if (route.parts[1]) {
        await loadPage(decodeURIComponent(route.parts[1]));
      }
      return;
    }
    if (head === "pending") {
      setWorkspace("pending");
      const filter = route.params.get("filter");
      if (filter) {
        state.pendingFilter = filter;
        syncPendingFilters();
      }
      await refreshPending();
      return;
    }
    if (head === "more") {
      setWorkspace("more");
      await refreshMore();
      return;
    }

    setWorkspace(head === "collect" ? "collect" : head);
    if (head === "collect") await refreshCollect();
    if (head === "pending") await refreshPending();
    if (head === "knowledge") await refreshKnowledgeList();
    if (head === "more") await refreshMore();
  }

  function syncPendingFilters() {
    $$("#pending-filters button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.filter === state.pendingFilter);
    });
  }

  function setKview(view) {
    state.kview = view;
    $$(".view-tabs button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.kview === view);
    });
    $$(".kview-panel").forEach(function (p) {
      const match = p.dataset.kview === view;
      p.classList.toggle("active", match);
      p.hidden = !match;
    });
  }

  async function refreshCollect() {
    try {
      const [summary, acqData, jobsData, llmConfig] = await Promise.all([
        api("/api/v1/status/summary"),
        api("/api/v1/acquisitions"),
        api("/api/v1/jobs"),
        api("/api/v1/config/llm").catch(function () { return {}; }),
      ]);

      updateModelPill(summary, llmConfig);

      const metrics = $("#collect-metrics");
      const items = [
        [summary.jobs_pending || 0, "进行中任务"],
        [summary.jobs_failed || 0, "失败任务"],
        [(acqData.acquisitions || []).length, "来源"],
        [summary.model_ready ? "就绪" : "未配置", "模型"],
      ];
      spreadChildren(
        metrics,
        items.map(function (v) {
          const d = document.createElement("div");
          d.className = "metric";
          d.innerHTML = "<b>" + esc(v[0]) + "</b><span>" + esc(v[1]) + "</span>";
          return d;
        })
      );

      const jobs = jobsData.jobs || [];
      const acqs = acqData.acquisitions || [];
      const timeline = $("#timeline");
      const rows = [];

      jobs.slice(0, 50).forEach(function (job) {
        const stage = STAGE_LABELS[job.stage] || job.stage;
        const kind = job.stage === "failed" ? "failed" : job.stage === "applied" || job.stage === "awaiting_review" ? "done" : "running";
        rows.push(
          makeRow(
            [job.id, badge(stage, kind), job.updated_at || job.created_at || ""],
            [
              { label: "详情", run: function () { location.hash = "#/jobs/" + encodeURIComponent(job.id); } },
              job.stage === "failed" ? { label: "重试", cls: "primary", run: function () { retryJob(job.id); } } : null,
              job.links && job.links.web_draft ? { label: "草稿", run: function () { location.hash = "#/drafts/" + encodeURIComponent(job.draft_id || ""); } } : null,
              job.links && job.links.obsidian ? { label: "Obsidian", run: function () { window.open(job.links.obsidian, "_blank"); } } : null,
            ].filter(Boolean),
            { clickable: true, onClick: function () { location.hash = "#/jobs/" + encodeURIComponent(job.id); } }
          )
        );
      });

      if (!rows.length && acqs.length) {
        acqs.slice(0, 20).forEach(function (acq) {
          rows.push(
            makeRow(
              [acq.title || acq.canonical_origin || acq.id, badge(acq.kind || "来源", "draft"), acq.updated_at || ""],
              acq.links && acq.links.obsidian ? [{ label: "Obsidian", run: function () { window.open(acq.links.obsidian, "_blank"); } }] : []
            )
          );
        });
      }

      spreadChildren(timeline, rows.length ? rows : [emptyRow("暂无采集任务。上传文件、提交 URL 或粘贴正文开始采集。")]);
      notice(summary.model_ready ? "模型已连接，可生成草稿" : "未检测到模型配置，归档仍可用");
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function showJobDetail(jobId) {
    try {
      const job = await api("/api/v1/jobs/" + encodeURIComponent(jobId));
      const inspector = $("#inspector");
      const body = $("#inspector-body");
      $("#inspector-title").textContent = "任务 · " + jobId;
      body.innerHTML =
        "<dl>" +
        "<dt>阶段</dt><dd>" + esc(STAGE_LABELS[job.stage] || job.stage) + "</dd>" +
        "<dt>创建时间</dt><dd>" + esc(job.created_at || "") + "</dd>" +
        "<dt>更新时间</dt><dd>" + esc(job.updated_at || "") + "</dd>" +
        (job.error ? "<dt>错误</dt><dd class='bad'>" + esc(job.error) + "</dd>" : "") +
        (job.draft_id ? "<dt>草稿</dt><dd><a href='#/drafts/" + encodeURIComponent(job.draft_id) + "'>" + esc(job.draft_id) + "</a></dd>" : "") +
        "</dl>";
      inspector.hidden = false;

      if (job.stage === "failed") {
        const retryBtn = document.createElement("button");
        retryBtn.type = "button";
        retryBtn.className = "btn primary";
        retryBtn.textContent = "重试";
        retryBtn.onclick = function () { retryJob(jobId); };
        body.appendChild(retryBtn);
      }
      if (job.links && job.links.obsidian) {
        const link = document.createElement("a");
        link.className = "btn";
        link.href = job.links.obsidian;
        link.target = "_blank";
        link.textContent = "在 Obsidian 打开";
        link.style.marginTop = "12px";
        link.style.display = "inline-block";
        body.appendChild(link);
      }
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function retryJob(jobId) {
    try {
      await api("/api/v1/jobs/" + encodeURIComponent(jobId) + "/retry", { method: "POST" });
      notice("已重新排队");
      await refreshCollect();
      await showJobDetail(jobId);
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function refreshPending() {
    try {
      const [drafts, facts, research, jobs] = await Promise.all([
        api("/api/drafts"),
        api("/api/reviews?queue=facts"),
        api("/api/reviews?queue=research"),
        api("/api/v1/jobs"),
      ]);

      const failedJobs = (jobs.jobs || []).filter(function (j) { return j.stage === "failed"; });
      const list = $("#pending-list");
      const filter = state.pendingFilter;
      const rows = [];

      if (filter === "all" || filter === "drafts") {
        drafts.forEach(function (d) {
          rows.push({
            sort: d.created_at || "",
            row: makeRow(
              [d.title, badge("草稿", "draft"), d.created_at],
              [
                { label: "差异", run: function () { showDraftDiff(d.id); } },
                { label: "应用", cls: "primary", run: function () { applyDraft(d.id); } },
                { label: "丢弃", cls: "danger", run: function () { discardDraft(d.id); } },
              ],
              { clickable: true, onClick: function () { location.hash = "#/drafts/" + encodeURIComponent(d.id); } }
            ),
          });
        });
      }

      if (filter === "all" || filter === "facts") {
        facts.forEach(function (r) {
          rows.push({
            sort: r.created_at || r.title,
            row: makeRow(
              [r.text, badge("事实核验", "facts"), r.title],
              [
                { label: "查看", run: function () { openReviewDetail(r.id); } },
                { label: "已核实", cls: "primary", run: function () { resolveReviewQuick(r.id); } },
              ],
              { clickable: true, onClick: function () { location.hash = "#/reviews/" + encodeURIComponent(r.id); } }
            ),
          });
        });
      }

      if (filter === "all" || filter === "research") {
        research.forEach(function (r) {
          rows.push({
            sort: r.created_at || r.title,
            row: makeRow(
              [r.text, badge("待补充", "research"), r.title],
              [{ label: "查看", run: function () { openReviewDetail(r.id); } }],
              { clickable: true, onClick: function () { location.hash = "#/reviews/" + encodeURIComponent(r.id); } }
            ),
          });
        });
      }

      if (filter === "all" || filter === "failed") {
        failedJobs.forEach(function (j) {
          rows.push({
            sort: j.updated_at || j.created_at || "",
            row: makeRow(
              [j.id, badge("失败", "failed"), j.error || STAGE_LABELS.failed],
              [
                { label: "详情", run: function () { location.hash = "#/jobs/" + encodeURIComponent(j.id); } },
                { label: "重试", cls: "primary", run: function () { retryJob(j.id); } },
              ]
            ),
          });
        });
      }

      rows.sort(function (a, b) { return String(b.sort).localeCompare(String(a.sort)); });
      spreadChildren(list, rows.length ? rows.sort(function (a, b) { return String(b.sort).localeCompare(String(a.sort)); }).map(function (x) { return x.row; }) : [emptyRow("暂无待处理事项")]);
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function showDraftDiff(id) {
    try {
      const d = await api("/api/drafts/" + encodeURIComponent(id));
      $("#diff-title").textContent = d.title + " · " + id;
      $("#diff-content").textContent =
        (d.diffs || []).map(function (x) { return x.diff || x.operation + " " + x.path; }).join("\n\n") || "无文本差异";
      $("#diff-dialog").showModal();
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function applyDraft(id) {
    if (!confirm("应用该草稿？")) return;
    try {
      await api("/api/drafts/" + encodeURIComponent(id) + "/accept", { method: "POST" });
      notice("草稿已应用");
      await refreshPending();
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function discardDraft(id) {
    if (!confirm("丢弃该草稿？")) return;
    try {
      await api("/api/drafts/" + encodeURIComponent(id) + "/discard", { method: "POST" });
      notice("草稿已丢弃");
      await refreshPending();
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function openReviewDetail(id) {
    try {
      const detail = await api("/api/reviews/" + encodeURIComponent(id));
      state.activeReviewId = id;
      $("#review-title").textContent = detail.review.title;
      $("#review-question").textContent = detail.review.text;
      const anchor = $("#review-anchor");
      const quote = detail.evidence.quote || "";
      anchor.hidden = false;
      anchor.textContent = quote
        ? "原文证据（" + (detail.evidence.anchor || "已定位") + "）\n" + quote
        : "此项属于待补充，尚无可核实的原文引句。";
      $("#review-evidence").textContent = detail.evidence.content;
      $("#review-wiki-page").textContent = detail.wiki_page.content;
      $("#review-note").value = detail.review.resolution_note || "";
      $("#open-evidence").href = obsidianLink(detail.evidence.absolute_path);
      $("#open-evidence").hidden = !detail.evidence.absolute_path;
      $("#open-wiki-page").href = obsidianLink(detail.wiki_page.absolute_path);
      $("#open-wiki-page").hidden = !detail.wiki_page.absolute_path;
      $("#review-dialog").showModal();
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function resolveReviewQuick(id) {
    try {
      await api("/api/reviews/" + encodeURIComponent(id), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "resolved" }),
      });
      await refreshPending();
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function refreshKnowledgeList() {
    try {
      const data = await api("/api/v1/pages");
      const list = $("#search-results");
      const pages = data.pages || [];
      list.replaceChildren.apply(
        list,
        pages.length
          ? pages.map(function (p) {
              return makeRow(
                [p.title || p.id, badge("页面", "draft"), p.id],
                [{ label: "阅读", run: function () { location.hash = "#/knowledge/" + encodeURIComponent(p.id); } }],
                {
                  clickable: true,
                  onClick: function () { location.hash = "#/knowledge/" + encodeURIComponent(p.id); },
                }
              );
            })
          : [emptyRow("暂无 Wiki 页面")]
      );
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function doSearch() {
    const q = $("#search-input").value.trim();
    if (!q) {
      await refreshKnowledgeList();
      return;
    }
    try {
      const hits = await api("/api/search?q=" + encodeURIComponent(q));
      const list = $("#search-results");
      setKview("list");
      list.replaceChildren.apply(
        list,
        hits.length
          ? hits.map(function (h) {
              return makeRow(
                [h.path, String(h.score), h.excerpt.slice(0, 80)],
                [{ label: "阅读", run: function () { location.hash = "#/knowledge/" + encodeURIComponent(h.path); } }],
                {
                  clickable: true,
                  onClick: function () { location.hash = "#/knowledge/" + encodeURIComponent(h.path); },
                }
              );
            })
          : [emptyRow("没有命中")]
      );
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function loadPage(pageId) {
    try {
      const page = await api("/api/v1/pages/" + encodeURIComponent(pageId));
      state.currentPageId = pageId;
      setKview("read");
      $("#page-title").textContent = pageId.split("/").pop();
      $("#page-content").innerHTML = renderMarkdown(page.content || "");
      $("#edit-obsidian").onclick = function () {
        if (page.links && page.links.obsidian) window.open(page.links.obsidian, "_blank");
      };
      $("#show-graph").onclick = function () {
        location.hash = "#/graph?focus=" + encodeURIComponent(pageId);
      };

      const meta = $("#page-meta");
      const parts = [];
      if (page.sources && page.sources.length) {
        parts.push("<div><strong>来源</strong><ul>" + page.sources.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ul></div>");
      }
      if (page.backlinks && page.backlinks.length) {
        parts.push(
          "<div><strong>反向链接</strong><ul>" +
            page.backlinks.map(function (b) {
              return '<li><a href="#/knowledge/' + encodeURIComponent(b) + '">' + esc(b) + "</a></li>";
            }).join("") +
            "</ul></div>"
        );
      }
      if (page.outlinks && page.outlinks.length) {
        parts.push(
          "<div><strong>出链</strong><ul>" +
            page.outlinks.map(function (b) {
              return '<li><a href="#/knowledge/' + encodeURIComponent(b) + '">' + esc(b) + "</a></li>";
            }).join("") +
            "</ul></div>"
        );
      }
      meta.innerHTML = parts.join("") || "<span class='muted'>无附加元数据</span>";
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function loadGraph(focusId) {
    try {
      const graph = await api("/api/v1/graph/neighborhood?page_id=" + encodeURIComponent(focusId));
      setKview("graph");
      if (!state.graphView) {
        state.graphView = new window.LLMWikiGraph.GraphView($("#graph-canvas"));
        state.graphView.onSelect = function (id) {
          location.hash = "#/knowledge/" + encodeURIComponent(id);
        };
      }
      state.graphView.resize();
      state.graphView.setData(graph, focusId);
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function doAsk(inputId, outputId) {
    const q = $(inputId).value.trim();
    if (!q) return;
    try {
      $(outputId).hidden = false;
      $(outputId).textContent = "思考中…";
      const data = await api("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      $(outputId).textContent = data.answer;
    } catch (err) {
      $(outputId).textContent = err.message;
    }
  }

  async function refreshMore() {
    try {
      const [health, trash, summary] = await Promise.all([
        api("/api/v1/health/wiki"),
        api("/api/trash"),
        api("/api/v1/status/summary"),
      ]);

      const metrics = $("#health-metrics");
      metrics.replaceChildren.apply(
        metrics,
        [
          [health.broken_links, "断链"],
          [health.orphan_pages, "孤儿页"],
          [health.missing_sources, "缺失来源"],
          [summary.drafts_pending, "待确认草稿"],
        ].map(function (v) {
          const d = document.createElement("div");
          d.className = "metric";
          d.innerHTML = "<b>" + esc(v[0]) + "</b><span>" + esc(v[1]) + "</span>";
          return d;
        })
      );

      const list = $("#trash-list");
      list.replaceChildren.apply(
        list,
        trash.length
          ? trash.map(function (t) {
              return makeRow([t.title, t.raw_path, t.trashed_at], [
                { label: "恢复", cls: "primary", run: function () { restoreTrash(t.digest); } },
              ]);
            })
          : [emptyRow("回收站为空")]
      );
      await refreshModelConfig();
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function restoreTrash(digest) {
    try {
      await api("/api/trash/" + encodeURIComponent(digest) + "/restore", { method: "POST" });
      await refreshMore();
    } catch (err) {
      notice(err.message, true);
    }
  }

  async function uploadFiles(files) {
    for (const file of files) {
      try {
        await api("/api/v1/acquisitions/file", {
          method: "POST",
          headers: {
            "X-Filename": encodeURIComponent(file.name),
            "Content-Type": "application/octet-stream",
          },
          body: file,
        });
        notice("已提交：" + file.name);
      } catch (err) {
        notice(err.message, true);
      }
    }
    await refreshCollect();
  }

  function bindEvents() {
    $$(".main-nav button").forEach(function (btn) {
      btn.onclick = function () {
        location.hash = "#/" + btn.dataset.workspace;
      };
    });

    $$("#pending-filters button").forEach(function (btn) {
      btn.onclick = function () {
        state.pendingFilter = btn.dataset.filter;
        syncPendingFilters();
        refreshPending();
      };
    });

    $$(".view-tabs button").forEach(function (btn) {
      btn.onclick = function () {
        setKview(btn.dataset.kview);
        if (btn.dataset.kview === "graph" && state.currentPageId) {
          loadGraph(state.currentPageId);
        }
        if (btn.dataset.kview === "list") refreshKnowledgeList();
      };
    });

    $("#choose-file").onclick = function () { $("#file-input").click(); };
    $("#file-input").onchange = function (e) { uploadFiles(e.target.files); e.target.value = ""; };

    const drop = $("#drop-zone");
    drop.ondragover = function (e) { e.preventDefault(); drop.classList.add("drag"); };
    drop.ondragleave = function () { drop.classList.remove("drag"); };
    drop.ondrop = function (e) {
      e.preventDefault();
      drop.classList.remove("drag");
      uploadFiles(e.dataTransfer.files);
    };

    $("#url-form").onsubmit = async function (e) {
      e.preventDefault();
      const url = $("#url-input").value.trim();
      if (!url) return;
      try {
        const data = await api("/api/v1/acquisitions/url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: url }),
        });
        notice("已提交 URL 采集");
        $("#url-input").value = "";
        if (data.links && data.links.web) location.hash = data.links.web.replace(/^[^#]*/, "") || "#/collect";
        await refreshCollect();
      } catch (err) {
        notice(err.message, true);
      }
    };

    $("#paste-form").onsubmit = async function (e) {
      e.preventDefault();
      const title = $("#paste-title").value.trim();
      const body = $("#paste-body").value.trim();
      const sourceUrl = $("#paste-url").value.trim();
      if (!title || !body) return;
      try {
        await api("/api/v1/acquisitions/paste", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: title, body: body, source_url: sourceUrl }),
        });
        notice("已提交粘贴正文");
        $("#paste-form").reset();
        await refreshCollect();
      } catch (err) {
        notice(err.message, true);
      }
    };

    $("#search-btn").onclick = doSearch;
    $("#search-input").onkeydown = function (e) { if (e.key === "Enter") doSearch(); };
    $("#ask-btn").onclick = function () {
      $("#ask-output").hidden = false;
      doAsk("#search-input", "#ask-output");
    };
    $("#more-ask-btn").onclick = function () { doAsk("#more-ask-input", "#more-ask-output"); };

    $("#diff-close").onclick = function () { $("#diff-dialog").close(); };
    $("#review-close").onclick = function () { $("#review-dialog").close(); };
    $("#inspector-close").onclick = function () { $("#inspector").hidden = true; };

    $("#resolve-review").onclick = async function () {
      if (!state.activeReviewId) return;
      try {
        await api("/api/reviews/" + encodeURIComponent(state.activeReviewId), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: "resolved",
            resolution_note: $("#review-note").value,
          }),
        });
        $("#review-dialog").close();
        await refreshPending();
      } catch (err) {
        notice(err.message, true);
      }
    };

    window.addEventListener("hashchange", navigateFromHash);
  }

  bindEvents();
  navigateFromHash();
  setInterval(function () {
    if (state.workspace === "collect") refreshCollect();
    else if (state.workspace === "pending") refreshPending();
  }, 5000);
})();
