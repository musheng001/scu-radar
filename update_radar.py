"""Incrementally refresh public SIS data and build the dashboard asset.

py update_radar.py              # incremental; full scan at least weekly
py update_radar.py --full       # force a full public-site scan
py update_radar.py --build-only # rebuild radar-data.js from existing files
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from secretary_brief import write_brief

SITE = Path(__file__).resolve().parent
STATE_FILE = SITE / "automation-state.json"
TZ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ)


def find_collector() -> Path:
    candidates = [p.parent for p in SITE.parent.glob("*/sis_collect.py") if p.parent != SITE]
    if not candidates:
        raise FileNotFoundError("没有找到 sis_collect.py。请保留与 scu-radar-web 同级的采集程序文件夹。")
    return candidates[0]


COLLECTOR = find_collector()
DATA = COLLECTOR / "data"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_module():
    spec = importlib.util.spec_from_file_location("sis_collect", COLLECTOR / "sis_collect.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def incremental_refresh():
    collector = load_module()
    existing = {str(row["id"]): row for row in load_json(DATA / "sis_articles.json", [])}
    cats = collector.categories()
    errors, changed = [], 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {pool.submit(collector.page, cid, 0, 100): (cid, name) for cid, name in cats.items()}
        for future in as_completed(jobs):
            cid, name = jobs[future]
            try:
                _, rows = future.result()
                for raw in rows:
                    if not raw.get("id"):
                        continue
                    item = collector.normalize(raw)
                    key = str(item["id"])
                    if key not in existing or existing[key].get("content_html") != item.get("content_html"):
                        existing[key] = item
                        changed += 1
            except Exception as exc:
                errors.append({"category": cid, "name": name, "error": str(exc)})
    rows = sorted(existing.values(), key=lambda x: x.get("published_at") or "", reverse=True)
    save_json(DATA / "sis_articles.json", rows)
    with (DATA / "sis_articles.csv").open("w", encoding="utf-8-sig", newline="") as file:
        fields = ["id", "title", "category", "published_at", "url", "text"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: row.get(k) for k in fields} for row in rows)
    run = {"retrieved_at": NOW.isoformat(), "unique_articles": len(rows), "errors": errors,
           "mode": "incremental", "changed_articles": changed}
    save_json(DATA / "sis_run.json", run)
    return run


def run_helpers():
    for name in ("sis_review.py", "sis_triage.py"):
        subprocess.run([sys.executable, str(COLLECTOR / name)], cwd=COLLECTOR, check=True)


def category_for(title: str, raw: str) -> str:
    text = title + " " + raw
    rules = [
        ("竞赛", r"竞赛|大赛|挑战赛|比赛|演讲赛"),
        ("讲座会议", r"讲座|论坛|会议|报告会|学术报告|研讨会|工作坊"),
        ("交流项目", r"交换|交流项目|访学|留学|夏令营|国际课程周|联合培养"),
        ("教务规则", r"推免|招生|考试|选课|培养方案|学籍|课程|成绩|奖学金|评奖|评优|免修|微专业"),
        ("招募实践", r"招募|招聘|志愿|实习|征集|申报|申请|遴选|选拔|项目"),
    ]
    for label, pattern in rules:
        if re.search(pattern, text):
            return label
    if re.search(r"活动|观影|展览|运动会|音乐会", text):
        return "校园活动"
    return "学院动态"


def score_item(article, ui_category, deadline, queue):
    title = article.get("title", "")
    text = (article.get("text") or "")[:1200]
    score, reasons = 18, []
    try:
        published = datetime.fromisoformat((article.get("published_at") or "").replace("Z", "+00:00")).astimezone(TZ)
        age = max(0, (NOW.date() - published.date()).days)
        score += max(0, 32 - min(32, age // 3))
    except ValueError:
        pass
    if deadline:
        try:
            left = (datetime.fromisoformat(deadline).date() - NOW.date()).days
            if 0 <= left <= 30:
                score += 28
                reasons.append("仍在窗口期")
            elif left < 0:
                score -= 32
        except ValueError:
            pass
    weights = {"竞赛": 15, "交流项目": 13, "招募实践": 11, "讲座会议": 10, "教务规则": 13, "校园活动": 3, "学院动态": -12}
    score += weights.get(ui_category, 0)
    if re.search(r"国际政治|国际关系|政治学|经济|金融|定量|数据|人工智能|Python|统计|计量", title + text, re.I):
        score += 12
        reasons.append("方向相关")
    if re.search(r"本科生|全校学生|2026级|新生", title + text):
        score += 8
        reasons.append("本科生可关注")
    if re.search(r"研究生|博士|硕士", title) and not re.search(r"本科", title):
        score -= 18
    if queue == "近期通知，核对原文":
        score += 12
    return max(0, min(100, score)), reasons


def audience_note(article, source_id):
    title = article.get('title', '')
    text = article.get('text', '')[:1800]
    if re.search(r'国际学生|留学生|在职|港澳台|拟录取|名单|复试成绩|选调|校园招聘|届秋招|生源信息|教师教学|思政榜样|教学任务', title):
        return '对象或事项不匹配，仅存档', True
    retrospective = re.search(
        r'圆满|纪实|顺利|成功举办|举办|举行|召开|喜迎|走访|获奖|'
        r'开展.{0,20}(?:活动|宣传周)|在.{0,15}举办|政务实习.{0,30}川大学子',
        title,
    )
    action_notice = re.search(r'将于|预告|报名|招募|通知|征集|选拔|申报|比赛', title)
    if retrospective and not action_notice:
        return '活动回顾，不是报名通知', True
    dated_title = re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', title)
    if dated_title:
        try:
            last_named_date = max(datetime(int(year), int(month), int(day), tzinfo=TZ).date()
                                  for year, month, day in dated_title)
            if last_named_date < NOW.date():
                return '标题所示日期已过，仅存档', True
        except ValueError:
            pass
    event_date = re.search(r'时间[：:]\s*(20\d{2})年(\d{1,2})月(\d{1,2})日', text)
    if event_date:
        try:
            named_event_date = datetime(*(int(part) for part in event_date.groups()), tzinfo=TZ).date()
            if named_event_date < NOW.date():
                return '正文所示活动日期已过，仅存档', True
        except ValueError:
            pass
    if not source_id.startswith(('scu', 'sis', 'jwc', 'xgb', 'campus')) and re.search(r'奖学金|分流|学籍|预毕业|答辩|军训|开学|新生', title):
        return '外校在校生事务，仅存档', True
    if re.search(r'(?:选拔|选派|面向|限).{0,35}(?:大二|大三|三年级|2024级|2025级)', text):
        return '年级可能不符，先核对象', True
    if re.search(r'推免|免试|研究生招生|硕士.*招生|初试科目', title):
        return '升学参考，不代表当前可申请', True
    return '资格与截止时间待核实', False


def build_asset(mode: str):
    articles = load_json(DATA / "sis_articles.json", [])
    run = load_json(DATA / "sis_run.json", {})
    triage = {}
    queue_file = DATA / "sis_review_queue.csv"
    if queue_file.exists():
        with queue_file.open(encoding="utf-8-sig", newline="") as file:
            triage = {str(row.get("文章ID")): row for row in csv.DictReader(file)}
    items = []
    for article in articles:
        review = triage.get(str(article.get("id")), {})
        deadline = review.get("候选截止日") or ""
        queue = review.get("审核队列") or ""
        ui_category = category_for(article.get("title", ""), article.get("category", ""))
        score, reasons = score_item(article, ui_category, deadline, queue)
        state = "archive"
        if deadline:
            try:
                state = "active" if datetime.fromisoformat(deadline).date() >= NOW.date() else "closed"
            except ValueError:
                state = "review"
        elif queue == "近期通知，核对原文":
            state = "review"
        text = re.sub(r"\s+", " ", article.get("text") or "").strip()
        eligibility, excluded = audience_note(article, 'sis')
        if excluded:
            score, state = min(score, 45), 'archive'
        items.append({"id": "sis-" + str(article.get("id")), "title": article.get("title", ""),
                      "category": ui_category, "rawCategory": article.get("category", ""),
                      "publishedAt": article.get("published_at"), "deadline": deadline,
                      "url": article.get("url", ""), "summary": text[:230] + ("…" if len(text) > 230 else ""),
                      "sourceId": "sis", "sourceName": "国际关系学院", "state": state,
                      "score": score, "reasons": reasons, "eligibility": eligibility})
    sources = [{"id": "sis", "name": "国关学院官网", "url": "https://sis.scu.edu.cn/",
                "status": "ok" if not run.get("errors") else "warning", "count": len(articles),
                "lastSuccess": run.get("retrieved_at")}]
    seen_urls = {x['url'] for x in items}
    registry = load_json(SITE / 'sources.json', {}).get('sources', [])
    for source in registry:
        if source['id'] == 'sis':
            continue
        folder = SITE / 'external-data' / source['id']
        health = load_json(folder / 'run.json', {})
        if not health:
            continue
        sources.append(health)
        for article in load_json(folder / 'articles.json', []):
            if article['url'] in seen_urls:
                continue
            seen_urls.add(article['url'])
            category = '竞赛' if source['id'] == 'jwc-contests' else category_for(article['title'], '')
            score, reasons = score_item(article, category, '', '')
            title = article['title']
            eligibility, excluded = audience_note(article, source['id'])
            if excluded:
                score = min(score, 20)
            state = 'archive'
            published = article.get('published_at')
            if published and not excluded:
                age = (NOW - datetime.fromisoformat(published)).days
                if 0 <= age <= 30:
                    state = 'review'
            text = article.get('text', '')
            items.append(dict(id=article['id'], title=title, category=category, rawCategory='',
                              publishedAt=published, deadline='', url=article['url'],
                              summary=(text[:230] + ('…' if len(text) > 230 else '')) or '图片或附件公告：正文尚未识别，请核对官方原文。',
                              sourceId=source['id'], sourceName=source['name'], state=state,
                              score=score, reasons=reasons, eligibility=eligibility,
                              attachments=article.get('attachments', []), images=article.get('images', []),
                              parseStatus=article.get('parse_status', '')))
    teachers = 0
    teacher_file = DATA / "sis_teachers.csv"
    if teacher_file.exists():
        with teacher_file.open(encoding="utf-8-sig", newline="") as file:
            teachers = sum(1 for _ in csv.DictReader(file))
    payload = {"schemaVersion": 1, "generatedAt": NOW.isoformat(), "mode": mode,
               "summary": {"totalArticles": len(items), "teacherCount": teachers,
                           "errors": sum(len(s.get('errors', [])) for s in sources),
                           "changedArticles": sum(s.get('changedArticles', 0) for s in sources)},
               "sources": sources, "items": items,
               "channels": load_json(SITE / 'private-channels.json', {})}
    target = SITE / "radar-data.js"
    temporary = target.with_suffix(".js.tmp")
    temporary.write_text("window.SCU_RADAR_DATA=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    temporary.replace(target)
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--external-only", action="store_true", help="refresh enabled external sources and build dashboard")
    args = parser.parse_args()
    state = load_json(STATE_FILE, {})
    last_full = state.get("last_full")
    full_due = not last_full
    if last_full:
        try:
            full_due = NOW - datetime.fromisoformat(last_full) >= timedelta(days=7)
        except ValueError:
            full_due = True
    mode = "build-only"
    state["last_attempt"] = NOW.isoformat()
    try:
        if not args.build_only and not args.external_only:
            if args.full or full_due:
                subprocess.run([sys.executable, str(COLLECTOR / "sis_collect.py")], cwd=COLLECTOR, check=True)
                state["last_full"] = NOW.isoformat()
                mode = "full"
            else:
                incremental_refresh()
                mode = "incremental"
            run_helpers()
        if not args.build_only:
            selected = [s['id'] for s in load_json(SITE / 'sources.json', {}).get('sources', [])
                        if s.get('enabled') and s['id'] != 'sis']
            if selected:
                collector_script = str(SITE / 'collect_sources.py')
                bounded = [sid for sid in selected if sid != 'jwc-contests']
                if bounded:
                    command = [sys.executable, collector_script]
                    for sid in bounded:
                        command.extend(['--source', sid])
                    subprocess.run(command, cwd=SITE, check=True)
                # Competitions are explicitly a full-history source: keep
                # walking its public list pages so new pages do not get lost
                # between scheduled runs. Keep this separate so --limit 600
                # cannot accidentally make every other source expensive.
                if 'jwc-contests' in selected:
                    subprocess.run([sys.executable, collector_script,
                                    '--source', 'jwc-contests', '--pages', '60', '--limit', '600'],
                                   cwd=SITE, check=True)
            if args.external_only:
                mode = 'external'
        payload = build_asset(mode)
        write_brief(payload)
        state.update({"last_attempt": NOW.isoformat(), "last_build": NOW.isoformat(), "last_mode": mode,
                      "last_error": '部分来源异常，请查看来源状态' if payload['summary']['errors'] else None})
        if not args.build_only and not payload['summary']['errors']:
            state['last_success'] = NOW.isoformat()
        save_json(STATE_FILE, state)
        print(f"Dashboard ready: {len(payload['items'])} items; mode={mode}; output={SITE / 'radar-data.js'}")
    except Exception as exc:
        state.update({"last_attempt": NOW.isoformat(), "last_error": str(exc)})
        save_json(STATE_FILE, state)
        raise


if __name__ == "__main__":
    main()
