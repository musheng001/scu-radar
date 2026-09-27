"""Read-only DOM diagnostics for stored source links; no browser or login automation."""
from collect_sources import *
import sys

for sid in sys.argv[1:]:
    source = next(s for s in read(ROOT / 'sources.json', {})['sources'] if s['id'] == sid)
    health = read(DATA / sid / 'run.json', {})
    failure = next((e['url'] for e in health.get('errors', []) if e.get('url')), None)
    discovered = read(DATA / sid / 'links.json', {})
    print('\nSOURCE', sid, flush=True)
    if not failure:
        print('LINKS', list(discovered.items())[-18:], flush=True)
        continue
    try:
        raw, tree, final = Reader(failure).page(failure)
        path = DATA / sid / 'diagnostic.html'
        path.write_bytes(raw)
        print('URL', final)
        print('META', tree.xpath('//meta[@name="ArticleTitle"]/@content|//meta[@name="PubDate"]/@content'))
        print('HEADINGS', [(e.tag, clean(e.text_content())[:100]) for e in tree.xpath('//h1|//h2|//h3')][-10:])
        print('DIVS', [(e.tag,e.get('id'),e.get('class'),len(clean(e.text_content())),clean(e.text_content())[:80]) for e in tree.xpath('//div[@class or @id]') if 15 < len(clean(e.text_content())) < 14000][-17:], flush=True)
    except Exception as exc:
        print(type(exc).__name__, str(exc), flush=True)
