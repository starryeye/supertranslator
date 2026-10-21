"""Source-derived preformatted projection behavior and real web consumers."""

from __future__ import annotations

import hashlib
from importlib.resources import files

from bs4 import BeautifulSoup
import pytest

from web_translator.preformatted_analysis import (
    analyze_preformatted, build_classification_packages, validate_review,
)
from web_translator.preformatted_contract import canonical_sha256


def _review(source: str, specifications: list[dict[str, object]]):
    analysis = analyze_preformatted(source)
    packages = build_classification_packages(analysis)
    blocks = []
    for index, spec in enumerate(specifications, 1):
        item = {
            "id": f"block-{index:06d}", "pre_id": spec.get("pre_id", "pre-000001"),
            "line_ids": spec["line_ids"], "role": spec["role"],
            "evidence": spec.get("evidence", ""), "metadata": spec.get("metadata", {}),
            "literal_spans": spec.get("literal_spans", []),
        }
        blocks.append(item)
    payload = {
        "schema_version": "1.0", "source_sha256": analysis.source_sha256,
        "analysis_sha256": canonical_sha256(analysis.to_dict()),
        "package_sha256": {p.id: canonical_sha256(p.to_dict()) for p in packages},
        "blocks": blocks, "unresolved_required": [],
    }
    return analysis, validate_review(analysis, packages, payload)


def _span(kind: str, start_line: str, start: int, end_line: str, end: int, text: str):
    return {"kind": kind, "start_line_id": start_line, "start_column": start,
            "end_line_id": end_line, "end_column": end,
            "source_sha256": hashlib.sha256(text.encode()).hexdigest()}


def _api():
    from web_translator.preformatted_projection import (
        project_preformatted, verify_projection, verify_projected_output,
    )
    return project_preformatted, verify_projection, verify_projected_output


def test_projection_reflows_only_reviewed_prose():
    # Catches a branch that leaves reviewed prose in <pre> or loses inline ownership.
    source = ('<!doctype html><html><head></head><body><p id="outside">Keep outside</p>'
              '<pre id="manual" class="source">Overview\nRead <a id="guide" href="/guide?x=1&amp;y=2" title="Go">the <em>guide</em></a>.\n'
              '- First item\nDiagram caption</pre></body></html>')
    marker = {"line_id": "line-000003", "start": 0, "end": 1}
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "heading", "evidence": "Overview", "metadata": {"level": 1}},
        {"line_ids": ["line-000002"], "role": "prose", "evidence": "Read"},
        {"line_ids": ["line-000003"], "role": "list-item", "evidence": "First item", "metadata": {"depth": 0, "marker_span": marker}},
        {"line_ids": ["line-000004"], "role": "caption", "evidence": "Diagram caption"},
    ])
    project, verify, verify_output = _api()
    artifact = project(source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    assert soup.find(id="outside").get_text() == "Keep outside"
    assert soup.find("pre", id="manual") is None
    assert soup.find(id="manual")["class"] == ["source"]
    assert [tag.name for tag in soup.select("[data-wt-preformatted-block]")] == ["h1", "p", "div", "figcaption"]
    assert [tag["data-wt-preformatted-block"] for tag in soup.select("[data-wt-preformatted-block]")] == [
        "block-000001", "block-000002", "block-000003", "block-000004"
    ]
    assert soup.find(id="guide")["href"] == "/guide?x=1&y=2"
    assert soup.find(id="guide")["title"] == "Go"
    assert soup.find(id="guide").em.get_text() == "guide"
    assert soup.select_one('[data-wt-preformatted-marker="block-000003"]').get_text() == "-"
    assert soup.select_one('[data-wt-preformatted-block="block-000003"]').get_text() == "- First item\n"
    assert artifact.summary.unknown_blocks == 0
    assert artifact.summary.translated_blocks == 4
    verify(source, analysis, review, artifact)
    verify_output(artifact, artifact.unmarked_html)
    with pytest.raises(ValueError, match="anchor|href"):
        verify_output(artifact, artifact.unmarked_html.replace('/guide?x=1&amp;y=2', '/evil'))
    with pytest.raises(ValueError, match="block|mapping"):
        verify_output(artifact, artifact.unmarked_html.replace('block-000002', 'block-000001'))


def test_projection_preserves_literal_islands_and_all_source_coverage():
    # Catches dropped blank/grid/code lines, CRLF normalization and stale review identity.
    source = ('<html><head></head><body><pre id="manual">Intro\r\n'
              '<code id="sample">x  y</code>\r\n'
              '+---+\r\n| A |\r\n\r\nEnd</pre><pre id="fixed"><code>must stay</code></pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Intro"},
        {"line_ids": ["line-000002"], "role": "literal-code", "evidence": "x  y"},
        {"line_ids": ["line-000003", "line-000004"], "role": "literal-table", "evidence": "+---+"},
        {"line_ids": ["line-000005"], "role": "blank"},
        {"line_ids": ["line-000006"], "role": "prose", "evidence": "End"},
    ])
    project, verify, verify_output = _api()
    artifact = project(source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "lxml")
    assert [tag.get_text() for tag in soup.select("[data-wt-preformatted-literal]")] == [
        "x  y\r\n", "+---+\r\n| A |\r\n", "\r\n"
    ]
    assert soup.find(id="fixed").get_text() == "must stay"
    assert artifact.summary.preserved_blocks == 3
    assert len(artifact.evidence["blocks"]) == 5
    verify(source, analysis, review, artifact)
    verify_output(artifact, artifact.unmarked_html)
    with pytest.raises(ValueError, match="literal"):
        verify_output(artifact, artifact.unmarked_html.replace("x  y", "x y"))
    changed = review.to_dict()
    changed["analysis_sha256"] = "0" * 64
    from web_translator.preformatted_contract import ReviewedBlocks
    with pytest.raises(ValueError, match="review|hash"):
        project(source, analysis, ReviewedBlocks.from_dict(changed))
    changed = review.to_dict()
    changed["blocks"][0]["role"] = "unknown"
    with pytest.raises(ValueError, match="unknown"):
        project(source, analysis, ReviewedBlocks.from_dict(changed))


