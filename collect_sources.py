"""Bounded public HTML collection. No login, CAPTCHA bypass, or attachment downloads.

--probe checks registered landing pages; --source ID collects one source.
Snapshots and last successful articles survive partial failures.
"""
import argparse
import base64
import hashlib
import io
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from lxml import html

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'external-data'
UA = 'SCUStudyRadar/0.1 (personal academic information reader)'
NOW = lambda: datetime.now(timezone(timedelta(hours=8))).isoformat()
ARTICLE = re.compile(r'/info/\d+/\d+\.htm|/\d{4,}[^/]*\.html?$|/\w{20,}\.html?$|a\d+/page\.htm|/content/|wbnewsid=|newsdetail\.html')
ARTICLE = re.compile(ARTICLE.pattern + r'|/zsxx/Details/')
BODY = ['//*[@id="vsb_content"]', '//*[contains(@id,"vsb_content_")]', '//*[contains(@class,"v_news_content")]', '//*[contains(@class,"wp_articlecontent")]', '//*[contains(@class,"article-content")]', '//*[contains(@class,"article_content")]', '//*[contains(@class,"TRS_Editor")]', '//*[contains(@class,"rich_media_content")]']
BODY += ['//*[@class="new-cont"]//*[@class="cont"]', '//*[@class="zsxxxq_cont_cent"]', '//*[@id="mycontent"]']
BODY += ['//*[contains(@class,"item-content")]', '//*[@class="content-box"]',
         '//*[@class="introductionContent"]', '//*[contains(@class,"text-indent-2")]/..']
BODY += ['//*[@class="info-detail"]/*[@class="detail"]']
SEEDS = {'jwc':['tzgg.htm'], 'pku-sis-grad':['postgraduate/enrollment89101/index.htm'],
         'pku-grad':['zsxx/sszs/index.htm'], 'ruc-grad':['sszs/tjms.htm']}
REFERENCES = {'ruc-sis-programs', 'ruc-sis-politics'}

