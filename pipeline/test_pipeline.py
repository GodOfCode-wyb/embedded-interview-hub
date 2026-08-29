from __future__ import annotations

import os
import io
import json
import tempfile
import unittest
import urllib.error
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

    def test_json_parser_repairs_trailing_commas(self) -> None:
        result = deepseek.parse_json_content('```json\n{"questions": [{"id": "q1",}],}\n```')
        self.assertEqual(result["questions"][0]["id"], "q1")

    def test_api_401_is_reported_as_non_retryable_authentication_error(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.deepseek.com/chat/completions",
            401,
            "Authorization Required",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"Authentication Fails"}}'),
        )
        with patch.object(deepseek.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(deepseek.DeepSeekAuthenticationError):
                deepseek.call_api("bad-key", "https://api.deepseek.com", "model", "prompt")

    def test_structured_json_requests_disable_thinking_by_default(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "choices": [{
                        "finish_reason": "stop",
                        "message": {"content": '{"ok": true}'},
                    }],
                }).encode("utf-8")

        with patch.object(deepseek.urllib.request, "urlopen", return_value=FakeResponse()) as opener:
            result = deepseek.call_api(
                "key", "https://api.example.com", "model", "prompt"
            )

        request = opener.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, {"ok": True})
        self.assertEqual(payload["thinking"], {"type": "disabled"})


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
                    "generation_kind": "expanded",
                    "knowledge_basis": "由原文中的驱动同步知识点扩展。",
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
            self.assertEqual(questions[0]["generation_kind"], "expanded")
            self.assertIn("驱动同步", questions[0]["knowledge_basis"])
            self.assertEqual(review[0]["decision"], "staged")
            self.assertEqual(candidates[0]["status"], "promoted")


