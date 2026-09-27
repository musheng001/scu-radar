"""Build a compact daily secretary brief from the local radar snapshot.

This file is connector-agnostic: it never stores mailbox tokens and never
sends mail. Outlook/Calendar connectors can later consume the resulting JSON
after the user reviews it.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from brief_page import render_html

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def read_radar(path: Path | None = None):
    path = path or ROOT / "radar-data.js"
    raw = path.read_text(encoding="utf-8")
    prefix = "window.SCU_RADAR_DATA="
    if not raw.startswith(prefix):
        raise ValueError("radar-data.js 不是预期的 SCU_RADAR_DATA 资产")
    payload = raw[len(prefix):].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("雷达数据缺少 items 列表")
    return data


def date_key(value):
    if not value:
        return datetime.min.replace(tzinfo=TZ)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(TZ)
    except ValueError:
        return datetime.min.replace(tzinfo=TZ)


def short(value, limit=110):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def load_config(path: Path | None = None):
    return read_json(path or ROOT / "secretary-config.json", {})


def item_priority(item, config):
    title_text = " ".join(str(item.get(key, "")) for key in ("title", "summary", "sourceName"))
    score = int(item.get("score") or 0)
    score += int((config.get("categoryWeights") or {}).get(item.get("category"), 0))
    if any(re.search(re.escape(word), title_text, re.I) for word in config.get("focusKeywords", [])):
        score += int(config.get("focusBonus", 0))
    if item.get("sourceName") in config.get("prioritySources", []):
        score += int(config.get("prioritySourceBonus", 0))
    if any(re.search(pattern, title_text, re.I) for pattern in config.get("archivePatterns", [])):
        score -= int(config.get("archivePenalty", 0))
    if item.get("parseStatus") in {"api_metadata", "list_only"}:
        score -= 8
    return score


def item_sort_key(item, config):
    state_weight = {"active": 3, "review": 2, "closed": 0, "archive": 0}.get(item.get("state"), 1)
    return (state_weight, item_priority(item, config), date_key(item.get("publishedAt")))


def make_brief(data, config=None):
    config = config or load_config()
    items = data.get("items", [])
    sources = data.get("sources", [])
    actionable = sorted([x for x in items if x.get("state") in {"active", "review"}], key=lambda x: item_sort_key(x, config), reverse=True)
    competitions = sorted([x for x in items if x.get("category") == "竞赛" and x.get("state") != "archive"], key=lambda x: item_sort_key(x, config), reverse=True)
    warnings = [
        {"name": s.get("name", s.get("id", "未命名来源")), "status": s.get("status", "unknown"),
         "errors": [str(e.get("error", "")) for e in (s.get("errors") or [])[:3]],
         "coverage": s.get("coverage", "")}
        for s in sources if s.get("status") not in {"ok", "connected"} or s.get("errors")
    ]
    return {
        "generatedAt": data.get("generatedAt"), "mode": data.get("mode"), "profile": config.get("profile", {}),
        "summary": {"total": len(items), "actionable": len(actionable), "competitions": len(competitions), "sourceWarnings": len(warnings)},
        "actionItems": actionable[: int(config.get("maxActionItems", 12))],
        "competitions": competitions[: int(config.get("maxCompetitions", 15))], "sourceWarnings": warnings,
        "loginEntrances": (data.get("channels") or {}).get("loginEntrances", []),
        "wechatAccounts": (data.get("channels") or {}).get("wechatAccounts", []),
    }


def render_markdown(brief):
    summary = brief["summary"]
    lines = ["# 川大雷达 · 秘书简报", "", f"生成时间：{brief.get('generatedAt') or '未记录'}", f"数据模式：{brief.get('mode') or '本地快照'}", "",
             f"> 当前共有 {summary['total']} 条公开记录；其中 {summary['actionable']} 条值得先核对，竞赛线索 {summary['competitions']} 条，来源异常 {summary['sourceWarnings']} 个。", "", "## 先处理", ""]
    if brief["actionItems"]:
        lines += ["| 优先级 | 类别 | 标题 | 来源 | 状态 | 原文 |", "|---:|---|---|---|---|---|"]
        for index, item in enumerate(brief["actionItems"], 1):
            state = item.get("eligibility") or ("仍在窗口期" if item.get("state") == "active" else "待核")
            lines.append(f"| {index} | {item.get('category', '未分类')} | {short(item.get('title'), 68).replace('|', '／')} | {short(item.get('sourceName', '公开来源'), 30)} | {short(state, 34)} | [核对]({item.get('url', '')}) |")
    else:
        lines.append("当前没有被标记为近期行动或待核的条目。")
    lines += ["", "## 竞赛清单（仍保留全量源，以下只是优先查看顺序）", ""]
    if brief["competitions"]:
        for item in brief["competitions"]:
            marker = "目录线索" if item.get("parseStatus") == "api_metadata" else "正文"
            lines.append(f"- **{short(item.get('title'), 90)}** · {marker} · [{item.get('sourceName', '来源')}]({item.get('url', '')})")
    else:
        lines.append("当前没有非历史竞赛条目。")
    lines += ["", "## 来源异常与待核", ""]
    if brief["sourceWarnings"]:
        for warning in brief["sourceWarnings"]:
            details = "；".join(x for x in warning["errors"] if x) or warning["coverage"] or "请查看验收报告"
            lines.append(f"- **{warning['name']}**（{warning['status']}）：{short(details, 180)}")
    else:
        lines.append("本次没有来源异常。")
    lines += ["", "## 登录入口（只保留入口，不保存账号密码）", ""]
    for entry in brief["loginEntrances"]:
        lines.append(f"- [{entry.get('name', '登录入口')}]({entry.get('url', '')})")
    lines += ["", "## 公众号登记", ""]
    for account in brief["wechatAccounts"]:
        note = "已有官网依据" if account.get("evidence") else "身份与访问待核验"
        lines.append(f"- {account.get('name', '未命名')} · {note}")
    lines += ["", "> 本简报只做信息整理，不把关键词命中、目录元数据或历史报道直接当成可报名资格。", ""]
    return "\n".join(lines)


def write_brief(data=None, markdown_path=None, json_path=None, config=None):
    data = data or read_radar()
    brief = make_brief(data, config)
    markdown_path = markdown_path or ROOT / "secretary-brief.md"
    json_path = json_path or ROOT / "secretary-brief.json"
    markdown_path.write_text(render_markdown(brief), encoding="utf-8")
    json_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.with_suffix('.html').write_text(render_html(brief), encoding="utf-8")
    return brief


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--radar", type=Path, default=ROOT / "radar-data.js")
    parser.add_argument("--markdown", type=Path, default=ROOT / "secretary-brief.md")
    parser.add_argument("--json", dest="json_path", type=Path, default=ROOT / "secretary-brief.json")
    parser.add_argument("--config", type=Path, default=ROOT / "secretary-config.json")
    args = parser.parse_args()
    brief = write_brief(read_radar(args.radar), args.markdown, args.json_path, load_config(args.config))
    print(json.dumps(brief["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
