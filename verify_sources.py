"""Recheck cached parses and produce a local source acceptance report (no network)."""
from collect_sources import *

def main():
    rows = []
    for source in read(ROOT / 'sources.json', {})['sources']:
        if source['id'] == 'sis':
            continue
        folder = DATA / source['id']
        items = read(folder / 'articles.json', [])
        for item in items:
            snapshot = folder / (item['id'] + '.html')
            if snapshot.exists() and item.get('parse_status') != 'embedded_pdf_text':
                try:
                    fresh = extract(html.fromstring(snapshot.read_bytes()), item['url'], item['title'])
                    # Local reparsing is not a new successful network retrieval.
                    fresh['retrieved_at'] = item['retrieved_at']
                    item.update(fresh)
                except ValueError:
                    pass
        if items:
            save(folder / 'articles.json', items)
        run = read(folder / 'run.json', read(folder / 'probe.json', {}))
        discovered = read(folder / 'discovered.json', {})
        known = {x['url'] for x in items}
        for error in run.get('errors',[]):
            url = error.get('url')
            if url in discovered and url not in known:
                items.append(dict(id=source['id']+'-'+hashlib.sha256(url.encode()).hexdigest()[:16],
                    sourceId=source['id'],sourceName=source['name'],url=url,title=discovered[url][:180],
                    text='',published_at=None,retrieved_at=None,parse_status='list_only',content_hash='',
                    attachments=[],images=[],eligibility='正文获取失败，仅列表线索'))
                known.add(url)
        if items:
            save(folder/'articles.json',items)
            run['count'] = len(items)
            save(folder/'run.json',run)
        text_count = sum(len(x.get('text','')) >= 30 for x in items)
        rows.append((source, run, len(items), text_count))
    report = ['# 多来源接入验收', '', '生成时间：'+NOW(), '',
              '范围：逐站公开入口和部分重点栏目，最近一批条目。不是全站历史镜像；未绕过登录或验证码。',
              '来源计数含交叉重复；网页按原链接合并。文本提取不等于申请资格已确认。',
              '定时任务尚未在本轮安装或验证；enabled 仅表示运行更新器时会采集。', '',
              '| 来源 | 结果 | 已存记录 | 有文本 | 最近成功 |', '|---|---|---:|---:|---|']
    for source, run, count, text_count in rows:
        report.append(f"| {source['name']} | {run.get('status','未运行')} | {count} | {text_count} | {run.get('lastSuccess') or '无'} |")
    report += ['', '## 待核与失败明细', '']
    for source, run, count, text_count in rows:
        if run.get('errors'):
            report += ['### '+source['name'], '', *['- '+str(e.get('url',''))+'：'+e['error'] for e in run['errors']], '']
    report += ['## 已测试能力', '', '- 正文和原链接入库、同网址增量覆盖、失败保留上次成功记录。',
               '- HTML正文与PDF文本层提取；图片公告、扫描PDF明确待OCR。',
               '- 标题、发布日期、来源、附件/图片链接可追溯；不拿正文截止日期充当发布日期。',
               '- 页面按来源筛选、检索、显示失败详情。',
               '- 竞赛平台公开目录已有只读适配器，但实时抓取默认关闭；暂未完成：所有附件解析、OCR、可靠截止时间结构化、主动提醒、无人值守计划任务验证。', '']
    (ROOT / '接入验收.md').write_text('\n'.join(report), encoding='utf-8')
    print('Sources with records:', sum(n>0 for _,_,n,_ in rows), '/', len(rows))
    print('External records:', sum(n for _,_,n,_ in rows))

if __name__ == '__main__':
    main()
