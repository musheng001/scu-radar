import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lxml import html
import collect_sources as c
import update_radar as dashboard
import collect_competition_api as competition_api
import secretary_brief as secretary

class CollectorTests(unittest.TestCase):
    def test_title_metadata_and_publication_not_deadline(self):
        tree=html.fromstring('<html><head><meta name="ArticleTitle" content="招生通知"><meta name="PubDate" content="2026-09-01"></head><body><div id="vsb_content">报名时间：2026年11月15日。申请材料请在截止前提交并认真核对。</div></body></html>')
        item=c.extract(tree,'https://example.edu/a.htm','wrong summary')
        self.assertEqual(item['title'],'招生通知')
        self.assertTrue(item['published_at'].startswith('2026-09-01'))

    def test_body_date_not_publication(self):
        tree=html.fromstring('<div id="vsb_content">报名时间：2026年11月15日。申请材料请在截止前提交并认真核对。</div>')
        self.assertIsNone(c.extract(tree,'https://example.edu/a.htm','title')['published_at'])

    def test_media_only_is_explicit(self):
        tree=html.fromstring('<div id="vsb_content"><img src="/poster.jpg"></div>')
        item=c.extract(tree,'https://example.edu/a.htm','title')
        self.assertEqual(item['parse_status'],'media_only')
        self.assertEqual(item['images'],['https://example.edu/poster.jpg'])

    def test_navigation_not_body(self):
        with self.assertRaises(ValueError):
            c.extract(html.fromstring('<div>首页 导航 菜单</div>'),'https://example.edu/','title')

    def test_no_cross_host_or_script_links(self):
        tree=html.fromstring('<div><a href="javascript:alert(1)">x</a><a href="https://evil.test/a">x</a><a href="/info/12/123.htm">notice</a></div>')
        self.assertEqual(list(c.links(tree,'https://example.edu/')),['https://example.edu/info/12/123.htm'])

    def test_failure_preserves_successful_snapshot(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(c,'DATA',Path(folder)), patch.object(c,'Reader',side_effect=RuntimeError('offline')):
            old=[{'url':'https://example.edu/a','title':'preserve'}]
            c.save(Path(folder)/'test'/'articles.json',old)
            c.save(Path(folder)/'test'/'run.json',{'lastSuccess':'previous'})
            result=c.run({'id':'test','name':'test','url':'https://example.edu/'})
            self.assertEqual(result['status'],'error')
            self.assertEqual(result['lastSuccess'],'previous')
            self.assertEqual(c.read(Path(folder)/'test'/'articles.json',[]),old)

    def test_null_date_does_not_break_build(self):
        score,_=dashboard.score_item({'title':'通知','published_at':None},'教务规则','','')
        self.assertIsInstance(score,int)

    def test_teacher_and_graduate_not_current_opportunity(self):
        for title in ['教师教学创新竞赛通知','北京大学2027年推免研究生招生办法','2026年奖学金初评名单']:
            note, excluded = dashboard.audience_note({'title':title,'text':''},'pku-sis')
            self.assertTrue(excluded, title)

    def test_live_snapshots_have_valid_shapes(self):
        for path in c.DATA.glob('*/articles.json'):
            for item in c.read(path,[]):
                self.assertLessEqual(len(item['title']),200, str(path))
                self.assertTrue(item['url'].startswith(('https://','http://')))
                self.assertTrue(item['id'].startswith(item['sourceId']+'-'))

    def test_competition_api_fixture_is_metadata_only(self):
        fixture = c.ROOT / 'external-data' / 'scu-contests' / 'public-api-sample.json'
        payload = competition_api.read_json(fixture, {})
        records, page = competition_api.parse_payload(payload)
        self.assertEqual(page['total'], 62)
        item = competition_api.normalize(records[0])
        self.assertEqual(item['parse_status'], 'api_metadata')
        self.assertIn('资格与截止时间待核实', item['eligibility'])
        self.assertIn('competitionId=', item['url'])
        self.assertEqual(item['sourceId'], 'scu-contests')

    def test_competition_api_fixture_collection_is_bounded(self):
        fixture = c.ROOT / 'external-data' / 'scu-contests' / 'public-api-sample.json'
        with tempfile.TemporaryDirectory() as folder, patch.object(competition_api, 'FOLDER', Path(folder)):
            result = competition_api.collect(fixture=fixture, pages=60)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual(result['count'], 6)
            saved = competition_api.read_json(Path(folder) / 'articles.json', [])
            self.assertEqual(len(saved), 6)
            self.assertTrue(all(x['url'].startswith('http://xkjs.scu.edu.cn/') for x in saved))

    def test_competition_api_request_is_public_and_same_origin(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, limit): return b'{"code":0,"data":{"records":[],"total":0,"pages":0}}'
        with patch.object(competition_api, 'urlopen', return_value=Response()) as opened:
            payload, url = competition_api.fetch_page('http://xkjs.scu.edu.cn/home/homepage', 1, 6)
            request = opened.call_args.args[0]
            self.assertEqual(payload['code'], 0)
            self.assertIn('/prod-api/home/notice/list?', url)
            self.assertIsNone(request.get_header('Authorization'))
            self.assertEqual(request.full_url.split('/prod-api')[0], 'http://xkjs.scu.edu.cn')

    def test_secretary_brief_is_review_first_and_connector_agnostic(self):
        data = secretary.read_radar()
        brief = secretary.make_brief(data)
        self.assertEqual(brief['summary']['total'], len(data['items']))
        self.assertLessEqual(len(brief['actionItems']), 12)
        self.assertLessEqual(len(brief['competitions']), 12)
        markdown = secretary.render_markdown(brief)
        self.assertIn('川大雷达 · 秘书简报', markdown)
        self.assertIn('不把关键词命中', markdown)

    def test_secretary_brief_writes_json_and_markdown(self):
        data = {'generatedAt': '2026-09-26T00:00:00+08:00', 'mode': 'test', 'items': [], 'sources': [], 'channels': {}}
        with tempfile.TemporaryDirectory() as folder:
            brief = secretary.write_brief(data, Path(folder) / 'brief.md', Path(folder) / 'brief.json')
            self.assertEqual(brief['summary']['total'], 0)
            self.assertTrue((Path(folder) / 'brief.md').exists())
            self.assertEqual(secretary.read_json(Path(folder) / 'brief.json', {})['summary']['total'], 0)

if __name__=='__main__':
    unittest.main()
