"""Validate the SEO contract of a static production build before media rewriting."""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

class Head(HTMLParser):
    def __init__(self):
        super().__init__(); self.canonical = ''; self.robots = ''; self.h1 = 0
        self.schemas = []; self.capture = False; self.buffer = ''; self.images = []; self.links = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'h1': self.h1 += 1
        if tag == 'a': self.links.append(a.get('href', ''))
        if tag == 'link' and a.get('rel') == 'canonical': self.canonical = a.get('href', '')
        if tag == 'meta' and a.get('name') == 'robots': self.robots = a.get('content', '')
        if tag == 'script' and a.get('type') == 'application/ld+json': self.capture = True; self.buffer = ''
        if tag == 'img':
            self.images.append(a.get('src', ''))
            self.images.extend(part.strip().split()[0] for part in a.get('srcset', '').split(',') if part.strip())
    def handle_data(self, text):
        if self.capture: self.buffer += text
    def handle_endtag(self, tag):
        if tag == 'script' and self.capture:
            self.schemas.append(json.loads(self.buffer)); self.capture = False

root = Path(sys.argv[1] if len(sys.argv)>1 else 'dist')
project = Path(__file__).resolve().parents[1]
manifest = json.loads((project / 'media-manifest.json').read_text('utf-8'))
namespace = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
urls = [node.text for node in ET.parse(root/'sitemap-0.xml').findall('s:url/s:loc', namespace)]
assert urls, 'Empty sitemap'
for url in urls:
    parsed = urlsplit(url)
    assert parsed.path.endswith('/'), f'Sitemap URL lacks slash: {url}'
    file = root / parsed.path.lstrip('/') / 'index.html'
    page = Head(); page.feed(file.read_text('utf-8'))
    assert page.canonical == url, f'Canonical differs from sitemap: {url}: {page.canonical}'
    assert 'noindex' not in page.robots, f'Indexed page marked noindex: {url}'
    assert page.h1 == 1, f'Expected one H1: {url}'
    if parsed.path.startswith('/blog/') and parsed.path != '/blog/':
        article = next(s for s in page.schemas if s.get('@type') == 'BlogPosting')
        assert article['mainEntityOfPage']['@id'] == url
        assert article.get('datePublished') and article.get('author')
        assert any(s.get('@type') == 'BreadcrumbList' for s in page.schemas)
    for image in page.images:
        if image.startswith('/'):
            if not (root / image.lstrip('/')).is_file():
                record = manifest.get(image)
                assert record, f'Image missing from build and media manifest: {image}'
                if record.get('repository'):
                    assert (project / record['repository']).is_file(), f'Missing registered media: {image}'
                # Legacy media lives on hosting; the upload/deployment step checks it.
    for link in page.links:
        path = urlsplit(link).path
        if link.startswith('/') and not link.startswith('//') and not re.search(r'\.[a-z0-9]+$', path, re.I):
            assert path.endswith('/'), f'Internal page link lacks slash: {url}: {link}'
source = Path(__file__).resolve().parents[1] / 'src/content/blog'
for file in source.glob('*.md'):
    text = file.read_text('utf-8').split('---', 2)[1]
    slug = re.search(r'^slug:\s*["\']?([^"\'\s]+)', text, re.M).group(1)
    draft = re.search(r'^draft:\s*true\s*$', text, re.M) is not None
    present = any(urlsplit(u).path == f'/blog/{slug}/' for u in urls)
    assert present != draft, f'Published/draft state differs from sitemap: {slug}'
print(f'SEO build checks passed: {len(urls)} public URLs; canonical, drafts, schema and images')
