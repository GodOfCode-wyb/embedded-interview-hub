from __future__ import annotations

import os
import tempfile
import unittest
import urllib.robotparser
import zipfile
from pathlib import Path
from unittest.mock import patch

import collect
import deepseek
import discover
import import_local
import promote
import refine_answers
from common import ROOT, read_json, write_json


class CollectorScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = read_json(ROOT / "config" / "sources.json", {}) or {}

    def test_real_interview_page_is_prioritized(self) -> None:
        item = {
            "title": "Linux 驱动开发一面面经：中断和设备树面试题",
            "summary": "嵌入式软件面试官追问字符设备、互斥锁和自旋锁。",
            "url": "https://www.nowcoder.com/discuss/example",
        }
        score, kind, status, signals = collect.score_candidate(item, self.config)
        self.assertGreaterEqual(score, self.config["minimum_interview_score"])
        self.assertEqual(kind, "interview")
        self.assertEqual(status, "discovered")
        self.assertTrue(any(value.startswith("interview:") for value in signals))

    def test_official_documentation_is_reference_only(self) -> None:
        item = {
            "title": "FreeRTOS Documentation",
            "summary": "Official RTOS API reference guide and getting started documentation.",
            "url": "https://www.freertos.org/Documentation/00-Overview",
        }
        _, kind, status, _ = collect.score_candidate(item, self.config)
        self.assertEqual(kind, "reference")
        self.assertEqual(status, "reference-only")

    def test_github_embedded_interview_repository_is_prioritized(self) -> None:
        item = {
            "title": "example/embedded-interview-notes",
            "summary": "Embedded Linux driver interview questions and RTOS notes.",
            "url": "https://github.com/example/embedded-interview-notes",
        }
        _, kind, status, _ = collect.score_candidate(item, self.config)
        self.assertEqual(kind, "interview")
        self.assertEqual(status, "discovered")

    def test_public_technical_qa_is_prioritized_as_bagu_source(self) -> None:
        item = {
            "title": "Why must volatile be used for a memory mapped register?",
            "summary": "公开技术问答，面试八股参考：C 指针内存技术问答；标签 c embedded volatile",
            "url": "https://stackoverflow.com/questions/123/example",
        }
        _, kind, status, _ = collect.score_candidate(item, self.config)
        self.assertEqual(kind, "interview")
        self.assertEqual(status, "discovered")

    def test_excluded_specialty_is_rejected(self) -> None:
        item = {
            "title": "FPGA 嵌入式开发面经",
            "summary": "技术面试题整理",
            "url": "https://blog.csdn.net/example/article/details/1",
        }
        _, kind, status, _ = collect.score_candidate(item, self.config)
        self.assertEqual(kind, "excluded")
        self.assertEqual(status, "out-of-scope")


class PageExtractionTests(unittest.TestCase):
    def test_visible_text_excludes_scripts(self) -> None:
        html = "<html><script>alert('x')</script><article><h1>Linux 驱动面试</h1><p>中断上半部和下半部有什么区别？</p></article></html>"
        text = deepseek.extract_visible_text(html, 500)
        self.assertIn("中断上半部和下半部", text)
        self.assertNotIn("alert", text)

    def test_robots_policy_is_respected(self) -> None:
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /private"])
        with patch.dict(deepseek.ROBOTS_CACHE, {"https://example.com": parser}, clear=True):
            self.assertFalse(deepseek.robots_allowed("https://example.com/private/article"))
            self.assertTrue(deepseek.robots_allowed("https://example.com/public/article"))

    def test_updated_source_is_enriched_again(self) -> None:
        candidate = {"provider": "github-search", "published_at": "2026-08-23T12:00:00+00:00"}
        previous = {
            "source_published_at": "2026-08-20T12:00:00+00:00",
            "generated_at": "2026-08-20T12:00:00+00:00",
            "review_status": "ai-draft",
        }
        self.assertTrue(deepseek.needs_enrichment(candidate, previous, 30))

    def test_recent_unchanged_source_is_not_repeated(self) -> None:
        candidate = {"provider": "github-search", "published_at": "2026-08-23T12:00:00+00:00"}
        previous = {
            "source_published_at": "2026-08-23T12:00:00+00:00",
            "generated_at": "2999-08-23T12:00:00+00:00",
            "review_status": "ai-draft",
        }
        self.assertFalse(deepseek.needs_enrichment(candidate, previous, 30))


class LinkDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = read_json(ROOT / "config" / "sources.json", {}) or {}
        cls.allowed = {value.lower() for value in cls.config.get("allowed_result_domains", [])}

    def test_parses_public_article_link(self) -> None:
        links = discover.parse_links(
            '<nav><a href="/login">登录</a></nav>'
            '<article><a href="/post/linux-driver-interview">Linux 驱动面试题</a></article>'
        )
        self.assertEqual(len(links), 2)
        self.assertEqual(links[1]["anchor"], "Linux 驱动面试题")

    def test_rejects_login_and_unapproved_domains(self) -> None:
        self.assertIsNone(discover.safe_public_link("https://juejin.cn/post/1", "/login", self.allowed))
        self.assertIsNone(discover.safe_public_link("https://juejin.cn/post/1", "https://example.com/a", self.allowed))

    def test_accepts_relevant_related_link(self) -> None:
        seed = {"title": "Linux 驱动开发面经", "summary": "嵌入式驱动", "provider": "bing-rss"}
        link = {"anchor": "字符设备与中断面试题", "url": "https://juejin.cn/post/linux-driver"}
        self.assertTrue(discover.link_is_relevant(link, seed, self.config))


class PromotionPolicyTests(unittest.TestCase):
    def test_valid_ai_draft_can_be_staged(self) -> None:
        item = {
            "source_url": "https://www.nowcoder.com/discuss/example",
            "source_title": "Linux 驱动面经",
            "recommendation": "new-draft",
            "decision": "pending",
            "duplicate_score": 0.2,
            "question": {
                "title": "自旋锁和互斥锁在驱动中如何选择？",
                "domain": "Linux 驱动",
                "question_evidence": "来源明确记录面试官询问两种锁的选择。",
                "answer_short": "自旋锁适合短临界区和不可睡眠上下文。",
            },
        }
        self.assertTrue(promote.is_publishable(item))

    def test_draft_without_source_evidence_is_not_staged(self) -> None:
        item = {
            "source_url": "https://www.nowcoder.com/discuss/example",
            "source_title": "Linux 驱动面经",
            "recommendation": "new-draft",
            "decision": "pending",
            "duplicate_score": 0.2,
            "question": {
                "title": "什么是中断？",
                "domain": "Linux 驱动",
                "answer_short": "中断是异步事件通知机制。",
            },
        }
        self.assertFalse(promote.is_publishable(item))

    def test_local_import_with_evidence_can_be_staged(self) -> None:
        item = {
            "source_url": "local://candidate-example",
            "source_title": "本地导入面经",
            "candidate_provider": "local-import",
            "recommendation": "new-draft",
            "decision": "pending",
            "duplicate_score": 0.1,
            "question": {
                "title": "Linux 驱动中为什么不能在中断上下文睡眠？",
                "domain": "Linux 驱动",
                "question_evidence": "本地面经明确记录了该追问。",
                "answer_short": "中断上下文没有可供调度恢复的普通进程语义。",
            },
        }
        self.assertTrue(promote.is_publishable(item))

    def test_structured_follow_up_and_pitfall_are_preserved(self) -> None:
        follow_ups = promote.follow_up_list([{
            "title": "中断上下文可以用互斥锁吗？",
            "answer_short": "不能使用可能睡眠的普通互斥锁。",
            "answer_detail": "中断上下文不能主动调度睡眠，应选择适合上下文的同步原语。",
        }])
        pitfalls = promote.pitfall_list([{
            "title": "任何临界区都使用自旋锁",
            "explanation": "长时间自旋会浪费 CPU 并增加中断延迟。",
            "correction": "根据上下文是否允许睡眠和临界区长度选择锁。",
        }])
        self.assertIsInstance(follow_ups[0], dict)
        self.assertIsInstance(pitfalls[0], dict)

    def test_main_stages_review_into_formal_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            content = Path(temp_dir) / "content"
            inbox = content / "inbox"
            write_json(content / "questions.json", [])
            write_json(content / "sources.json", [])
            write_json(content / "experiences.json", [])
            write_json(content / "updates.json", [])
            write_json(inbox / "candidates.json", [{"id": "candidate-1", "status": "discovered"}])
            write_json(inbox / "review.json", [{
                "review_id": "review-1",
                "candidate_id": "candidate-1",
                "source_url": "https://www.nowcoder.com/discuss/example",
                "source_title": "Linux 驱动面经",
                "recommendation": "new-draft",
                "decision": "pending",
                "duplicate_score": 0.2,
                "experience": {},
                "question": {
                    "title": "自旋锁和互斥锁在驱动中如何选择？",
                    "domain": "Linux 驱动",
                    "subtopic": "并发控制",
                    "difficulty": "进阶",
                    "question_evidence": "来源明确记录了锁选择这一问题。",
                    "answer_short": "根据上下文是否允许睡眠和临界区长度选择。",
                    "answer_detail": "自旋锁用于短临界区或不可睡眠上下文，互斥锁用于允许睡眠的进程上下文。",
                    "follow_ups": ["中断上下文能否使用互斥锁？"],
                    "pitfalls": ["忽略上下文是否允许睡眠。"],
                    "tags": ["锁"],
                },
            }])

            with (
                patch.object(promote, "CONTENT", content),
                patch.object(promote, "INBOX", inbox),
                patch.dict(os.environ, {"MAX_STAGE_QUESTIONS": "12"}),
            ):
                self.assertEqual(promote.main(), 0)

            questions = read_json(content / "questions.json", [])
            review = read_json(inbox / "review.json", [])
            candidates = read_json(inbox / "candidates.json", [])
            self.assertEqual(len(questions), 1)
            self.assertEqual(questions[0]["status"], "ai-draft")
            self.assertEqual(review[0]["decision"], "staged")
            self.assertEqual(candidates[0]["status"], "promoted")


