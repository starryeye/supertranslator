"""Reader behavior, not a copy of the exporter implementation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from supertranslator.cli import main


@pytest.mark.parametrize("evidence", [None, {}, {"schema_version": "1.0", "semantic_input_sha256": "0" * 64,
    "approval_sha256": "1" * 64, "html_sha256": "2" * 64},
    {"schema_version": "2.0", "semantic_input_sha256": "0" * 64, "approval_sha256": "1" * 64, "html_sha256": "2" * 64},
    {"schema_version": "1.0", "semantic_input_sha256": "A" * 64, "approval_sha256": "1" * 64, "html_sha256": "2" * 64},
    {"schema_version": "1.0", "semantic_input_sha256": "0" * 64, "approval_sha256": 1, "html_sha256": "2" * 64},
    {"schema_version": "1.0", "semantic_input_sha256": "0" * 64, "approval_sha256": "1" * 64, "html_sha256": "2" * 64, "extra": True}])
def test_reader_refuses_missing_or_mismatched_web_integrity(bundle, evidence):
    source, _, output = bundle
    path = source / "manifest.json"
    manifest = json.loads(path.read_bytes())
    if evidence is None:
        manifest.pop("web_integrity", None)
    else:
        manifest["web_integrity"] = evidence
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match="web.integrity|semantic review"):
        export(bundle)
    assert not output.exists()
    assert {p.name: p.read_bytes() for p in source.iterdir() if p.is_file()} == before


def test_reader_refuses_modified_html_even_with_fresh_reader_review(bundle):
    source, review_path, output = bundle
    path = source / "index.html"
    path.write_bytes(path.read_bytes().replace("테스트 문서".encode(), "다른 문서".encode()))
    review = json.loads(review_path.read_bytes())
    review["input_html_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    review_path.write_text(json.dumps(review), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="web_integrity HTML digest mismatch"):
        export(bundle)
    assert path.read_bytes() == before
    assert not output.exists()


@pytest.fixture
def bundle(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "assets").mkdir()
    (source / "assets" / "picture.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
    , encoding="utf-8", newline="")
    html = '''<!doctype html><html><head><title>Viewer</title></head><body>
    <nav>원문 사이트 메뉴</nav><article id="doc" style="font-size:8px">
    <h1 id="title">테스트 문서</h1><h2 id="section-1">1. 소개</h2>
    <p id="left">클라이언트는 접근을 <a href="#section-1">허용</a>해야 합니다(MUST).</p>
    <pre id="blank">\n</pre><pre id="page"><span id="page-2"></span>Author [Page 2]</pre>
    <p id="right">이 조건은 두 요청 모두에 적용됩니다.</p>
    <p id="item">   o  목록의 내용이 여러 줄로 표시됩니다.</p>
    <pre id="code">GET /?a=1&amp;b=2 HTTP/1.1\n+------------------------------+\n| Client             Server    |\n+------------------------------+</pre>
    <img src="assets/picture.svg" alt="그림"><script>alert(1)</script>
    </article><aside>원문 사이트 패널</aside></body></html>'''
    (source / "index.html").write_text(html, encoding="utf-8", newline="")
    (source / "manifest.json").write_text(json.dumps({
        "qa_status": "passed", "required_findings": [],
        "web_integrity": {"schema_version": "1.0", "semantic_input_sha256": "0" * 64,
            "approval_sha256": "1" * 64, "html_sha256": hashlib.sha256(html.encode()).hexdigest()},
        "source_url": "https://example.com/spec", "tool": {"version": "0.8.0"},
    }), encoding="utf-8", newline="")
    (source / "review-report.md").write_text("Input review", encoding="utf-8", newline="")
    review = {
        "schema_version": "1.0", "input_html_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "content_selector": "#doc", "title": "테스트 문서",
        "removals": [{"selector": "#page", "text_sha256": hashlib.sha256(b"Author [Page 2]").hexdigest(), "reason": "Repeated page furniture"}],
        "joins": [{"selectors": ["#left", "#right"]}],
        "heading_levels": {}, "list_items": ["#item"],
    }
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8", newline="")
    return source, review_path, tmp_path / "output"


def export(bundle, change=None):
    from supertranslator import reader
    source, review_path, output = bundle
    if change:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        change(review)
        review_path.write_text(json.dumps(review), encoding="utf-8", newline="")
    return reader.export_reader(source, review_path, output)


def test_exports_reading_article_without_viewer_and_preserves_exact_literals(bundle):
    path = export(bundle)
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    assert soup.select_one("nav, script, aside") is None
    article = soup.select_one(".st-reader")
    assert article is not None
    assert article.find(id="left").get_text() == "클라이언트는 접근을 허용해야 합니다(MUST). 이 조건은 두 요청 모두에 적용됩니다."
    assert article.find(id="right") is not None  # Old fragment destination remains.
    assert article.find(id="page-2") is not None
    assert article.find(id="page").find_parent("details") is not None
    assert article.find(id="code").get_text() == "GET /?a=1&b=2 HTTP/1.1\n+------------------------------+\n| Client             Server    |\n+------------------------------+"
    assert article.select_one("a[href='#section-1']").get_text() == "허용"
    assert article.find(id="item").get("role") == "listitem"
    fragment = BeautifulSoup((path.parent / "article.html").read_text(encoding="utf-8"), "html.parser")
    assert str(fragment.select_one(".st-reader")) == str(article)
    assert (path.parent / "assets/picture.svg").read_bytes() == (bundle[0] / "assets/picture.svg").read_bytes()
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["qa_status"] == "pending-visual-review"
    assert manifest["input_html_sha256"] == json.loads(bundle[1].read_text(encoding="utf-8"))["input_html_sha256"]


def _replace_reviewed_item(bundle, markup, selectors):
    source, review_path, _ = bundle
    soup = BeautifulSoup((source / "index.html").read_bytes(), "lxml")
    fragment = BeautifulSoup(markup, "html.parser")
    item = soup.find(id="item")
    for child in list(fragment.contents):
        item.insert_before(child.extract())
    item.decompose()
    data = str(soup).encode("utf-8")
    (source / "index.html").write_bytes(data)
    _bind_synthetic_html(source, data)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review.update(input_html_sha256=hashlib.sha256(data).hexdigest(), list_items=selectors)
    review_path.write_text(json.dumps(review), encoding="utf-8", newline="")


def test_reviewed_list_item_has_an_owning_list(bundle):
    soup = BeautifulSoup(export(bundle).read_bytes(), "lxml")
    item = soup.find(id="item")
    assert item.parent.get("role") == "list"
    assert item.name == "p"
    assert item.get_text() == "   o  목록의 내용이 여러 줄로 표시됩니다."


def test_reviewed_definition_separates_term_without_changing_text_or_inline_links(bundle):
    _replace_reviewed_item(bundle, '<p id="item"><a id="term" href="#section-1">verifier</a>\n  두 요청을 연결하는 값입니다.</p>', [])
    structure = {"definitions": [{"selector": "#item", "term_end": 8, "evidence": "Source term precedes its definition."}], "lists": []}
    soup = BeautifulSoup(export(bundle, lambda r: r.update(structure=structure)).read_bytes(), "lxml")
    definition = soup.find(id="item")
    assert definition.select_one('.st-definition-term').get_text() == "verifier"
    assert definition.select_one('.st-definition-description').get_text() == "\n  두 요청을 연결하는 값입니다."
    assert definition.get_text() == "verifier\n  두 요청을 연결하는 값입니다."
    assert str(definition.find(id="term")) == '<a href="#section-1" id="term">verifier</a>'
    assert soup.find(id="code").get_text() == "GET /?a=1&b=2 HTTP/1.1\n+------------------------------+\n| Client             Server    |\n+------------------------------+"
    manifest = json.loads((bundle[2] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest['structure'] == structure


def test_reviewed_lists_keep_child_under_parent_and_groups_separate(bundle):
    _replace_reviewed_item(bundle,
        '<p id="item">4. 다음 중 하나입니다.</p>\n<span id="gap"><a id="old"></a></span>'
        '<p id="child">4a. 응답을 관찰합니다.</p><p id="grandchild">세부 조건입니다.</p>'
        '<p id="sibling">4b. 요청도 관찰합니다.</p><p id="last">5. 마지막 조건입니다.</p>'
        '<p id="record">o 이름: example</p><p id="owner">o 주체: IESG</p>', [])
    structure = {"definitions": [], "lists": [
        {"items": [{"selector": s, "depth": d} for s, d in [("#item", 0), ("#child", 1), ("#grandchild", 2), ("#sibling", 1), ("#last", 0)]], "evidence": "Source shows parent and child indentation."},
        {"items": [{"selector": "#record", "depth": 0}, {"selector": "#owner", "depth": 0}], "evidence": "Separate source registration record."},
    ]}
    soup = BeautifulSoup(export(bundle, lambda r: r.update(structure=structure)).read_bytes(), "lxml")
    item, child, grandchild, sibling, last, record = [soup.find(id=i) for i in ['item', 'child', 'grandchild', 'sibling', 'last', 'record']]
    parent_item = item.parent
    assert parent_item.get('role') == 'listitem'
    assert child.parent.parent.get('role') == 'list'
    assert child.parent.parent.parent is parent_item
    assert grandchild.parent.parent.parent is child.parent
    assert sibling.parent.parent is child.parent.parent
    assert last.parent.parent is parent_item.parent
    assert record.parent.parent is not parent_item.parent
    assert [t['id'] for t in parent_item.parent.find_all(id=True)] == ['item', 'gap', 'old', 'child', 'grandchild', 'sibling', 'last']
    assert parent_item.parent.get_text() == '4. 다음 중 하나입니다.\n4a. 응답을 관찰합니다.세부 조건입니다.4b. 요청도 관찰합니다.5. 마지막 조건입니다.'


@pytest.mark.parametrize('offset', [None, True, -1, 0, 1.5, 15, 99, '8'])
def test_invalid_definition_boundary_does_not_publish(bundle, offset):
    _replace_reviewed_item(bundle, '<p id="item">verifier 설명입니다.</p>', [])
    with pytest.raises(ValueError, match='structure'):
        export(bundle, lambda r: r.update(structure={"definitions": [{"selector": "#item", "term_end": offset, "evidence": "Reviewed."}], "lists": []}))
    assert not bundle[2].exists()


def test_definition_boundary_inside_an_inline_subtree_is_rejected(bundle):
    _replace_reviewed_item(bundle, '<p id="item"><a href="#section-1">verifier 설명</a>입니다.</p>', [])
    with pytest.raises(ValueError, match='structure'):
        export(bundle, lambda r: r.update(structure={"definitions": [{"selector": "#item", "term_end": 8, "evidence": "Reviewed."}], "lists": []}))
    assert not bundle[2].exists()


def test_definition_boundary_ignores_comments_removed_by_sanitization(bundle):
    _replace_reviewed_item(bundle, '<p id="item"><!--x--><a href="#section-1">verifier</a> 설명입니다.</p>', [])
    structure = {'definitions': [{'selector': '#item', 'term_end': 8, 'evidence': 'Reviewed inline label; comments are not text.'}], 'lists': []}
    soup = BeautifulSoup(export(bundle, lambda r: r.update(structure=structure)).read_bytes(), 'lxml')
    assert soup.find(id='item').select_one('.st-definition-term').get_text() == 'verifier'
    assert soup.find(id='item').select_one('.st-definition-description').get_text() == ' 설명입니다.'


def test_existing_projected_item_gets_one_structured_owner(bundle):
    _replace_reviewed_item(bundle, '<div id="item" role="listitem" data-wt-preformatted-depth="0">1. 항목입니다.</div>', [])
    structure = {'definitions': [], 'lists': [{'items': [{'selector': '#item', 'depth': 0}], 'evidence': 'Reviewed original list item.'}]}
    soup = BeautifulSoup(export(bundle, lambda r: r.update(structure=structure)).read_bytes(), 'lxml')
    assert soup.find(id='item').parent.get('role') == 'listitem'
    assert soup.find(id='item').get('role') is None
    assert len(soup.select('[role="listitem"]')) == 1


@pytest.mark.parametrize('markup', [
    '<p id="item">   설명입니다.</p>', '<p id="item">verifier   </p>',
    '<div id="item">verifier<p>설명입니다.</p></div>',
    '<ul><li><p id="item">verifier 설명입니다.</p></li></ul>',
    '<div role="list"><div role="listitem"><p id="item">verifier 설명입니다.</p></div></div>',
])
def test_unsafe_definition_targets_are_rejected(bundle, markup):
    _replace_reviewed_item(bundle, markup, [])
    offset = 3 if '   설명' in markup else 8
    with pytest.raises(ValueError, match='structure'):
        export(bundle, lambda r: r.update(structure={"definitions": [{"selector": "#item", "term_end": offset, "evidence": "Reviewed."}], "lists": []}))
    assert not bundle[2].exists()


@pytest.mark.parametrize('structure', [
    None, [], {}, {'definitions': [], 'lists': [], 'extra': []},
    {'definitions': None, 'lists': []}, {'definitions': [], 'lists': {}},
    {'definitions': [{'selector': '#item', 'term_end': 1}], 'lists': []},
    {'definitions': [{'selector': '', 'term_end': 1, 'evidence': 'Reviewed.'}], 'lists': []},
    {'definitions': [{'selector': '#item', 'term_end': 1, 'evidence': ' '}], 'lists': []},
    {'definitions': [], 'lists': [{'items': [], 'evidence': 'Reviewed.'}]},
    {'definitions': [], 'lists': [{'items': [{'selector': '#item', 'depth': 0, 'extra': 0}], 'evidence': 'Reviewed.'}]},
])
def test_malformed_structure_is_not_ignored(bundle, structure):
    with pytest.raises(ValueError, match='structure'):
        export(bundle, lambda r: r.update(structure=structure))
    assert not bundle[2].exists()


@pytest.mark.parametrize('selectors,depths', [
    (['#item', '#second'], [1, 1]), (['#item', '#second'], [0, 2]),
    (['#item', '#second'], [0, -1]), (['#item', '#second'], [0, True]),
    (['#item', '#second'], [0, '1']), (['#item', '#item'], [0, 0]),
    (['#second', '#item'], [0, 0]), (['#item', '#code'], [0, 0]),
    (['#item', '#page'], [0, 0]), (['#item', '#doc'], [0, 0]),
])
def test_invalid_structured_list_is_rejected(bundle, selectors, depths):
    _replace_reviewed_item(bundle, '<p id="item">1. 첫 항목</p><p id="second">a. 다음 항목</p>', [])
    structure = {'definitions': [], 'lists': [{'items': [{'selector': s, 'depth': d} for s, d in zip(selectors, depths)], 'evidence': 'Reviewed.'}]}
    with pytest.raises(ValueError, match='structure'):
        export(bundle, lambda r: r.update(structure=structure))
    assert not bundle[2].exists()


@pytest.mark.parametrize('barrier', ['<p>별도 설명</p>', '<h3>제목</h3>', '<pre>literal</pre>', '<span>내용</span>'])
def test_structured_list_cannot_swallow_unreviewed_content(bundle, barrier):
    _replace_reviewed_item(bundle, '<p id="item">첫 항목</p>' + barrier + '<p id="second">다음 항목</p>', [])
    structure = {'definitions': [], 'lists': [{'items': [{'selector': '#item', 'depth': 0}, {'selector': '#second', 'depth': 0}], 'evidence': 'Reviewed.'}]}
    with pytest.raises(ValueError, match='structure'):
        export(bundle, lambda r: r.update(structure=structure))
    assert not bundle[2].exists()


@pytest.mark.parametrize('collision', ['old-list', 'definition-list', 'duplicate-definition', 'duplicate-list', 'presentation'])
def test_conflicting_structure_selections_are_rejected(bundle, collision):
    _replace_reviewed_item(bundle, '<p id="item">verifier 설명입니다.</p>', ['#item'] if collision == 'old-list' else [])
    definition = {'selector': '#item', 'term_end': 8, 'evidence': 'Reviewed.'}
    group = {'items': [{'selector': '#item', 'depth': 0}], 'evidence': 'Reviewed.'}
    structure = {'definitions': [definition], 'lists': []}
    if collision == 'definition-list': structure['lists'] = [group]
    if collision == 'duplicate-definition': structure['definitions'].append(definition)
    if collision == 'duplicate-list': structure = {'definitions': [], 'lists': [group, group]}
    def change(review):
        review['structure'] = structure
        if collision == 'presentation':
            review['presentation'] = {'toc_selectors': ['#item'], 'metadata_selectors': [], 'title_selectors': [], 'navigation': False}
    with pytest.raises(ValueError):
        export(bundle, change)
    assert not bundle[2].exists()


def test_positional_edits_and_structure_resolve_before_wrapping(bundle):
    _replace_reviewed_item(bundle,
        '<p id="item">先頭 説明</p><p id="second">client가 검사합니다.</p><p id="third">server가 응답합니다.</p>', [])
    def change(review):
        review['structure'] = {'definitions': [{'selector': '#doc > p:nth-of-type(2)', 'term_end': 2, 'evidence': 'Reviewed Japanese label, not an English heuristic.'}],
            'lists': [{'items': [{'selector': '#doc > p:nth-of-type(3)', 'depth': 0}, {'selector': '#doc > p:nth-of-type(4)', 'depth': 1}], 'evidence': 'Reviewed.'}]}
        review['text_edits'] = [{'selector': '#doc > p:nth-of-type(4)', 'input_html_sha256': hashlib.sha256('server가 응답합니다.'.encode()).hexdigest(),
            'replacement_html': 'server가 응답을 보냅니다.', 'source_text': 'The server responds.', 'evidence': 'AI comparison retains the actor and response.'}]
    soup = BeautifulSoup(export(bundle, change).read_bytes(), 'lxml')
    assert soup.find(id='item').select_one('.st-definition-term').get_text() == '先頭'
    assert soup.find(id='third').get_text() == 'server가 응답을 보냅니다.'
    assert soup.find(id='third').parent.parent.parent is soup.find(id='second').parent


def test_unreviewed_structure_markers_cannot_authorize_layout(bundle):
    _replace_reviewed_item(bundle, '<p id="item" class="st-definition st-definition-term" data-reader-structure="definition">본문은 그대로입니다.</p>', [])
    soup = BeautifulSoup(export(bundle, lambda r: r.update(structure={'definitions': [], 'lists': []})).read_bytes(), 'lxml')
    assert not soup.select('.st-definition,.st-definition-term')
    assert soup.find(id='item').get_text() == '본문은 그대로입니다.'


@pytest.mark.parametrize('width', [1440, 768, 390])
def test_reviewed_structure_renders_separated_readable_groups(bundle, width):
    from playwright.sync_api import sync_playwright
    _replace_reviewed_item(bundle,
        '<p id="item">VeryLongTechnicalParameterNameWithNoSpaces\n설명과 조건을 읽을 수 있어야 합니다.</p>'
        '<p id="parent">4. 다음 조건</p><p id="child">4a. 하위 조건</p>'
        '<p id="record">o 다음 등록 자료</p>', [])
    structure = {'definitions': [{'selector': '#item', 'term_end': 42, 'evidence': 'Reviewed name boundary.'}],
        'lists': [{'items': [{'selector': '#parent', 'depth': 0}, {'selector': '#child', 'depth': 1}], 'evidence': 'Reviewed hierarchy.'},
                  {'items': [{'selector': '#record', 'depth': 0}], 'evidence': 'Separate record.'}]}
    # The literal is a hand-counted label, not derived by the production splitter.
    assert len('VeryLongTechnicalParameterNameWithNoSpaces') == 42
    path = export(bundle, lambda r: r.update(structure=structure))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900})
            page.goto(path.as_uri())
            term = page.locator('#item .st-definition-term').bounding_box()
            description = page.locator('#item .st-definition-description').bounding_box()
            assert description['y'] >= term['y'] + term['height']
            assert description['width'] >= min(width - 80, 300)
            parent = page.locator('#parent').bounding_box()
            child = page.locator('#child').bounding_box()
            record = page.locator('#record').bounding_box()
            assert child['x'] > parent['x']
            assert record['y'] - child['y'] - child['height'] >= 16
            assert page.locator('#child').evaluate('(el) => parseFloat(getComputedStyle(el).fontSize)') >= 16
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


def test_contiguous_reviewed_items_keep_anchor_spacers_and_exact_text(bundle):
    _replace_reviewed_item(bundle,
        '<p id="item">o client MUST 검증합니다.</p>\n<span id="boundary"><a id="old-anchor"></a></span>\n'
        '<div id="second">o <a href="#section-1">server</a>가 응답합니다.</div>',
        ["#item", "#second"])
    before = BeautifulSoup((bundle[0] / "index.html").read_bytes(), "lxml")
    soup = BeautifulSoup(export(bundle).read_bytes(), "lxml")
    first, second = soup.find(id="item"), soup.find(id="second")
    assert first.parent is second.parent
    assert first.parent.get("role") == "list"
    assert [tag["id"] for tag in first.parent.find_all(id=True)] == ["item", "boundary", "old-anchor", "second"]
    assert first.parent.get_text() == "o client MUST 검증합니다.\n\no server가 응답합니다."
    assert soup.find(id="code").get_text() == before.find(id="code").get_text()
    assert second.a["href"] == "#section-1"


@pytest.mark.parametrize("barrier", [
    '<p id="between">별도 설명</p>', '<h3 id="between">제목</h3>',
    '<pre id="between">GET / HTTP/1.1</pre>', '<span id="between">주석 내용</span>',
])
def test_reviewed_list_groups_never_swallow_unreviewed_content(bundle, barrier):
    _replace_reviewed_item(bundle, '<p id="item">첫 항목</p>' + barrier + '<p id="second">둘째 항목</p>',
                           ["#item", "#second"])
    soup = BeautifulSoup(export(bundle).read_bytes(), "lxml")
    first, second, middle = (soup.find(id=name) for name in ["item", "second", "between"])
    assert first.parent.get("role") == second.parent.get("role") == "list"
    assert first.parent is not second.parent
    assert middle.find_parent(attrs={"role": "list"}) is None


def test_reviewed_item_with_existing_aria_list_parent_is_not_wrapped_again(bundle):
    _replace_reviewed_item(bundle, '<div id="owner" role="list"><p id="item">목록 항목</p></div>', ["#item"])
    soup = BeautifulSoup(export(bundle).read_bytes(), "lxml")
    assert soup.find(id="item").parent is soup.find(id="owner")
    assert len(soup.select('[role="list"]')) == 1


def test_generic_wrappers_do_not_interrupt_existing_list_ownership(bundle):
    _replace_reviewed_item(bundle,
        '<div id="owner" role="list"><div><section><p id="item">목록 항목</p></section></div></div>',
        ["#item"])
    soup = BeautifulSoup(export(bundle).read_bytes(), "lxml")
    assert len(soup.select('[role="list"]')) == 1
    assert soup.find(id="item").find_parent(attrs={"role": "list"}) is soup.find(id="owner")


@pytest.mark.parametrize("barrier", [
    '<h2 id="between" data-reader-list="true">검토하지 않은 제목</h2>',
    '<p id="between" data-reader-list="true">검토하지 않은 문단</p>',
])
def test_source_markers_cannot_impersonate_explicitly_reviewed_items(bundle, barrier):
    _replace_reviewed_item(bundle, '<p id="item">첫 항목</p>' + barrier + '<p id="second">둘째 항목</p>',
                           ["#item", "#second"])
    soup = BeautifulSoup(export(bundle).read_bytes(), "lxml")
    assert soup.find(id="item").parent is not soup.find(id="second").parent
    assert soup.find(id="between").find_parent(attrs={"role": "list"}) is None
    assert soup.find(id="between").get("role") != "listitem"


@pytest.mark.parametrize("parent", ['<div role="list">', '<ul>'])
def test_reviewed_prose_inside_an_existing_item_gets_its_own_list_context(bundle, parent):
    closing = "</ul>" if parent == "<ul>" else "</div>"
    _replace_reviewed_item(bundle, parent + '<li><p id="item">목록 항목</p></li>' + closing, ["#item"])
    # Select an existing ARIA/native item container, with a prose child reviewed
    # independently. A nested prose item still needs its own owning context.
    soup = BeautifulSoup(export(bundle).read_bytes(), "lxml")
    item = soup.find(id="item")
    assert item.parent.get("role") == "list"
    assert item.parent.parent.name == "li"


def test_positional_text_edit_selectors_resolve_before_list_wrapping(bundle):
    from supertranslator.reader import _transform
    _replace_reviewed_item(bundle, '<p id="item">client가 검사합니다(MUST).</p><p id="after">server가 응답합니다.</p>', ["#item"])
    source, review_path, _ = bundle
    review = json.loads(review_path.read_text(encoding="utf-8"))
    article = _transform(BeautifulSoup((source / "index.html").read_bytes(), "lxml"), review)
    target = article.find(id="after")
    ordinal = [tag for tag in target.parent.children if getattr(tag, "name", None) == "p"].index(target) + 1
    selector = f"#doc > p:nth-of-type({ordinal})"
    assert article.select_one(selector) is target
    edit = {"selector": selector, "input_html_sha256": hashlib.sha256(target.decode_contents().encode()).hexdigest(),
            "replacement_html": "server가 응답을 보냅니다.", "source_text": "The server responds.",
            "evidence": "AI comparison retains the responding server and changes Korean wording only."}
    path = export(bundle, lambda r: r.update(text_edits=[edit]))
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    assert soup.find(id="after").get_text() == "server가 응답을 보냅니다."
    assert soup.find(id="item").parent.get("role") == "list"


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(input_html_sha256="0" * 64),
    lambda r: r.update(content_selector="article, nav"),
    lambda r: r["removals"][0].update(text_sha256="0" * 64),
    lambda r: r.update(joins=[{"selectors": ["#left", "#item"]}]),
    lambda r: r.update(joins=[{"selectors": ["#left", "#code"]}]),
    lambda r: r.update(heading_levels={"#left": 2}),
    lambda r: r.update(content_selector="head"),
])
def test_invalid_review_does_not_publish(bundle, mutation):
    with pytest.raises(ValueError):
        export(bundle, mutation)
    assert not bundle[2].exists()


def test_input_change_after_review_is_rejected(bundle):
    with (bundle[0] / "index.html").open("a") as handle:
        handle.write("<!-- changed -->")
    with pytest.raises(ValueError, match="digest"):
        export(bundle)


def test_existing_output_is_never_overwritten(bundle):
    bundle[2].mkdir()
    (bundle[2] / "keep").write_text("keep", encoding="utf-8", newline="")
    with pytest.raises(ValueError):
        export(bundle)
    assert (bundle[2] / "keep").read_text(encoding="utf-8") == "keep"


def test_symlink_asset_is_rejected(bundle, tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("not an asset", encoding="utf-8", newline="")
    (bundle[0] / "assets" / "escape").symlink_to(secret)
    with pytest.raises(ValueError):
        export(bundle)
    assert not bundle[2].exists()


def test_failed_input_qa_is_not_exported(bundle):
    manifest = bundle[0] / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["qa_status"] = "failed"
    manifest.write_text(json.dumps(data), encoding="utf-8", newline="")
    with pytest.raises(ValueError):
        export(bundle)


def test_command_exports_without_legacy_run_allocation(bundle):
    source, review, output = bundle
    assert main(["export-reader", "--input-dir", str(source), "--review", str(review), "--output-dir", str(output)]) == 0
    assert (output / "article.html").is_file()


def test_non_preformatted_print_furniture_is_archived_without_losing_anchors(bundle):
    source, review_path, output = bundle
    html = (source / "index.html").read_text(encoding="utf-8").replace('<pre id="page">', '<table id="page"><tr><td>').replace('Author [Page 2]</pre>', 'Author [Page 2]</td></tr></table>')
    (source / "index.html").write_text(html, encoding="utf-8", newline="")
    _bind_synthetic_html(source, html.encode())
    data = json.loads(review_path.read_text(encoding="utf-8"))
    data["input_html_sha256"] = hashlib.sha256(html.encode()).hexdigest()
    review_path.write_text(json.dumps(data), encoding="utf-8", newline="")
    result = export(bundle)
    soup = BeautifulSoup(result.read_text(encoding="utf-8"), "lxml")
    assert soup.find(id="page").find_parent("details") is not None
    assert soup.find(id="page-2") is not None


def test_reader_rejects_traversal_media_and_leaves_no_output(bundle):
    source, review_path, output = bundle
    html = (source / "index.html").read_text(encoding="utf-8").replace('src="assets/picture.svg"', 'src="assets/%2e%2e/secret.svg"')
    (source / "index.html").write_text(html, encoding="utf-8", newline="")
    data = json.loads(review_path.read_text(encoding="utf-8"))
    data["input_html_sha256"] = hashlib.sha256(html.encode()).hexdigest()
    review_path.write_text(json.dumps(data), encoding="utf-8", newline="")
    with pytest.raises(ValueError):
        export(bundle)
    assert not output.exists()


def test_browser_keeps_prose_readable_and_literals_scroll_locally(bundle):
    from playwright.sync_api import sync_playwright
    path = export(bundle)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for width in [1440, 768, 390]:
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.goto(path.as_uri())
                # Existing blog themes can use a larger root rem size.
                page.evaluate("document.documentElement.style.fontSize = '22px'")
                metrics = page.evaluate('''() => {
                  const p = document.querySelector('#left');
                  const a = document.querySelector('.st-reader');
                  const code = document.querySelector('#code');
                  return {font: parseFloat(getComputedStyle(p).fontSize),
                    line: parseFloat(getComputedStyle(p).lineHeight),
                    width: a.getBoundingClientRect().width,
                    overflow: document.documentElement.scrollWidth > innerWidth,
                    code: code.textContent, pre: getComputedStyle(code).whiteSpace};
                }''')
                assert metrics["font"] >= 16
                assert metrics["line"] >= metrics["font"] * 1.6
                assert metrics["width"] <= 800
                assert metrics["overflow"] is False
                assert metrics["pre"] == "pre"
                page.close()
        finally:
            browser.close()


def test_reader_qa_rejects_changed_plain_text_even_if_protected_tokens_match(bundle):
    from supertranslator.reader_qa import qa_reader
    path = export(bundle)
    path.write_text(path.read_text(encoding="utf-8").replace("허용", "거부"), encoding="utf-8", newline="")
    with pytest.raises(ValueError, match="digest"):
        qa_reader(path.parent)
    assert not (path.parent / "browser-qa.json").exists()


def test_reader_qa_requires_exact_visual_review_for_final_success(bundle, tmp_path):
    from supertranslator.reader_qa import qa_reader
    path = export(bundle)
    first = qa_reader(path.parent)
    assert first["automated_status"] == "passed"
    assert json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))["qa_status"] == "pending-visual-review"
    visual = tmp_path / "visual.json"
    visual.write_text(json.dumps({"render_input_sha256": "0" * 64, "verdict": "pass", "evidence": "Looked at all layouts"}), encoding="utf-8", newline="")
    with pytest.raises(ValueError):
        qa_reader(path.parent, visual)
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    visual.write_text(json.dumps({"render_input_sha256": manifest["render_input_sha256"], "verdict": "pass", "evidence": "Compared source and desktop/mobile full article screenshots"}), encoding="utf-8", newline="")
    result = qa_reader(path.parent, visual)
    assert result["visual_status"] == "passed"
    assert json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))["qa_status"] == "passed"


@pytest.mark.parametrize("fragment, missing", [
    ("Legacy", False),
    ("%20Legacy%20%25%20", False),
    ("legacy", True),
    ("absent", True),
    ("not-an-anchor", True),
    ("svg-anchor", True),
    ("math-anchor", True),
    ("template-anchor", True),
    ("math-html-anchor", False),
    ("svg-html-anchor", False),
])
def test_reading_edition_resolves_legacy_named_anchors(bundle, fragment, missing):
    from supertranslator.reader_qa import qa_reader

    change_html(bundle, '<h2 id="section-1">', (
        '<a name="Legacy"></a><a name="Legacy"></a><a name=" Legacy % "></a>'
        '<span name="not-an-anchor"></span><svg><a name="svg-anchor"></a></svg>'
        '<math><a name="math-anchor"></a></math><template><a name="template-anchor"></a></template>'
        '<math><mtext><a name="math-html-anchor"></a></mtext></math>'
        '<svg><desc><a name="svg-html-anchor"></a></desc></svg>'
        f'<p><a href="#{fragment}">절로 이동</a></p><h2 id="section-1">'
    ))
    path = export(bundle)
    if missing:
        with pytest.raises(ValueError, match="missing article anchor destinations"):
            qa_reader(path.parent)
    else:
        assert qa_reader(path.parent)["automated_status"] == "passed"


def test_reader_qa_rejects_duplicate_ids_even_with_named_anchors(bundle):
    from supertranslator.reader_qa import qa_reader

    change_html(bundle, '<h2 id="section-1">', (
        '<a name="legacy"></a><p id="section-1"><a href="#legacy">절로 이동</a></p>'
        '<h2 id="section-1">'
    ))
    path = export(bundle)
    with pytest.raises(ValueError, match="duplicate reader anchor IDs"):
        qa_reader(path.parent)


def test_reader_inventories_exact_named_anchor_counts():
    from supertranslator.reader import _preserved

    article = BeautifulSoup(
        '<article><a name=" Root % "></a><a name=" Root % "></a><a name=""></a>'
        '<span name="other"></span><svg><a name="svg-anchor"></a></svg></article>', "lxml",
    ).article
    assert _preserved(article, "https://example.com/spec").get("anchor_names") == {" Root % ": 2}


def change_html(bundle, old, new):
    source, review, _ = bundle
    raw = (source / "index.html").read_text(encoding="utf-8").replace(old, new)
    (source / "index.html").write_text(raw, encoding="utf-8", newline="")
    _bind_synthetic_html(source, raw.encode())
    data = json.loads(review.read_text(encoding="utf-8"))
    data["input_html_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    review.write_text(json.dumps(data), encoding="utf-8", newline="")


def _bind_synthetic_html(source, payload):
    """TEST ONLY evidence for a new authored reader fixture before export."""
    path = source / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["web_integrity"]["html_sha256"] = hashlib.sha256(payload).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize("name", ["browser-qa.json", "visual-review.json", "review-report.md"])
def test_qa_never_follows_evidence_symlinks(bundle, tmp_path, name):
    from supertranslator.reader_qa import qa_reader
    path = export(bundle)
    target = tmp_path / "unrelated"
    target.write_text("keep this", encoding="utf-8", newline="")
    evidence = path.parent / name
    evidence.unlink(missing_ok=True)
    evidence.symlink_to(target)
    with pytest.raises(ValueError):
        qa_reader(path.parent)
    assert target.read_text(encoding="utf-8") == "keep this"


def test_static_svg_geometry_and_numbered_list_semantics_survive(bundle):
    change_html(bundle, '<h1 id="title">', '<svg viewBox="0 0 100 100"><path d="M0,0 L100,100" stroke="black"/></svg><ol start="7"><li value="9">Ninth</li></ol><h1 id="title">')
    path = export(bundle)
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    assert soup.svg["viewbox"] == "0 0 100 100"
    assert soup.path["d"] == "M0,0 L100,100"
    assert soup.path["stroke"] == "black"
    assert soup.ol["start"] == "7"
    assert soup.li["value"] == "9"


def test_join_cannot_skip_image_inside_text_empty_span(bundle):
    change_html(bundle, '<p id="right">', '<span><img src="assets/picture.svg" alt="other figure"></span><p id="right">')
    with pytest.raises(ValueError, match="unreviewed"):
        export(bundle)


@pytest.mark.parametrize("value", ["assets/../../private-note.html", "assets/%2e%2e/%2e%2e/private-note.html"])
def test_local_link_cannot_traverse_bundle(bundle, value):
    change_html(bundle, 'href="#section-1"', f'href="{value}"')
    with pytest.raises(ValueError):
        export(bundle)


def test_visual_review_cannot_be_reused_after_asset_only_change(bundle):
    first = export(bundle)
    old = json.loads((first.parent / "manifest.json").read_text(encoding="utf-8"))
    asset = bundle[0] / "assets/picture.svg"
    asset.write_text(asset.read_text(encoding="utf-8").replace('width="10"', 'width="20"'), encoding="utf-8", newline="")
    from supertranslator.reader import export_reader
    second = export_reader(bundle[0], bundle[1], first.parent.with_name("changed-asset"))
    new = json.loads((second.parent / "manifest.json").read_text(encoding="utf-8"))
    assert old["html_sha256"] == new["html_sha256"]
    assert old["render_input_sha256"] != new["render_input_sha256"]


def test_malformed_editorial_review_is_cli_contract_failure(bundle):
    source, review, output = bundle
    data = json.loads(review.read_text(encoding="utf-8"))
    data["heading_levels"] = None
    review.write_text(json.dumps(data), encoding="utf-8", newline="")
    assert main(["export-reader", "--input-dir", str(source), "--review", str(review), "--output-dir", str(output)]) == 4
    assert not output.exists()


def test_host_theme_cannot_shrink_nested_reader_lists(bundle):
    from playwright.sync_api import sync_playwright
    change_html(bundle, '<h1 id="title">', '<ul><li>첫 항목<ul><li id="nested">중첩된 항목</li></ul></li></ul><h1 id="title">')
    path = export(bundle)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width":390,"height":844})
            page.goto(path.as_uri())
            page.evaluate('''() => {
              document.body.classList.add('host');
              const style=document.createElement('style');
              style.textContent='.host ul {font-size:.75em}';
              document.head.insertBefore(style, document.head.firstChild);
            }''')
            assert page.locator('#nested').evaluate('(el) => parseFloat(getComputedStyle(el).fontSize)') == 16
        finally:
            browser.close()


def test_long_reader_qa_records_complete_bounded_screenshot_tiles(bundle):
    from supertranslator.reader_qa import qa_reader
    change_html(bundle, '<h1 id="title">', ('<p>긴 문서의 본문과 문단 간격을 실제 화면에서 검사합니다. '+ '내용을 보존합니다. '*25+'</p>')*80+'<h1 id="title">')
    path = export(bundle)
    result = qa_reader(path.parent)
    for width in ["1440", "768", "390"]:
        tiles = result["screenshot_tiles"][width]
        assert len(tiles) > 1
        covered = 0
        for tile in tiles:
            assert tile["y"] <= covered
            assert tile["height"] <= 3000
            covered = tile["y"] + tile["height"]
            assert (path.parent / tile["path"]).is_file()
        assert covered >= result["viewports"][width]["documentHeight"]


def test_mobile_long_definition_labels_leave_readable_description_width(bundle):
    from playwright.sync_api import sync_playwright
    change_html(bundle, '<h1 id="title">', '<dl><dt>[W3C.webappsec-referrer-policy]</dt><dd id="citation">저자와 참고 문헌의 제목 및 원문 주소를 읽을 수 있어야 합니다.</dd></dl><h1 id="title">')
    path = export(bundle)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width":390,"height":844})
            page.goto(path.as_uri())
            assert page.locator('#citation').bounding_box()["width"] >= 300
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 768, 390])
def test_native_definition_list_leaves_readable_description_width(bundle, width):
    from playwright.sync_api import sync_playwright

    term = 'VeryLongTechnicalParameterNameWithNoSpaces' * 3
    description = '설명과 조건을 읽을 수 있어야 합니다.'
    change_html(bundle, '<h1 id="title">',
        f'<dl id="compact"><dt>API</dt><dd>{description}</dd></dl>'
        f'<dl id="long"><dt>{term}</dt><dd>{description}</dd></dl><h1 id="title">')
    path = export(bundle)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900})
            page.goto(path.as_uri())
            term_box = page.locator('#long dt').bounding_box()
            description_box = page.locator('#long dd').bounding_box()
            if width == 390:
                assert description_box['y'] >= term_box['y'] + term_box['height']
            else:
                list_width = page.locator('#long').bounding_box()['width']
                assert description_box['width'] >= list_width / 2
                assert term_box['width'] <= list_width * .4 + 1
                assert page.locator('#compact dt').bounding_box()['width'] < term_box['width']
                assert description_box['x'] >= term_box['x'] + term_box['width']
                assert description_box['y'] == term_box['y']
            assert page.locator('#compact :is(dt, dd), #long :is(dt, dd)').evaluate_all('''items => items.every(item => {
                const range = document.createRange();
                range.selectNodeContents(item);
                const box = item.getBoundingClientRect();
                return [...range.getClientRects()].every(text =>
                    text.left >= box.left - 1 && text.right <= Math.min(box.right, innerWidth) + 1);
            })''')
        finally:
            browser.close()


def test_export_hashes_match_written_bytes_under_windows_text_defaults(bundle, monkeypatch):
    original_write = Path.write_text
    def windows_write(path, data, encoding=None, errors=None, newline=None):
        return original_write(path, data, encoding=encoding or "cp1252", errors=errors,
                              newline="\r\n" if newline is None else newline)
    monkeypatch.setattr(Path, "write_text", windows_write)
    path = export(bundle)
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["article_sha256"] == hashlib.sha256((path.parent / "article.html").read_bytes()).hexdigest()


def reviewed_edit(bundle, replacement=None):
    original = 'client는 <code>code</code>를 MUST NOT 두 번 이상 사용해서는 안 됩니다.'
    change_html(bundle, '<h1 id="title">', f'<p id="sentence">{original}</p><h1 id="title">')
    return {"selector": "#sentence", "input_html_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "replacement_html": replacement or 'client는 <code>code</code>를 두 번 이상 사용해서는 안 됩니다(MUST NOT).',
            "source_text": "The client MUST NOT use the code more than once.",
            "evidence": "Source-compared AI correction: retains client, code, the prohibition and the single-use condition."}


def test_bound_ai_edit_repairs_sentence_without_translating_english_nouns(bundle):
    edit = reviewed_edit(bundle)
    path = export(bundle, lambda r: r.update(text_edits=[edit]))
    sentence = BeautifulSoup(path.read_bytes(), "lxml").find(id="sentence")
    assert sentence.get_text() == "client는 code를 두 번 이상 사용해서는 안 됩니다(MUST NOT)."
    assert str(sentence.code) == "<code>code</code>"
    manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["text_edits"][0]["source_text"] == "The client MUST NOT use the code more than once."


def test_ai_edit_can_move_intact_inline_reference_after_predicate(bundle):
    original = '값에 의무가 적용됩니다(<span>MUST</span>): <a href="#section-1">기준</a>을 따라야 합니다.'
    change_html(bundle, '<h1 id="title">', f'<p id="sentence">{original}</p><h1 id="title">')
    edit = {"selector": "#sentence", "input_html_sha256": hashlib.sha256(original.encode()).hexdigest(),
            "replacement_html": '<a href="#section-1">기준</a>을 따라야 합니다(<span>MUST</span>).',
            "source_text": "The value MUST follow the standard.", "evidence": "Same obligation and reference, natural Korean order."}
    path = export(bundle, lambda r: r.update(text_edits=[edit]))
    sentence = BeautifulSoup(path.read_bytes(), "lxml").find(id="sentence")
    assert sentence.get_text() == "기준을 따라야 합니다(MUST)."
    assert sentence.a["href"] == "#section-1"


@pytest.mark.parametrize("mutation", [
    lambda e: e.update(input_html_sha256="0" * 64),
    lambda e: e.update(evidence=""),
    lambda e: e.update(source_text=""),
    lambda e: e.update(replacement_html='client는 <code>code</code>를 사용해도 됩니다(MAY).'),
    lambda e: e.update(replacement_html='client는 <code>other</code>를 사용해서는 안 됩니다(MUST NOT).'),
    lambda e: e.update(replacement_html='클라이언트는 <code>code</code>를 사용해서는 안 됩니다(MUST NOT).'),
    lambda e: e.update(replacement_html='client는 <code>code</code>를 2번 사용해서는 안 됩니다(MUST NOT).'),
    lambda e: e.update(replacement_html='client는 <code>code</code>를 사용해서는 안 됩니다(MUST NOT).<script>alert(1)</script>'),
    lambda e: e.update(selector="#code"),
])
def test_ai_edit_rejects_stale_or_unreviewed_or_protected_content_changes(bundle, mutation):
    edit = reviewed_edit(bundle)
    mutation(edit)
    with pytest.raises(ValueError):
        export(bundle, lambda r: r.update(text_edits=[edit]))
    assert not bundle[2].exists()


def test_duplicate_ai_edits_cannot_overwrite_an_already_edited_sentence(bundle):
    edit = reviewed_edit(bundle)
    with pytest.raises(ValueError):
        export(bundle, lambda r: r.update(text_edits=[edit, edit]))
    assert not bundle[2].exists()


def layout_review(bundle):
    change_html(bundle, '<h1 id="title">', '<div id="metadata"><dl><dt>발행</dt><dd>2024</dd></dl></div><nav id="old-toc"><a href="#section-1">기존 목차</a></nav><span id="st-heading-0001"></span><h1 id="title">')
    change_html(bundle, '<p id="left">', '<h3>1.1. 세부 항목</h3><h2>2. 다음 절</h2><p id="left">')
    return {"toc_selectors": ["#old-toc"], "metadata_selectors": ["#metadata"],
            "title_selectors": ["#title"], "navigation": True}


def test_presentation_builds_collision_safe_hierarchical_navigation_and_retains_source(bundle):
    review = layout_review(bundle)
    change_html(bundle, '<span id="st-heading-0001"></span>',
                '<span id="st-heading-0001"></span><a name="st-heading-0002"></a>')
    path = export(bundle, lambda r: r.update(presentation=review))
    article = BeautifulSoup(path.read_bytes(), "lxml").select_one('.st-reader')
    toc = article.select_one('details.st-toc')
    assert toc is not None and not toc.has_attr('open')
    assert toc.summary.get_text() == '목차'
    assert [a.get_text() for a in toc.select('a')] == ['1. 소개', '1.1. 세부 항목', '2. 다음 절']
    for a in toc.select('a'):
        assert article.find(id=a['href'][1:]).name in {'h2', 'h3'}
    assert toc.select_one('ol ol a').get_text() == '1.1. 세부 항목'
    ids = [t['id'] for t in article.select('[id]')]
    assert len(ids) == len(set(ids))
    assert article.select_one('a[name="st-heading-0002"]') is not None
    assert "st-heading-0002" not in ids
    assert article.find(id='old-toc').find_parent('details', class_='st-source-notes') is not None
    assert article.find(id='metadata').find_parent('details', class_='st-document-info') is not None
    assert article.find(id='metadata').get_text() == '발행2024'
    assert article.find(id='title').get_text() == '테스트 문서'
    assert article.find(id='code').get_text().startswith('GET /?a=1&b=2 HTTP/1.1')


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(toc_selectors=['#left']),
    lambda r: r.update(toc_selectors=['#doc']),
    lambda r: r.update(metadata_selectors=['#left']),
    lambda r: r.update(title_selectors=['#code']),
    lambda r: r.update(toc_selectors=['#title']),
    lambda r: r.update(navigation='yes'),
    lambda r: r.update(metadata_selectors=None),
])
def test_presentation_rejects_unsafe_or_overlapping_selections(bundle, mutation):
    review = layout_review(bundle)
    mutation(review)
    with pytest.raises(ValueError):
        export(bundle, lambda r: r.update(presentation=review))
    assert not bundle[2].exists()


def test_metadata_container_cannot_archive_unrelated_body_prose(bundle):
    review = layout_review(bundle)
    change_html(bundle, '</dd></dl></div>', '</dd></dl><p>이 본문은 숨기면 안 됩니다.</p></div>')
    with pytest.raises(ValueError):
        export(bundle, lambda r: r.update(presentation=review))


def test_presentation_selectors_resolve_original_classes_and_data_markers(bundle):
    review = layout_review(bundle)
    change_html(bundle, '<div id="metadata">', '<div id="metadata" class="publication-info">')
    change_html(bundle, '<nav id="old-toc">', '<nav id="old-toc" data-print-toc="yes">')
    review['metadata_selectors'] = ['.publication-info']
    review['toc_selectors'] = ['[data-print-toc]']
    path = export(bundle, lambda r: r.update(presentation=review))
    article = BeautifulSoup(path.read_bytes(), 'lxml').select_one('.st-reader')
    assert article.find(id='metadata').find_parent('details', class_='st-document-info') is not None
    assert article.find(id='old-toc').find_parent('details', class_='st-source-notes') is not None


def test_embedded_presentation_is_compact_but_standalone_title_stays_visible(bundle):
    from playwright.sync_api import sync_playwright
    review = layout_review(bundle)
    change_html(bundle, '<p id="right">', '<p id="right"><a href="#right">¶</a>')
    path = export(bundle, lambda r: r.update(presentation=review))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width in [1440, 390]:
                page = browser.new_page(viewport={'width': width, 'height': 900})
                page.goto(path.as_uri())
                assert page.locator('#title').is_visible()
                assert page.locator('details.st-toc').bounding_box()['height'] < 70
                assert not page.locator('#metadata').is_visible()
                page.locator('.st-reader').evaluate('''el => {let host=document.createElement('div');host.className='st-reader-embed';el.replaceWith(host);host.append(el);}''')
                assert not page.locator('#title').is_visible()
                assert page.locator('#left').evaluate('e => parseFloat(getComputedStyle(e).fontSize)') == (16 if width == 390 else 18)
                permalink = page.locator('a.st-permalink')
                assert float(permalink.evaluate('e => getComputedStyle(e).opacity')) < .4
                permalink.focus()
                assert float(permalink.evaluate('e => getComputedStyle(e).opacity')) == 1
                assert permalink.get_attribute('href') == '#right'
                page.locator('details.st-toc > summary').focus()
                page.keyboard.press('Enter')
                assert page.locator('details.st-toc').get_attribute('open') is not None
                page.close()
        finally:
            browser.close()


@pytest.mark.parametrize('container,group', [
    ('<div id="selected"><nav>원래 목차</nav><h2>보안</h2><div>숨기면 안 되는 본문</div></div>', 'toc_selectors'),
    ('<div id="selected"><dl><dt>발행</dt><dd>2024</dd></dl><section>숨기면 안 되는 본문</section></div>', 'metadata_selectors'),
])
def test_presentation_cannot_fold_body_text_in_nonparagraph_containers(bundle, container, group):
    review = layout_review(bundle)
    change_html(bundle, '<h1 id="title">', container+'<h1 id="title">')
    review[group] = ['#selected']
    with pytest.raises(ValueError):
        export(bundle, lambda r: r.update(presentation=review))
    assert not bundle[2].exists()


@pytest.mark.parametrize('replacement', ['+10', '10'])
def test_ai_edit_cannot_change_or_delete_numeric_sign(bundle, replacement):
    original = '온도는 -10°C 이상이어야 합니다(MUST).'
    change_html(bundle, '<h1 id="title">', f'<p id="signed">{original}</p><h1 id="title">')
    edit = {'selector':'#signed','input_html_sha256':hashlib.sha256(original.encode()).hexdigest(),
            'replacement_html':f'온도는 {replacement}°C 이상이어야 합니다(MUST).',
            'source_text':'The temperature MUST be at least -10°C.','evidence':'Purported review cannot override the numeric preservation contract.'}
    with pytest.raises(ValueError):
        export(bundle,lambda r:r.update(text_edits=[edit]))


def test_navigation_percent_encodes_existing_id_without_renaming_it(bundle):
    from urllib.parse import unquote
    review=layout_review(bundle)
    change_html(bundle, '<p id="left">', '<h2 id="a%20b">특수 ID</h2><p id="left">')
    path=export(bundle,lambda r:r.update(presentation=review))
    article=BeautifulSoup(path.read_bytes(),'lxml').select_one('.st-reader')
    link=next(a for a in article.select('.st-toc a') if a.get_text()=='특수 ID')
    assert link['href']=='#a%2520b'
    assert article.find(id=unquote(link['href'][1:])) is not None


def test_navigation_includes_source_authored_details_headings_but_not_archived_toc(bundle):
    review=layout_review(bundle)
    change_html(bundle,'<p id="left">','<details id="appendix"><summary>부록</summary><h2 id="deep">중요한 추가 규칙</h2><p>접어 둔 본문도 탐색할 수 있어야 합니다.</p></details><p id="left">')
    path=export(bundle,lambda r:r.update(presentation=review))
    article=BeautifulSoup(path.read_bytes(),'lxml').select_one('.st-reader')
    assert article.select_one('.st-toc a[href="#deep"]') is not None


def test_pilcrow_preserves_existing_accessible_name(bundle):
    change_html(bundle, '<p id="right">', '<p id="right"><a href="#right" aria-label="보안 요구 사항의 문단 링크">¶</a>')
    path=export(bundle)
    link=BeautifulSoup(path.read_bytes(),'lxml').select_one('a.st-permalink')
    assert link['aria-label']=='보안 요구 사항의 문단 링크'


def test_archived_heading_never_reappears_in_live_navigation(bundle):
    review=layout_review(bundle)
    change_html(bundle,'<nav id="old-toc">','<nav id="old-toc"><h2 id="print-heading">원래 인쇄 목차</h2>')
    path=export(bundle,lambda r:r.update(presentation=review))
    article=BeautifulSoup(path.read_bytes(),'lxml').select_one('.st-reader')
    assert article.find(id='print-heading') is not None
    assert article.find(id='print-heading').find_parent('details',class_='st-source-notes') is not None
    assert article.select_one('.st-toc a[href="#print-heading"]') is None
    assert '원래 인쇄 목차' not in article.select_one('.st-toc').get_text()
