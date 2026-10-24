from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from supertranslator.models import (
    Finding,
    MasterReview,
    ProtectedToken,
    QAInputs,
    QAResult,
)
from supertranslator.qa import _check_external_dependencies, run_qa
from supertranslator.protection import protect_fragment
from supertranslator.report import write_manifest, write_review_report


TOKEN = "⟦WT:000000⟧"


def _producer_url_boundary_result(tmp_path, source_fragment, translation, output_fragment,
                                  expected_urls, in_title=False):
    prefix = "<!--wt-location:attribute:title-->" if in_title else ""
    _, raw_tokens = protect_fragment(prefix + source_fragment)
    assert [t.value for t in raw_tokens if t.kind == "url"] == expected_urls
    tokens = [ProtectedToken(t.token, "location" if t.value == prefix and prefix else t.kind,
                             t.value) for t in raw_tokens]
    if in_title:
        source_body = f'<main><p data-wt-segment="a" title="{source_fragment}">Hello</p></main>'
        output_body = f'<main><p title="{output_fragment}">안녕</p></main>'
        translation = "⟦WT:000000⟧" + translation.replace("⟦WT:000000⟧", "⟦WT:000001⟧")
    else:
        source_body = f'<main><p data-wt-segment="a">{source_fragment}</p></main>'
        output_body = f'<main><p>{output_fragment}</p></main>'
    source, output = _write_pages(tmp_path, source_body=source_body, output_body=output_body)
    return run_qa(_inputs(source, output, protected_tokens={"a": tokens},
                          translated_texts={"a": translation}))


@pytest.mark.parametrize("in_title", [False, True], ids=["body", "title"])
@pytest.mark.parametrize("source_fragment,translation,output_fragment,expected_urls", [
    ("Read https://example.com/doc today.", "⟦WT:000000⟧에서 확인하세요.",
     "https://example.com/doc에서 확인하세요.", ["https://example.com/doc"]),
    ("Read https://example.com/안내 today.", "⟦WT:000000⟧로 이동합니다.",
     "https://example.com/안내로 이동합니다.", ["https://example.com/안내"]),
    ("Read &lt;https://example.com/doc&gt;.", "참조 &lt;⟦WT:000000⟧;.",
     "참조 &lt;https://example.com/doc&gt;.", ["https://example.com/doc&gt"]),
    ("Read &lt;https://example.com/doc?r=1&amp;s=2&gt;.",
     "참조 &lt;⟦WT:000000⟧;.", "참조 &lt;https://example.com/doc?r=1&amp;s=2&gt;.",
     ["https://example.com/doc?r=1&amp;s=2&gt"]),
    ("Read https://example.com/doc&rarr;.", "참조 ⟦WT:000000⟧;.",
     "참조 https://example.com/doc&rarr;.", ["https://example.com/doc&rarr"]),
], ids=["korean-adjacency", "korean-path", "split-gt", "query-and-split-gt", "split-nonlegacy-entity"])
def test_source_bound_url_boundary_accepts_owned_prose_and_complete_entity(
    tmp_path, in_title, source_fragment, translation, output_fragment, expected_urls,
):
    # Catch lexical overconsumption and decoding each side of a producer boundary separately.
    result = _producer_url_boundary_result(tmp_path, source_fragment, translation,
                                           output_fragment, expected_urls, in_title)
    assert result.passed
    assert result.required_findings == []
    assert result.warnings == []


@pytest.mark.parametrize("in_title", [False, True], ids=["body", "title"])
@pytest.mark.parametrize("output_fragment", [
    "https://example.com/doc/extra에서 확인하세요.",
    "https://example.com/doc?q=2에서 확인하세요.",
    "https://example.com/doc#extra에서 확인하세요.",
    "https://other.example/doc에서 확인하세요.",
    "https://example.com/docX에서 확인하세요.",
    "https://example.com/doc한글에서 확인하세요.",
    "https://example.com/doc에서추가 확인하세요.",
    "https://example.com/doc에서 확인하세요. https://example.com/doc로 이동합니다.",
    "https://example.com/doc에서 확인하세요. https://example.com/doc 문서.",
], ids=["path", "query", "fragment", "host", "ascii-suffix", "unicode-suffix",
         "partial-prose-prefix", "duplicate-other-particle", "duplicate-spaced"])
def test_source_bound_url_boundary_rejects_extensions_and_duplicate_particles(
    tmp_path, in_title, output_fragment,
):
    # A prefix or just the first Korean guard character cannot establish token ownership.
    result = _producer_url_boundary_result(
        tmp_path, "Read https://example.com/doc today.", "⟦WT:000000⟧에서 확인하세요.",
        output_fragment, ["https://example.com/doc"], in_title)
    assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("output_fragment", [
    "https://example.com/안내서로 이동합니다.",
    "https://example.com/안내/다음로 이동합니다.",
    "https://example.com/안로 이동합니다.",
])
def test_source_bound_url_boundary_does_not_terminate_at_nonascii_path(tmp_path, output_fragment):
    result = _producer_url_boundary_result(
        tmp_path, "Read https://example.com/안내 today.", "⟦WT:000000⟧로 이동합니다.",
        output_fragment, ["https://example.com/안내"])
    assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("output_fragment", ["https://example.com/doc에서/extra", "https://example.com/doc에서추가"])
def test_source_bound_url_boundary_rejects_extension_after_entire_adjacent_literal(tmp_path, output_fragment):
    # Even the entire held literal is only evidence if its end boundary is preserved.
    result = _producer_url_boundary_result(
        tmp_path, "Read https://example.com/doc today.", "⟦WT:000000⟧에서",
        output_fragment, ["https://example.com/doc"])
    assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("following,kind", [
    ("MUST", "keyword"), ("git status", "command"), ("https://example.com/next", "url"),
])
@pytest.mark.parametrize("gap,accepted", [("", True), ("추가", False), ("/extra", False)])
def test_source_bound_url_literal_anchors_following_regular_token(tmp_path, following, kind, gap, accepted):
    # The literal's far edge must be the held next token, not arbitrary added URL/prose data.
    _, tokens = protect_fragment(f"Read https://example.com/doc then {following}")
    assert [(t.kind, t.value) for t in tokens] == [
        ("url", "https://example.com/doc"), (kind, following),
    ]
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">Read https://example.com/doc then {following}</p></main>',
        output_body=f'<main><p>https://example.com/doc에서{gap}{following}</p></main>',
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens},
                           translated_texts={"a": "⟦WT:000000⟧에서⟦WT:000001⟧"}))
    if accepted:
        assert result.passed
        assert result.required_findings == []
    else:
        assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("output_fragment,accepted", [
    ("https://example.com/doc에서MUST 및 https://example.com/doc에서추가MAY", True),
    ("https://example.com/doc에서추가MUST 및 https://example.com/doc에서MAY", False),
])
def test_source_bound_url_literal_keeps_its_following_token_pair(tmp_path, output_fragment, accepted):
    # Repeated URLs cannot swap literal/token pairs merely because all first letters agree.
    source_fragment = "Read https://example.com/doc then MUST and https://example.com/doc then MAY"
    _, tokens = protect_fragment(source_fragment)
    assert [(t.kind, t.value) for t in tokens] == [
        ("url", "https://example.com/doc"), ("keyword", "MUST"),
        ("url", "https://example.com/doc"), ("keyword", "MAY"),
    ]
    source, output = _write_pages(
        tmp_path, source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f'<main><p>{output_fragment}</p></main>',
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens}, translated_texts={
        "a": "⟦WT:000000⟧에서⟦WT:000001⟧ 및 ⟦WT:000002⟧에서추가⟦WT:000003⟧",
    }))
    if accepted:
        assert result.passed
    else:
        assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("output_fragment,accepted", [
    ("https://example.com/doc에서MUST. https://example.com/doc에서MAY. MUST.", True),
    ("https://example.com/doc에서MUST. https://example.com/doc에서MUST. MAY.", False),
])
def test_source_bound_url_literal_keeps_repeated_next_token_multiplicity(tmp_path, output_fragment, accepted):
    # Matching any known pair is insufficient when an unrelated keyword copy masks a lost pair.
    source_fragment = "Read https://example.com/doc then MUST. Read https://example.com/doc then MAY. MUST."
    _, tokens = protect_fragment(source_fragment)
    assert [(t.kind, t.value) for t in tokens] == [
        ("url", "https://example.com/doc"), ("keyword", "MUST"),
        ("url", "https://example.com/doc"), ("keyword", "MAY"), ("keyword", "MUST"),
    ]
    source, output = _write_pages(
        tmp_path, source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f'<main><p>{output_fragment}</p></main>',
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens}, translated_texts={
        "a": "⟦WT:000000⟧에서⟦WT:000001⟧. ⟦WT:000002⟧에서⟦WT:000003⟧. ⟦WT:000004⟧.",
    }))
    if accepted:
        assert result.passed
    else:
        assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("output_fragment,accepted", [
    ("https://example.com/doc에서https://example.com/안. https://example.com/안내.", True),
    ("https://example.com/doc에서https://example.com/안내. https://example.com/안.", False),
])
def test_source_bound_url_literal_requires_exact_following_url_occurrence(tmp_path, output_fragment, accepted):
    # A next-URL anchor cannot accept a Unicode path prefix while an intact copy lives elsewhere.
    source_fragment = "Read https://example.com/doc then https://example.com/안. Read https://example.com/안내."
    _, tokens = protect_fragment(source_fragment)
    assert [(t.kind, t.value) for t in tokens] == [
        ("url", "https://example.com/doc"), ("url", "https://example.com/안"),
        ("url", "https://example.com/안내"),
    ]
    source, output = _write_pages(
        tmp_path, source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f'<main><p>{output_fragment}</p></main>',
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens}, translated_texts={
        "a": "⟦WT:000000⟧에서⟦WT:000001⟧. ⟦WT:000002⟧.",
    }))
    if accepted:
        assert result.passed
    else:
        assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("source_fragment,translation,output_fragment,accepted", [
    ("Read <em>https://example.com/doc</em> today.",
     "⟦WT:000000⟧⟦WT:000001⟧에서 확인하세요.⟦WT:000002⟧",
     "<em>https://example.com/doc에서 확인하세요.</em>", True),
    ("Read https://example.com/doc today. <code>https://example.com/doc</code>",
     "⟦WT:000000⟧에서 확인하세요. ⟦WT:000001⟧",
     "https://example.com/changed에서 확인하세요. <code>https://example.com/doc</code>", False),
    ('Read <a href="https://example.com/doc">https://example.com/doc</a> today.',
     "⟦WT:000000⟧⟦WT:000001⟧에서 확인하세요.⟦WT:000002⟧",
     '<a href="https://example.com/doc">https://example.com/changed에서 확인하세요.</a>', False),
], ids=["inline-tag", "opaque-code-not-owned", "href-not-owned"])
def test_source_bound_url_boundary_respects_inline_and_opaque_ownership(
    tmp_path, source_fragment, translation, output_fragment, accepted,
):
    result = _producer_url_boundary_result(
        tmp_path, source_fragment, translation, output_fragment, ["https://example.com/doc"])
    assert ("protected-token-integrity" not in {f.code for f in result.required_findings}) == accepted


