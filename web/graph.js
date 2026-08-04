/**
 * Vanilla canvas local graph view for LLM Wiki.
 */
(function (global) {
  "use strict";

  const STAGE_COLORS = {
    focus: "#2563eb",
    default: "#94a3b8",
    edge: "#cbd5e1",
  };

  function dist(a, b) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy) || 1;
  }

  class GraphView {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.nodes = [];
      this.edges = [];
      this.focusId = null;
      this.onSelect = null;
      this.dragging = null;
      this.pan = { x: 0, y: 0 };
      this.scale = 1;
      this._raf = null;

      canvas.addEventListener("mousedown", (e) => this._onDown(e));
      canvas.addEventListener("mousemove", (e) => this._onMove(e));
      canvas.addEventListener("mouseup", () => { this.dragging = null; });
      canvas.addEventListener("mouseleave", () => { this.dragging = null; });
      canvas.addEventListener("wheel", (e) => this._onWheel(e), { passive: false });
      canvas.addEventListener("click", (e) => this._onClick(e));
      window.addEventListener("resize", () => this.resize());
    }

    resize() {
      const rect = this.canvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = Math.max(1, rect.width * dpr);
      this.canvas.height = Math.max(1, rect.height * dpr);
      this.canvas.style.width = rect.width + "px";
      this.canvas.style.height = rect.height + "px";
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.draw();
    }

    setData(graph, focusId) {
      const pages = graph.pages || {};
      const edges = graph.edges || [];
      this.focusId = focusId || graph.focus || null;
      const ids = Object.keys(pages);
      const cx = (this.canvas.clientWidth || 400) / 2;
      const cy = (this.canvas.clientHeight || 300) / 2;
      const radius = Math.min(cx, cy) * 0.65;

      this.nodes = ids.map((id, i) => {
        const angle = (2 * Math.PI * i) / Math.max(ids.length, 1);
        const entry = pages[id] || {};
        const label = id.split("/").pop() || id;
        return {
          id,
          label: label.length > 18 ? label.slice(0, 16) + "…" : label,
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
          vx: 0,
          vy: 0,
          sources: entry.sources || [],
        };
      });

      if (this.focusId) {
        const focus = this.nodes.find((n) => n.id === this.focusId);
        if (focus) {
          focus.x = cx;
          focus.y = cy;
        }
      }

      this.edges = edges
        .filter((e) => e.from && e.to)
        .map((e) => ({ from: e.from, to: e.to, kind: e.kind || "references" }));

      this._startSim();
      this.draw();
    }

    _startSim() {
      if (this._raf) cancelAnimationFrame(this._raf);
      let ticks = 0;
      const step = () => {
        ticks += 1;
        this._simulate();
        this.draw();
        if (ticks < 120) this._raf = requestAnimationFrame(step);
      };
      this._raf = requestAnimationFrame(step);
    }

    _simulate() {
      const repulsion = 2800;
      const attraction = 0.004;
      const centerPull = 0.02;
      const cx = (this.canvas.clientWidth || 400) / 2;
      const cy = (this.canvas.clientHeight || 300) / 2;

      for (let i = 0; i < this.nodes.length; i++) {
        for (let j = i + 1; j < this.nodes.length; j++) {
          const a = this.nodes[i];
          const b = this.nodes[j];
          const d = dist(a, b);
          const force = repulsion / (d * d);
          const dx = (a.x - b.x) / d;
          const dy = (a.y - b.y) / d;
          if (a.id !== this.focusId) { a.vx += dx * force; a.vy += dy * force; }
          if (b.id !== this.focusId) { b.vx -= dx * force; b.vy -= dy * force; }
        }
      }

      for (const edge of this.edges) {
        const a = this.nodes.find((n) => n.id === edge.from);
        const b = this.nodes.find((n) => n.id === edge.to);
        if (!a || !b) continue;
        const d = dist(a, b);
        const force = (d - 100) * attraction;
        const dx = (b.x - a.x) / d;
        const dy = (b.y - a.y) / d;
        if (a.id !== this.focusId) { a.vx += dx * force; a.vy += dy * force; }
        if (b.id !== this.focusId) { b.vx -= dx * force; b.vy -= dy * force; }
      }

      for (const node of this.nodes) {
        if (node.id === this.focusId) continue;
        node.vx += (cx - node.x) * centerPull;
        node.vy += (cy - node.y) * centerPull;
        node.vx *= 0.85;
        node.vy *= 0.85;
        node.x += node.vx;
        node.y += node.vy;
      }
    }

    draw() {
      const w = this.canvas.clientWidth;
      const h = this.canvas.clientHeight;
      const ctx = this.ctx;
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(this.pan.x, this.pan.y);
      ctx.scale(this.scale, this.scale);

      for (const edge of this.edges) {
        const a = this.nodes.find((n) => n.id === edge.from);
        const b = this.nodes.find((n) => n.id === edge.to);
        if (!a || !b) continue;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = edge.kind === "supported_by" ? "#93c5fd" : STAGE_COLORS.edge;
        ctx.lineWidth = edge.kind === "supported_by" ? 1.5 : 1;
        ctx.stroke();
      }

      for (const node of this.nodes) {
        const isFocus = node.id === this.focusId;
        const r = isFocus ? 10 : 7;
        ctx.beginPath();
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
        ctx.fillStyle = isFocus ? STAGE_COLORS.focus : STAGE_COLORS.default;
        ctx.fill();
        ctx.font = "11px Segoe UI, sans-serif";
        ctx.fillStyle = "#334155";
        ctx.textAlign = "center";
        ctx.fillText(node.label, node.x, node.y + r + 12);
      }

      ctx.restore();
    }

    _screenToGraph(e) {
      const rect = this.canvas.getBoundingClientRect();
      return {
        x: (e.clientX - rect.left - this.pan.x) / this.scale,
        y: (e.clientY - rect.top - this.pan.y) / this.scale,
      };
    }

    _hitTest(x, y) {
      for (let i = this.nodes.length - 1; i >= 0; i--) {
        const n = this.nodes[i];
        if (dist(n, { x, y }) <= 12) return n;
      }
      return null;
    }

    _onDown(e) {
      const p = this._screenToGraph(e);
      const node = this._hitTest(p.x, p.y);
      if (node) this.dragging = node;
    }

    _onMove(e) {
      if (!this.dragging) return;
      const p = this._screenToGraph(e);
      this.dragging.x = p.x;
      this.dragging.y = p.y;
      this.dragging.vx = 0;
      this.dragging.vy = 0;
      this.draw();
    }

    _onWheel(e) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      this.scale = Math.min(2.5, Math.max(0.4, this.scale * delta));
      this.draw();
    }

    _onClick(e) {
      const p = this._screenToGraph(e);
      const node = this._hitTest(p.x, p.y);
      if (node && this.onSelect) this.onSelect(node.id);
    }
  }

  global.LLMWikiGraph = { GraphView };
})(window);
