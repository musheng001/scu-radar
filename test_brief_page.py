import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from lxml import html
from brief_page import render_html
from secretary_brief import write_brief


class BriefPageTests(unittest.TestCase):
    def test_untrusted_feed_is_text_and_links_are_safe(self):
        brief = {'actionItems': [{'title':'<script>alert(1)</script>', 'url':'javascript:alert(1)', 'category':'竞赛'}], 'sourceWarnings': [], 'summary': {}}
        page = render_html(brief, {})
        tree = html.fromstring(page)
        self.assertFalse(tree.xpath('//script'))
        self.assertFalse(tree.xpath('//a[starts-with(@href,"javascript:")]'))
        self.assertIn('&lt;script&gt;', page)

    def test_offline_output_in_requested_directory(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            write_brief({'items': [], 'sources': []}, root/'sample.md', root/'sample.json')
            page = (root/'sample.html').read_text(encoding='utf-8')
            self.assertIn('本学期课程', page)
            self.assertNotIn('fetch(', page)
            self.assertIn('第 13 周为 5—6 节', page)


if __name__ == '__main__':
    unittest.main()