def test_source_bound_url_boundary_cannot_count_title_url_as_content_occurrence(tmp_path):
    producer = ("<!--wt-location:attribute:title-->Read https://example.com/doc today."
                "<!--wt-location:content-->Read https://example.com/doc today.")
    _, raw_tokens = protect_fragment(producer)
    tokens = [ProtectedToken(t.token, "location" if t.value.startswith("<!--wt-location:") else t.kind,
                             t.value) for t in raw_tokens]
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a" title="Read https://example.com/doc today.">'
                    'Read https://example.com/doc today.</p></main>',
        output_body='<main><p title="https://example.com/doc로 이동합니다. '
                    'https://example.com/doc에서 확인하세요.">'
                    'https://example.com/changed에서 확인하세요.</p></main>',
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens}, translated_texts={
        "a": "⟦WT:000000⟧⟦WT:000001⟧로 이동합니다.⟦WT:000002⟧⟦WT:000003⟧에서 확인하세요.",
    }))
    assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("translation,accepted", [
    ("⟦WT:000000⟧⟦WT:000001⟧에서 확인하세요.⟦WT:000002⟧⟦WT:000003⟧로 이동합니다.", True),
    ("⟦WT:000000⟧⟦WT:000001⟧에서⟦WT:000003⟧⟦WT:000002⟧", False),
], ids=["correct-location-order", "cross-location-next-url"])
def test_source_bound_url_cross_location_next_anchor_fails_closed(tmp_path, translation, accepted):
    # Exact placeholder counts do not authorize a next URL owned by another location.
    producer = ("<!--wt-location:attribute:title-->Read https://example.com/title today."
                "<!--wt-location:content-->Read https://example.com/body today.")
    _, raw_tokens = protect_fragment(producer)
    tokens = [ProtectedToken(t.token, "location" if t.value.startswith("<!--wt-location:") else t.kind,
                             t.value) for t in raw_tokens]
    assert [(t.kind, t.value) for t in tokens] == [
        ("location", "<!--wt-location:attribute:title-->"), ("url", "https://example.com/title"),
        ("location", "<!--wt-location:content-->"), ("url", "https://example.com/body"),
    ]
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a" title="Read https://example.com/title today.">'
                    'Read https://example.com/body today.</p></main>',
        output_body='<main><p title="https://example.com/title에서 확인하세요.">'
                    'https://example.com/body로 이동합니다.</p></main>',
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens},
                           translated_texts={"a": translation}))
    if accepted:
        assert result.passed
        assert result.required_findings == []
    else:
        assert {f.code for f in result.required_findings} == {"protected-token-integrity"}


@pytest.mark.parametrize("in_title", [False, True], ids=["body", "title"])
@pytest.mark.parametrize("output_fragment", [
    "참조 &lt;https://example.com/doc&lt;.",
    "참조 &lt;https://example.com/doc&gt;;.",
    "참조 &lt;https://example.com/doc&gt;,",
    "참조 &lt;https://example.com/doc/extra&gt;.",
    "참조 &lt;https://example.com/doc?q=2&gt;.",
    "참조 &lt;https://example.com/doc&gt;. https://example.com/doc&gt;.",
    "참조 &lt;https://example.com/doc&amp;gt;.",
], ids=["changed-delimiter", "extra-semicolon", "changed-terminator", "path", "query",
         "duplicate", "no-double-decode"])
def test_source_bound_url_boundary_keeps_entity_delimiter_and_terminator_guards(
    tmp_path, in_title, output_fragment,
):
    result = _producer_url_boundary_result(
        tmp_path, "Read &lt;https://example.com/doc&gt;.", "참조 &lt;⟦WT:000000⟧;.",
        output_fragment, ["https://example.com/doc&gt"], in_title)
    assert "protected-token-integrity" in {f.code for f in result.required_findings}


@pytest.mark.parametrize("output_fragment,accepted", [
    ("https://example.com/doc에서 읽고 https://example.com/doc로 이동합니다.", True),
    ("https://example.com/doc에서 읽고 https://example.com/doc에서 읽고 "
     "https://example.com/doc로 이동합니다.", False),
    ("https://example.com/doc에서 읽고 https://example.com/doc/next로 이동합니다.", False),
])
def test_source_bound_url_boundary_keeps_repeated_occurrence_counts(tmp_path, output_fragment, accepted):
    result = _producer_url_boundary_result(
        tmp_path, "Read https://example.com/doc and https://example.com/doc today.",
        "⟦WT:000000⟧에서 읽고 ⟦WT:000001⟧로 이동합니다.", output_fragment,
        ["https://example.com/doc", "https://example.com/doc"])
    assert ("protected-token-integrity" not in {f.code for f in result.required_findings}) == accepted


@pytest.mark.parametrize("output_fragment,accepted", [
    ("https://example.com/doc에서 읽고 https://example.com/doc/next로 이동합니다.", True),
    ("https://example.com/doc/next에서 읽고 https://example.com/doc/next로 이동합니다.", False),
    ("https://example.com/doc에서 읽고 https://example.com/doc로 이동합니다.", False),
])
def test_source_bound_url_boundary_keeps_overlapping_value_ownership(tmp_path, output_fragment, accepted):
    result = _producer_url_boundary_result(
        tmp_path, "Read https://example.com/doc and https://example.com/doc/next today.",
        "⟦WT:000000⟧에서 읽고 ⟦WT:000001⟧로 이동합니다.", output_fragment,
        ["https://example.com/doc", "https://example.com/doc/next"])
    assert ("protected-token-integrity" not in {f.code for f in result.required_findings}) == accepted


def test_source_bound_url_boundaries_survive_normal_extraction_assembly_and_qa(tmp_path):
    # Catch a unit-only fix that fails with real extracted location metadata and restored HTML.
    from supertranslator.assemble import assemble_page
    from supertranslator.extract import extract_segments
    from supertranslator.models import Translation

    captured = tmp_path / "capture" / "source.html"
    captured.parent.mkdir()
    captured.write_text('<!doctype html><html><head><meta charset="utf-8"></head><body><main>'
                        '<p id="prose" title="Read https://example.com/안내 today.">'
                        'Read https://example.com/doc today.</p>'
                        '<p id="citation">Read &lt;https://example.com/ref&gt;.</p>'
                        '</main></body></html>', encoding="utf-8")
    segments = extract_segments(captured, captured.parent / "segments.jsonl")
    authored = {
        "prose": ("https://example.com/doc에서 확인하세요.", "https://example.com/안내로 이동합니다."),
        "citation": ("참조 <https://example.com/ref>.", None),
    }
    source_dom = BeautifulSoup(captured.read_text(encoding="utf-8"), "html.parser")
    translations = {}
    for segment in segments:
        owner = source_dom.select_one(segment.locator)["id"]
        if owner == "prose":
            translated = segment.source_text.replace("Read ", "").replace(" today.", "로 이동합니다.", 1)
            translated = translated.replace(" today.", "에서 확인하세요.")
        else:
            translated = segment.source_text.replace("Read ", "참조 ")
        translations[segment.id] = Translation(segment.id, translated, None, {})
    index = assemble_page(captured, {s.id: s for s in segments}, translations, {},
                          tmp_path / "output", "https://example.com/")
    final = BeautifulSoup(index.read_text(encoding="utf-8"), "html.parser")
    for owner, (body, title) in authored.items():
        assert final.find(id=owner).get_text() == body
        if title is not None:
            assert final.find(id=owner)["title"] == title
    result = run_qa(_inputs(
        captured, index, source_segment_ids={s.id for s in segments},
        translated_segment_ids=set(translations),
        protected_tokens={s.id: s.protected for s in segments},
        translated_texts={sid: t.text for sid, t in translations.items()},
    ))
    assert result.passed
    assert result.required_findings == []


def _write_pages(
    root: Path,
    *,
    source_body: str = '<main><p data-wt-segment="a">Hello</p></main>',
    output_body: str = "<main><p>안녕하세요</p></main>",
    head: str = "",
    output_head: str | None = None,
) -> tuple[Path, Path]:
    work = root / "작업 공간"
    output = root / "번역 결과"
    work.mkdir(parents=True)
    output.mkdir(parents=True)
    source = work / "source.html"
    index = output / "index.html"
    source.write_text(
        f"<!doctype html><html><head>{head}</head><body>{source_body}</body></html>",
        encoding="utf-8",
    )
    index.write_text(
        f"<!doctype html><html><head>{head if output_head is None else output_head}</head><body>{output_body}"
        '<footer data-wt-attribution="source">source</footer></body></html>',
        encoding="utf-8",
    )
    return source, index


def _inputs(source: Path, output: Path, **overrides: object) -> QAInputs:
    values: dict[str, object] = {
        "source_html": source,
        "output_html": output,
        "source_url": "https://example.com/docs",
        "source_segment_ids": {"a"},
        "translated_segment_ids": {"a"},
        "critical_assets": [],
        "optional_assets": [],
        "screenshot_dir": source.parent / "QA 스크린샷",
        "master_review": MasterReview([], {}, {}),
    }
    values.update(overrides)
    return QAInputs(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize('indicator', ['preformatted', 'assets'])
def test_direct_legacy_qa_holds_absence_through_checks(tmp_path, monkeypatch, indicator):
    # A late state appearance must invalidate even direct callers without capture.json.
    import supertranslator.qa as qa
    source, output = _write_pages(tmp_path)
    real = qa._run_qa

    def check_then_prepare(inputs):
        result = real(inputs)
        if indicator == 'assets':
            (source.parent / 'assets').mkdir()
            (source.parent / 'assets/wt-preformatted-new.css').write_bytes(b'/* new */')
        else:
            (source.parent / 'preformatted').mkdir()
        return result

    monkeypatch.setattr(qa, '_run_qa', check_then_prepare)
    result = qa.run_qa(_inputs(source, output, translated_segment_ids=set()))
    assert not result.passed
    assert 'preformatted-provenance' in {f.code for f in result.required_findings}
    assert not (source.parent / 'capture.json').exists()


def test_qa_fails_incomplete_translation_and_broken_critical_asset(tmp_path: Path) -> None:
    source, output = _write_pages(tmp_path)
    result = run_qa(
        _inputs(
            source,
            output,
            source_segment_ids={"a", "b"},
            translated_segment_ids={"a"},
            critical_assets=[Path("assets/main.css")],
        )
    )

    assert result.passed is False
    assert {finding.code for finding in result.required_findings} == {
        "translation-coverage",
        "critical-asset-missing",
    }
    coverage = result.required_findings[0].evidence
    assert coverage == {"foreign": [], "missing": ["b"]}
    assert result.screenshots == []


def test_qa_detects_changed_protected_token_multiset_and_leaked_placeholder(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        output_body=f"<main><p>번역 {TOKEN}</p></main>",
    )
    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={"a": [ProtectedToken(TOKEN, "keyword", "MUST")]},
            translated_texts={"a": "번역"},
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity"
    ]
    assert result.required_findings[0].evidence == {
        "changed_segments": ["a"],
        "leaked_placeholders": [TOKEN],
    }


