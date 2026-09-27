import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from brief_page import render_html
from progress_server import (
    UserInputError,
    build_openai_payload,
    extract_output_text,
    load_entries,
    save_entry,
    validate_parsed,
)


SAMPLE = {
    "summary": "完成英语任务并安排小组资料",
    "completed": [{
        "title": "完成英语慕课前两单元",
        "course": "大学英语",
        "completed_at": "今天",
        "evidence": "用户明确说已做完",
        "notes": "",
    }],
    "tasks": [{
        "title": "向组长发送资料",
        "course": "中国近现代史纲要",
        "due_date": "下周三前",
        "status": "todo",
        "next_action": "查找资料并整理",
        "source": "用户输入",
    }],
    "notes": ["论文读到一半"],
}


class ProgressServerTests(unittest.TestCase):
    def test_openai_payload_uses_strict_schema_and_no_storage(self):
        payload = build_openai_payload("英语慕课做完了", "gpt-5-mini")
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual("json_schema", payload["text"]["format"]["type"])
        self.assertNotIn("api_key", json.dumps(payload))

    def test_extract_and_validate_structured_output(self):
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(SAMPLE, ensure_ascii=False)}]}]}
        parsed = json.loads(extract_output_text(response))
        self.assertEqual(SAMPLE, validate_parsed(parsed))

    def test_rejects_unapproved_shape(self):
        malformed = {**SAMPLE, "unexpected": "field"}
        # Root extras are removed by the explicit allow-list; nested extras are rejected.
        self.assertEqual(SAMPLE, validate_parsed(malformed))
        nested = json.loads(json.dumps(SAMPLE, ensure_ascii=False))
        nested["tasks"][0]["secret"] = "no"
        with self.assertRaises(UserInputError):
            validate_parsed(nested)

    def test_save_is_local_bounded_and_rendered_safely(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "progress-log.json"
            entries = save_entry("<script>alert(1)</script>", SAMPLE, path)
            self.assertEqual(1, len(entries))
            self.assertEqual(entries, load_entries(path))
            page = render_html({"actionItems": [], "sourceWarnings": [], "summary": {}}, {}, entries)
            self.assertIn("最近进展", page)
            self.assertIn("完成英语慕课前两单元", page)
            self.assertNotIn("<script>alert(1)</script>", page)


if __name__ == "__main__":
    unittest.main()