def test_projection_keeps_anchor_ownership_or_rejects_unsafe_boundary():
    # Catches cloning an ID into two translated blocks or moving its parent.
    source = '<html><head></head><body><pre><a id="cross" href="/safe">Alpha\nBeta</a></pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Alpha"},
        {"line_ids": ["line-000002"], "role": "prose", "evidence": "Beta"},
    ])
    project, _, _ = _api()
    with pytest.raises(ValueError, match="block-000001|block-000002|cross"):
        project(source, analysis, review)
    analysis, review = _review(source, [
        {"line_ids": ["line-000001", "line-000002"], "role": "prose", "evidence": "Alpha"},
    ])
    artifact = project(source, analysis, review)
    assert BeautifulSoup(artifact.unmarked_html, "html.parser").find_all(id="cross")[0]["href"] == "/safe"


def test_inline_code_cannot_be_split_between_reviewed_prose_blocks():
    source = '<pre>Call <code id="api">open(\npath)</code> to read.</pre>'
    project, _, _ = _api()
    with pytest.raises(ValueError, match="constraint|cross-node|DOM boundary"):
        analysis, review = _review(source, [
            {"line_ids": ["line-000001"], "role": "prose", "evidence": "Call"},
            {"line_ids": ["line-000002"], "role": "prose", "evidence": "to read."},
        ])
        project(source, analysis, review)


@pytest.mark.parametrize('mutation', ['content', 'attributes', 'removed'])
def test_inline_code_is_source_bound_inside_translated_prose(mutation):
    source = '<pre>Call <code class="api" title="Exact">open(path)</code> to read.</pre>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Call"},
    ])
    project, _, verify_output = _api()
    artifact = project(source, analysis, review)
    rendered = artifact.unmarked_html.replace('Call ', '호출: ').replace(' to read.', ' 읽습니다.')
    verify_output(artifact, rendered)
    soup = BeautifulSoup(rendered, 'html.parser')
    if mutation == 'content':
        soup.code.string = 'close(path)'
    elif mutation == 'attributes':
        soup.code['title'] = 'Changed'
    else:
        soup.code.unwrap()
    with pytest.raises(ValueError, match="constraint"):
        verify_output(artifact, str(soup))