def test_location_tokens_are_transparent_metadata_but_keep_placeholder_integrity(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><input data-wt-segment="a" placeholder="Enter token"></main>'
        ),
        output_body='<main><input placeholder="토큰 입력"></main>',
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={
                "a": [
                    ProtectedToken(
                        TOKEN,
                        "location",
                        "<!--wt-location:attribute:placeholder-->",
                    )
                ]
            },
            translated_texts={"a": f"{TOKEN}토큰 입력"},
        )
    )

    assert result.passed is True
    assert result.required_findings == []


def test_nested_segment_tokens_are_transparent_after_child_translation(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><div data-wt-segment="a">'
            '<p data-wt-segment="b">Hello child</p></div></main>'
        ),
        output_body='<main><div><p>번역된 하위 항목</p></div></main>',
    )
    child_token = ProtectedToken(
        TOKEN,
        "segment",
        '<p data-wt-segment="b">Hello child</p>',
    )

    result = run_qa(
        _inputs(
            source,
            output,
            source_segment_ids={"a", "b"},
            translated_segment_ids={"a", "b"},
            protected_tokens={"a": [child_token]},
            translated_texts={"a": TOKEN, "b": "번역된 하위 항목"},
        )
    )

    assert result.passed is True
    assert result.required_findings == []


def test_location_aware_attribute_protected_values_are_checked_in_attributes(
    tmp_path: Path,
) -> None:
    identifier_token = TOKEN.replace("000000", "000001")
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><input data-wt-segment="a" placeholder="OAuth token"></main>'
        ),
        output_body='<main><input placeholder="OAuth 토큰"></main>',
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={
                "a": [
                    ProtectedToken(
                        TOKEN,
                        "location",
                        "<!--wt-location:attribute:placeholder-->",
                    ),
                    ProtectedToken(identifier_token, "identifier", "OAuth"),
                ]
            },
            translated_texts={"a": f"{TOKEN}{identifier_token} 토큰"},
        )
    )

    assert result.passed is True
    assert result.required_findings == []


def test_location_aware_attribute_rejects_changed_protected_values(
    tmp_path: Path,
) -> None:
    identifier_token = TOKEN.replace("000000", "000001")
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><input data-wt-segment="a" placeholder="OAuth token"></main>'
        ),
        output_body='<main><input placeholder="OIDC 토큰"></main>',
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={
                "a": [
                    ProtectedToken(
                        TOKEN,
                        "location",
                        "<!--wt-location:attribute:placeholder-->",
                    ),
                    ProtectedToken(identifier_token, "identifier", "OAuth"),
                ]
            },
            translated_texts={"a": f"{TOKEN}{identifier_token} 토큰"},
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity"
    ]


def test_protected_token_integrity_locates_marked_title_in_document_head(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body="<main>Body</main>",
        output_body="<main>본문</main>",
        head='<title data-wt-segment="a">OAuth Guide</title>',
        output_head="<title>OAuth 가이드</title>",
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={
                "a": [ProtectedToken(TOKEN, "identifier", "OAuth")]
            },
            translated_texts={"a": f"{TOKEN} 가이드"},
        )
    )

    assert result.passed is True
    assert result.required_findings == []


@pytest.mark.parametrize(
    "source_head",
    [
        "<title>OAuth Guide</title>",
        (
            '<title data-wt-segment="a">OAuth Guide</title>'
            '<meta data-wt-segment="a" content="OAuth">'
        ),
    ],
)
def test_protected_token_integrity_rejects_missing_or_duplicate_source_markers(
    tmp_path: Path, source_head: str
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body="<main>Body</main>",
        output_body="<main>본문</main>",
        head=source_head,
        output_head="<title>OAuth 가이드</title>",
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={
                "a": [ProtectedToken(TOKEN, "identifier", "OAuth")]
            },
            translated_texts={"a": f"{TOKEN} 가이드"},
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity"
    ]


def test_qa_detects_protected_value_changed_after_placeholder_restoration(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a">Clients MUST retry.</p></main>',
        output_body="<main><p>Client는 SHOULD 재시도한다.</p></main>",
    )
    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={"a": [ProtectedToken(TOKEN, "keyword", "MUST")]},
            translated_texts={"a": f"Client는 {TOKEN} 재시도한다."},
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity"
    ]
    assert result.required_findings[0].evidence["changed_segments"] == ["a"]


def test_protected_keyword_must_not_match_inside_a_larger_word(tmp_path: Path) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a">Clients MUST retry.</p></main>',
        output_body="<main><p>Client는 MUSTARD를 재시도한다.</p></main>",
    )
    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={"a": [ProtectedToken(TOKEN, "keyword", "MUST")]},
            translated_texts={"a": f"Client는 {TOKEN}를 재시도한다."},
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity"
    ]


def test_punctuation_terminated_protected_value_cannot_gain_a_suffix(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">See https://example.com/.</p>'
            '<p data-wt-segment="b">Run python -m pip install .</p></main>'
        ),
        output_body=(
            '<main><p>https://example.com/evil 참조.</p>'
            '<p>python -m pip install .evil 실행.</p></main>'
        ),
    )
    command_token = "⟦WT:000001⟧"
    result = run_qa(
        _inputs(
            source,
            output,
            source_segment_ids={"a", "b"},
            translated_segment_ids={"a", "b"},
            protected_tokens={
                "a": [ProtectedToken(TOKEN, "url", "https://example.com/")],
                "b": [
                    ProtectedToken(command_token, "command", "python -m pip install .")
                ],
            },
            translated_texts={
                "a": f"{TOKEN} 참조.",
                "b": f"{command_token} 실행.",
            },
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity"
    ]
    assert result.required_findings[0].evidence["changed_segments"] == ["a", "b"]


def test_protected_url_rejects_added_path_and_query_but_allows_sentence_period(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">Visit https://example.com.</p>'
            '<p data-wt-segment="b">Visit https://example.com/.</p>'
            '<p data-wt-segment="c">Visit https://safe.example/.</p></main>'
        ),
        output_body=(
            '<main><p>https://example.com/evil 방문.</p>'
            '<p>https://example.com/?evil 방문.</p>'
            '<p>https://safe.example/. 방문.</p></main>'
        ),
    )
    tokens = [f"⟦WT:{index:06d}⟧" for index in range(3)]
    result = run_qa(
        _inputs(
            source,
            output,
            source_segment_ids={"a", "b", "c"},
            translated_segment_ids={"a", "b", "c"},
            protected_tokens={
                "a": [ProtectedToken(tokens[0], "url", "https://example.com")],
                "b": [ProtectedToken(tokens[1], "url", "https://example.com/")],
                "c": [ProtectedToken(tokens[2], "url", "https://safe.example/")],
            },
            translated_texts={
                "a": f"{tokens[0]} 방문.",
                "b": f"{tokens[1]} 방문.",
                "c": f"{tokens[2]}. 방문.",
            },
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity"
    ]
    assert result.required_findings[0].evidence["changed_segments"] == ["a", "b"]


def test_protected_url_rejects_an_extra_complete_value_with_a_different_boundary(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">'
            'Visit https://example.com/docs normal.</p></main>'
        ),
        output_body=(
            '<main><p>https://example.com/docs normal. '
            'Duplicate https://example.com/docs.</p></main>'
        ),
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={
                "a": [ProtectedToken(TOKEN, "url", "https://example.com/docs")]
            },
            translated_texts={"a": f"{TOKEN} normal."},
            master_review=MasterReview(["skip Chromium for token regression"], {}, {}),
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity",
        "master-review-unresolved",
    ]
    assert result.required_findings[0].evidence["changed_segments"] == ["a"]


def test_protected_keyword_rejects_an_extra_complete_value_with_a_different_boundary(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a">MUST retry.</p></main>',
        output_body='<main><p>MUST retry. Duplicate MUST.</p></main>',
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={"a": [ProtectedToken(TOKEN, "keyword", "MUST")]},
            translated_texts={"a": f"{TOKEN} retry."},
            master_review=MasterReview(["skip Chromium for token regression"], {}, {}),
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "protected-token-integrity",
        "master-review-unresolved",
    ]
    assert result.required_findings[0].evidence["changed_segments"] == ["a"]


def test_protected_value_shared_by_keyword_and_identifier_counts_once_per_occurrence(
    tmp_path: Path,
) -> None:
    identifier_token = "⟦WT:000001⟧"
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a">MUST MUST</p></main>',
        output_body='<main><p>MUST MUST</p></main>',
    )

    result = run_qa(
        _inputs(
            source,
            output,
            protected_tokens={
                "a": [
                    ProtectedToken(TOKEN, "keyword", "MUST"),
                    ProtectedToken(identifier_token, "identifier", "MUST"),
                ]
            },
            translated_texts={"a": f"{TOKEN} {identifier_token}"},
        )
    )

    assert result.passed is True
    assert result.required_findings == []


def test_protected_url_text_and_href_are_distinct_locations(tmp_path: Path) -> None:
    url = "https://example.com/spec"
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a"><a href="{url}">Read {url}.</a></p></main>',
        output_body=f'<main><p><a href="{url}">{url} 문서.</a></p></main>',
    )
    result = run_qa(_inputs(
        source, output,
        protected_tokens={"a": [ProtectedToken(TOKEN, "url", url)]},
        translated_texts={"a": f"{TOKEN} 문서."},
    ))
    assert result.required_findings == []
    assert result.warnings == []


@pytest.mark.parametrize(
    ("output_fragment", "accepted"),
    [
        ("Read https://example.com/spec?a=1&amp;b=2.", True),
        ("Read https://example.com/spec?a=1&amp;b=3.", False),
        ("Read https://example.com/spec?a=1&amp;b=2. Again https://example.com/spec?a=1&amp;b=2.", False),
        ("Read https://example.com/spec?a=1&amp;b=2&amp;c=3.", False),
        ("Read https://example.com/spec?a=1&amp;b=2extra.", False),
    ],
    ids=["unchanged", "changed-query", "duplicate", "added-query", "suffix"],
)
def test_producer_entity_url_matches_decoded_owned_text_without_weakening_guards(
    tmp_path: Path, output_fragment: str, accepted: bool,
) -> None:
    source_fragment = "Read https://example.com/spec?a=1&amp;b=2."
    protected_text, tokens = protect_fragment(source_fragment)
    assert [(token.kind, token.value) for token in tokens] == [
        ("url", "https://example.com/spec?a=1&amp;b=2")
    ]
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f"<main><p>{output_fragment}</p></main>",
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens},
                            translated_texts={"a": protected_text}))
    if accepted:
        assert result.required_findings == []
        assert result.warnings == []
    else:
        assert "protected-token-integrity" in {finding.code for finding in result.required_findings}


