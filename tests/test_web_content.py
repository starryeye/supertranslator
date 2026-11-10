"""Approved payload expectations are independent of the final HTML under test."""
from dataclasses import replace

import pytest

from supertranslator.models import MasterReview, QAInputs, Segment, Translation
from supertranslator.qa import run_qa


def segment(identifier="a", semantic_type="paragraph", protected=None):
    return Segment(identifier, f"[data-wt-segment='{identifier}']", semantic_type,
                   [], "Accept the request.", protected or [], [], True)


def page(body):
    return f"<!doctype html><html><head></head><body>{body}</body></html>"


@pytest.mark.parametrize("text,accepted", [("요청을 수락합니다.", True), ("요청을 거부합니다.", False)])
def test_plain_text_inversion_fails_full_qa(tmp_path, text, accepted):
    # Removing the content gate must make the refusal case fail this test.
    source = tmp_path / "run/source.html"
    output = tmp_path / "output/index.html"
    source.parent.mkdir()
    output.parent.mkdir()
    source_text = page('<main><p data-wt-segment="a">Accept the request.</p></main>')
    source.write_text(source_text, encoding="utf-8", newline="")
    output.write_text(page(f"<main><p>{text}</p></main>"), encoding="utf-8", newline="")
    inputs = QAInputs(source, output, "https://example.com/", {"a"}, {"a"}, [], [],
                      source.parent / "screenshots", MasterReview([], {}, {}))
    from supertranslator.models import ApprovedWebContent
    inputs = replace(inputs, target_segments={"a": segment()},
                     approved_contents={"a": ApprovedWebContent({}, "요청을 수락합니다.")})
    result = run_qa(inputs)
    assert result.passed == accepted
    assert ("approved-content-integrity" in {f.code for f in result.required_findings}) == (not accepted)
    if accepted:
        assert len(result.screenshots) == 2  # real Chromium, not a mocked browser


@pytest.mark.parametrize("altered", [
    "", "거부", "수락수락", "수락 추가", '<span hidden>수락</span>거부',
])
def test_owned_content_rejects_omission_addition_and_duplication(altered):
    from supertranslator.models import ApprovedWebContent
    from supertranslator.web_content import check_approved_web_content
    source = page('<main>fixed<p data-wt-segment="a">Accept</p></main>')
    expected = {"a": ApprovedWebContent({}, "수락")}
    findings = check_approved_web_content(source, page(f"<main>fixed<p>{altered}</p></main>"),
                                          {"a": segment()}, expected)
    assert {f.code for f in findings} == {"approved-content-integrity"}


def test_unowned_prose_and_literal_whitespace_are_exact():
    from supertranslator.models import ApprovedWebContent
    from supertranslator.web_content import check_approved_web_content
    source = page('<main>fixed<p data-wt-segment="a">Accept</p><pre>x  y\r\nz</pre></main>')
    expected = {"a": ApprovedWebContent({}, "수락 &amp; <em id='keep'>yes  now</em>")}
    good = page('<main>fixed<p>수락 &amp; <em id="keep">yes  now</em></p><pre>x  y\r\nz</pre></main>')
    assert check_approved_web_content(source, good, {"a": segment()}, expected) == []
    for bad in [good.replace("fixed", "fixed extra"), good.replace("yes  now", "yes now"),
                good.replace("x  y", "x y"), good.replace("\r\n", "\n"), good.replace('id="keep"', 'id="other"')]:
        assert check_approved_web_content(source, bad, {"a": segment()}, expected)


def test_expected_content_preserves_normalization_and_literals():
    from supertranslator.web_content import prepare_approved_web_content
    from supertranslator.models import ProtectedToken
    source = page('<p data-wt-segment="a">OAuth <code>x  y</code></p><p data-wt-segment="b">OAuth</p>')
    tokens = [ProtectedToken("⟦WT:000000⟧", "code", "<code>x  y</code>")]
    segments = {"b": segment("b"), "a": segment("a", protected=tokens)}
    translations = {"b": Translation("b", "OAuth 재사용"), "a": Translation("a", "OAuth ⟦WT:000000⟧ &amp; 수락")}
    original = dict(translations)
    expected = prepare_approved_web_content(source, segments, translations, {"OAuth": "권한 위임"})
    assert expected["a"].content_html == "OAuth(권한 위임) <code>x  y</code> &amp; 수락"
    assert expected["b"].content_html == "OAuth 재사용"
    assert translations == original