def test_wrapped_url_is_one_exact_opaque_span():
    # Catches invented hrefs and joining a source URL that physically wraps.
    url = "https://exam\nple.test/a?x=1&y=2"
    source = '<html><head></head><body><pre>Read https://exam\nple.test/a?x=1&amp;y=2 today</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001", "line-000002"], "role": "prose", "evidence": "Read",
         "literal_spans": [_span("url", "line-000001", 5, "line-000002", 18, url)]},
    ])
    project, _, verify_output = _api()
    artifact = project(source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "lxml")
    codes = soup.select("[data-wt-preformatted-url]")
    assert len(codes) == 1
    assert codes[0].name == "code"
    assert codes[0].get_text() == url
    assert soup.find("a") is None
    verify_output(artifact, artifact.unmarked_html)
    with pytest.raises(ValueError, match="opaque|url"):
        verify_output(artifact, artifact.unmarked_html.replace("ple.test", "other.test"))


def test_scoped_css_preserves_grid_and_narrow_flow(tmp_path):
    # Catches CSS that applies globally or lets a literal grid overflow the page.
    source = '<html><head></head><body><pre>' + ('한글 흐름 ' * 35) + '\n' + ('+-----+' * 55) + '\n| A   |</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "한글 흐름"},
        {"line_ids": ["line-000002", "line-000003"], "role": "literal-table", "evidence": "+-----+"},
    ])
    project, _, _ = _api()
    artifact = project(source, analysis, review)
    assert artifact.css_bytes == files("web_translator").joinpath("web_assets", "preformatted-flow.css").read_bytes()
    assert artifact.css_path.startswith("assets/wt-preformatted-")
    assert artifact.css_path.endswith(".css")
    css = artifact.css_bytes.decode()
    assert "[data-wt-preformatted-root]" in css
    assert "[data-wt-preformatted-literal]" in css
    assert "overflow-x: auto" in css
    assert "max-width: 100%" in css
    assert "white-space: pre" in css
    assert "min-width: 0" in css
    assert "pre, code" not in css
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    assert soup.find("link", href=artifact.css_path) is not None
    from playwright.sync_api import sync_playwright

    rendered = tmp_path / "render"
    (rendered / "assets").mkdir(parents=True)
    (rendered / "index.html").write_bytes(artifact.unmarked_html.encode())
    (rendered / artifact.css_path).write_bytes(artifact.css_bytes)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto((rendered / "index.html").as_uri())
            metrics = page.evaluate("""() => {
              const grid = document.querySelector('[data-wt-preformatted-literal]');
              const prose = document.querySelector('p[data-wt-preformatted-block]');
              return {
                pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
                gridScroll: grid.scrollWidth > grid.clientWidth,
                gridWhitespace: getComputedStyle(grid).whiteSpace,
                proseWhitespace: getComputedStyle(prose).whiteSpace,
                stylesheetLoaded: [...document.styleSheets].some(s => s.href && s.href.endsWith('.css')),
              };
            }""")
        finally:
            browser.close()
    assert metrics == {"pageOverflow": False, "gridScroll": True,
                       "gridWhitespace": "pre", "proseWhitespace": "normal",
                       "stylesheetLoaded": True}


