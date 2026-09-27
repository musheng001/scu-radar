"""Collect the public competition-platform catalogue without logging in.

The platform exposes a public notice endpoint used by its own homepage:
``/prod-api/home/notice/list``.  This adapter deliberately collects catalogue
metadata only.  It does not send an Authorization header, call sign-up APIs,
or attempt to infer eligibility/deadlines from the catalogue.  Detail pages
remain links for manual verification.

Examples::

    py collect_competition_api.py --fixture external-data/scu-contests/public-api-sample.json
    py collect_competition_api.py --pages 11 --page-size 6

The first command is offline and is useful for testing.  The second command
uses the public endpoint and is bounded to at most 60 pages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
FOLDER = ROOT / "external-data" / "scu-contests"
BASE_URL = "http://xkjs.scu.edu.cn/home/homepage"
API_PATH = "/prod-api/home/notice/list"
SOURCE_ID = "scu-contests"
SOURCE_NAME = "四川大学学科竞赛管理平台"
TZ = timezone(timedelta(hours=8))


def now() -> str:
    return datetime.now(TZ).isoformat()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def parse_publish_time(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=TZ).isoformat()
        except ValueError:
            continue
    return None


def parse_payload(payload):
    """Return records and pagination from one validated public response."""
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise ValueError("竞赛平台接口返回非成功 code，未写入数据")
    data = payload.get("data") or {}
    records = data.get("records") or []
    if not isinstance(records, list):
        raise ValueError("竞赛平台接口 records 不是列表")
    return records, {
        "total": data.get("total"),
        "pages": data.get("pages"),
        "current": data.get("current"),
        "size": data.get("size"),
    }


def detail_url(competition_id) -> str:
    # The public Vue route uses /home/competition and reads competitionId.
    return urljoin(BASE_URL, "/home/competition?" + urlencode({"competitionId": competition_id}))


def normalize(record: dict) -> dict:
    competition_id = record.get("competitionId")
    if competition_id in (None, ""):
        raise ValueError("竞赛目录项缺少 competitionId")
    title = str(record.get("name") or f"竞赛平台目录项 {competition_id}").strip()[:200]
    published = parse_publish_time(record.get("publishTime"))
    status = record.get("status")
    grade = record.get("grade")
    audit = record.get("signupNeedAudit")
    note = (
        f"平台目录线索：{title}。"
        f"平台状态码 {status if status is not None else '未提供'}，"
        f"竞赛等级码 {grade if grade is not None else '未提供'}。"
        "报名条件、报名时间、竞赛时间及附件请打开平台原文核对；本条不代表当前仍可报名。"
    )
    digest = hashlib.sha256(f"{SOURCE_ID}:{competition_id}".encode()).hexdigest()[:16]
    return {
        "id": f"{SOURCE_ID}-{digest}",
        "sourceId": SOURCE_ID,
        "sourceName": SOURCE_NAME,
        "url": detail_url(competition_id),
        "title": title,
        "text": note,
        "published_at": published,
        "retrieved_at": now(),
        "content_hash": hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "eligibility": "平台目录线索，资格与截止时间待核实",
        "parse_status": "api_metadata",
        "attachment_status": "平台详情附件未在目录接口中返回",
        "image_status": "目录封面仅保留元数据",
        "attachments": [],
        "images": [record["coverImage"]] if record.get("coverImage") else [],
        "competition_id": competition_id,
        "competition_status": status,
        "competition_grade": grade,
        "signup_need_audit": audit,
        "api_record": record,
    }


def fetch_page(base_url: str, page_num: int, page_size: int, topic_id: int = 10000):
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("base URL 必须是 http(s) 地址")
    query = urlencode({"pageNum": page_num, "pageSize": page_size, "topicId": topic_id})
    origin = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
    url = urljoin(origin, API_PATH.lstrip("/")) + "?" + query
    request = Request(url, headers={"User-Agent": "SCUStudyRadar/0.1 (public catalogue reader)", "Accept": "application/json"})
    with urlopen(request, timeout=18) as response:
        return json.loads(response.read(2_000_001).decode("utf-8")), url


def collect(*, base_url=BASE_URL, pages=11, page_size=6, fixture: Path | None = None, pause=0.8):
    pages = max(1, min(int(pages), 60))
    page_size = max(1, min(int(page_size), 100))
    previous = read_json(FOLDER / "articles.json", [])
    articles = {str(x.get("competition_id")): x for x in previous if x.get("competition_id") is not None}
    errors = []
    pages_read = 0
    total = None
    changed = 0
    raw_pages = []
    for index in range(1, pages + 1):
        try:
            if fixture is not None:
                payload = read_json(fixture, {})
                page_url = str(fixture)
            else:
                if index > 1 and pause:
                    time.sleep(pause)
                payload, page_url = fetch_page(base_url, index, page_size)
            records, page_info = parse_payload(payload)
            raw_pages.append({"page": index, "url": page_url, "payload": payload})
            pages_read += 1
            total = page_info.get("total") or total
            for record in records:
                try:
                    item = normalize(record)
                    old = articles.get(str(item["competition_id"]))
                    if old is None or old.get("content_hash") != item.get("content_hash"):
                        changed += 1
                    articles[str(item["competition_id"])] = item
                except Exception as exc:
                    errors.append({"page": index, "error": str(exc)})
            if fixture is not None or not records or (page_info.get("pages") and index >= page_info["pages"]):
                break
        except Exception as exc:
            errors.append({"page": index, "error": str(exc)})
            break
    result = {
        "id": SOURCE_ID,
        "name": SOURCE_NAME,
        "url": base_url,
        "lastAttempt": now(),
        "lastSuccess": now() if pages_read else None,
        "status": "warning" if errors else ("ok" if pages_read else "error"),
        "errors": errors,
        "count": len(articles),
        "changedArticles": changed,
        "fetchedArticles": len(articles),
        "pagesRead": pages_read,
        "apiTotal": total,
        "coverage": f"公开通知接口读取 {pages_read} 页；目录元数据 {len(articles)} 条；详情正文与资格仍需打开原文核对。",
        "mode": "fixture" if fixture is not None else "public-api",
    }
    if pages_read:
        FOLDER.mkdir(parents=True, exist_ok=True)
        write_json(FOLDER / "articles.json", list(articles.values()))
        write_json(FOLDER / "run.json", result)
        if fixture is None:
            write_json(FOLDER / "api-pages.json", raw_pages)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--pages", type=int, default=11)
    parser.add_argument("--page-size", type=int, default=6)
    parser.add_argument("--fixture", type=Path, help="use a saved API response; no network")
    args = parser.parse_args()
    result = collect(base_url=args.base_url, pages=args.pages, page_size=args.page_size, fixture=args.fixture)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result["status"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