class LocalImportTests(unittest.TestCase):
    def test_progress_log_has_local_timestamp(self) -> None:
        output = io.StringIO()
        import_local.log("导入开始", file=output)
        self.assertRegex(
            output.getvalue(),
            r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] 导入开始\n$",
        )

    def test_api_key_input_removes_quotes_and_bearer_prefix(self) -> None:
        self.assertEqual(import_local.normalize_api_key('  "Bearer key-value"  '), "key-value")

    def test_local_api_key_can_be_saved_and_loaded_without_overriding_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env.local"
            path.write_text("DEEPSEEK_MODEL=test-model\n", encoding="utf-8")
            import_local.save_local_api_key("Bearer saved-key", path)
            values = {"DEEPSEEK_MODEL": "process-model"}
            import_local.load_local_env(path, values)
            self.assertEqual(values["DEEPSEEK_API_KEY"], "saved-key")
            self.assertEqual(values["DEEPSEEK_MODEL"], "process-model")
            self.assertNotIn("Bearer", path.read_text(encoding="utf-8"))

    def test_project_import_readme_is_not_treated_as_source(self) -> None:
        files = import_local.collect_input_files([])
        self.assertNotIn((ROOT / "imports" / "README.md").resolve(), files)

    def test_requested_outline_and_scenario_files_are_ignored(self) -> None:
        self.assertTrue(import_local.is_ignored_input_file(Path("index.md")))
        self.assertTrue(import_local.is_ignored_input_file(Path("04 嵌入式场景题（示例）.md")))
        self.assertFalse(import_local.is_ignored_input_file(Path("05bootloader.md")))

    def test_domain_spacing_variant_is_canonicalized(self) -> None:
        self.assertEqual(promote.canonical_domain("嵌入式AI"), "嵌入式 AI")

    def test_requested_outline_and_scenario_files_are_ignored(self) -> None:
        self.assertTrue(import_local.is_ignored_input_file(Path("index.md")))
        self.assertTrue(import_local.is_ignored_input_file(Path("04 嵌入式场景题（示例）.md")))
        self.assertFalse(import_local.is_ignored_input_file(Path("05bootloader.md")))

    def test_domain_spacing_variant_is_canonicalized(self) -> None:
        self.assertEqual(promote.canonical_domain("嵌入式AI"), "嵌入式 AI")

    def test_markdown_images_are_ignored_but_qa_text_is_preserved(self) -> None:
        source = (
            "问题：DMA 为什么能降低 CPU 负担？\n\n"
            "答案：外设和内存之间的数据搬运由 DMA 控制器完成。\n"
            "![时序图](img/dma.png)\n"
            '<img src="data:image/png;base64,AAAA" alt="截图">\n'
            "[diagram]: img/dma.webp\n"
        )
        cleaned = import_local.strip_markdown_images(source)
        self.assertIn("DMA 为什么能降低 CPU 负担", cleaned)
        self.assertIn("由 DMA 控制器完成", cleaned)
        self.assertNotIn("img/dma", cleaned)
        self.assertNotIn("data:image", cleaned)

    def test_chunks_long_local_notes_without_losing_text(self) -> None:
        text = "第一段问题。\n\n" + "第二段内容。" * 40
        chunks = import_local.chunk_text(text, limit=80)
        self.assertGreater(len(chunks), 1)
        self.assertIn("第一段问题", chunks[0])
        self.assertIn("第二段内容", "".join(chunks))

    def test_chunks_cap_dense_question_sections_without_losing_text(self) -> None:
        text = "\n\n".join(f"第 {index} 个问题？" for index in range(30))
        chunks = import_local.chunk_text(text, limit=8_000, question_mark_limit=10)
        self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))
        self.assertTrue(all(chunk.count("？") <= 10 for chunk in chunks))

    def test_output_retry_split_avoids_extremely_unbalanced_paragraphs(self) -> None:
        halves = import_local.split_text_balanced("A" * 2500 + "\n\n" + "B" * 100)
        self.assertIsNotNone(halves)
        left, right = halves
        self.assertGreater(min(len(left), len(right)), 900)

    def test_tiny_recursive_segment_is_not_split_again(self) -> None:
        self.assertIsNone(import_local.split_text_balanced("### IPC 怎么选？\n\n回答模板："))

    def test_tiny_segment_has_small_outline_limit(self) -> None:
        self.assertEqual(import_local.segment_outline_limit("### IPC 怎么选？", 60, 1), 3)
        self.assertEqual(import_local.segment_outline_limit("A" * 2_000, 60, 1), 60)

    def test_truncated_extraction_is_split_without_reducing_question_count(self) -> None:
        first = ValueError("DeepSeek 输出被截断（finish_reason=length）")
        left = {"questions": [{
            "title": "问题一？",
            "domain": "C 语言",
            "generation_kind": "source",
            "question_evidence": "原文问题一",
        }]}
        right = {"questions": [{
            "title": "问题二？",
            "domain": "操作系统",
            "generation_kind": "source",
            "question_evidence": "原文问题二",
        }]}
        source = "问题一？\n" + "A" * 300 + "\n\n问题二？\n" + "B" * 300
        with patch.object(import_local, "call_api", side_effect=[first, left, right]) as call:
            result = import_local.extract_segment(
                "1", 1, source, "source", ["绝不能输出的旧题"], 0, 60,
                "key", "https://api.example.com", "model", 1, 30,
            )
        self.assertEqual(call.call_count, 3)
        self.assertEqual(len(result["questions"]), 2)
        self.assertIn("绝不能输出的旧题", call.call_args_list[0].args[3])
        self.assertNotIn("绝不能输出的旧题", call.call_args_list[1].args[3])
        self.assertNotIn("绝不能输出的旧题", call.call_args_list[2].args[3])

    def test_recursive_extraction_resumes_successful_child(self) -> None:
        truncated = ValueError("DeepSeek 输出被截断（finish_reason=length）")
        interrupted = urllib.error.URLError("temporary network failure")
        left = {"questions": [{
            "title": "问题一？", "domain": "C 语言", "generation_kind": "source",
            "question_evidence": "原文问题一",
        }]}
        right = {"questions": [{
            "title": "问题二？", "domain": "操作系统", "generation_kind": "source",
            "question_evidence": "原文问题二",
        }]}
        source = "问题一？\n" + "A" * 300 + "\n\n问题二？\n" + "B" * 300
        segment_results: dict[str, dict] = {}
        split_segments: dict[str, bool] = {}
        saves = []

        with patch.object(import_local, "call_api", side_effect=[truncated, left, interrupted]) as first_call:
            with self.assertRaises(ValueError):
                import_local.extract_segment(
                    "1", 1, source, "source", [], 0, 60,
                    "key", "https://api.example.com", "model", 1, 30,
                    segment_results=segment_results,
                    split_segments=split_segments,
                    save_progress=lambda: saves.append(True),
                )
        self.assertEqual(first_call.call_count, 3)
        self.assertIn("1.1", segment_results)
        self.assertTrue(split_segments["1"])
        self.assertGreaterEqual(len(saves), 2)

        with patch.object(import_local, "call_api", return_value=right) as resumed_call:
            result = import_local.extract_segment(
                "1", 1, source, "source", [], 0, 60,
                "key", "https://api.example.com", "model", 1, 30,
                segment_results=segment_results,
                split_segments=split_segments,
                save_progress=lambda: saves.append(True),
            )
        self.assertEqual(resumed_call.call_count, 1)
        self.assertEqual(len(result["questions"]), 2)

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

    def test_large_docx_archive_is_allowed_when_document_xml_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "illustrated-interview.docx"
            document = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>STM32 中断优先级如何配置，FreeRTOS 临界区有什么边界？</w:t></w:r></w:p></w:body></w:document>'
            )
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("word/document.xml", document)
                archive.writestr("word/media/large.bin", b"0" * (import_local.MAX_TEXT_FILE_BYTES + 1))
            self.assertGreater(path.stat().st_size, import_local.MAX_TEXT_FILE_BYTES)
            self.assertIn("FreeRTOS", import_local.read_source_file(path))

    def test_import_prompt_marks_knowledge_expansion_as_inferred(self) -> None:
        prompt = import_local.build_prompt(
            "local-1", "原文知识点：volatile。", 1, 1, [], expanded_limit=1
        )
        self.assertIn("generation_kind=expanded", prompt)
        self.assertIn("不能臆造面试官真的问过", prompt)
        self.assertIn("题目纲要和对应的原文答案摘录", prompt)
        self.assertIn('"source_answer"', prompt)
        self.assertNotIn('"answer_detail"', prompt)

    def test_answer_prompt_reviews_and_reuses_source_answer(self) -> None:
        prompt = import_local.build_answer_prompt({
            "title": "volatile 能否保证线程安全吗？",
            "source_answer": "volatile 只约束特定访问的优化，不能提供互斥或原子性。",
        })
        self.assertIn("先审核题目纲要中的 source_answer", prompt)
        self.assertIn("不要为了改写而改写", prompt)
        self.assertIn('"ai_review"', prompt)

    def test_expanded_question_without_knowledge_basis_is_rejected(self) -> None:
        merged = import_local.merge_results([{
            "questions": [{"title": "扩展问题？", "generation_kind": "expanded"}],
        }])
        self.assertEqual(merged["questions"], [])

    def test_answer_normalization_keeps_outline_identity(self) -> None:
        outline = {
            "title": "中断上下文为什么不能睡眠？",
            "domain": "Linux 驱动",
            "subtopic": "中断上下文",
            "difficulty": "进阶",
            "generation_kind": "expanded",
            "knowledge_basis": "由原文中断知识点推导。",
            "question_evidence": "非原文直接问题。",
            "tags": ["中断"],
        }
        result = {"question": {
            "title": "模型擅自改写的标题",
            "ai_review": {"verdict": "expanded", "issues": ["缺少工程边界"], "summary": "保留原结论并补充调用上下文。"},
            "answer_short": "先判断当前执行上下文是否允许调度和阻塞，再选择明确不会睡眠的同步、内存分配及延迟处理接口，并检查完整调用链。",
            "answer_detail": "中断上下文没有普通进程可供阻塞后恢复的调度语义。" * 30,
            "follow_ups": [
                {"title": "哪些接口可能睡眠？", "answer_short": "检查分配标志和锁类型。", "answer_detail": "结合调用链和内核文档确认。" * 20},
                {"title": "如何排查睡眠告警？", "answer_short": "查看堆栈和上下文标志。", "answer_detail": "使用调试配置定位调用路径。" * 20},
            ],
            "pitfalls": [{
                "title": "只看函数名判断",
                "explanation": "封装层可能隐藏会睡眠的调用。",
                "correction": "沿完整调用链检查上下文要求。",
            }],
            "tags": ["IRQ"],
        }}
        normalized = import_local.normalize_answered_question(outline, result)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized["title"], outline["title"])
        self.assertEqual(normalized["generation_kind"], "expanded")
        self.assertEqual(normalized["ai_review"]["verdict"], "expanded")

    def test_answer_retry_increases_output_allowance(self) -> None:
        outline = {
            "title": "中断上下文为什么不能睡眠？",
            "domain": "Linux 驱动",
            "subtopic": "中断上下文",
            "difficulty": "进阶",
            "generation_kind": "source",
            "question_evidence": "原文问题。",
            "tags": ["中断"],
        }
        draft = {"question": {
            "ai_review": {"verdict": "corrected", "issues": ["原答案缺少上下文"], "summary": "纠正并补充中断上下文限制。"},
            "answer_short": "需要先识别当前执行上下文是否允许阻塞与调度，再沿完整调用链选择不会导致睡眠的接口、内存分配标志和同步原语。",
            "answer_detail": "中断上下文不具备普通进程阻塞后恢复的调度语义。" * 30,
            "follow_ups": [
                {"title": "哪些接口可能睡眠？", "answer_short": "检查锁、分配和等待接口。", "answer_detail": "沿完整调用链检查上下文约束。" * 20},
                {"title": "如何排查？", "answer_short": "查看告警和调用栈。", "answer_detail": "启用调试配置并定位调用路径。" * 20},
            ],
            "pitfalls": [{
                "title": "只检查当前函数",
                "explanation": "下层封装仍可能睡眠。",
                "correction": "检查完整调用链。",
            }],
            "tags": ["IRQ"],
        }}
        with patch.object(
            import_local,
            "call_api",
            side_effect=[ValueError("finish_reason=length"), draft],
        ) as call:
            _, question, error = import_local.request_answer(
                1, 1, outline, "key", "https://api.example.com", "model", 2, 45
            )

        self.assertIsNone(error)
        self.assertIsNotNone(question)
        self.assertEqual(call.call_args_list[0].kwargs["max_tokens"], 8000)
        self.assertEqual(call.call_args_list[1].kwargs["max_tokens"], 12000)


