import io
import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

from backend import ai


class FakeResponse(io.BytesIO):
    headers = {"Content-Type": "text/event-stream"}


class AIAdaptersTest(unittest.TestCase):
    def test_provider_status_uses_configured_key_environment(self):
        with patch.dict(os.environ, {"CUSTOM_WENCHENG_KEY": "test-only"}, clear=True):
            self.assertFalse(ai.providers_status()[-1]["available"])
            self.assertTrue(ai.providers_status({"api_key_env": "CUSTOM_WENCHENG_KEY"})[-1]["available"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}, clear=True):
            self.assertTrue(ai.providers_status({"api_key_env": ""})[-1]["available"])
            self.assertFalse(ai.providers_status({"api_key_env": "CUSTOM_WENCHENG_KEY"})[-1]["available"])

    def test_rewrite_preserves_only_structured_fields(self):
        with patch.object(ai, "_chunks", return_value=iter(['{"replacement":"研究结果仍不确定[2]。","reason":"删除冗余开场。"}'])):
            result = ai.rewrite("值得注意的是，研究结果仍不确定[2]。", "简洁表达", "", {}, {})
        self.assertEqual(result["replacement"], "研究结果仍不确定[2]。")

    def test_invalid_result_and_structural_rewrite_rejected(self):
        for output in ("不是JSON", '{"replacement":null}', '{"replacement":"第一段\\n第二段"}'):
            with self.subTest(output=output), patch.object(ai, "_chunks", return_value=iter([output])):
                with self.assertRaises(ai.AIError):
                    ai.rewrite("原文", "改写", "", {}, {})

    def test_paragraphs_split_across_stream_events(self):
        self.assertEqual(list(ai._paragraphs(iter(["第一", "段。\n", "\n第二段。\n\n", "第三段。"]))), ["第一段。", "第二段。", "第三段。"])

    def test_codex_generation_is_paragraph_by_paragraph(self):
        responses = [iter(['{"paragraphs":["背景","结果"]}']), iter(["研究背景。"]), iter(["研究结果。"])]
        with patch.object(ai, "_chunks", side_effect=responses) as mocked:
            result = ai.generate("写两段", {}, {"provider": "codex"})
            self.assertEqual(next(result), "研究背景。")
            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(next(result), "研究结果。")
            self.assertEqual(list(result), [])

    def test_api_sse_and_auth_header(self):
        raw = b'data: {"choices":[{"delta":{"content":"First."}}]}\n\ndata: {"choices":[{"delta":{"content":"\\n\\nSecond."}}]}\n\ndata: [DONE]\n'
        with patch.dict(os.environ, {"TEST_WENCHENG_KEY": "test-only"}), patch.object(ai.urllib.request, "urlopen", return_value=FakeResponse(raw)) as open_mock:
            result = list(ai.generate("Write", {}, {"provider": "openai", "model": "configured-model", "api_key_env": "TEST_WENCHENG_KEY"}))
        self.assertEqual(result, ["First.", "Second."])
        request = open_mock.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only")
        self.assertNotIn("test-only", request.full_url)

    def test_api_key_missing_is_actionable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ai.AIError, "OPENAI_API_KEY"):
                list(ai._api_chunks([], {"model": "configured-model"}))

    def test_cli_codex_events_with_real_local_process(self):
        script = 'import json,sys; p=sys.stdin.read(); print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"edited"}}))'
        with patch.object(ai, "_cli_command", return_value=[sys.executable, "-c", script]):
            self.assertEqual(list(ai._cli_chunks("Input", {"provider": "codex"})), ["edited"])

    def test_claude_deltas_are_not_duplicated_by_final_message(self):
        events = [
            {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "正文"}}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "正文"}]}},
            {"type": "result", "result": "正文", "is_error": False},
        ]
        script = "import sys; sys.stdin.read(); " + "; ".join("print(" + repr(json.dumps(e)) + ")" for e in events)
        with patch.object(ai, "_cli_command", return_value=[sys.executable, "-c", script]):
            self.assertEqual(list(ai._cli_chunks("Input", {"provider": "claude"})), ["正文"])

    def test_cli_error_does_not_become_generated_prose(self):
        script = 'import sys; sys.stdin.read(); print(\'{"type":"result","is_error":true,"result":"Please log in"}\')'
        with patch.object(ai, "_cli_command", return_value=[sys.executable, "-c", script]):
            with self.assertRaisesRegex(ai.AIError, "Please log in"):
                list(ai._cli_chunks("Input", {"provider": "claude"}))

    def test_cancel_stops_local_process(self):
        event = threading.Event()
        timer = threading.Timer(.2, event.set)
        script = "import sys,time; sys.stdin.read(); time.sleep(30)"
        start = time.monotonic()
        timer.start()
        try:
            with patch.object(ai, "_cli_command", return_value=[sys.executable, "-c", script]):
                with self.assertRaises(ai.Cancelled):
                    list(ai._cli_chunks("Input", {"provider": "codex"}, event))
            self.assertLess(time.monotonic() - start, 4)
        finally:
            timer.cancel()

    def test_cli_commands_do_not_enable_tools_or_reuse_chat(self):
        with patch.object(ai.shutil, "which", side_effect=lambda name: name):
            codex = ai._cli_command("codex", {})
            claude = ai._cli_command("claude", {})
        self.assertIn("read-only", codex)
        self.assertIn("--ignore-user-config", codex)
        self.assertIn("--disable", codex)
        self.assertEqual(claude[claude.index("--tools") + 1], "")
        self.assertNotIn("--continue", claude)
        self.assertNotIn("resume", codex)

    def test_cancel_while_child_has_not_read_large_prompt(self):
        event = threading.Event()
        timer = threading.Timer(.2, event.set)
        timer.start()
        started = time.monotonic()
        try:
            with patch.object(ai, "_cli_command", return_value=[sys.executable, "-c", "import time; time.sleep(30)"]):
                with self.assertRaises(ai.Cancelled):
                    list(ai._cli_chunks("x" * 2_000_000, {"provider": "codex"}, event))
            self.assertLess(time.monotonic() - started, 4)
        finally:
            timer.cancel()


if __name__ == "__main__":
    unittest.main()