class LocalImportTests(unittest.TestCase):
    def test_chunks_long_local_notes_without_losing_text(self) -> None:
        text = "第一段问题。\n\n" + "第二段内容。" * 40
        chunks = import_local.chunk_text(text, limit=80)
        self.assertGreater(len(chunks), 1)
        self.assertIn("第一段问题", chunks[0])
        self.assertIn("第二段内容", "".join(chunks))

    def test_reads_docx_with_standard_library(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "interview.docx"
            document = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>Linux 驱动面试问题：中断上下半部有什么区别，如何选择同步机制？</w:t></w:r></w:p></w:body></w:document>'
            )
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document)
            self.assertIn("Linux 驱动面试问题", import_local.read_source_file(path))


class AnswerRefinementTests(unittest.TestCase):
    def test_legacy_string_followups_require_refinement(self) -> None:
        question = {
            "answer_version": 2,
            "answer_detail": "足够长" * 200,
            "follow_ups": ["为什么？"],
            "pitfalls": ["误区"],
        }
        self.assertTrue(refine_answers.needs_refinement(question))

    def test_applies_complete_structured_refinement(self) -> None:
        question = {"id": "q1", "status": "verified"}
        draft = {
            "id": "q1",
            "answer_short": "先判断调用上下文是否允许睡眠，再根据临界区长度、竞争程度和实时性要求选择同步原语。",
            "answer_detail": "详细机制与工程约束。" * 40,
            "follow_ups": [
                {"title": "中断上下文如何同步？", "answer_short": "使用适合原子上下文的机制。", "answer_detail": "结合中断状态和锁粒度分析。" * 20},
                {"title": "何时使用互斥锁？", "answer_short": "允许睡眠且临界区较长时考虑。", "answer_detail": "还要评估优先级反转和持锁路径。" * 20},
            ],
            "pitfalls": [{
                "title": "所有场景都用自旋锁",
                "explanation": "长临界区会持续占用 CPU。",
                "correction": "按上下文和临界区特性选择同步原语。",
            }],
        }
        self.assertTrue(refine_answers.apply_refinement(question, draft, "test-model", "2026-08-24"))
        self.assertEqual(question["answer_version"], 2)
        self.assertEqual(question["status"], "ai-draft")
        self.assertIsInstance(question["follow_ups"][0], dict)

    def test_refinement_request_uses_bounded_timeout(self) -> None:
        with patch.object(refine_answers, "call_api", return_value={"questions": []}) as call:
            result, error = refine_answers.request_refinement(
                1,
                1,
                [{"id": "q1", "title": "测试问题"}],
                "key",
                "https://api.example.com",
                "model",
                attempts=1,
                timeout_seconds=45,
            )
        self.assertEqual(result, {"questions": []})
        self.assertIsNone(error)
        self.assertEqual(call.call_args.kwargs["timeout_seconds"], 45)


if __name__ == "__main__":
    unittest.main()
