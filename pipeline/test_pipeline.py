from __future__ import annotations

import os
import tempfile
import unittest
import urllib.robotparser
from pathlib import Path
from unittest.mock import patch

import collect
import deepseek
import promote
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


if __name__ == "__main__":
    unittest.main()