def test_projection_crlf_and_opaque_url_survive_extract_and_assemble(tmp_path):
    # Catches a source-only proof that misses lxml/read_text newline normalization.
    from web_translator.extract import extract_segments
    from web_translator.assemble import assemble_page
    from web_translator.models import Translation

    url = "https://exam\r\nple.test/x"
    source = ('<html><head></head><body><pre id="manual">Read https://exam\r\n'
              'ple.test/x\r\n+---+\r\n| A |</pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001", "line-000002"], "role": "prose", "evidence": "Read",
         "literal_spans": [_span("url", "line-000001", 5, "line-000002", 10, url)]},
        {"line_ids": ["line-000003", "line-000004"], "role": "literal-table", "evidence": "+---+"},
    ])
    project, _, verify_output = _api()
    artifact = project(source, analysis, review)
    source_dir = tmp_path / "run"
    assets = source_dir / "assets"
    assets.mkdir(parents=True)
    (source_dir / "preformatted-source.html").write_bytes(artifact.unmarked_html.encode())
    (source_dir / artifact.css_path).write_bytes(artifact.css_bytes)
    segments = extract_segments(source_dir / "preformatted-source.html", source_dir / "segments.jsonl")
    assert [segment.semantic_type for segment in segments] == ["paragraph"]
    assert any(token.kind == "code" and url in token.value for token in segments[0].protected)
    from web_translator.preformatted_projection import encode_projection_transport
    marked = (source_dir / "preformatted-source.html").read_bytes().decode("utf-8")
    transported = encode_projection_transport(marked, artifact)
    assert "&#13;" in transported
    assert "\r" not in transported
    (source_dir / "preformatted-source.html").write_bytes(transported.encode("utf-8"))
    output = assemble_page(
        source_dir / "preformatted-source.html",
        {segment.id: segment for segment in segments},
        {segment.id: Translation(segment.id, segment.source_text, notes="reviewed") for segment in segments},
        {}, tmp_path / "output", "https://example.com/manual",
    )
    output_html = output.read_bytes().decode("utf-8")
    verify_output(artifact, output_html)
    output_soup = BeautifulSoup(output_html, "html.parser")
    assert output_soup.select_one("[data-wt-preformatted-url]").get_text() == url
    assert output_soup.select_one("[data-wt-preformatted-literal]").get_text() == "+---+\r\n| A |"
    assert (tmp_path / "output" / artifact.css_path).read_bytes() == artifact.css_bytes


def test_caption_association_groups_only_adjacent_literal():
    # Catches a claimed figure association that has no semantic output.
    source = '<html><head></head><body><pre>+---+\n| A |\nFigure A</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001", "line-000002"], "role": "literal-diagram", "evidence": "+---+"},
        {"line_ids": ["line-000003"], "role": "caption", "evidence": "Figure A",
         "metadata": {"adjacent_block_id": "block-000001"}},
    ])
    artifact = _api()[0](source, analysis, review)
    figure = BeautifulSoup(artifact.unmarked_html, "html.parser").find("figure")
    assert figure is not None
    assert [tag["data-wt-preformatted-block"] for tag in figure.select("[data-wt-preformatted-block]")] == [
        "block-000001", "block-000002"
    ]


def test_multiple_opaque_urls_and_anchor_block_owner_are_verified():
    # Catches accepting only the first URL or an anchor moved under another block.
    first = "https://a.test"
    second = "https://b.test"
    source = ('<html><head></head><body><pre>See https://a.test and https://b.test\n'
              '<a id="owned" href="/keep">Read this</a>\nOther</pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "See",
         "literal_spans": [_span("url", "line-000001", 4, "line-000001", 18, first),
                           _span("url", "line-000001", 23, "line-000001", 37, second)]},
        {"line_ids": ["line-000002"], "role": "prose", "evidence": "Read this"},
        {"line_ids": ["line-000003"], "role": "prose", "evidence": "Other"},
    ])
    project, _, verify_output = _api()
    artifact = project(source, analysis, review)
    assert [tag.get_text() for tag in BeautifulSoup(artifact.unmarked_html, "html.parser").select(
        "[data-wt-preformatted-url]")] == [first, second]
    verify_output(artifact, artifact.unmarked_html)
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    anchor = soup.find(id="owned")
    assert anchor is not None
    soup.select_one('[data-wt-preformatted-block="block-000003"]').append(anchor.extract())
    with pytest.raises(ValueError, match="ownership"):
        verify_output(artifact, str(soup))


def test_transport_encodes_only_generated_text_not_comments_or_attributes():
    # Catches a blind CR substitution that corrupts markup or source comments.
    from web_translator.preformatted_projection import encode_projection_transport
    source = '<html><head></head><body><pre>Alpha\r\nBeta</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001", "line-000002"], "role": "literal-layout", "evidence": "Alpha"},
    ])
    artifact = _api()[0](source, analysis, review)
    marked = artifact.unmarked_html.replace(
        '<pre data-wt-preformatted-block="block-000001"',
        '<pre title="attribute\r\nexact" data-wt-preformatted-block="block-000001"'
    ).replace('Alpha&#13;\nBeta', '<!--comment\r\nexact-->Alpha\r\nBeta')
    transported = encode_projection_transport(marked, artifact)
    assert 'title="attribute\r\nexact"' in transported
    assert '<!--comment\r\nexact-->' in transported
    assert 'Alpha&#13;\nBeta' in transported
    assert BeautifulSoup(marked, "html.parser").pre.get_text() == BeautifulSoup(
        transported, "html.parser").pre.get_text()