@pytest.mark.parametrize("output_title,accepted", [
    ("문서 https://example.com/spec?a=1&amp;b=2", True),
    ("문서 https://example.com/spec?a=1&amp;b=3", False),
], ids=["unchanged-url", "changed-query"])
def test_producer_entity_url_in_translated_attribute_keeps_exact_value(
    tmp_path: Path, output_title: str, accepted: bool,
) -> None:
    protected_text, raw_tokens = protect_fragment(
        "<!--wt-location:attribute:title-->Read https://example.com/spec?a=1&amp;b=2"
    )
    assert [(token.kind, token.value) for token in raw_tokens] == [
        ("tag", "<!--wt-location:attribute:title-->"),
        ("url", "https://example.com/spec?a=1&amp;b=2"),
    ]
    tokens = [ProtectedToken(token.token, "location" if token.kind == "tag" else token.kind, token.value)
              for token in raw_tokens]
    source, output = _write_pages(
        tmp_path,
        source_body='<main><span data-wt-segment="a" title="Read https://example.com/spec?a=1&amp;b=2">Hello</span></main>',
        output_body=f'<main><span title="{output_title}">안녕</span></main>',
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens},
                            translated_texts={"a": protected_text}))
    if accepted:
        assert result.required_findings == []
        assert result.warnings == []
    else:
        assert "protected-token-integrity" in {finding.code for finding in result.required_findings}


@pytest.mark.parametrize(
    ("source_fragment", "output_fragment", "expected_urls", "in_title"),
    [
        ("See (https://example.com/docs).", "참조 (https://example.com/docs).",
         ["https://example.com/docs"], False),
        ("See [https://example.com/docs]", "참조 [https://example.com/docs]",
         ["https://example.com/docs"], False),
        ("See {https://example.com/docs}", "참조 {https://example.com/docs}",
         ["https://example.com/docs"], False),
        ("See https://example.com/docs, then continue.",
         "참조 https://example.com/docs, 계속.", ["https://example.com/docs"], False),
        ("See https://example.com/a(b).", "참조 https://example.com/a(b).",
         ["https://example.com/a(b)"], False),
        ("See https://example.com/a[b].", "참조 https://example.com/a[b].",
         ["https://example.com/a[b]"], False),
        ("See https://example.com/spec?a=1&amp;b=2.",
         "참조 https://example.com/spec?a=1&amp;b=2.",
         ["https://example.com/spec?a=1&amp;b=2"], False),
        ("See (https://example.com/docs).", "참조 (https://example.com/docs).",
         ["https://example.com/docs"], True),
        ("See https://example.com/docs and https://example.com/docs.",
         "참조 https://example.com/docs 및 https://example.com/docs.",
         ["https://example.com/docs", "https://example.com/docs"], False),
        ("See https://example.com/docs and https://example.com/docs/next.",
         "참조 https://example.com/docs 및 https://example.com/docs/next.",
         ["https://example.com/docs", "https://example.com/docs/next"], False),
    ],
    ids=["parenthesis", "bracket", "brace", "comma", "balanced-parenthesis",
         "balanced-bracket", "entity-query", "title-parenthesis", "repeated",
         "overlapping-prefixes"],
)
def test_producer_url_prose_delimiters_preserve_exact_values(
    tmp_path: Path, source_fragment: str, output_fragment: str,
    expected_urls: list[str], in_title: bool,
) -> None:
    # This catches a matcher that rejects producer-trimmed prose or loses full URLs.
    producer_input = (
        f"<!--wt-location:attribute:title-->{source_fragment}"
        if in_title else source_fragment
    )
    protected_text, raw_tokens = protect_fragment(producer_input)
    assert [token.value for token in raw_tokens if token.kind == "url"] == expected_urls
    tokens = [
        ProtectedToken(token.token, "location" if token.kind == "tag" else token.kind,
                       token.value)
        for token in raw_tokens
    ]
    if in_title:
        source_body = f'<main><span data-wt-segment="a" title="{source_fragment}">Hello</span></main>'
        output_body = f'<main><span title="{output_fragment}">안녕</span></main>'
    else:
        source_body = f'<main><p data-wt-segment="a">{source_fragment}</p></main>'
        output_body = f'<main><p>{output_fragment}</p></main>'
    source, output = _write_pages(
        tmp_path, source_body=source_body, output_body=output_body,
    )
    result = run_qa(_inputs(
        source, output, protected_tokens={"a": tokens},
        translated_texts={"a": protected_text},
    ))
    assert result.required_findings == []
    assert result.warnings == []


@pytest.mark.parametrize(
    ("source_fragment", "output_fragment", "expected_urls", "in_title"),
    [
        ("See (https://example.com/docs).", "참조 (https://example.com/docs/extra).",
         ["https://example.com/docs"], False),
        ("See (https://example.com/docs).", "참조 (https://example.com/docs?q=2).",
         ["https://example.com/docs"], False),
        ("See (https://example.com/docs).", "참조 (https://example.com/docs.evil).",
         ["https://example.com/docs"], False),
        ("See (https://example.com/docs).", "참조 (https://example.com/docs)/extra.",
         ["https://example.com/docs"], False),
        ("See https://example.com/a(b).", "참조 https://example.com/a(c).",
         ["https://example.com/a(b)"], False),
        ("See https://example.com/a[b].", "참조 https://example.com/a[c].",
         ["https://example.com/a[b]"], False),
        ("See https://example.com/spec?a=1&amp;b=2.",
         "참조 https://example.com/spec?a=1&amp;b=3.",
         ["https://example.com/spec?a=1&amp;b=2"], False),
        ("See (https://example.com/docs).", "참조 (https://example.com/docs). "
         "또 https://example.com/docs]", ["https://example.com/docs"], False),
        ("See https://example.com/docs and https://example.com/docs.",
         "참조 https://example.com/docs 및 https://example.com/docs 및 "
         "https://example.com/docs.",
         ["https://example.com/docs", "https://example.com/docs"], False),
        ("See https://example.com/docs and https://example.com/docs/next.",
         "참조 https://example.com/docs/next 및 https://example.com/docs/next.",
         ["https://example.com/docs", "https://example.com/docs/next"], False),
        ("See (https://example.com/docs).", "참조 (https://example.com/docs/extra).",
         ["https://example.com/docs"], True),
    ],
    ids=["path", "query", "dotted-extension", "closer-then-path",
         "changed-balanced-parenthesis", "changed-balanced-bracket", "changed-entity-query",
         "duplicate-different-delimiter", "extra-repeated", "overlapping-prefix-substitution",
         "title-path"],
)
def test_producer_url_prose_delimiters_reject_extensions_and_duplicates(
    tmp_path: Path, source_fragment: str, output_fragment: str,
    expected_urls: list[str], in_title: bool,
) -> None:
    # This catches accepting a protected URL prefix inside a larger URL or losing counts.
    producer_input = (
        f"<!--wt-location:attribute:title-->{source_fragment}"
        if in_title else source_fragment
    )
    protected_text, raw_tokens = protect_fragment(producer_input)
    assert [token.value for token in raw_tokens if token.kind == "url"] == expected_urls
    tokens = [
        ProtectedToken(token.token, "location" if token.kind == "tag" else token.kind,
                       token.value)
        for token in raw_tokens
    ]
    if in_title:
        source_body = f'<main><span data-wt-segment="a" title="{source_fragment}">Hello</span></main>'
        output_body = f'<main><span title="{output_fragment}">안녕</span></main>'
    else:
        source_body = f'<main><p data-wt-segment="a">{source_fragment}</p></main>'
        output_body = f'<main><p>{output_fragment}</p></main>'
    source, output = _write_pages(
        tmp_path, source_body=source_body, output_body=output_body,
    )
    result = run_qa(_inputs(
        source, output, protected_tokens={"a": tokens},
        translated_texts={"a": protected_text},
    ))
    assert "protected-token-integrity" in {
        finding.code for finding in result.required_findings
    }


@pytest.mark.parametrize("prefix", ["x", "7", "_"], ids=["letter", "digit", "underscore"])
def test_producer_adjacent_prefix_url_preserves_exact_value(
    tmp_path: Path, prefix: str,
) -> None:
    # A producer-recognized URL remains owned even beside an ASCII word character.
    source_fragment = f"See {prefix}https://example.com/docs."
    protected_text, tokens = protect_fragment(source_fragment)
    assert [(token.kind, token.value) for token in tokens] == [
        ("url", "https://example.com/docs")
    ]
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f'<main><p>참조 {prefix}https://example.com/docs.</p></main>',
    )
    result = run_qa(_inputs(
        source, output, protected_tokens={"a": tokens},
        translated_texts={"a": protected_text},
    ))
    assert result.required_findings == []
    assert result.warnings == []


@pytest.mark.parametrize(
    ("source_fragment", "output_fragment"),
    [
        ("See xhttps://example.com/docs.", "참조 xhttps://example.com/docs/evil."),
        ("See https://example.com/docs normal.",
         "https://example.com/docs normal. 또 xhttps://example.com/docs."),
    ],
    ids=["adjacent-extension", "ordinary-plus-prefixed-duplicate"],
)
def test_producer_adjacent_prefix_url_rejects_extension_and_duplicate(
    tmp_path: Path, source_fragment: str, output_fragment: str,
) -> None:
    # The duplicate case catches a missed prefixed URL even if another copy matches.
    protected_text, tokens = protect_fragment(source_fragment)
    assert [(token.kind, token.value) for token in tokens] == [
        ("url", "https://example.com/docs")
    ]
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f'<main><p>{output_fragment}</p></main>',
    )
    result = run_qa(_inputs(
        source, output, protected_tokens={"a": tokens},
        translated_texts={"a": protected_text},
    ))
    assert "protected-token-integrity" in {
        finding.code for finding in result.required_findings
    }


@pytest.mark.parametrize(
    ("source_fragment", "output_fragment", "expected_url", "in_title"),
    [
        ("See https://example.com/?name=O&apos;Reilly.",
         "참조 https://example.com/?name=O&apos;Reilly.",
         "https://example.com/?name=O&apos;Reilly", False),
        ("See https://example.com/?name=O&apos;Reilly.",
         "참조 https://example.com/?name=O&apos;Reilly.",
         "https://example.com/?name=O&apos;Reilly", True),
        ("See https://example.com/?name=O&quot;Reilly.",
         "참조 https://example.com/?name=O&quot;Reilly.",
         "https://example.com/?name=O&quot;Reilly", False),
        ("See https://example.com/?name=O&lt;Reilly.",
         "참조 https://example.com/?name=O&lt;Reilly.",
         "https://example.com/?name=O&lt;Reilly", False),
        ("See https://example.com/?name=O&gt;Reilly.",
         "참조 https://example.com/?name=O&gt;Reilly.",
         "https://example.com/?name=O&gt;Reilly", False),
        ("See https://example.com/docs' after.",
         "참조 https://example.com/docs' 이후.",
         "https://example.com/docs", False),
        ('See https://example.com/docs" after.',
         '참조 https://example.com/docs" 이후.',
         "https://example.com/docs", False),
    ],
    ids=["body-apostrophe", "title-apostrophe", "body-double-quote",
         "body-less-than", "body-greater-than", "literal-apostrophe-boundary",
         "literal-double-quote-boundary"],
)
def test_producer_entity_delimiter_url_preserves_exact_value(
    tmp_path: Path, source_fragment: str, output_fragment: str,
    expected_url: str, in_title: bool,
) -> None:
    # HTML entities can decode to URL characters that delimit raw producer input.
    producer_input = (
        f"<!--wt-location:attribute:title-->{source_fragment}"
        if in_title else source_fragment
    )
    protected_text, raw_tokens = protect_fragment(producer_input)
    assert [(token.kind, token.value) for token in raw_tokens if token.kind == "url"] == [
        ("url", expected_url)
    ]
    tokens = [
        ProtectedToken(token.token, "location" if token.kind == "tag" else token.kind,
                       token.value)
        for token in raw_tokens
    ]
    if in_title:
        source_body = f'<main><span data-wt-segment="a" title="{source_fragment}">Hello</span></main>'
        output_body = f'<main><span title="{output_fragment}">안녕</span></main>'
    else:
        source_body = f'<main><p data-wt-segment="a">{source_fragment}</p></main>'
        output_body = f'<main><p>{output_fragment}</p></main>'
    source, output = _write_pages(
        tmp_path, source_body=source_body, output_body=output_body,
    )
    result = run_qa(_inputs(
        source, output, protected_tokens={"a": tokens},
        translated_texts={"a": protected_text},
    ))
    assert result.required_findings == []
    assert result.warnings == []


