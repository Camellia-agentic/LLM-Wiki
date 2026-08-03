from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from urllib.request import Request, urlopen


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "wiki.py"
SPEC = importlib.util.spec_from_file_location("wiki_tool", SCRIPT)
assert SPEC and SPEC.loader
wiki_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wiki_tool)


class WikiToolTests(unittest.TestCase):
    def test_ingest_search_and_lint_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "notes.md"
            source.write_text("# 设备维护\n\n每周检查传送带张力，并记录异常。\n\n## 安全\n\n停机后才能清洁设备。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            self.assertTrue(wiki.ingest(source, args))
            wiki.rebuild_index()
            wiki.rebuild_overview()
            self.assertTrue(any((root / "raw" / "sources").glob("*.md")))
            self.assertTrue(list((root / "wiki" / "sources").glob("*.md")))
            hits = wiki.search("传送带检查", 3)
            self.assertTrue(hits)
            broken, _, missing_sources = wiki.lint()
            self.assertEqual([], broken)
            self.assertEqual([], missing_sources)

    def test_watch_once_archives_new_and_changed_inbox_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            inbox_note = root / "raw" / "inbox" / "巡检记录.md"
            inbox_note.write_text("# 巡检记录\n\n初始记录：检查风机。\n", encoding="utf-8")
            args = Namespace(
                llm_url=None,
                model=None,
                api_key="",
                timeout=1,
                max_tokens=200,
                interval=0.01,
                settle_seconds=0,
                once=True,
            )
            self.assertEqual(0, wiki_tool.watch_inbox(wiki, wiki.inbox, args))
            self.assertEqual(1, len(list((root / "raw" / "sources").glob("*.md"))))
            inbox_note.write_text("# 巡检记录\n\n修订记录：检查风机并清洁滤网。\n", encoding="utf-8")
            self.assertEqual(0, wiki_tool.watch_inbox(wiki, wiki.inbox, args))
            self.assertEqual(2, len(list((root / "raw" / "sources").glob("*.md"))))
            self.assertEqual(2, len(list((root / "wiki" / "sources").glob("*.md"))))

    def test_refine_updates_archived_source_with_model_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# 缓存策略\n\n缓存应设置失效时间。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            offline_args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            args = Namespace(llm_url="http://example.test/v1/chat/completions", model="test", api_key="", timeout=1, max_tokens=200, apply=True)
            self.assertTrue(wiki.ingest(source, offline_args))
            archived = next((root / "raw" / "sources").glob("*.md"))
            wiki.llm_analysis = lambda *_: {
                "summary": "缓存策略要求设置失效时间，并根据场景选择更新方式。",
                "concepts": [{"name": "缓存失效", "summary": "缓存条目在规定时间后必须重新获取。"}],
                "entities": [{"name": "缓存服务", "summary": "提供热点数据缓存的组件。"}],
                "links": ["[[wiki/sources/not-found]]"],
                "review_items": ["需确认不同业务场景的失效时间。"],
            }
            wiki.llm_generation = lambda _, __, analysis, ___: analysis
            self.assertTrue(wiki.refine(archived, args))
            self.assertTrue(list((root / "wiki" / "concepts").glob("*.md")))
            self.assertTrue(list((root / "wiki" / "entities").glob("*.md")))
            source_page = next((root / "wiki" / "sources").glob("*.md"))
            self.assertIn("根据场景选择更新方式", source_page.read_text(encoding="utf-8"))
            self.assertNotIn("not-found", source_page.read_text(encoding="utf-8"))
            query = root / "wiki" / "queries" / "缓存策略问答.md"
            wiki_tool.write_text(query, wiki_tool.frontmatter("缓存策略问答", "query", ["sources/" + source_page.stem]) + "# 缓存策略问答\n")
            _, _, missing_sources = wiki.lint()
            self.assertEqual([], missing_sources)
            self.assertTrue((root / ".llm-wiki" / "analyses" / (wiki_tool.sha256(archived) + ".json")).is_file())

    def test_queue_persists_and_processes_inbox_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            source = wiki.inbox / "队列资料.md"
            source.write_text("# 队列资料\n\n队列需要持久化并支持重试。\n", encoding="utf-8")
            args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            task_id = wiki.enqueue_source(source)
            self.assertTrue(task_id)
            result = wiki.process_queue(args)
            self.assertEqual(1, result["completed"])
            task = wiki.load_queue()["tasks"][0]
            self.assertEqual("completed", task["status"])
            self.assertTrue((root / ".llm-wiki" / "search.db").is_file())

    def test_failed_queue_task_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            source = wiki.inbox / "失败资料.md"
            source.write_text("# 失败资料\n\n模型暂时不可用。\n", encoding="utf-8")
            task_id = wiki.enqueue_source(source)
            wiki.ingest = lambda *_: (_ for _ in ()).throw(RuntimeError("temporary model error"))
            args = Namespace(llm_url="http://example.test", model="test", api_key="", timeout=1, max_tokens=200)
            result = wiki.process_queue(args)
            self.assertEqual(1, result["failed"])
            self.assertEqual("failed", wiki.load_queue()["tasks"][0]["status"])
            self.assertTrue(wiki.retry_queue_task(task_id))
            task = wiki.load_queue()["tasks"][0]
            self.assertEqual("pending", task["status"])
            self.assertEqual(0, task["attempts"])

    def test_missing_queue_source_counts_toward_retry_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            source = wiki.inbox / "已删除.md"
            source.write_text("# 已删除\n", encoding="utf-8")
            wiki.enqueue_source(source)
            source.unlink()
            args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            self.assertEqual(1, wiki.process_queue(args)["failed"])
            self.assertEqual(1, wiki.load_queue()["tasks"][0]["attempts"])

    def test_synthesize_and_remove_preserve_shared_topic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            first = Path(directory) / "first.md"
            second = Path(directory) / "second.md"
            first.write_text("# 第一资料\n\n缓存提高读取性能。\n", encoding="utf-8")
            second.write_text("# 第二资料\n\n缓存降低后端压力。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            offline_args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            wiki.ingest(first, offline_args)
            wiki.ingest(second, offline_args)
            state = wiki.load_state()["sources"]
            entries = list(state.values())
            concept = root / "wiki" / "concepts" / "缓存.md"
            wiki_tool.write_text(concept, wiki_tool.frontmatter("缓存", "concept", [entries[0]["raw_path"], entries[1]["raw_path"]]) + "# 缓存\n\n## 说明\n\n共享主题。\n")
            self.assertEqual([entries[0]["raw_path"], entries[1]["raw_path"]], wiki.frontmatter_sources(concept.read_text(encoding="utf-8")))
            model_args = Namespace(llm_url="http://example.test", model="test", api_key="", timeout=1, max_tokens=200, apply=True)
            wiki.llm_json = lambda *_: {"title": "缓存专题", "summary": "两份资料都讨论缓存。", "findings": ["缓存改善性能。"], "comparisons": [], "open_questions": ["缓存失效策略如何选择？"], "related_pages": []}
            synthesis = wiki.synthesize("缓存", model_args)
            self.assertTrue(synthesis.is_file())
            self.assertEqual([entries[0]["raw_path"], entries[1]["raw_path"]], wiki.frontmatter_sources(concept.read_text(encoding="utf-8")), concept.read_text(encoding="utf-8"))
            self.assertEqual([entries[0]["raw_path"], entries[1]["raw_path"]], wiki.frontmatter_sources(wiki_tool.read_text(concept)), wiki_tool.read_text(concept))
            raw_to_remove = entries[0]["raw_path"]
            self.assertEqual(raw_to_remove, wiki.remove_source(raw_to_remove))
            self.assertFalse((root / raw_to_remove).exists())
            self.assertTrue(concept.exists())
            concept_content = concept.read_text(encoding="utf-8")
            self.assertEqual([entries[1]["raw_path"]], wiki.frontmatter_sources(concept_content), concept_content)

    def test_ask_retries_when_answer_lacks_citation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# 缓存\n\n缓存减少重复计算。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            offline_args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            wiki.ingest(source, offline_args)
            source_page = next((root / "wiki" / "sources").glob("*.md"))
            model_args = Namespace(llm_url="http://example.test", model="test", api_key="", timeout=1, top_k=6, save=False)
            replies = iter(["缓存能减少重复计算。", f"缓存能减少重复计算。[{wiki.wiki_link(source_page)}]"])
            wiki.llm_request = lambda *_args, **_kwargs: next(replies)
            answer = wiki.ask("缓存有什么作用？", model_args)
            self.assertIn(f"[{wiki.wiki_link(source_page)}]", answer)

    def test_llm_ingest_stages_then_applies_and_detects_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# 缓存策略\n\n缓存需要设置失效时间。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            args = Namespace(llm_url="http://example.test", model="test", api_key="", timeout=1, max_tokens=200, apply=False)
            analysis = {
                "summary": "缓存策略应设置失效时间。",
                "concepts": [{"name": "缓存失效", "summary": "条目到期后重新获取。"}],
                "entities": [],
                "links": [],
                "review_items": ["确认不同场景的失效时间。"],
            }
            wiki.llm_analysis = lambda *_: analysis
            wiki.llm_generation = lambda _, __, value, ___: value
            self.assertTrue(wiki.ingest(source, args))
            draft = wiki.list_drafts("draft")[0]
            self.assertEqual("draft", draft["status"])
            self.assertFalse(list((root / "wiki" / "sources").glob("*.md")))
            wiki.apply_draft(draft["id"])
            page = next((root / "wiki" / "sources").glob("*.md"))
            self.assertIn("缓存策略应设置失效时间", page.read_text(encoding="utf-8"))
            self.assertTrue(list((root / "wiki" / "concepts").glob("*.md")))
            archived = next((root / "raw" / "sources").glob("*.md"))
            analysis["summary"] = "更新后的缓存策略。"
            self.assertTrue(wiki.refine(archived, args))
            conflict_draft = wiki.list_drafts("draft")[0]
            page.write_text(page.read_text(encoding="utf-8") + "\n## 人工补充\n\n保留这段说明。\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                wiki.apply_draft(conflict_draft["id"])
            self.assertEqual("draft", wiki.load_draft(conflict_draft["id"])["status"])

    def test_discarded_draft_leaves_wiki_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# 队列\n\n需要可恢复任务。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            args = Namespace(llm_url="http://example.test", model="test", api_key="", timeout=1, max_tokens=200, apply=False)
            wiki.llm_analysis = lambda *_: {"summary": "队列应保留失败状态。", "concepts": [], "entities": [], "links": [], "review_items": []}
            wiki.llm_generation = lambda _, __, value, ___: value
            wiki.ingest(source, args)
            draft = wiki.list_drafts("draft")[0]
            wiki.discard_draft(draft["id"])
            self.assertEqual("discarded", wiki.load_draft(draft["id"])["status"])
            self.assertFalse(list((root / "wiki" / "sources").glob("*.md")))
            self.assertTrue(next((root / "raw" / "sources").glob("*.md")).is_file())

    def test_refine_preserves_unknown_frontmatter_and_human_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# 网络\n\n网络需要可观测性。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            offline_args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            wiki.ingest(source, offline_args)
            page = next((root / "wiki" / "sources").glob("*.md"))
            page.write_text(page.read_text(encoding="utf-8").replace("updated:", "owner: \"me\"\nupdated:") + "\n## 人工补充\n\n这里是人工结论。\n", encoding="utf-8")
            model_args = Namespace(llm_url="http://example.test", model="test", api_key="", timeout=1, max_tokens=200, apply=True)
            wiki.llm_analysis = lambda *_: {"summary": "网络需要持续可观测。", "concepts": [], "entities": [], "links": [], "review_items": []}
            wiki.llm_generation = lambda _, __, value, ___: value
            wiki.refine(next((root / "raw" / "sources").glob("*.md")), model_args)
            content = page.read_text(encoding="utf-8")
            self.assertIn('owner: "me"', content)
            self.assertIn("这里是人工结论。", content)

    def test_trash_restore_and_explicit_topic_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# RDMA\n\n远程直接内存访问降低延迟。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            offline_args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            wiki.ingest(source, offline_args)
            entry = next(iter(wiki.load_state()["sources"].values()))
            source_page = root / "wiki" / entry["source_page"]
            wiki.trash_source(entry["raw_path"])
            self.assertFalse(wiki.is_visible_page(source_page))
            self.assertTrue(source_page.exists())
            digest = next(iter(wiki.load_state()["trash"]))
            wiki.restore_source(digest)
            self.assertTrue(wiki.is_visible_page(source_page))
            concept = root / "wiki" / "concepts" / "rdma.md"
            wiki_tool.write_text(concept, wiki_tool.frontmatter("RDMA", "concept", []) + "# RDMA\n")
            candidates = wiki.duplicate_candidates("concepts", "RDMA技术", wiki.topic_path("concepts", "RDMA技术"))
            self.assertTrue(candidates)
            draft = wiki.create_draft("ingest", "重复候选", {}, duplicate_candidates=candidates)
            self.assertIn("疑似重复", wiki.draft_diff(draft)[0]["diff"])
            wiki.add_topic_alias("concepts", "rdma", "远程直接内存访问")
            self.assertIn("aliases:", concept.read_text(encoding="utf-8"))

    def test_review_detail_exposes_source_and_persists_resolution_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# 数据校验\n\n延迟数据需要注明测试条件。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            offline_args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            wiki.ingest(source, offline_args)
            entry = next(iter(wiki.load_state()["sources"].values()))
            wiki.append_reviews("数据校验", entry["raw_path"], ["确认延迟数据的来源和时效性。"])
            review = wiki.load_reviews()["items"][0]
            detail = wiki.review_detail(review["id"])
            self.assertIn("延迟数据需要注明测试条件", detail["evidence"]["content"])
            self.assertIn("数据校验", detail["wiki_page"]["content"])
            self.assertTrue(wiki.set_review_status(review["id"], "resolved", "已复核 2026-07 测试记录。"))
            resolved = wiki.load_reviews()["items"][0]
            self.assertEqual("已复核 2026-07 测试记录。", resolved["resolution_note"])

    def test_only_exactly_anchored_source_claims_enter_fact_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            source = Path(directory) / "source.md"
            source.write_text("# 数据校验\n\n延迟数据需要注明测试条件。\n", encoding="utf-8")
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            offline_args = Namespace(llm_url=None, model=None, api_key="", timeout=1, max_tokens=200)
            wiki.ingest(source, offline_args)
            entry = next(iter(wiki.load_state()["sources"].values()))
            wiki.append_reviews("数据校验", entry["raw_path"], [
                {"kind": "source_claim", "text": "资料要求延迟数据注明测试条件。", "evidence_quote": "延迟数据需要注明测试条件。", "evidence_anchor": "模型提供的位置"},
                {"kind": "source_claim", "text": "没有证据的断言。", "evidence_quote": "原文不存在的句子"},
                {"kind": "gap", "text": "补充测试环境和样本量。"},
            ])
            reviews = wiki.load_reviews()["items"]
            facts = [item for item in reviews if wiki.review_queue(item) == "facts"]
            research = [item for item in reviews if wiki.review_queue(item) == "research"]
            self.assertEqual(1, len(facts))
            self.assertEqual("第 3 行", facts[0]["evidence_anchor"])
            self.assertEqual("延迟数据需要注明测试条件。", facts[0]["evidence_quote"])
            self.assertEqual(2, len(research))
            self.assertIn("research_question", {item["kind"] for item in research})
            rendered = wiki_tool.read_text(root / "wiki" / "reviews.md")
            self.assertIn("## 待核实事实", rendered)
            self.assertIn("## 待补充", rendered)
            self.assertIn("> 延迟数据需要注明测试条件。", rendered)

    def test_legacy_unanchored_reviews_migrate_to_research_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            wiki.save_json(wiki.reviews_path, {"items": [{
                "id": "legacy-review",
                "title": "旧资料",
                "raw_path": "raw/sources/old.md",
                "text": "确认旧资料的版本。",
                "status": "open",
                "created_at": "2026-07-20 10:00",
                "resolved_at": "",
            }]})
            migrated = wiki.load_reviews()
            item = migrated["items"][0]
            self.assertEqual(2, migrated["schema"])
            self.assertEqual("legacy_unanchored", item["kind"])
            self.assertEqual("research", wiki.review_queue(item))
            self.assertIn("旧版审核项未保存", item["migration_note"])
            self.assertIn("待补充", wiki_tool.read_text(root / "wiki" / "reviews.md"))

    def test_local_control_center_exposes_status_and_inbox_upload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            args = Namespace(
                llm_url=None,
                model=None,
                api_key="",
                timeout=1,
                interval=1,
                settle_seconds=0,
                max_tokens=200,
                auto_accept=False,
                no_watch=True,
            )
            control = wiki_tool.LocalControl(wiki, args)
            server = wiki_tool.ThreadingHTTPServer(("127.0.0.1", 0), wiki_tool.make_control_handler(control))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            address = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(address + "/api/status", timeout=3) as response:
                    status = json.loads(response.read().decode("utf-8"))
                self.assertEqual([], status["inbox"])
                source = Path(directory) / "review-source.md"
                source.write_text("# 审核来源\n\n需要核实数据条件。\n", encoding="utf-8")
                wiki.ingest(source, args)
                entry = next(iter(wiki.load_state()["sources"].values()))
                wiki.append_reviews("审核来源", entry["raw_path"], ["确认数据条件。"])
                wiki.append_reviews("审核来源", entry["raw_path"], [{
                    "kind": "source_claim",
                    "text": "资料要求核实数据条件。",
                    "evidence_quote": "需要核实数据条件。",
                }])
                review_id = wiki.load_reviews()["items"][0]["id"]
                review_request = Request(address + f"/api/reviews/{review_id}", headers={"X-LLM-Wiki-Token": control.token})
                with urlopen(review_request, timeout=3) as response:
                    detail = json.loads(response.read().decode("utf-8"))
                self.assertIn("需要核实数据条件", detail["evidence"]["content"])
                with urlopen(Request(address + "/api/reviews?queue=facts", headers={"X-LLM-Wiki-Token": control.token}), timeout=3) as response:
                    facts = json.loads(response.read().decode("utf-8"))
                with urlopen(Request(address + "/api/reviews?queue=research", headers={"X-LLM-Wiki-Token": control.token}), timeout=3) as response:
                    research = json.loads(response.read().decode("utf-8"))
                self.assertEqual(["source_claim"], [item["kind"] for item in facts])
                self.assertEqual(["research_question"], [item["kind"] for item in research])
                request = Request(
                    address + "/api/inbox",
                    data="# 新资料\n\n通过控制中心放入收件箱。\n".encode("utf-8"),
                    headers={"X-LLM-Wiki-Token": control.token, "X-Filename": "new-note.md", "Content-Type": "application/octet-stream"},
                    method="POST",
                )
                with urlopen(request, timeout=3) as response:
                    self.assertEqual(201, response.status)
                self.assertTrue((root / "raw" / "inbox" / "new-note.md").is_file())
                with urlopen(address + "/", timeout=3) as response:
                    page = response.read().decode("utf-8")
                self.assertIn("LLM Wiki", page)
                self.assertIn(r'join("\n\n")', page)
                self.assertIn("查看正文", page)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_rebuild_index_does_not_truncate_wikilinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "vault"
            wiki = wiki_tool.Wiki(root)
            wiki.ensure_layout()
            source_page = root / "wiki" / "sources" / "来源.md"
            wiki_tool.write_text(source_page, wiki_tool.frontmatter("来源", "source_summary", []) + "# 来源\n\n摘要。\n")
            query = root / "wiki" / "queries" / "长回答.md"
            long_answer = "说明" * 120 + " [[wiki/sources/来源]]"
            wiki_tool.write_text(query, wiki_tool.frontmatter("长回答", "query", []) + f"# 长回答\n\n{long_answer}\n")
            wiki.rebuild_index()
            broken, _, _ = wiki.lint()
            self.assertEqual([], broken)


if __name__ == "__main__":
    unittest.main()