def read(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def clean(value):
    return re.sub(r'\s+', ' ', value).strip()

class Reader:
    def __init__(self, url):
        self.host = urlsplit(url).netloc
        self.base = urlunsplit((urlsplit(url).scheme, self.host, '/', '', ''))
        self.robot = urllib.robotparser.RobotFileParser()
        self.last = 0
        try:
            raw, _ = self.fetch(urljoin(self.base, 'robots.txt'), robots=False)
            self.robot.parse(raw.decode('utf-8', errors='replace').splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 410):
                self.robot.parse([])
            else:
                raise

    def fetch(self, url, robots=True):
        if urlsplit(url).netloc != self.host or urlsplit(url).scheme not in ('http', 'https'):
            raise ValueError('outside source host')
        if robots and not self.robot.can_fetch(UA, url):
            raise PermissionError('robots.txt disallows this URL')
        time.sleep(max(0, 0.8 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        try:
            response = urllib.request.urlopen(req, timeout=18)
        except urllib.error.URLError as exc:
            if 'CERTIFICATE_VERIFY_FAILED' not in str(exc):
                raise
            # Windows trust validation can build a missing intermediate chain.
            # Never disable TLS checks or accept arbitrary certificates.
            encoded_url = base64.b64encode(url.encode()).decode()
            ps = "$u=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded_url + "')); $ErrorActionPreference='Stop'; $r=Invoke-WebRequest -UseBasicParsing -Uri $u -TimeoutSec 18 -UserAgent '" + UA + "'; @{url=$r.BaseResponse.ResponseUri.AbsoluteUri; data=[Convert]::ToBase64String($r.RawContentStream.ToArray())}|ConvertTo-Json -Compress"
            command = base64.b64encode(ps.encode('utf-16le')).decode()
            output = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', command], capture_output=True, timeout=30, check=True)
            result = json.loads(output.stdout.decode('utf-8-sig'))
            if urlsplit(result['url']).netloc != self.host:
                raise ValueError('cross-host redirect; review required')
            raw = base64.b64decode(result['data'])
            if len(raw) > 3_000_000:
                raise ValueError('page exceeds 3 MB limit')
            return raw, result['url']
        with response:
            if urlsplit(response.url).netloc != self.host:
                raise ValueError('cross-host redirect; review required')
            raw = response.read(3_000_001)
            if len(raw) > 3_000_000:
                raise ValueError('page exceeds 3 MB limit')
            return raw, response.url

    def page(self, url):
        raw, final = self.fetch(url)
        tree = html.fromstring(raw, base_url=final)
        if b'$_ts' in raw and not tree.xpath('//title/text()'):
            raise PermissionError('站点返回访问校验页，未绕过校验；需人工或官方接口')
        return raw, tree, final

def links(tree, url):
    found = {}
    for a in tree.xpath('//a[@href]'):
        target = urljoin(url, a.get('href')).split('#')[0]
        title = clean(a.get('title') or a.text_content())
        if urlsplit(target).scheme in ('http', 'https') and urlsplit(target).netloc == urlsplit(url).netloc and title:
            found[target] = title
    return found

def extract(tree, url, fallback):
    page_title = clean(' '.join(tree.xpath('//title/text()')))
    if re.search(r'[-—_]\s*四川大学', page_title):
        fallback = re.split(r'[-—_]\s*四川大学', page_title)[0]
    title = clean(' '.join(tree.xpath('//meta[@name="ArticleTitle"]/@content'))) or clean(' '.join(tree.xpath('//*[@id="ccc"]//text()'))) or clean(' '.join(tree.xpath('//h1//text()'))) or fallback
    title = re.sub(r'^(?:\d{4}[/.-]\d{1,2}[/.-]\d{1,2}|\d{2}\d{4}\.\d{2})\s*', '', title)
    specific_title = tree.xpath('//*[@class="info-detail"]/*[@class="title"]/*[1]//text()')
    if specific_title:
        title = clean(' '.join(specific_title))
    if len(title) > 200:
        raise ValueError('title too long; dedicated title selector required')
    body = None
    for xpath in BODY:
        nodes = tree.xpath(xpath)
        if nodes and (len(clean(nodes[0].text_content())) >= 15 or nodes[0].xpath('.//img|.//iframe|.//a[@href]')):
            body = nodes[0]
            break
    if body is None:
        raise ValueError('article body selector not verified')
    for node in body.xpath('.//script|.//style'):
        node.drop_tree()
    text = clean(body.text_content())
    meta_dates = tree.xpath('//meta[@name="PubDate"]/@content|//meta[@name="publishdate"]/@content|//meta[@name="publishDate"]/@content')
    context = clean(tree.text_content()).split(text[:50])[0] if text else clean(tree.text_content())
    date = re.search(r'(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})', ' '.join(meta_dates))
    if not date:
        date = re.search(r'(?:发布时间|发布日期|添加时间|日期)\s*[:：]?\s*(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})', context)
    if not date:
        heading_date = ' '.join(tree.xpath('//*[@class="info-detail"]/*[@class="title"]//text()'))
        date = re.search(r'(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})', heading_date)
    published = None
    if date:
        try:
            published = datetime(*map(int, date.groups()), tzinfo=timezone(timedelta(hours=8))).isoformat()
        except ValueError:
            pass
    attachments = [{'title': clean(a.text_content()), 'url': urljoin(url, a.get('href'))} for a in body.xpath('.//a[@href]') if re.search(r'\.(pdf|docx?|xlsx?|zip)(?:$|\?)|download', a.get('href'), re.I)]
    images = [urljoin(url, src) for src in body.xpath('.//img/@src') if not src.startswith('data:')]
    attachments += [{'title': '嵌入PDF', 'url': urljoin(url, src)} for src in body.xpath('.//iframe/@src') if '.pdf' in src.lower()]
    return dict(title=title, text=text, published_at=published, url=url, attachments=attachments, images=images,
                content_hash=hashlib.sha256(text.encode()).hexdigest(), retrieved_at=NOW(), eligibility='待核实',
                parse_status='text' if len(text) >= 30 else 'media_only',
                attachment_status='仅保留原链接，尚未解析', image_status='仅保留原链接，尚未OCR')

def extract_pdf(raw, url, title):
    from pypdf import PdfReader
    pdf = PdfReader(io.BytesIO(raw))
    if len(pdf.pages) > 100:
        raise ValueError('PDF exceeds 100-page extraction limit')
    text = clean(' '.join(page.extract_text() or '' for page in pdf.pages))
    if len(text) < 30:
        raise ValueError('PDF has no usable text layer; OCR/manual review required')
    return dict(title=title, text=text, published_at=None, url=url, attachments=[], images=[],
                content_hash=hashlib.sha256(text.encode()).hexdigest(), retrieved_at=NOW(),
                eligibility='待核实', attachment_status='PDF文本层已提取；排版及表格未人工核对',
                image_status='未OCR', format='pdf', pages=len(pdf.pages))

def run(source, probe=False, limit=20, pages=1):
    sid = source['id']
    folder = DATA / sid
    previous = read(folder / 'run.json', {})
    articles = {x['url']: x for x in read(folder / 'articles.json', [])}
    result = dict(id=sid, name=source['name'], url=source['url'], lastAttempt=NOW(),
                  lastSuccess=previous.get('lastSuccess'), status='error', errors=[], mode='probe' if probe else 'bounded-latest')
    try:
        reader = Reader(source['url'])
        raw, tree, final = reader.page(source['url'])
        discovered = links(tree, final)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'landing.html').write_bytes(raw)
        save(folder / 'links.json', discovered)
        result['landingTitle'] = clean(' '.join(tree.xpath('//title/text()')))
        if probe:
            result['status'] = 'reachable'
        else:
            pages_read = 1
            if sid == 'jwc-contests' and pages > 1:
                cursor_tree, cursor_url = tree, final
                visited = {final}
                for _ in range(pages - 1):
                    next_links = [urljoin(cursor_url,a.get('href')) for a in cursor_tree.xpath('//a[@href]') if clean(a.text_content()) in ('下页','下一页')]
                    if not next_links or next_links[0] in visited:
                        break
                    next_url = next_links[0]
                    if urlsplit(next_url).netloc != reader.host or '/jxgl/xkjs/' not in next_url:
                        break
                    try:
                        _, cursor_tree, cursor_url = reader.page(next_url)
                        visited.add(next_url)
                        discovered.update(links(cursor_tree, cursor_url))
                        pages_read += 1
                    except Exception as exc:
                        result['errors'].append({'url':next_url,'error':str(exc)})
                        break
            for path in SEEDS.get(sid, []):
                try:
                    _, page_tree, page_url = reader.page(urljoin(reader.base, path))
                    # Dedicated notice lists precede general homepage links.
                    discovered = {**links(page_tree, page_url), **discovered}
                except Exception as exc:
                    result['errors'].append({'url': urljoin(reader.base, path), 'error': str(exc)})
            candidates = [(u, t) for u, t in discovered.items() if ARTICLE.search(u) or urlsplit(u).path.lower().endswith('.pdf')]
            if sid == 'ruc-sis-notices':
                candidates = [(u,t) for u,t in candidates if '/ch/xxgkzw/tzggzw/' in u]
            if sid == 'jwc-contests':
                candidates = [(u,t) for u,t in candidates if '/info/1043/' in u]
            if sid == 'pku-sis-grad':
                candidates = [(u,t) for u,t in candidates if '/schoolprofile' not in u]
                candidates.sort(key=lambda x: '/enrollment' not in x[0])
            if sid == 'tsinghua-grad':
                candidates = [(u,t) for u,t in candidates if '/info/1024/' in u]
            if sid in REFERENCES:
                candidates = [(source['url'], source['name'])]
            if not candidates:
                raise ValueError('no verified article links on landing page; adapter required')
            result['candidateCount'] = len(candidates)
            result['listPagesRead'] = pages_read
            save(folder / 'discovered.json', dict(candidates))
            changed = 0
            successes = 0
            for url, title in candidates[:limit]:
                try:
                    if urlsplit(url).path.lower().endswith('.pdf'):
                        raw, final = reader.fetch(url)
                        item = extract_pdf(raw, final, title)
                    else:
                        raw, detail, final = reader.page(url)
                        item = extract(detail, final, title)
                        if item.get('parse_status') == 'media_only':
                            for attachment in item['attachments'][:2]:
                                if urlsplit(attachment['url']).netloc == reader.host and urlsplit(attachment['url']).path.endswith('.pdf'):
                                    try:
                                        pdf_raw, pdf_url = reader.fetch(attachment['url'])
                                        (folder / (hashlib.sha256(pdf_url.encode()).hexdigest()[:16] + '.pdf')).write_bytes(pdf_raw)
                                        pdf_item = extract_pdf(pdf_raw, pdf_url, title)
                                        item['text'] += '\n' + pdf_item['text']
                                        item['parse_status'] = 'embedded_pdf_text'
                                        item['attachment_status'] = '嵌入PDF文本层已提取'
                                    except Exception as exc:
                                        result['errors'].append({'url': attachment['url'], 'error': str(exc)})
                            if item['parse_status'] == 'media_only':
                                result['errors'].append({'url': url, 'error': '仅图片/附件，正文待OCR或人工核验'})
                        item['content_hash'] = hashlib.sha256(json.dumps([item['title'], item['text'], item['attachments'], item['images']],ensure_ascii=False).encode()).hexdigest()
                    item['id'] = sid + '-' + hashlib.sha256(final.encode()).hexdigest()[:16]
                    item['sourceId'], item['sourceName'] = sid, source['name']
                    old = articles.get(final)
                    if old is None or old['content_hash'] != item['content_hash']:
                        changed += 1
                    articles[final] = item
                    (folder / (item['id'] + ('.pdf' if item.get('format') == 'pdf' else '.html'))).write_bytes(raw)
                    successes += 1
                except Exception as exc:
                    result['errors'].append({'url': url, 'error': str(exc)})
                    if url not in articles:
                        articles[url] = dict(id=sid+'-'+hashlib.sha256(url.encode()).hexdigest()[:16],
                            sourceId=sid,sourceName=source['name'],url=url,title=title[:180],text='',
                            published_at=None,retrieved_at=None,last_attempt=NOW(),parse_status='list_only',
                            content_hash='',attachments=[],images=[],eligibility='正文获取失败，仅列表线索')
            result.update(changedArticles=changed, fetchedArticles=successes, limit=limit,
                          coverage=f'读取 {pages_read} 个列表页；发现 {len(candidates)} 个详情链接；本次最多读取 {limit} 条。其他栏目不在本轮范围。')
            if successes:
                result['lastSuccess'] = NOW()
                result['status'] = 'warning' if result['errors'] else 'ok'
            else:
                result['errors'].append({'error': 'no article body successfully parsed'})
    except Exception as exc:
        result['errors'].append({'error': str(exc)})
    result['count'] = len(articles)
    if not probe:
        save(folder / 'articles.json', list(articles.values()))
    save(folder / ('probe.json' if probe else 'run.json'), result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', action='append')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--pages', type=int, default=1, help='contest list pagination, max 60')
    args = parser.parse_args()
    sources = read(ROOT / 'sources.json', {})['sources']
    for source in sources:
        if source['id'] == 'sis':
            continue
        if args.source and source['id'] not in args.source:
            continue
        if not args.source and not args.probe and not source.get('enabled'):
            continue
        run(source, args.probe, max(1, min(args.limit, 600)), max(1,min(args.pages,60)))

if __name__ == '__main__':
    main()