@pytest.mark.parametrize(
    ("source_fragment", "output_fragment", "in_title"),
    [
        ("See https://example.com/?name=O&apos;Reilly.",
         "참조 https://example.com/?name=O&apos;Reilly/evil.", False),
        ("See https://example.com/?name=O&apos;Reilly.",
         "참조 https://example.com/?name=O&apos;Reilly&amp;q=2.", False),
        ("See https://example.com/?name=O&apos;Reilly.",
         "참조 https://example.com/?name=O&apos;Reilly. "
         "또 https://example.com/?name=O&apos;Reilly.", False),
        ("See https://example.com/?name=O&apos;Reilly.",
         "참조 https://example.com/?name=O&apos;Reilly/evil.", True),
    ],
    ids=["apostrophe-path", "apostrophe-query", "apostrophe-duplicate",
         "title-apostrophe-path"],
)
def test_producer_entity_delimiter_url_rejects_extensions_and_duplicates(
    tmp_path: Path, source_fragment: str, output_fragment: str, in_title: bool,
) -> None:
    producer_input = (
        f"<!--wt-location:attribute:title-->{source_fragment}"
        if in_title else source_fragment
    )
    protected_text, raw_tokens = protect_fragment(producer_input)
    assert [(token.kind, token.value) for token in raw_tokens if token.kind == "url"] == [
        ("url", "https://example.com/?name=O&apos;Reilly")
    ]
    tokens = [
        ProtectedToken(token.token, "location" if token.kind == "tag" else token.kind,
                       token.value)
        for token in raw_tokens
    ]
    if in_title:
        source_body = f'<main><span data-wt-segment="a" title="{source_fragment}">Hello</span></main>'
        output_body = f'<main><span title="{output_fragment}">안녕</span></main>'
    else:
        source_body = f'<main><p data-wt-segment="a">{source_fragment}</p></main>'
        output_body = f'<main><p>{output_fragment}</p></main>'
    source, output = _write_pages(
        tmp_path, source_body=source_body, output_body=output_body,
    )
    result = run_qa(_inputs(
        source, output, protected_tokens={"a": tokens},
        translated_texts={"a": protected_text},
    ))
    assert "protected-token-integrity" in {
        finding.code for finding in result.required_findings
    }


@pytest.mark.parametrize(
    ("output_fragment", "accepted"),
    [
        ("참조 https://example.com/?name=O&apos;Reilly 및 "
         "https://example.com/?name=O&apos;Reilly/next.", True),
        ("참조 https://example.com/?name=O&apos;Reilly/next 및 "
         "https://example.com/?name=O&apos;Reilly/next.", False),
    ],
    ids=["overlap-unchanged", "overlap-short-value-lost"],
)
def test_producer_entity_delimiter_url_keeps_overlapping_values(
    tmp_path: Path, output_fragment: str, accepted: bool,
) -> None:
    source_fragment = (
        "See https://example.com/?name=O&apos;Reilly and "
        "https://example.com/?name=O&apos;Reilly/next."
    )
    protected_text, tokens = protect_fragment(source_fragment)
    assert [(token.kind, token.value) for token in tokens] == [
        ("url", "https://example.com/?name=O&apos;Reilly"),
        ("url", "https://example.com/?name=O&apos;Reilly/next"),
    ]
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f'<main><p>{output_fragment}</p></main>',
    )
    result = run_qa(_inputs(
        source, output, protected_tokens={"a": tokens},
        translated_texts={"a": protected_text},
    ))
    if accepted:
        assert result.required_findings == []
        assert result.warnings == []
    else:
        assert "protected-token-integrity" in {
            finding.code for finding in result.required_findings
        }


@pytest.mark.parametrize("source_fragment,output_fragment,accepted", [
    ("MUST<em> retry</em>.", "MUST<em> retry</em>.", True),
    ("MUST<em> retry</em>.", "SHOULD<em> retry</em>.", False),
    ("MUST<em> retry</em>.", "MUSTARD<em> retry</em>.", False),
    ("https://example.com/spec<strong> documentation</strong>.",
     "https://example.com/spec<strong> documentation</strong>.", True),
    ("https://example.com/spec<strong> documentation</strong>.",
     "https://example.com/spec/evil<strong> documentation</strong>.", False),
], ids=["keyword-unchanged", "keyword-changed", "keyword-suffix", "url-unchanged", "url-suffix"])
def test_producer_inline_tag_boundary_preserves_protected_value_and_suffix_guard(
    tmp_path: Path, source_fragment: str, output_fragment: str, accepted: bool,
) -> None:
    protected_text, tokens = protect_fragment(source_fragment)
    assert tokens[0].kind in {"keyword", "url"}
    assert [token.kind for token in tokens[1:]] == ["tag", "tag"]
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">{source_fragment}</p></main>',
        output_body=f"<main><p>{output_fragment}</p></main>",
    )
    result = run_qa(_inputs(source, output, protected_tokens={"a": tokens},
                            translated_texts={"a": protected_text}))
    if accepted:
        assert result.required_findings == []
        assert result.warnings == []
    else:
        assert "protected-token-integrity" in {finding.code for finding in result.required_findings}


@pytest.mark.parametrize(
    ("source_body", "output_body", "tokens", "translation", "expected"),
    [
        ('<main><p data-wt-segment="a"><a href="https://example.com/spec">Read https://example.com/spec.</a></p></main>',
         '<main><p><a href="https://example.com/spec">https://example.com/other 문서.</a></p></main>',
         [("url", "https://example.com/spec")], "⟦WT:000000⟧ 문서.", "protected-token-integrity"),
        ('<main><p data-wt-segment="a"><a href="https://example.com/spec">Read https://example.com/spec.</a></p></main>',
         '<main><p><a href="https://example.com/other">https://example.com/spec 문서.</a></p></main>',
         [("url", "https://example.com/spec")], "⟦WT:000000⟧ 문서.", "structural-signature"),
        ('<main><input data-wt-segment="a" title="OAuth token" aria-label="OAuth token"></main>',
         '<main><input title="OIDC 토큰" aria-label="OAuth OAuth 토큰"></main>',
         [("location", "<!--wt-location:attribute:title-->"), ("identifier", "OAuth"),
          ("location", "<!--wt-location:attribute:aria-label-->"), ("identifier", "OAuth")],
         "⟦WT:000000⟧⟦WT:000001⟧ 토큰⟦WT:000002⟧⟦WT:000003⟧ 토큰", "protected-token-integrity"),
        ('<main><p data-wt-segment="a"><a href="https://example.com/spec">Read https://example.com/spec.</a></p></main>',
         '<main><p><a href="https://example.com/spec">https://example.com/spec 문서. https://example.com/spec</a></p></main>',
         [("url", "https://example.com/spec")], "⟦WT:000000⟧ 문서.", "protected-token-integrity"),
        ('<main><p data-wt-segment="a"><a href="https://example.com/spec">Read https://example.com/spec.</a></p></main>',
         '<main><p><a href="https://example.com/spec">https://example.com/spec?x=1 문서.</a></p></main>',
         [("url", "https://example.com/spec")], "⟦WT:000000⟧ 문서.", "protected-token-integrity"),
        ('<main><p data-wt-segment="a">Read <code>OAuth</code> and OAuth.</p></main>',
         '<main><p>OAuth 문서 <code>OIDC</code>.</p></main>',
         [("code", "<code>OAuth</code>"), ("identifier", "OAuth")],
         "⟦WT:000000⟧ and ⟦WT:000001⟧.", "protected-token-integrity"),
        ('<main><p data-wt-segment="a">Read <svg><text>OAuth</text></svg> and OAuth.</p></main>',
         '<main><p>OAuth 문서 <svg><text>OIDC</text></svg>.</p></main>',
         [("excluded", "<svg><text>OAuth</text></svg>"), ("identifier", "OAuth")],
         "⟦WT:000000⟧ and ⟦WT:000001⟧.", "protected-token-integrity"),
        ('<main><div data-wt-segment="a">OAuth <span data-wt-segment="b">Child</span></div></main>',
         '<main><div>OIDC <span>자식</span></div></main>',
         [("identifier", "OAuth"), ("segment", '<span data-wt-segment="b">Child</span>')],
         "⟦WT:000000⟧ ⟦WT:000001⟧", "protected-token-integrity"),
    ],
    ids=["body-url", "href", "translated-attribute", "extra-url", "query-suffix", "opaque-code", "opaque-svg", "nested-owner"],
)
def test_protected_locations_reject_independent_tampering(
    tmp_path: Path, source_body: str, output_body: str,
    tokens: list[tuple[str, str]], translation: str, expected: str,
) -> None:
    source, output = _write_pages(tmp_path, source_body=source_body, output_body=output_body)
    protected = [ProtectedToken(f"⟦WT:{index:06d}⟧", kind, value)
                 for index, (kind, value) in enumerate(tokens)]
    result = run_qa(_inputs(source, output, protected_tokens={"a": protected},
                            translated_texts={"a": translation},
                            source_segment_ids={"a", "b"} if 'data-wt-segment="b"' in source_body else {"a"},
                            translated_segment_ids={"a", "b"} if 'data-wt-segment="b"' in source_body else {"a"}))
    assert expected in {finding.code for finding in result.required_findings}


@pytest.mark.parametrize("kind,markup", [
    ("code", "<code>OAuth</code>"),
    ("excluded", "<svg><text>OAuth</text></svg>"),
], ids=["code", "svg"])
@pytest.mark.parametrize("tampered", [False, True], ids=["unchanged", "changed-second"])
def test_repeated_identical_opaque_tokens_keep_exact_multiplicity(
    tmp_path: Path, kind: str, markup: str, tampered: bool,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">Read {markup} and {markup}.</p></main>',
        output_body=(f'<main><p>{markup} 및 '
                     f'{markup.replace("OAuth", "OIDC") if tampered else markup} 문서.</p></main>'),
    )
    result = run_qa(_inputs(
        source, output,
        protected_tokens={"a": [ProtectedToken(TOKEN, kind, markup),
                                ProtectedToken("⟦WT:000001⟧", kind, markup)]},
        translated_texts={"a": f"{TOKEN} 및 ⟦WT:000001⟧ 문서."},
    ))
    codes = {finding.code for finding in result.required_findings}
    if tampered:
        assert "protected-token-integrity" in codes
    else:
        assert result.required_findings == []
        assert result.warnings == []


