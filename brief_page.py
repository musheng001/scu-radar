"""Render a readable, offline-first brief. External text is always escaped."""
from html import escape
from urllib.parse import urlsplit, quote
from datetime import datetime
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent


def text(value):
    return escape(str(value or ""), quote=True)


def link(url, label, local=False):
    url = str(url or "")
    parts = urlsplit(url)
    allowed = parts.scheme in {"http", "https"} and bool(parts.netloc)
    if local:
        allowed = allowed or (not parts.scheme and not parts.netloc and not url.startswith(("/", "\\")) and "\\" not in url)
    if not allowed:
        return text(label)
    return f'<a class="source" href="{text(quote(url, safe="/:?=&%#"))}" target="_blank" rel="noopener noreferrer">{text(label)} ↗</a>'


def entries(rows):
    return ''.join(f'<article class="entry"><h3>{text(x["title"])}</h3><p>{text(x["body"])}</p>{link(x["source"],x["sourceLabel"],True)}</article>' for x in rows)


def render_progress(progress):
    cards = []
    for record in progress[:8]:
        try:
            stamp = datetime.fromisoformat(str(record.get('savedAt') or '')).strftime('%m月%d日 %H:%M')
        except ValueError:
            stamp = '时间未记录'
        rows = []
        for item in record.get('completed', []):
            detail = f' · {text(item.get("course"))}' if item.get('course') else ''
            rows.append(f'<li><span class="progress-mark done">已完成</span><b>{text(item.get("title"))}</b>{detail}</li>')
        for item in record.get('tasks', []):
            detail = f' · {text(item.get("due_date"))}' if item.get('due_date') else ''
            rows.append(f'<li><span class="progress-mark next">下一步</span><b>{text(item.get("title"))}</b>{detail}</li>')
        for item in record.get('notes', []):
            rows.append(f'<li><span class="progress-mark note">备注</span>{text(item)}</li>')
        cards.append(
            f'<article class="progress-card"><time>{text(stamp)}</time><h3>{text(record.get("summary") or "学习进展")}</h3>'
            f'<ul>{"".join(rows)}</ul></article>'
        )
    return ''.join(cards)


def render_html(brief, context=None, progress=None):
    if context is None:
        path = ROOT / 'study-context.json'
        context = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if progress is None:
        progress_path = ROOT / 'progress-log.json'
        progress_data = json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {}
        progress = progress_data.get('entries', []) if isinstance(progress_data, dict) else []
    stamp = str(brief.get('generatedAt') or '')
    try:
        stamp = datetime.fromisoformat(stamp).strftime('%Y.%m.%d · %H:%M')
    except ValueError:
        stamp = '更新时间未记录'
    tasks = ''.join(f'<article class="task"><div><span class="tag">{text(x["when"])}</span><h3>{text(x["title"])}</h3><p>{text(x["body"])}</p>{link(x["source"],x["sourceLabel"],True)}</div></article>' for x in context.get('actions', []))
    courses = ''.join(f'<tr><td class="day">{text(x["day"])}</td><td>{text(x["name"])}</td><td>{text(x["sessions"])}</td><td>{text(x["room"])}</td></tr>' for x in context.get('courses', []))
    opportunities = ''.join(f'<article class="opportunity"><span class="tag">{text(x.get("category"))} · 报名条件待核</span><h3>{text(x.get("title"))}</h3><p>{text(x.get("sourceName"))} · 截止：{text(x.get("deadline") or "尚未确认")}。此条保留为线索，未转成你的任务。</p>{link(x.get("url"),"查看官方通知")}</article>' for x in brief.get('actionItems', []))
    diagnostics = ''.join(f'<li>{text(x.get("name"))}：{text("；".join(x.get("errors", [])) or x.get("coverage") or x.get("status"))}</li>' for x in brief.get('sourceWarnings', []))
    gaps = ''.join(f'<li>{text(x)}</li>' for x in context.get('gaps', []))
    total = text(brief.get('summary', {}).get('total', 0))
    course_count = len({x['name'] for x in context.get('courses', [])})
    progress_cards = render_progress(progress)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>案头简报 · 进德修业</title><link rel="stylesheet" href="brief-page.css?v=1"></head>
