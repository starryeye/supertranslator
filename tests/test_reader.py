"""Reader behavior, not a copy of the exporter implementation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from supertranslator.cli import main


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


def change_html(bundle, old, new):
    source, review, _ = bundle
    raw = (source / "index.html").read_text(encoding="utf-8").replace(old, new)
    (source / "index.html").write_text(raw, encoding="utf-8", newline="")
    data = json.loads(review.read_text(encoding="utf-8"))
    data["input_html_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
    review.write_text(json.dumps(data), encoding="utf-8", newline="")


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