@pytest.mark.parametrize("phrase", ["MUST NOT", "SHALL NOT", "SHOULD NOT", "NOT RECOMMENDED"])
def test_compound_normative_tokens_do_not_overlap(tmp_path: Path, phrase: str) -> None:
    first = phrase.split()[0]
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">{first} and {phrase} and OAuth.</p></main>',
        output_body=f'<main><p>{first} 및 {phrase} 및 OAuth.</p></main>',
    )
    result = run_qa(_inputs(
        source, output,
        protected_tokens={"a": [ProtectedToken(TOKEN, "keyword", first),
                                ProtectedToken("⟦WT:000001⟧", "keyword", phrase),
                                ProtectedToken("⟦WT:000002⟧", "identifier", "OAuth")]},
        translated_texts={"a": "⟦WT:000000⟧ 및 ⟦WT:000001⟧ 및 ⟦WT:000002⟧."},
    ))
    assert result.required_findings == []
    assert result.warnings == []


@pytest.mark.parametrize(
    "output_phrase",
    ["MUST and MUST and OAuth.", "MUST NOT and MUST NOT and OAuth.",
     "MUST NOT and OAuth.", "MUST NOT and MUST NOT and MUST and OAuth.",
     "MUSTARD and MUST NOT and OAuth."],
    ids=["lost-negation", "lost-standalone", "missing-standalone", "duplicate-compound", "larger-word"],
)
def test_compound_normative_tokens_reject_loss_negation_and_duplicates(
    tmp_path: Path, output_phrase: str,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a">MUST and MUST NOT and OAuth.</p></main>',
        output_body=f"<main><p>{output_phrase}</p></main>",
    )
    result = run_qa(_inputs(
        source, output,
        protected_tokens={"a": [ProtectedToken(TOKEN, "keyword", "MUST"),
                                ProtectedToken("⟦WT:000001⟧", "keyword", "MUST NOT"),
                                ProtectedToken("⟦WT:000002⟧", "identifier", "OAuth")]},
        translated_texts={"a": "⟦WT:000000⟧ and ⟦WT:000001⟧ and ⟦WT:000002⟧."},
    ))
    assert "protected-token-integrity" in {finding.code for finding in result.required_findings}


@pytest.mark.parametrize(
    ("output_head", "accepted"),
    [
        ('<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" content="script-src \'none\'"><meta charset="utf-8"><link rel="canonical" href="https://example.com/doc" title="OAuth 안내"><title>OAuth 안내</title>', True),
        ('<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" content="script-src \'none\'"><meta charset="utf-8"><title>OAuth 안내</title>', False),
        ('<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" content="script-src \'none\'"><meta charset="utf-8"><link rel="canonical" href="https://example.com/doc" title="OAuth 안내"><link rel="canonical" href="https://example.com/doc" title="OAuth 안내"><title>OAuth 안내</title>', False),
        ('<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" content="script-src \'none\'"><meta charset="utf-8"><title>OAuth 안내</title><link rel="canonical" href="https://example.com/doc" title="OAuth 안내">', False),
        ('<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" content="script-src \'none\'"><meta charset="utf-8"><link rel="canonical" href="https://example.com/doc" title="OAuth 안내" aria-label="surprise"><title>OAuth 안내</title>', False),
    ], ids=["normalized", "missing-link", "duplicate-link", "reordered", "added-translatable-attribute"],
)
def test_head_targets_survive_known_metadata_normalization(
    tmp_path: Path, output_head: str, accepted: bool,
) -> None:
    source, output = _write_pages(
        tmp_path, source_body="<main>Body</main>", output_body="<main>본문</main>",
        head='<meta charset="iso-8859-1"><meta http-equiv="content-type" content="text/html; charset=iso-8859-1"><meta charset="utf-8"><link data-wt-segment="a" rel="canonical" href="https://example.com/doc" title="OAuth guide"><title data-wt-segment="b">OAuth guide</title>',
        output_head=output_head,
    )
    result = run_qa(_inputs(
        source, output, source_segment_ids={"a", "b"}, translated_segment_ids={"a", "b"},
        protected_tokens={"a": [ProtectedToken(TOKEN, "location", "<!--wt-location:attribute:title-->"),
                                ProtectedToken("⟦WT:000001⟧", "identifier", "OAuth")],
                          "b": [ProtectedToken("⟦WT:000002⟧", "identifier", "OAuth")]},
        translated_texts={"a": "⟦WT:000000⟧⟦WT:000001⟧ 안내", "b": "⟦WT:000002⟧ 안내"},
    ))
    codes = {finding.code for finding in result.required_findings}
    assert (codes == set()) if accepted else ("protected-token-integrity" in codes)
    if accepted:
        assert result.warnings == []


def test_qa_detects_structural_change_and_unresolved_internal_anchor(tmp_path: Path) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main id="doc"><p class="lead" data-wt-segment="a">Hello</p>'
            '<a href="#target">Jump</a><section id="target"></section></main>'
        ),
        output_body=(
            '<main id="doc"><p class="changed">안녕</p>'
            '<a href="#missing">이동</a><section id="target"></section></main>'
        ),
    )
    result = run_qa(_inputs(source, output))

    assert {finding.code for finding in result.required_findings} == {
        "structural-signature",
        "internal-anchor-unresolved",
    }
    anchor = next(
        finding for finding in result.required_findings
        if finding.code == "internal-anchor-unresolved"
    )
    assert anchor.evidence == {"fragments": ["missing"]}


def test_nested_attribution_marker_cannot_hide_a_structural_change(tmp_path: Path) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body='<main><p data-wt-segment="a">Hello</p></main>',
        output_body=(
            '<main><p>안녕</p><aside data-wt-attribution="source">'
            "unauthorized nested content</aside></main>"
        ),
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "structural-signature"
    ]


def test_structural_signature_allows_only_marked_translatable_attribute_values(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><input data-wt-segment="a" alt="Configure OAuth" '
            'aria-label="Configuration" aria-description="Security diagram" '
            'title="Token exchange" placeholder="Enter token" data-state="ready"></main>'
        ),
        output_body=(
            '<main><input alt="OAuth 설정" aria-label="설정" '
            'aria-description="보안 다이어그램" title="토큰 교환" '
            'placeholder="토큰 입력" data-state="ready"></main>'
        ),
    )

    result = run_qa(_inputs(source, output))

    assert result.passed is True
    assert result.required_findings == []


@pytest.mark.parametrize(
    "output_attribute",
    [
        'aria-label="설정"',
        'data-alt="OAuth 설정" aria-label="설정"',
    ],
)
def test_structural_signature_still_requires_translatable_attribute_presence_and_name(
    tmp_path: Path, output_attribute: str
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><input data-wt-segment="a" alt="Configure OAuth" '
            'aria-label="Configuration"></main>'
        ),
        output_body=f"<main><input {output_attribute}></main>",
    )

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "structural-signature"
    ]


def test_structural_signature_rejects_nontranslatable_attribute_value_changes(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><input data-wt-segment="a" alt="Configure OAuth" '
            'data-state="ready"></main>'
        ),
        output_body='<main><input alt="OAuth 설정" data-state="changed"></main>',
    )

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "structural-signature"
    ]


def test_same_document_path_anchor_is_resolved_and_malformed_href_does_not_crash(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">Hello</p>'
            '<a href="index.html#missing">Missing</a>'
            '<a href="http://[malformed">Malformed external link</a></main>'
        ),
        output_body=(
            '<main><p>안녕</p><a href="index.html#missing">누락</a>'
            '<a href="http://[malformed">잘못된 외부 링크</a></main>'
        ),
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "internal-anchor-unresolved"
    ]
    assert result.required_findings[0].evidence == {"fragments": ["missing"]}


def test_qa_classifies_external_critical_and_optional_dependencies(tmp_path: Path) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">Hello</p>'
            '<link rel="stylesheet" href="https://cdn.example/theme.css">'
            '<img src="https://cdn.example/optional.png"></main>'
        ),
        output_body=(
            '<main><p>안녕</p>'
            '<link rel="stylesheet" href="https://cdn.example/theme.css">'
            '<img src="https://cdn.example/optional.png"></main>'
        ),
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert [finding.code for finding in result.warnings] == [
        "external-optional-dependency"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["https://cdn.example/theme.css"]
    }
    assert result.warnings[0].evidence == {
        "urls": ["https://cdn.example/optional.png"]
    }


def test_qa_statically_detects_external_import_hidden_by_offline_csp(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        head=(
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'style-src \'self\'">'
            '<style>@import url("https://cdn.example/theme.css");</style>'
        ),
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["https://cdn.example/theme.css"]
    }
    assert result.screenshots == []


def test_external_source_script_is_not_an_offline_dependency_when_csp_blocks_scripts(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        head='<script src="https://cdn.example/app.js"></script>',
        output_head=(
            '<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; script-src \'none\'">'
            '<script src="https://cdn.example/app.js"></script>'
        ),
    )

    result = run_qa(_inputs(source, output))

    assert result.passed is True
    assert result.required_findings == []


def test_external_script_remains_required_without_the_offline_csp(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        head='<script src="https://cdn.example/app.js"></script>',
    )

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["https://cdn.example/app.js"]
    }


@pytest.mark.parametrize("link", [
    '<link rel="modulepreload" href="https://cdn.example/app.js">',
    '<link rel="MoDuLePrElOaD" href="//cdn.example/app.js">',
    '<link rel="preload" as="script" href="https://cdn.example/app.js">',
    '<link rel="PRELOAD" as="ScRiPt" href="//cdn.example/app.js">',
])
def test_script_preloads_require_effective_prior_blocking_csp(
    tmp_path: Path, link: str,
) -> None:
    csp = ('<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" '
           'content="default-src \'none\'; script-src \'none\'">')
    source, output = _write_pages(tmp_path, head=link, output_head=csp + link)
    result = run_qa(_inputs(source, output))
    assert result.required_findings == []
    assert result.warnings == []
    assert {path.name for path in result.screenshots} == {
        "desktop-1440x900.png", "narrow-390x844.png"
    }