<body><div class="sheet"><header class="masthead"><a class="brand back" href="index.html">川大雷达</a><span class="meta">公开信息快照 {text(stamp)}</span></header>
<div class="hero"><div><div class="eyebrow">进德修业 / 本地学习简报</div><h1>案头简报</h1><p class="lead">本学期课程、考核要求与近期安排。依据已有材料整理，完成状态与待核事项分别标明。</p></div><aside class="compass"><span class="meta">当前方向</span><strong>高 GPA · IPE · 定量方法</strong><span class="meta">2026 级国际政治<br>本地材料核对：{text(context.get('reviewedAt','未记录'))}</span></aside></div>
<nav aria-label="简报导航"><a href="#progress">最近进展</a><a href="#actions">先核对三件事</a><a href="#courses">本学期课程</a><a href="#rules">规则与材料</a><a href="#opportunities">公开机会</a></nav>
<main><section class="section" id="progress"><div class="section-head"><h2>最近进展</h2><small>由你确认后写入 · 共 {len(progress)} 次记录</small></div><div class="progress-grid">{progress_cards or '<p class="notice">还没有登记进展。请从首页点击“GPT 录入进展”。</p>'}</div></section>
<section class="section" id="actions"><div class="section-head"><h2>先核对三件事</h2><small>请结合上方已登记进展核对 · 已完成的无需重做</small></div><div class="tasks">{tasks or '<p>暂未整理个人课程任务。</p>'}</div></section>
<section class="section" id="courses"><div class="section-head"><h2>本学期课程</h2><small>{text(context.get('semester'))} · {course_count} 门课</small></div><p class="notice">{text(context.get('scheduleNote'))}</p>{link(context.get('scheduleSource'),'查看原始选课结果',True)}
<details><summary>展开完整周课表 · 含特殊周次</summary><div><table class="schedule"><thead><tr><th scope="col">星期</th><th scope="col">课程</th><th scope="col">节次与教学周</th><th scope="col">教室</th></tr></thead><tbody>{courses}</tbody></table></div></details>
<div class="two-col"><div>{entries(context.get('assessments',[])[:2])}</div><aside>{entries(context.get('assessments',[])[2:])}</aside></div></section>
<section class="section" id="rules"><div class="section-head"><h2>规则与材料</h2><small>本地版本依据 · 后续变更另行核实</small></div><details><summary>展开推免、综测与培养计划要点</summary><div class="two-col"><div>{entries(context.get('rules',[])[:2])}</div><div>{entries(context.get('rules',[])[2:])}</div></div></details><details><summary>还缺哪些信息</summary><ul>{gaps}</ul></details></section>
<section class="section" id="opportunities"><div class="section-head"><h2>公开机会</h2><small>{total} 条公开记录仍在雷达中保留</small></div><p class="notice">资格、截止日与课程冲突核实后，再决定是否加入个人安排。</p><details><summary>查看 {len(brief.get('actionItems', []))} 条候选线索</summary><div>{opportunities or '<p>暂无候选线索。</p>'}</div></details><details><summary>来源诊断 · {len(brief.get('sourceWarnings', []))} 项需维护</summary><p class="notice">以下是采集维护事项，不是你的学习任务。</p><ul class="diagnostic">{diagnostics}</ul></details></section></main>
<footer>本页可直接在本地浏览器打开。课程要求来自本地文件；日期未知时保留教学周。<br><a href="index.html">返回全部信息</a> · <a href="本地课程与规则盘点.md">材料盘点</a> · <a href="secretary-brief.md">文本备份</a></footer></div></body></html>'''