def test_projection_records_round_trip_and_reject_tampered_css_or_summary():
    # Catches noncanonical resource identity or mutable evidence escaping records.
    from web_translator.preformatted_contract import ProjectionArtifact
    source = '<html><head></head><body><pre>Alpha</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Alpha"},
    ])
    artifact = _api()[0](source, analysis, review)
    assert artifact.summary.policy == "prose-reflow-literals-preserved"
    wire = artifact.to_dict()
    assert wire["summary"]["policy"] == "prose-reflow-literals-preserved"
    loaded = ProjectionArtifact.from_dict(wire)
    wire["evidence"]["blocks"][0]["id"] = "evil"
    assert loaded.evidence["blocks"][0]["id"] == "block-000001"
    _api()[1](source, analysis, review, loaded)
    bad = artifact.to_dict()
    bad["css_base64"] = "aW52YWxpZA=="
    with pytest.raises(ValueError, match="CSS"):
        ProjectionArtifact.from_dict(bad)
    bad = artifact.to_dict()
    bad["summary"]["unknown_blocks"] = 1
    with pytest.raises(ValueError, match="summary"):
        ProjectionArtifact.from_dict(bad)
    bad = artifact.to_dict()
    bad["summary"]["policy"] = "reviewed-flow-v1"
    with pytest.raises(ValueError, match="policy"):
        ProjectionArtifact.from_dict(bad)
    bad = artifact.to_dict()
    bad["unmarked_html"] += " "
    with pytest.raises(ValueError, match="projection"):
        ProjectionArtifact.from_dict(bad)


def test_nested_list_uses_reviewed_depth_without_invented_marker():
    # Catches lost reviewed indentation or native bullets duplicating source markers.
    source = '<html><head></head><body><pre>- Parent\n  * Child</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "list-item", "evidence": "Parent",
         "metadata": {"depth": 0, "marker_span": {"line_id": "line-000001", "start": 0, "end": 1}}},
        {"line_ids": ["line-000002"], "role": "list-item", "evidence": "Child",
         "metadata": {"depth": 1, "marker_span": {"line_id": "line-000002", "start": 2, "end": 3}}},
    ])
    artifact = _api()[0](source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    items = soup.select('[role="listitem"]')
    assert [item.get("style") for item in items] == [
        "--wt-list-depth: 0", "--wt-list-depth: 1"
    ]
    assert [item.get_text() for item in items] == ["- Parent\n", "  * Child"]
    assert [tag.get_text() for tag in soup.select("[data-wt-preformatted-marker]")] == ["-", "  *"]


def test_projection_rejects_whitespace_loss_at_opaque_boundary():
    # Catches a source-derived projection whose reparsed text silently loses a space.
    url = "https://a.test"
    source = '<html><head></head><body><pre>  https://a.test</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "https://a.test",
         "literal_spans": [_span("url", "line-000001", 2, "line-000001", 16, url)]},
    ])
    with pytest.raises(ValueError, match="block-000001.*whitespace|block-000001.*serialization"):
        _api()[0](source, analysis, review)


def test_projection_verifier_rejects_reordered_original_anchors():
    # Catches a DOM mutation that keeps IDs/attributes but reverses source order.
    source = ('<html><head></head><body><pre>Read '
              '<a id="first" href="/a">A</a> then '
              '<a id="second" href="/b">B</a>.</pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Read"},
    ])
    artifact = _api()[0](source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    first = soup.find(id="first")
    second = soup.find(id="second")
    first.replace_with(second.extract())
    soup.select_one('[data-wt-preformatted-block="block-000001"]').append(first)
    with pytest.raises(ValueError, match="order"):
        _api()[2](artifact, str(soup))


def test_projection_leaves_exterior_raw_text_and_comments_unchanged():
    source = ('<html><head><script>const x="a\r\nb";</script>'
              '<style>/*a\r\nb*/</style></head><body><!--keep\r\ncomment-->'
              '<pre>Alpha\r\nBeta</pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001", "line-000002"], "role": "literal-layout", "evidence": "Alpha"},
    ])
    artifact = _api()[0](source, analysis, review)
    original = BeautifulSoup(source, "html.parser")
    projected = BeautifulSoup(artifact.unmarked_html, "html.parser")
    assert projected.script.string == original.script.string
    assert projected.style.string == original.style.string
    assert projected.find(string=lambda text: text.__class__.__name__ == "Comment") == original.find(
        string=lambda text: text.__class__.__name__ == "Comment")
    assert "<!--keep\r\ncomment-->" in artifact.unmarked_html