def test_nested_parent_link_and_located_attributes_are_checked_once():
    from supertranslator.models import ApprovedWebContent, ProtectedToken
    from supertranslator.web_content import check_approved_web_content
    source = page('<main><p data-wt-segment="a" id="parent">Read <a data-wt-segment="b" title="Label" href="#parent">Accept</a>.</p></main>')
    segments = {"a": segment(), "b": segment("b", "located:link", [
        ProtectedToken("⟦WT:000000⟧", "location", "<!--wt-location:attribute:title-->"),
        ProtectedToken("⟦WT:000001⟧", "location", "<!--wt-location:content-->"),
    ])}
    expected = {"a": ApprovedWebContent({}, '확인 <a data-wt-segment="b" title="Label" href="#parent">Accept</a>.'),
                "b": ApprovedWebContent({"title": "제목"}, "수락")}
    good = page('<main><p id="parent">확인 <a title="제목" href="#parent">수락</a>.</p></main>')
    assert check_approved_web_content(source, good, segments, expected) == []
    for bad in [good.replace("수락", "거부"), good.replace("확인", "삭제"),
                good.replace('title="제목"', 'title="다름"'), good.replace("수락", "수락수락"),
                good.replace('<p id="parent">', '<p id="parent" title="제목">')]:
        assert check_approved_web_content(source, bad, segments, expected)


@pytest.mark.parametrize("expected", [None, {}])
def test_missing_or_partial_contract_fails_closed(tmp_path, expected):
    from supertranslator.web_content import check_approved_web_content
    source = page('<p data-wt-segment="a">Accept</p>')
    findings = check_approved_web_content(source, page('<p>수락</p>'), {"a": segment()}, expected)
    assert {f.code for f in findings} == {"approved-content-contract"}


@pytest.mark.parametrize("original,altered", [("  ", " "), ("\n\n", "\n"), ("\t ", " ")])
def test_whitespace_only_content_is_not_a_comparison_bypass(original, altered):
    from supertranslator.models import ApprovedWebContent
    from supertranslator.web_content import check_approved_web_content
    source = page('<p data-wt-segment="a">Accept</p><code>  </code>')
    expected = {"a": ApprovedWebContent({}, original)}
    good = page(f'<p>{original}</p><code>  </code>')
    bad = page(f'<p>{altered}</p><code>  </code>')
    assert check_approved_web_content(source, good, {"a": segment()}, expected) == []
    assert {f.code for f in check_approved_web_content(source, bad, {"a": segment()}, expected)} == {"approved-content-integrity"}


def test_backend_metadata_does_not_hide_duplicate_or_body_additions():
    from supertranslator.assemble import _CSP
    from supertranslator.models import ApprovedWebContent
    from supertranslator.web_content import check_approved_web_content
    source = page('<p data-wt-segment="a">Accept</p>')
    csp = f'<meta data-wt-csp="offline" http-equiv="Content-Security-Policy" content="{_CSP}">'
    expected = {"a": ApprovedWebContent({}, "수락")}
    good = page('<p>수락</p>').replace('<head>', '<head>' + csp + '<meta charset="utf-8">')
    assert check_approved_web_content(source, good, {"a": segment()}, expected) == []
    for bad in [good.replace(csp, csp + csp), good.replace('<body>', '<body><meta charset="utf-8">')]:
        assert {f.code for f in check_approved_web_content(source, bad, {"a": segment()}, expected)} == {"approved-content-integrity"}


@pytest.mark.parametrize("wrapped,accepted", [(False, True), (True, False)],
                         ids=["genuine-footer", "wrapped-anchor-with-added-prose"])