def test_nonascii_csp_whitespace_cannot_exempt_an_attempted_script_preload(
    tmp_path: Path,
) -> None:
    url = "https://cdn.example/app.js"
    link = f'<link rel="modulepreload" href="{url}">'
    malformed_policy = "script-src\u00a0'none'"
    source, output = _write_pages(
        tmp_path, head=link,
        output_head=(f'<meta http-equiv="Content-Security-Policy" '
                     f'content="{malformed_policy}">{link}'),
    )
    required: list[Finding] = []
    warnings: list[Finding] = []
    _check_external_dependencies(
        _inputs(source, output), BeautifulSoup(output.read_text("utf-8"), "lxml"),
        required, warnings,
    )
    assert [finding.code for finding in required] == ["external-critical-dependency"]
    assert required[0].evidence == {"urls": [url]}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for policy, expected_requests in (
                ("script-src 'none'", []),
                (malformed_policy, [url]),
            ):
                attempted: list[str] = []
                context = browser.new_context(service_workers="block")

                def intercept(route: object) -> None:
                    attempted.append(route.request.url)  # type: ignore[attr-defined]
                    route.fulfill(status=200, content_type="text/javascript", body="export default 0")  # type: ignore[attr-defined]

                context.route("**/*", intercept)
                page = context.new_page()
                try:
                    page.set_content(
                        f'<html><head><meta http-equiv="Content-Security-Policy" '
                        f'content="{policy}">{link}</head><body></body></html>',
                        wait_until="networkidle",
                    )
                finally:
                    context.close()
                assert attempted == expected_requests
        finally:
            browser.close()


@pytest.mark.parametrize("policy_before,policy_after,body_policy", [
    ("", "", ""),
    ('<meta data-wt-csp="offline">', "", ""),
    ('<meta http-equiv="Content-Security-Policy-Report-Only" content="script-src \'none\'">', "", ""),
    ("", '<meta http-equiv="Content-Security-Policy" content="script-src \'none\'">', ""),
    ("", "", '<meta http-equiv="Content-Security-Policy" content="script-src \'none\'">'),
    ('<meta http-equiv="Content-Security-Policy" content="script-src \'none">', "", ""),
    ('<meta http-equiv="Content-Security-Policy" content="script-src https:; script-src \'none\'">', "", ""),
    ('<meta http-equiv="Content-Security-Policy" content="script-src \'none\'; script-src-elem https:">', "", ""),
], ids=["absent", "marker-only", "report-only", "late-head", "body", "malformed", "permissive-first", "element-override"])
def test_script_preloads_require_effective_prior_blocking_csp_negative(
    tmp_path: Path, policy_before: str, policy_after: str, body_policy: str,
) -> None:
    link = '<link rel="modulepreload" href="https://cdn.example/app.js">'
    source, output = _write_pages(
        tmp_path, head=link, output_head=policy_before + link + policy_after,
        output_body=f"<main><p>안녕하세요</p>{body_policy}</main>",
    )
    result = run_qa(_inputs(source, output))
    assert "external-critical-dependency" in {finding.code for finding in result.required_findings}


@pytest.mark.parametrize("extra,expected,warning", [
    ('<link rel="stylesheet modulepreload" href="https://cdn.example/theme.css">',
     "external-critical-dependency", False),
    ('<link rel="preload" as="style" href="https://cdn.example/theme.css">',
     "external-critical-dependency", False),
    ('<style>@import url("https://cdn.example/theme.css");</style>',
     "external-critical-dependency", False),
    ('<base href="https://cdn.example/"><link rel="stylesheet" href="theme.css">',
     "external-critical-dependency", False),
    ('<link rel="stylesheet" href="http://[bad">',
     "invalid-critical-dependency-url", False),
    ('<link rel="stylesheet" href="blob:https://cdn.example/theme">',
     "unsupported-critical-dependency-scheme", False),
    ('<link rel="icon" href="https://cdn.example/icon.png">',
     "external-optional-dependency", True),
    ('<link rel="preload" as="font" href="https://cdn.example/font.woff2">',
     "external-optional-dependency", True),
], ids=["mixed-stylesheet", "preload-style", "css-import", "external-base", "malformed", "unsupported", "icon", "font"])
def test_script_preload_exemption_never_hides_css_or_other_dependencies(
    tmp_path: Path, extra: str, expected: str, warning: bool,
) -> None:
    csp = ('<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" '
           'content="default-src \'none\'; script-src \'none\'">')
    preload = '<link rel="modulepreload" href="https://cdn.example/app.js">'
    source, output = _write_pages(
        tmp_path, head=preload + extra, output_head=csp + preload + extra,
    )
    result = run_qa(_inputs(source, output))
    codes = {finding.code for finding in result.warnings if warning}
    codes.update(finding.code for finding in result.required_findings)
    assert expected in codes
    assert not any("app.js" in str(finding.evidence) for finding in result.required_findings)


def test_protocol_relative_stylesheet_is_external_but_metadata_link_is_not(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">Hello</p></main>'
            '<link rel="canonical" href="https://example.com/docs">'
            '<link rel="stylesheet" href="//cdn.example/theme.css">'
        ),
        output_body=(
            '<main><p>안녕</p></main>'
            '<link rel="canonical" href="https://example.com/docs">'
            '<link rel="stylesheet" href="//cdn.example/theme.css">'
        ),
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["//cdn.example/theme.css"]
    }


def test_external_icon_and_font_preload_are_optional_not_required(tmp_path: Path) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">Hello</p></main>'
            '<link rel="icon" href="https://cdn.example/icon.png">'
            '<link rel="preload" as="font" href="https://cdn.example/font.woff2">'
        ),
        output_body=(
            '<main><p>안녕</p></main>'
            '<link rel="icon" href="https://cdn.example/icon.png">'
            '<link rel="preload" as="font" href="https://cdn.example/font.woff2">'
        ),
    )
    result = run_qa(_inputs(source, output))

    assert result.required_findings == []
    assert [finding.code for finding in result.warnings] == [
        "external-optional-dependency"
    ]
    assert result.warnings[0].evidence == {
        "urls": [
            "https://cdn.example/font.woff2",
            "https://cdn.example/icon.png",
        ]
    }


def test_external_base_makes_relative_stylesheet_a_critical_dependency(
    tmp_path: Path,
) -> None:
    head = (
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
        '<base href="https://cdn.example/theme/">'
        '<link rel="stylesheet" href="main.css">'
    )
    source, output = _write_pages(tmp_path, head=head)
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["https://cdn.example/theme/main.css"]
    }
    assert result.screenshots == []


def test_malformed_critical_dependency_url_is_a_stable_required_finding(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        head='<link rel="stylesheet" href="http://[malformed">',
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "invalid-critical-dependency-url"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["http://[malformed"]
    }


@pytest.mark.parametrize(
    "reference",
    [
        "data:text/css,body%7Bcolor%3Ared%7D",
        "blob:https://example.com/theme",
        "#theme",
        "file:///C:/theme.css",
        "javascript:alert(1)",
    ],
)
def test_qa_fails_closed_for_every_unsupported_critical_stylesheet_scheme(
    tmp_path: Path, reference: str
) -> None:
    source, output = _write_pages(
        tmp_path,
        head=f'<link rel="stylesheet" href="{reference}">',
    )

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "unsupported-critical-dependency-scheme"
    ]
    assert result.required_findings[0].evidence == {"urls": [reference]}
    assert result.screenshots == []


@pytest.mark.parametrize(
    "reference",
    ["data:text/css,p%7Bcolor%3Ared%7D", "blob:https://example.com/import", "#theme"],
)
def test_qa_fails_closed_for_unsupported_critical_css_import_scheme(
    tmp_path: Path, reference: str
) -> None:
    source, output = _write_pages(
        tmp_path,
        head=f'<style>@import url("{reference}");</style>',
    )

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "unsupported-critical-dependency-scheme"
    ]
    assert result.required_findings[0].evidence == {"urls": [reference]}
    assert result.screenshots == []


def test_qa_rejects_asset_path_escape_and_records_optional_missing_asset(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(tmp_path)
    result = run_qa(
        _inputs(
            source,
            output,
            critical_assets=[Path("../outside.css")],
            optional_assets=[Path("assets/font.woff2")],
        )
    )

    assert [finding.code for finding in result.required_findings] == [
        "critical-asset-unsafe"
    ]
    assert [finding.code for finding in result.warnings] == [
        "optional-asset-missing"
    ]


def test_qa_reports_optional_asset_escape_separately(tmp_path: Path) -> None:
    source, output = _write_pages(tmp_path)
    result = run_qa(
        _inputs(source, output, optional_assets=[Path("../outside-font.woff2")])
    )

    assert [finding.code for finding in result.warnings] == [
        "optional-asset-unsafe"
    ]


def test_master_unresolved_required_item_is_a_required_gate(tmp_path: Path) -> None:
    source, output = _write_pages(tmp_path)
    result = run_qa(
        _inputs(
            source,
            output,
            master_review=MasterReview(
                unresolved_required=["zone-002: qualification omitted"],
                retries={"zone-002": 2},
                section_findings={"zone-002": ["qualification omitted"]},
            ),
        )
    )

    assert result.passed is False
    assert [finding.code for finding in result.required_findings] == [
        "master-review-unresolved"
    ]
    assert result.screenshots == []


def test_browser_qa_uses_two_viewports_and_writes_screenshots_under_work_dir(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><h1 data-wt-segment="a">Hello</h1>'
            '<p data-wt-segment="b">World</p></main>'
        ),
        output_body="<main><h1>안녕</h1><p>세상</p></main>",
        head="<style>body{max-width:60rem;margin:auto} img{max-width:100%}</style>",
    )
    result = run_qa(
        _inputs(
            source,
            output,
            source_segment_ids={"a", "b"},
            translated_segment_ids={"a", "b"},
        )
    )

    assert result.passed is True
    assert result.required_findings == []
    assert [path.name for path in result.screenshots] == [
        "desktop-1440x900.png",
        "narrow-390x844.png",
    ]
    assert all(path.is_file() and path.parent == source.parent / "QA 스크린샷" for path in result.screenshots)
    assert result.browser_metrics == {
        "desktop-1440x900": {
            "brokenImages": [],
            "clippedText": 0,
            "horizontalOverflow": False,
        },
        "narrow-390x844": {
            "brokenImages": [],
            "clippedText": 0,
            "horizontalOverflow": False,
        },
    }


def test_browser_qa_requires_each_critical_stylesheet_to_load_and_be_accessible(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        head=(
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'style-src \'none\'">'
            '<link rel="stylesheet" href="assets/theme.css">'
        ),
    )
    asset = output.parent / "assets" / "theme.css"
    asset.parent.mkdir()
    asset.write_bytes(b"body { color: red }")

    result = run_qa(
        _inputs(source, output, critical_assets=[Path("assets/theme.css")])
    )

    assert result.passed is False
    assert [finding.code for finding in result.required_findings] == [
        "critical-stylesheet-unavailable"
    ]
    assert set(result.required_findings[0].evidence["viewports"]) == {
        "desktop-1440x900",
        "narrow-390x844",
    }


def test_browser_qa_requires_local_stylesheet_imports_to_load(
    tmp_path: Path,
) -> None:
    source, output = _write_pages(
        tmp_path,
        head='<style>@import url("assets/missing.css");</style>',
    )

    result = run_qa(_inputs(source, output))

    assert result.passed is False
    assert [finding.code for finding in result.required_findings] == [
        "critical-stylesheet-unavailable"
    ]