def test_retained_explicit_code_crlf_survives_real_consumers(tmp_path):
    from web_translator.extract import extract_segments
    from web_translator.assemble import assemble_page
    from web_translator.models import Translation
    from web_translator.preformatted_projection import encode_projection_transport

    source = ('<html><head></head><body><pre>Read this</pre>'
              '<pre><code>A\r\nB</code></pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Read this"},
    ])
    artifact = _api()[0](source, analysis, review)
    staged = tmp_path / "run" / "source.html"
    staged.parent.mkdir()
    staged.write_bytes(artifact.unmarked_html.encode())
    segments = extract_segments(staged, tmp_path / "segments.jsonl")
    marked = staged.read_bytes().decode("utf-8")
    staged.write_bytes(encode_projection_transport(marked, artifact).encode())
    output = assemble_page(staged, {item.id: item for item in segments},
                           {item.id: Translation(item.id, item.source_text) for item in segments},
                           {}, tmp_path / "output", "https://example.com/")
    rendered = output.read_bytes().decode("utf-8")
    _api()[2](artifact, rendered)
    assert BeautifulSoup(rendered, "html.parser").find("pre").code.get_text() == "A\r\nB"


def test_flow_anchor_approved_attribute_translation_survives_real_consumers(tmp_path):
    from web_translator.extract import extract_segments
    from web_translator.assemble import assemble_page
    from web_translator.models import Translation
    from web_translator.preformatted_projection import encode_projection_transport

    source = ('<html><head></head><body><pre>Read '
              '<a id="guide" href="/safe" title="English title" aria-label="English label">docs</a>'
              '</pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Read docs"},
    ])
    artifact = _api()[0](source, analysis, review)
    staged = tmp_path / "run" / "source.html"
    staged.parent.mkdir()
    staged.write_bytes(artifact.unmarked_html.encode())
    segments = extract_segments(staged, tmp_path / "segments.jsonl")
    located = [item for item in segments if item.semantic_type == "located:link"]
    assert len(located) == 1
    assert "English title" in located[0].source_text
    translations = {item.id: Translation(item.id, item.source_text.replace(
        "English title", "Korean title").replace("English label", "Korean label")) for item in segments}
    staged.write_bytes(encode_projection_transport(staged.read_bytes().decode(), artifact).encode())
    output = assemble_page(staged, {item.id: item for item in segments}, translations,
                           {}, tmp_path / "output", "https://example.com/")
    rendered = output.read_bytes().decode()
    anchor = BeautifulSoup(rendered, "html.parser").find(id="guide")
    assert anchor["title"] == "Korean title"
    assert anchor["aria-label"] == "Korean label"
    assert anchor["href"] == "/safe"
    _api()[2](artifact, rendered)
    with pytest.raises(ValueError, match="anchor|href"):
        _api()[2](artifact, rendered.replace('href="/safe"', 'href="/evil"'))


def test_ordinary_neighbor_anchor_attribute_translation_remains_valid(tmp_path):
    from web_translator.extract import extract_segments
    from web_translator.assemble import assemble_page
    from web_translator.models import Translation
    from web_translator.preformatted_projection import encode_projection_transport

    source = ('<html><head></head><body><p><a id="outside" href="/manual" '
              'title="Read manual">Manual</a></p><pre>Reviewed prose</pre>'
              '<pre><code id="fixed" title="Literal title">x</code></pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Reviewed prose"},
    ])
    artifact = _api()[0](source, analysis, review)
    staged = tmp_path / "run" / "source.html"
    staged.parent.mkdir()
    staged.write_bytes(artifact.unmarked_html.encode())
    segments = extract_segments(staged, tmp_path / "segments.jsonl")
    assert any(item.semantic_type == "located:link" and "Read manual" in item.source_text
               for item in segments)
    translations = {item.id: Translation(item.id, item.source_text.replace(
        "Read manual", "Lire le manuel")) for item in segments}
    staged.write_bytes(encode_projection_transport(staged.read_bytes().decode(), artifact).encode())
    output = assemble_page(staged, {item.id: item for item in segments}, translations,
                           {}, tmp_path / "output", "https://example.com/")
    rendered = output.read_bytes().decode()
    soup = BeautifulSoup(rendered, "html.parser")
    assert soup.find(id="outside")["title"] == "Lire le manuel"
    assert soup.find(id="outside")["href"] == "/manual"
    assert soup.find(id="fixed")["title"] == "Literal title"
    _api()[2](artifact, rendered)