def test_backend_attribution_requires_exact_direct_children(tmp_path, wrapped, accepted):
    from supertranslator.models import ApprovedWebContent
    from supertranslator.web_content import check_approved_web_content
    source, output = tmp_path / "run/source.html", tmp_path / "output/index.html"
    source.parent.mkdir()
    output.parent.mkdir()
    source_text = page('<p data-wt-segment="a">Accept</p>')
    link = '<a href="https://example.com/" rel="noopener noreferrer">원문 보기</a>'
    second_child = f'<span>{link} 승인되지 않은 거부 문구</span>' if wrapped else link
    output_text = page('<p>수락</p><footer data-wt-attribution="source">'
                       f'AI 번역본 · {second_child}</footer>')
    expected = {"a": ApprovedWebContent({}, "수락")}
    findings = check_approved_web_content(source_text, output_text, {"a": segment()}, expected)
    assert {f.code for f in findings} == (set() if accepted else {"approved-content-integrity"})
    source.write_bytes(source_text.encode("utf-8"))
    output.write_bytes(output_text.encode("utf-8"))
    result = run_qa(QAInputs(source, output, "https://example.com/", {"a"}, {"a"}, [], [],
                            source.parent / "screenshots", MasterReview([], {}, {}),
                            target_segments={"a": segment()}, approved_contents=expected))
    assert result.passed == accepted
    assert {f.code for f in result.required_findings} == (set() if accepted else {"approved-content-integrity"})
    assert len(result.screenshots) == (2 if accepted else 0)


def test_fragment_comparison_never_truncates_at_a_wrapper_name():
    from supertranslator.models import ApprovedWebContent
    from supertranslator.web_content import check_approved_web_content
    source = page('<p data-wt-segment="a">Accept</p>')
    expected = {"a": ApprovedWebContent({}, "수락</wt-fragment>거부")}
    assert check_approved_web_content(source, page('<p>수락</p>'), {"a": segment()}, expected)


def test_duplicate_attributes_cannot_choose_a_different_browser_value():
    from supertranslator.models import ApprovedWebContent, ProtectedToken
    from supertranslator.web_content import check_approved_web_content
    source = page('<input data-wt-segment="a" title="Accept">')
    item = segment("a", "located:attributes", [ProtectedToken("⟦WT:000000⟧", "location", "<!--wt-location:attribute:title-->")])
    expected = {"a": ApprovedWebContent({"title": "수락"}, None)}
    bad = page('<input title="거부" title="수락">')
    assert {f.code for f in check_approved_web_content(source, bad, {"a": item}, expected)} == {"approved-content-integrity"}


def test_located_contract_preserves_untranslated_empty_and_literal_attributes():
    from supertranslator.models import ApprovedWebContent, ProtectedToken
    from supertranslator.web_content import check_approved_web_content
    source = page('<img data-wt-segment="a" alt="" title="Open docs" aria-label="https://example.com/">')
    item = segment("a", "located:attributes", [ProtectedToken("⟦WT:000000⟧", "location", "<!--wt-location:attribute:title-->")])
    expected = {"a": ApprovedWebContent({"title": "문서 열기"}, None)}
    good = page('<img alt="" title="문서 열기" aria-label="https://example.com/">')
    assert check_approved_web_content(source, good, {"a": item}, expected) == []
    assert check_approved_web_content(source, good.replace('alt=""', 'alt="추가"'), {"a": item}, expected)


@pytest.mark.parametrize("held_bytes", [False, True])
def test_full_qa_preserves_literal_newlines(tmp_path, held_bytes):
    from supertranslator.models import ApprovedWebContent
    source, output = tmp_path / "run/source.html", tmp_path / "output/index.html"
    source.parent.mkdir()
    output.parent.mkdir()
    source_text = page('<p data-wt-segment="a">Accept</p><pre>x\r\ny</pre>')
    output_text = page('<p>수락</p><pre>x\ny</pre>')
    source.write_bytes(source_text.encode())
    output.write_bytes(output_text.encode())
    inputs = QAInputs(source, output, "https://example.com/", {"a"}, {"a"}, [], [],
                      source.parent / "screenshots", MasterReview([], {}, {}),
                      target_segments={"a": segment()}, approved_contents={"a": ApprovedWebContent({}, "수락")},
                      source_bytes=source.read_bytes() if held_bytes else None,
                      output_bytes=output.read_bytes() if held_bytes else None)
    result = run_qa(inputs)
    assert not result.passed
    assert "approved-content-integrity" in {f.code for f in result.required_findings}
    assert not result.screenshots