def test_browser_setup_failure_is_recorded_instead_of_escaping(tmp_path: Path) -> None:
    source, output = _write_pages(tmp_path)
    screenshot_path = source.parent / "not-a-directory"
    screenshot_path.write_text("occupied", encoding="utf-8")

    result = run_qa(_inputs(source, output, screenshot_dir=screenshot_path))

    assert result.passed is False
    assert [finding.code for finding in result.required_findings] == [
        "browser-qa-failed"
    ]


def test_browser_blocks_localhost_different_port_and_websocket(tmp_path: Path) -> None:
    script = (
        '<script>fetch("http://localhost:9/private").catch(() => {});'
        'new WebSocket("ws://localhost:9/socket");</script>'
    )
    source, output = _write_pages(
        tmp_path,
        source_body=f'<main><p data-wt-segment="a">Hello</p>{script}</main>',
        output_body=f"<main><p>안녕</p>{script}</main>",
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert result.required_findings[0].evidence == {
        "urls": [
            "http://localhost:9/private",
            "ws://localhost:9/socket",
        ]
    }


def test_browser_context_blocks_popup_navigation_to_other_loopback_server(
    tmp_path: Path,
) -> None:
    hits: list[str] = []

    class VictimHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"escaped")

        def log_message(self, format: str, *args: object) -> None:
            return

    victim = ThreadingHTTPServer(("127.0.0.1", 0), VictimHandler)
    thread = threading.Thread(target=victim.serve_forever, daemon=True)
    thread.start()
    escape_url = f"http://127.0.0.1:{victim.server_port}/escape"
    script = f'<script>window.open("{escape_url}", "_blank")</script>'
    try:
        source, output = _write_pages(
            tmp_path,
            source_body=f'<main><p data-wt-segment="a">Hello</p>{script}</main>',
            output_body=f"<main><p>안녕</p>{script}</main>",
        )
        result = run_qa(_inputs(source, output))
    finally:
        victim.shutdown()
        victim.server_close()
        thread.join(timeout=5)

    assert hits == []
    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert result.required_findings[0].evidence == {"urls": [escape_url]}
    assert set(result.browser_metrics) == {"desktop-1440x900", "narrow-390x844"}


def test_same_url_requested_as_image_and_fetch_is_always_required(tmp_path: Path) -> None:
    url = "https://cdn.example/shared"
    script = f'<script>fetch("{url}").catch(() => {{}})</script>'
    source, output = _write_pages(
        tmp_path,
        source_body=(
            f'<main><p data-wt-segment="a">Hello</p>{script}'
            f'<img src="{url}"></main>'
        ),
        output_body=f'<main><p>안녕</p>{script}<img src="{url}"></main>',
    )
    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]


def test_loopback_server_does_not_follow_nested_asset_symlink(tmp_path: Path) -> None:
    source, output = _write_pages(
        tmp_path,
        source_body=(
            '<main><p data-wt-segment="a">Hello</p>'
            '<img src="assets/escape/secret.svg"></main>'
        ),
        output_body=(
            '<main><p>안녕</p><img src="assets/escape/secret.svg"></main>'
        ),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>',
        encoding="utf-8",
    )
    assets = output.parent / "assets"
    assets.mkdir()
    try:
        (assets / "escape").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        import pytest

        pytest.skip(f"directory symlinks unavailable on this Windows host: {error}")

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.warnings] == ["viewport-broken-images"]


def test_report_records_warnings_retries_source_and_deterministic_json(
    tmp_path: Path,
) -> None:
    result = QAResult(
        passed=True,
        required_findings=[],
        warnings=[
            Finding(
                code="optional-asset-missing",
                severity="warning",
                message="Optional asset is unavailable.",
                evidence={"paths": ["assets/font.woff2"]},
            )
        ],
        screenshots=[Path("QA screenshots/desktop-1440x900.png")],
        source_url="https://example.com/docs",
        browser_metrics={
            "desktop-1440x900": {
                "horizontalOverflow": False,
                "brokenImages": [],
                "clippedText": 0,
            }
        },
    )
    review = MasterReview(
        unresolved_required=[],
        retries={"zone-010": 0, "zone-002": 1},
        section_findings={"zone-002": ["resolved after retry"]},
    )
    manifest_a = tmp_path / "a" / "manifest.json"
    manifest_b = tmp_path / "b" / "manifest.json"
    report = tmp_path / "review-report.md"

    write_manifest(result, manifest_a)
    write_manifest(result, manifest_b)
    write_review_report(result, review, report)

    assert manifest_a.read_bytes() == manifest_b.read_bytes()
    payload = json.loads(manifest_a.read_text("utf-8"))
    assert payload["qa_status"] == "passed"
    assert payload["source_url"] == "https://example.com/docs"
    assert payload["warnings"][0]["code"] == "optional-asset-missing"
    text = report.read_text("utf-8")
    assert "https://example.com/docs" in text
    assert "zone-002" in text
    assert "1" in text
    assert "PASS" in text
    assert text.index("zone-002") < text.index("zone-010")


def test_markdown_report_escapes_active_markup_and_table_delimiters(tmp_path: Path) -> None:
    result = QAResult(
        False,
        [
            Finding(
                "unsafe",
                "required",
                "<script>alert(1)</script> | **bold**",
                {"payload": "`code` </code><img src=x onerror=alert(1)>"},
            )
        ],
        [],
        [],
        source_url="https://example.com/?x=<script>",
    )
    review = MasterReview([], {"zone|bad": 1}, {})
    path = tmp_path / "review.md"

    write_review_report(result, review, path)

    text = path.read_text("utf-8")
    assert "<script>" not in text
    assert "<img" not in text
    assert "zone\\|bad" in text
    assert "| **bold** `" in text


def test_report_rejects_destination_outside_qa_result_bundle(tmp_path: Path) -> None:
    # Reports may be written to caller-selected output directories; this test instead
    # guards the observable contract that parent directories are created safely.
    result = QAResult(False, [], [], [], source_url="https://example.com/")
    destination = tmp_path / "Windows 공간" / "결과" / "manifest.json"

    write_manifest(result, destination)

    assert destination.is_file()
    assert destination.read_bytes().endswith(b"\n")


def test_manifest_canonicalizes_finding_and_screenshot_order(tmp_path: Path) -> None:
    first = Finding("a", "warning", "A", {"value": 1})
    second = Finding("b", "warning", "B", {"value": 2})
    result_a = QAResult(
        True,
        [],
        [second, first],
        [Path("z.png"), Path("a.png")],
        source_url="https://example.com/",
    )
    result_b = QAResult(
        True,
        [],
        [first, second],
        [Path("a.png"), Path("z.png")],
        source_url="https://example.com/",
    )
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"

    write_manifest(result_a, path_a)
    write_manifest(result_b, path_b)

    assert path_a.read_bytes() == path_b.read_bytes()


def test_inline_css_dependencies_resolve_against_external_document_base(
    tmp_path: Path,
) -> None:
    head = (
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'">'
        '<base href="https://cdn.example/theme/">'
        '<style>@import "main.css"; .hero{background:url("image.png")}</style>'
    )
    source, output = _write_pages(
        tmp_path,
        head=head,
        source_body=(
            '<main><p data-wt-segment="a" style="background:url(avatar.png)">Hello</p></main>'
        ),
        output_body='<main><p style="background:url(avatar.png)">안녕</p></main>',
    )

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "external-critical-dependency"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["https://cdn.example/theme/main.css"]
    }
    assert [finding.code for finding in result.warnings] == [
        "external-optional-dependency"
    ]
    assert result.warnings[0].evidence == {
        "urls": [
            "https://cdn.example/theme/avatar.png",
            "https://cdn.example/theme/image.png",
        ]
    }
    assert result.screenshots == []


def test_malformed_css_dependencies_have_sorted_stable_findings(tmp_path: Path) -> None:
    head = (
        '<style>@import "http://[z-bad";'
        '@import url("http://[a-bad");'
        '.hero{background:url("http://[optional-z")}</style>'
    )
    source, output = _write_pages(
        tmp_path,
        head=head,
        source_body=(
            '<main><p data-wt-segment="a" '
            'style="background:url(\'http://[optional-a\')">Hello</p></main>'
        ),
        output_body=(
            '<main><p style="background:url(\'http://[optional-a\')">안녕</p></main>'
        ),
    )

    result = run_qa(_inputs(source, output))

    assert [finding.code for finding in result.required_findings] == [
        "invalid-critical-dependency-url"
    ]
    assert result.required_findings[0].evidence == {
        "urls": ["http://[a-bad", "http://[z-bad"]
    }
    assert [finding.code for finding in result.warnings] == [
        "invalid-optional-dependency-url"
    ]
    assert result.warnings[0].evidence == {
        "urls": ["http://[optional-a", "http://[optional-z"]
    }


def test_report_wraps_all_source_values_in_inert_gfm_code_spans(tmp_path: Path) -> None:
    attack = (
        "~~strike~~ # heading\r\n- list\r> quote "
        "<https://evil.example> [link](https://evil.example) "
        "![image](https://evil.example/x) `code`"
    )
    result = QAResult(
        False,
        [Finding("# code", "required", attack, {"payload": attack})],
        [],
        [],
        source_url=f"https://example.com/{attack}",
    )
    review = MasterReview([attack], {attack: 1}, {attack: [attack]})
    path = tmp_path / "review.md"

    write_review_report(result, review, path)

    text = path.read_text("utf-8")
    assert "\r" not in text
    assert "<https://evil.example>" not in text
    assert "![image]" in text
    assert "~~strike~~" in text
    # The one-backtick payload forces a two-backtick delimiter; all attack
    # syntax remains inside inert code spans instead of becoming GFM structure.
    assert "`` ~~strike~~ # heading - list &gt; quote" in text
    assert "``" in text


def test_optional_normalization_report_is_typed_and_legacy_is_omitted(tmp_path):
    from dataclasses import replace
    from supertranslator.preformatted_contract import NormalizationSummary
    summary = NormalizationSummary.from_dict({
        'schema_version': '1.0', 'policy': 'prose-reflow-literals-preserved',
        'source_sha256': '1' * 64, 'review_sha256': '2' * 64,
        'projection_sha256': '3' * 64, 'translated_blocks': 2,
        'preserved_blocks': 1, 'unknown_blocks': 0,
        'preserved_reasons': {'literal-table': 1},
        'generated_assets': [{'path': 'assets/wt-preformatted-' + '4' * 16 + '.css',
                              'sha256': '4' * 64}]})
    legacy = QAResult(True, [], [], [])
    normalized = replace(legacy, normalization=summary)
    review = MasterReview([], {}, {})
    for name, result in [('legacy', legacy), ('normalized', normalized)]:
        write_manifest(result, tmp_path / (name + '.json'))
        write_review_report(result, review, tmp_path / (name + '.md'))
    assert 'normalization' not in json.loads((tmp_path / 'legacy.json').read_bytes())
    assert 'Preformatted normalization' not in (tmp_path / 'legacy.md').read_text()
    assert json.loads((tmp_path / 'normalized.json').read_bytes())['normalization'] == summary.to_dict()
    report = (tmp_path / 'normalized.md').read_text()
    assert '## Preformatted normalization' in report
    assert 'literal-table' in report and '3' * 64 in report
