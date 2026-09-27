"""Local-only web server for GPT-assisted progress capture.

The browser never receives the OpenAI API key. It sends raw progress text to
this localhost server, receives a structured draft for review, and only writes
the draft after an explicit second request.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import uuid
import webbrowser
from datetime import date, datetime, timezone, timedelta
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from secretary_brief import write_brief

ROOT = Path(__file__).resolve().parent
PROGRESS_PATH = ROOT / "progress-log.json"
TZ = timezone(timedelta(hours=8))
DEFAULT_MODEL = "gpt-5-mini"
MAX_BODY_BYTES = 24_000
MAX_TEXT_CHARS = 6_000
MAX_ENTRIES = 200

PROGRESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "completed": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "course": {"type": "string"},
                    "completed_at": {"type": "string"},
                    "evidence": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "required": ["title", "course", "completed_at", "evidence", "notes"],
            },
        },
        "tasks": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string"},
                    "course": {"type": "string"},
                    "due_date": {"type": "string"},
                    "status": {"type": "string", "enum": ["todo", "waiting"]},
                    "next_action": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["title", "course", "due_date", "status", "next_action", "source"],
            },
        },
        "notes": {"type": "array", "maxItems": 20, "items": {"type": "string"}},
    },
    "required": ["summary", "completed", "tasks", "notes"],
}


class UserInputError(ValueError):
    pass


class OpenAIServiceError(RuntimeError):
    pass


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def course_names():
    context = read_json(ROOT / "study-context.json", {})
    return sorted({str(row.get("name", "")).strip() for row in context.get("courses", []) if row.get("name")})


def validate_parsed(value):
    if not isinstance(value, dict):
        raise UserInputError("GPT 草稿格式不正确")
    summary = value.get("summary")
    completed = value.get("completed")
    tasks = value.get("tasks")
    notes = value.get("notes")
    if not isinstance(summary, str) or not summary.strip():
        raise UserInputError("草稿缺少摘要")
    if not all(isinstance(group, list) for group in (completed, tasks, notes)):
        raise UserInputError("草稿列表格式不正确")
    if len(completed) > 20 or len(tasks) > 20 or len(notes) > 20:
        raise UserInputError("一次最多保存 20 条同类记录")
    completed_fields = {"title", "course", "completed_at", "evidence", "notes"}
    task_fields = {"title", "course", "due_date", "status", "next_action", "source"}
    for item in completed:
        if not isinstance(item, dict) or set(item) != completed_fields or not all(isinstance(item[key], str) for key in completed_fields):
            raise UserInputError("已完成事项格式不正确")
    for item in tasks:
        if not isinstance(item, dict) or set(item) != task_fields or not all(isinstance(item[key], str) for key in task_fields):
            raise UserInputError("下一步事项格式不正确")
        if item["status"] not in {"todo", "waiting"}:
            raise UserInputError("任务状态不正确")
    if not all(isinstance(item, str) for item in notes):
        raise UserInputError("备注格式不正确")
    return {
        "summary": summary.strip()[:500],
        "completed": completed,
        "tasks": tasks,
        "notes": notes,
    }


def build_openai_payload(raw_text: str, model: str):
    known_courses = "、".join(course_names()) or "未读取到课程表"
    instructions = (
        "你是一个严谨的个人学业进展整理助手。只提取用户明确说出的事实，不猜测完成状态、日期、成绩或截止日。"
        "区分已经完成的事项和下一步任务；信息缺失时使用空字符串。相对日期只有在语义明确时才结合今天换算，"
        "否则保留用户原话。不要把情绪、愿望或含糊计划写成已经完成。summary 用一句简洁中文。"
    )
    user_text = (
        f"今天是 {date.today().isoformat()}（中国标准时间）。\n"
        f"已知课程名：{known_courses}\n\n"
        f"用户本次进展：\n{raw_text}"
    )
    return {
        "model": model,
        "store": False,
        "instructions": instructions,
        "input": user_text,
        "max_output_tokens": 1800,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "progress_update",
                "strict": True,
                "schema": PROGRESS_SCHEMA,
            }
        },
    }


def extract_output_text(response):
    if response.get("status") == "incomplete":
        reason = (response.get("incomplete_details") or {}).get("reason", "未知原因")
        raise OpenAIServiceError(f"GPT 输出未完成：{reason}")
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise OpenAIServiceError(content.get("refusal") or "GPT 拒绝处理这段内容")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise OpenAIServiceError("GPT 没有返回可读取的结构化内容")


def parse_with_openai(raw_text: str, api_key: str, model: str):
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(build_openai_payload(raw_text, model), ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            detail = json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = ""
        raise OpenAIServiceError(detail or f"OpenAI 服务返回 {error.code}") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise OpenAIServiceError(f"无法连接 OpenAI：{error}") from error
    try:
        parsed = json.loads(extract_output_text(payload))
    except json.JSONDecodeError as error:
        raise OpenAIServiceError("GPT 返回的结构化内容无法解析") from error
    return validate_parsed(parsed)


def load_entries(path: Path = PROGRESS_PATH):
    data = read_json(path, {"version": 1, "entries": []})
    entries = data.get("entries", []) if isinstance(data, dict) else []
    return entries if isinstance(entries, list) else []


def save_entry(raw_input: str, parsed, path: Path = PROGRESS_PATH):
    raw_input = str(raw_input or "").strip()
    if not raw_input:
        raise UserInputError("原始进展不能为空")
    if len(raw_input) > MAX_TEXT_CHARS:
        raise UserInputError(f"一次最多输入 {MAX_TEXT_CHARS} 个字符")
    clean = validate_parsed(parsed)
    entry = {
        "id": str(uuid.uuid4()),
        "savedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "rawInput": raw_input,
        **clean,
    }
    entries = [entry, *load_entries(path)][:MAX_ENTRIES]
    payload = {"version": 1, "entries": entries}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return entries


class ProgressHandler(SimpleHTTPRequestHandler):
    server_version = "SCURadar/1.0"

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise UserInputError("请求长度不正确") from error
        if length <= 0 or length > MAX_BODY_BYTES:
            raise UserInputError("请求为空或过大")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise UserInputError("请求不是有效 JSON") from error
        if not isinstance(value, dict):
            raise UserInputError("请求格式不正确")
        return value

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/api/progress":
            model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
            return self.send_json(HTTPStatus.OK, {
                "gptConfigured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
                "model": model,
                "entries": load_entries()[:20],
            })
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self.read_json_body()
            if path == "/api/progress/parse":
                raw_text = str(body.get("text") or "").strip()
                if not raw_text:
                    raise UserInputError("请先输入本次进展")
                if len(raw_text) > MAX_TEXT_CHARS:
                    raise UserInputError(f"一次最多输入 {MAX_TEXT_CHARS} 个字符")
                api_key = os.environ.get("OPENAI_API_KEY", "").strip()
                if not api_key:
                    return self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "尚未设置 OPENAI_API_KEY，请先按 GPT_SETUP.md 配置"})
                model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
                return self.send_json(HTTPStatus.OK, parse_with_openai(raw_text, api_key, model))
            if path == "/api/progress":
                entries = save_entry(body.get("rawInput"), body.get("parsed"))
                write_brief()
                return self.send_json(HTTPStatus.CREATED, {"entries": entries[:20]})
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except UserInputError as error:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except OpenAIServiceError as error:
            return self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
        except Exception:
            # Keep local paths, credentials and Python internals out of the browser.
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "本地服务处理失败，请查看启动窗口"})

    def log_message(self, format, *args):
        # Do not log request bodies or Authorization headers.
        super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description="启动川大雷达本地 GPT 进展服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SCU_RADAR_PORT", "8767")))
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    handler = partial(ProgressHandler, directory=str(ROOT))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/index.html"
    print(f"川大雷达已启动：{url}")
    print("关闭此窗口即可停止本地服务。API 密钥不会发送给浏览器。")
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
