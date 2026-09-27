"""Inspect only public scripts linked by a registered public landing page."""
from collect_sources import *
import sys

for sid in sys.argv[1:]:
    source=next(s for s in read(ROOT/'sources.json',{})['sources'] if s['id']==sid)
    reader=Reader(source['url'])
    tree=html.fromstring((DATA/sid/'landing.html').read_bytes())
    base_nodes=tree.xpath('//base/@href')
    base=urljoin(source['url'],base_nodes[0]) if base_nodes else source['url']
    scripts=[urljoin(base,s) for s in tree.xpath('//script[@src]/@src') if 'upload/portal/' in s or 'assets/index-' in s]
    for i,url in enumerate(scripts):
        raw,final=reader.fetch(url)
        text=raw.decode('utf-8',errors='replace')
        (DATA/sid/f'public-script-{i}.js').write_text(text,encoding='utf-8')
        print(sid,final,len(raw))
        matches=list(re.finditer(r'baseURL|axios|\.ajax\(|fetch\(|/api/|/entry/|competition|news/list|article/list',text,re.I))
        for m in matches[:35]:
            print(text[max(0,m.start()-80):m.end()+150])