def test_verifier_rejects_opaque_url_moved_outside_owned_block():
    url = "https://example.test"
    source = f'<html><head></head><body><pre>Read {url}</pre></body></html>'
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Read",
         "literal_spans": [_span("url", "line-000001", 5, "line-000001", 25, url)]},
    ])
    artifact = _api()[0](source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    url_tag = soup.select_one("[data-wt-preformatted-url]")
    soup.body.append(url_tag.extract())
    with pytest.raises(ValueError, match="opaque|ownership"):
        _api()[2](artifact, str(soup))


def test_verifier_rejects_missing_identical_retained_constraints():
    source = ('<html><head></head><body><pre>Read this</pre>'
              '<pre><code>same</code></pre><pre><code>same</code></pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Read this"},
    ])
    artifact = _api()[0](source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    soup.find_all("pre")[1].decompose()
    with pytest.raises(ValueError, match="constraint"):
        _api()[2](artifact, str(soup))


def test_verifier_rejects_relocated_retained_constraint_with_same_content():
    source = ('<html><head></head><body><pre>Read this</pre><p>Outside</p>'
              '<pre><code>fixed</code></pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Read this"},
    ])
    artifact = _api()[0](source, analysis, review)
    soup = BeautifulSoup(artifact.unmarked_html, "html.parser")
    retained = soup.find("pre")
    soup.body.insert(0, retained.extract())
    with pytest.raises(ValueError, match="constraint"):
        _api()[2](artifact, str(soup))


@pytest.mark.parametrize("document_prefix, source_path, projected_path", [
    ("<!doctype html>", "/html[1]/body[1]/pre[1]", "/html[2]/body[1]/pre[1]"),
    ("<!doctype html>\n<!--document comment-->\n", "/html[4]/body[1]/pre[1]",
     "/html[4]/body[1]/pre[1]"),
])
def test_doctype_retained_code_path_survives_real_consumers_and_rejects_relocation(
    tmp_path, document_prefix, source_path, projected_path
):
    # Catches recording the retained pre's path before serialization inserts a doctype newline.
    from web_translator.extract import extract_segments
    from web_translator.assemble import assemble_page
    from web_translator.models import Translation
    from web_translator.preformatted_projection import encode_projection_transport

    source = (document_prefix + '<html><head></head><body><pre>Reviewed prose</pre>'
              '<pre id="code"><code>A\r\nB</code></pre></body></html>')
    analysis, review = _review(source, [
        {"line_ids": ["line-000001"], "role": "prose", "evidence": "Reviewed prose"},
    ])
    artifact = _api()[0](source, analysis, review)
    assert artifact.evidence["constraints"][0]["path"] == source_path
    assert artifact.evidence["constraints"][0]["projected_path"] == projected_path
    staged = tmp_path / "run" / "source.html"
    staged.parent.mkdir()
    staged.write_bytes(artifact.unmarked_html.encode())
    segments = extract_segments(staged, tmp_path / "segments.jsonl")
    staged.write_bytes(encode_projection_transport(staged.read_bytes().decode(), artifact).encode())
    output = assemble_page(staged, {item.id: item for item in segments},
                           {item.id: Translation(item.id, item.source_text) for item in segments},
                           {}, tmp_path / "output", "https://example.com/")
    rendered = output.read_bytes().decode()
    _api()[2](artifact, rendered)
    soup = BeautifulSoup(rendered, "html.parser")
    assert soup.find("pre", id="code").get_text() == "A\r\nB"
    retained = soup.find("pre", id="code")
    soup.body.insert(0, retained.extract())
    with pytest.raises(ValueError, match="constraint"):
        _api()[2](artifact, str(soup))