class AnswerRefinementTests(unittest.TestCase):
    def test_legacy_string_followups_require_refinement(self) -> None:
        question = {
            "answer_version": 2,
            "answer_detail": "足够长" * 200,
            "follow_ups": ["为什么？"],
            "pitfalls": ["误区"],
        }
        self.assertTrue(refine_answers.needs_refinement(question))

    def test_shallow_structured_followups_require_refinement(self) -> None:
        question = {
            "answer_version": 2,
            "answer_short": "先给出足够明确的结论和判断条件。" * 4,
            "answer_detail": "主答案具有足够长度和工程背景。" * 40,
            "ai_review": {"verdict": "accepted", "issues": [], "summary": "现有内容准确。"},
            "follow_ups": [{
                "title": "为什么？",
                "answer_short": "过短",
                "answer_detail": "仍然过短",
            }] * 3,
            "pitfalls": [{
                "title": "误区",
                "explanation": "错误原因和失效上下文。" * 5,
                "correction": "正确方法和排查步骤。" * 5,
            }] * 2,
        }
        self.assertIn("follow_up_detail", refine_answers.quality_issues(question))
        self.assertTrue(refine_answers.needs_refinement(question))

    def test_applies_complete_structured_refinement(self) -> None:
        question = {"id": "q1", "status": "verified"}
        draft = {
            "id": "q1",
            "ai_review": {"verdict": "expanded", "issues": ["追问深度不足"], "summary": "保留主结论并扩展追问机制与边界。"},
            "answer_short": "先判断调用上下文是否允许睡眠，再根据临界区长度、竞争程度、实时性要求、持锁路径和优先级反转风险选择同步原语。" * 2,
            "answer_detail": "详细说明底层机制、调用上下文、工程约束、实现步骤、平台边界和排查方法。" * 50,
            "follow_ups": [
                {"title": "中断上下文如何同步？", "answer_short": "使用适合原子上下文且不会引起调度睡眠的同步机制，并控制临界区长度。" * 2, "answer_detail": "结合中断状态、锁粒度、实时性和完整调用链分析同步边界。" * 20},
                {"title": "何时使用互斥锁？", "answer_short": "允许睡眠且临界区较长时考虑，并评估竞争、持锁路径和优先级反转。" * 2, "answer_detail": "还要结合调度上下文、优先级继承支持和错误恢复路径进行判断。" * 20},
                {"title": "如何定位锁竞争？", "answer_short": "结合跟踪、统计和调用栈确认竞争位置、持续时间及调度影响。" * 2, "answer_detail": "使用平台可用的跟踪工具记录持锁时间、等待者和上下文，再逐步缩小锁粒度。" * 20},
            ],
            "pitfalls": [
                {
                    "title": "所有场景都用自旋锁",
                    "explanation": "长临界区会持续占用 CPU，并放大中断延迟和实时性抖动。" * 2,
                    "correction": "按上下文是否允许睡眠、临界区长度和竞争程度选择同步原语。" * 2,
                },
                {
                    "title": "只检查当前函数",
                    "explanation": "下层封装仍可能获取其他锁或进入睡眠，形成隐藏的上下文违规。" * 2,
                    "correction": "沿完整调用链检查锁顺序、睡眠点和异常退出路径。" * 2,
                },
            ],
        }
        self.assertTrue(refine_answers.apply_refinement(question, draft, "test-model", "2026-08-24"))
        self.assertEqual(question["answer_version"], 2)
        self.assertEqual(question["status"], "ai-draft")
        self.assertIsInstance(question["follow_ups"][0], dict)
        self.assertEqual(question["ai_review"]["verdict"], "expanded")

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

    def test_retry_prompt_is_more_compact(self) -> None:
        regular = refine_answers.build_prompt([{"id": "q1", "title": "测试"}])
        compact = refine_answers.build_prompt([{"id": "q1", "title": "测试"}], compact=True)
        self.assertIn("主详解 450 至 1000 字", regular)
        self.assertIn("失败后的压缩重试", compact)
        self.assertIn("准确且深度、宽度足够的部分应继续使用", regular)

    def test_legacy_followups_are_prioritized_before_audit_only_items(self) -> None:
        legacy = {
            "answer_version": 2,
            "answer_short": "结论和判断条件。" * 10,
            "answer_detail": "主答案。" * 100,
            "follow_ups": ["为什么？"],
            "pitfalls": ["误区"],
        }
        audit_only = {
            "answer_version": 2,
            "answer_short": "结论和判断条件。" * 10,
            "answer_detail": "主答案。" * 100,
            "follow_ups": [{"title": "追问", "answer_short": "简答。" * 20, "answer_detail": "详解。" * 50}] * 3,
            "pitfalls": [{"title": "误区", "explanation": "原因。" * 20, "correction": "做法。" * 20}] * 2,
        }
        self.assertLess(
            refine_answers.refinement_priority(legacy),
            refine_answers.refinement_priority(audit_only),
        )


if __name__ == "__main__":
    unittest.main()
