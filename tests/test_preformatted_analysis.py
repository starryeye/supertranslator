"""Behavioral contracts for the preformatted-source producer."""

from __future__ import annotations

import hashlib
import json

import pytest


def _api():
    # Keep collection successful while the new producer is still absent (TDD RED).
    from web_translator.preformatted_analysis import (
        analyze_preformatted,
        build_classification_packages,
        validate_review,
    )

    return analyze_preformatted, build_classification_packages, validate_review


def _review_payload(analysis, packages, blocks):
    from web_translator.preformatted_contract import canonical_sha256

    return {
        "schema_version": "1.0",
        "source_sha256": analysis.source_sha256,
        "analysis_sha256": canonical_sha256(analysis.to_dict()),
        "package_sha256": {item.id: canonical_sha256(item.to_dict()) for item in packages},
        "blocks": blocks,
        "unresolved_required": [],
    }


def _block(line_ids, *, role="prose", evidence="Alpha", **extra):
    return {
        "id": "block-000001",
        "pre_id": "pre-000001",
        "line_ids": line_ids,
        "role": role,
        "evidence": evidence,
        "metadata": {},
        "literal_spans": [],
        **extra,
    }


def test_analysis_maps_all_lines_and_inline_nodes():
    analyze, packages_for, _ = _api()
    source = (
        '<main><p>Neighbor</p><pre id="a" class="poem">'
        'A<a href="/x">β</a>\r\nC\n</pre><p>Between</p>'
        '<pre id="b">終\rD</pre></main>'
    )
    analysis = analyze(source)

    assert analysis.source_sha256 == hashlib.sha256(source.encode()).hexdigest()
    assert [root.id for root in analysis.roots] == ["pre-000001", "pre-000002"]
    assert [root["attributes"] for root in analysis.to_dict()["roots"]] == [
        {"id": "a", "class": ["poem"]}, {"id": "b"}
    ]
    assert analysis.to_dict()["roots"][0]["inline_nodes"] == [
        {"path": "/main[0]/pre[1]/a[1]", "tag": "a", "attributes": {"href": "/x"}}
    ]
    assert [line.text for line in analysis.lines] == ["Aβ", "C", "", "終", "D"]
    assert [line.separator for line in analysis.lines] == ["\r\n", "\n", "", "\r", ""]
    assert [line.id for line in analysis.lines] == [
        "line-000001", "line-000002", "line-000003", "line-000004", "line-000005"
    ]
    assert [line.pre_id for line in analysis.lines] == [
        "pre-000001", "pre-000001", "pre-000001", "pre-000002", "pre-000002"
    ]
    # The DOM text stream contains ordinary neighbors, and offsets are codepoints.
    assert analysis.roots[0].text_start == 8
    assert analysis.roots[0].text_end == 14
    assert analysis.lines[0].slices == (
        {"path": "/main[0]/pre[1]/#text[0]", "start": 8, "end": 9},
        {"path": "/main[0]/pre[1]/a[1]/#text[0]", "start": 9, "end": 10},
    )
    assert analysis.lines[0].separator_slices == (
        {"path": "/main[0]/pre[1]/#text[2]", "start": 10, "end": 12},
    )
    assert [package.id for package in packages_for(analysis)] == ["package-000001"]
    assert analysis.package_ids == ("package-000001",)


def test_packages_are_bounded_and_partition_exactly():
    analyze, packages_for, _ = _api()
    analysis = analyze("<pre>" + "\n".join(f"L{i:03}" for i in range(201)) + "</pre>")
    packages = packages_for(analysis)
    assert [len(item.target_lines) for item in packages] == [200, 1]
    assert packages[0].target_lines == tuple(f"line-{i:06}" for i in range(1, 201))
    assert packages[1].target_lines == ("line-000201",)
    assert [context["id"] for context in packages[1].context_before] == [
        "line-000199", "line-000200"
    ]
    assert packages[0].context_after[0]["id"] == "line-000201"
    assert all(len(item["text"]) <= 256 for p in packages for item in p.context_before + p.context_after)
    assert sum(len(analysis.lines[int(i[-6:]) - 1].text) for p in packages for i in p.target_lines) == 804

    with pytest.raises(ValueError, match="12000"):
        analyze("<pre>" + "x" * 12001 + "</pre>")

    split = analyze("<pre>" + "x" * 6001 + "\n" + "y" * 6001 + "</pre>")
    assert [len(item.target_lines) for item in packages_for(split)] == [1, 1]
    combined = _review_payload(split, packages_for(split), [
        _block(["line-000001", "line-000002"], evidence="xxx")
    ])
    with pytest.raises(ValueError, match="12000"):
        _api()[2](split, packages_for(split), combined)


def test_review_requires_exact_ordered_coverage():
    analyze, packages_for, validate = _api()
    analysis = analyze("<pre>Alpha\nBeta\nGamma</pre>")
    packages = packages_for(analysis)
    good = _review_payload(analysis, packages, [
        _block(["line-000001", "line-000002"], evidence="Alpha"),
        _block(["line-000003"], evidence="Gamma", id="block-000002"),
    ])
    assert [block.id for block in validate(analysis, packages, good).blocks] == [
        "block-000001", "block-000002"
    ]

    mutations = [
        (lambda p: p["blocks"][0]["line_ids"].pop(), "coverage"),
        (lambda p: p["blocks"][1]["line_ids"].append("line-000002"), "coverage"),
        (lambda p: p["blocks"][1]["line_ids"].append("line-999999"), "coverage"),
        (lambda p: p["blocks"].reverse(), "id"),
        (lambda p: p["blocks"][0].update(role="alien"), "role"),
        (lambda p: p["blocks"][0].update(unknown_key=True), "fields"),
        (lambda p: p.update(unknown_key=True), "fields"),
        (lambda p: p["blocks"][0].update(id="block-999999"), "id"),
        (lambda p: p["blocks"][0].update(evidence="Not in source"), "evidence"),
        (lambda p: p["blocks"][0].update(evidence="data-wt-preformatted-block"), "reserved"),
        (lambda p: p["blocks"][0].update(metadata={"depth": 0, "marker_span": {"line_id": "line-000001", "start": 0, "end": 1}}), "metadata"),
        (lambda p: p["package_sha256"].update({"package-000001": "0" * 64}), "hash"),
    ]
    for mutate, reason in mutations:
        payload = json.loads(json.dumps(good))
        mutate(payload)
        with pytest.raises(ValueError, match=reason):
            validate(analysis, packages, payload)

    # A source-bound marker cannot be invented in a list-item review.
    marker = _review_payload(analysis, packages, [
        _block([line.id for line in analysis.lines], role="list-item", evidence="Alpha",
               metadata={"depth": 0, "marker_span": {"line_id": "line-000001", "start": 0, "end": 1}})
    ])
    with pytest.raises(ValueError, match="marker"):
        validate(analysis, packages, marker)


def test_explicit_code_constraints_cannot_be_reclassified():
    analyze, packages_for, validate = _api()
    analysis = analyze('<pre id="code"><code class="language-python">print(1)</code></pre>')
    assert len(analysis.roots) == 0
    assert len(analysis.constraints) == 1
    assert analysis.constraints[0].kind == "explicit-code"
    assert analysis.constraints[0].text == "print(1)"
    assert analysis.constraints[0].attributes == {"id": "code"}
    assert packages_for(analysis) == ()

    mixed = analyze('<pre>Intro\n<code>print(1)</code>\nEnd</pre>')
    assert [line.constraint_ids for line in mixed.lines] == [(), ("constraint-000001",), ()]
    payload = _review_payload(mixed, packages_for(mixed), [
        _block([line.id for line in mixed.lines], evidence="Intro")
    ])
    with pytest.raises(ValueError, match="constraint"):
        validate(mixed, packages_for(mixed), payload)


def test_html_language_and_empty_pre_keep_stable_text_offsets():
    analyze, _, _ = _api()
    analysis = analyze('<!doctype html><p>Lead</p><pre lang="en"></pre><pre>Text</pre>')
    assert [root.id for root in analysis.roots] == ["pre-000001", "pre-000002"]
    assert analysis.roots[0].text_start == 4
    assert analysis.roots[0].text_end == 4
    assert analysis.roots[1].text_start == 4
    assert analysis.lines[0].text == ""
    assert analysis.lines[1].text == "Text"


def test_strict_records_reject_unknown_fields_and_duplicate_json_keys():
    analyze, packages_for, validate = _api()
    from web_translator.preformatted_contract import PreformattedAnalysis, canonical_loads

    analysis = analyze("<pre>Alpha</pre>")
    bad = analysis.to_dict()
    bad["extra"] = 1
    with pytest.raises(ValueError, match="fields"):
        PreformattedAnalysis.from_dict(bad)
    with pytest.raises(ValueError, match="duplicate"):
        canonical_loads('{"x":1,"x":2}')
    payload = _review_payload(analysis, packages_for(analysis), [_block(["line-000001"])])
    payload["analysis_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        validate(analysis, packages_for(analysis), payload)


def test_records_are_deeply_immutable_and_export_independent_json():
    analyze, packages_for, validate = _api()
    from web_translator.preformatted_contract import PreformattedAnalysis

    analysis = analyze('<pre class="poem"><a href="/safe">- Alpha</a></pre>')
    wire = analysis.to_dict()
    loaded = PreformattedAnalysis.from_dict(wire)
    wire["roots"][0]["attributes"]["class"].append("tampered")
    wire["roots"][0]["inline_nodes"][0]["attributes"]["href"] = "/evil"
    assert loaded.roots[0].attributes["class"] == ("poem",)
    assert loaded.roots[0].inline_nodes[0]["attributes"]["href"] == "/safe"
    with pytest.raises((TypeError, AttributeError)):
        loaded.roots[0].attributes["class"] += ("evil",)
    exported = loaded.to_dict()
    exported["roots"][0]["attributes"]["class"].append("other")
    assert loaded.to_dict()["roots"][0]["attributes"]["class"] == ["poem"]

    packages = packages_for(analysis)
    contextual = packages_for(analyze("<pre>" + "\n".join("x" for _ in range(201)) + "</pre>"))
    with pytest.raises(TypeError):
        contextual[1].context_before[0]["text"] = "evil"

    payload = _review_payload(analysis, packages, [
        _block(["line-000001"], role="list-item", evidence="Alpha",
               metadata={"depth": 0, "marker_span": {"line_id": "line-000001", "start": 0, "end": 1}})
    ])
    reviewed = validate(analysis, packages, payload)
    payload["blocks"][0]["metadata"]["marker_span"]["start"] = 99
    payload["package_sha256"]["package-000001"] = "0" * 64
    assert reviewed.blocks[0].metadata["marker_span"]["start"] == 0
    assert reviewed.package_sha256["package-000001"] != "0" * 64
    with pytest.raises(TypeError):
        reviewed.blocks[0].metadata["marker_span"]["start"] = 99
    wire_review = reviewed.to_dict()
    wire_review["blocks"][0]["metadata"]["marker_span"]["start"] = 44
    assert reviewed.blocks[0].metadata["marker_span"]["start"] == 0


def test_nondefault_package_budget_is_rejected_before_wire_record():
    analyze, _, _ = _api()
    from web_translator.preformatted_contract import PreformattedAnalysis

    with pytest.raises(ValueError, match="fixed.*12000"):
        analyze("<pre>Alpha</pre>", max_chars=100)
    default = analyze("<pre>Alpha</pre>")
    assert PreformattedAnalysis.from_dict(default.to_dict()).to_dict() == default.to_dict()


def test_list_markers_must_lead_first_line_and_depth_transitions_are_supported():
    analyze, packages_for, validate = _api()
    source = analyze("<pre>- First\n  - Child\n  - Sibling\n- Last</pre>")
    packages = packages_for(source)

    def item(index, depth, start):
        line_id = f"line-{index:06d}"
        return _block([line_id], id=f"block-{index:06d}", role="list-item",
                      evidence=source.lines[index - 1].text.strip(),
                      metadata={"depth": depth,
                                "marker_span": {"line_id": line_id, "start": start, "end": start + 1}})

    good = _review_payload(source, packages, [item(1, 0, 0), item(2, 1, 2),
                                               item(3, 1, 2), item(4, 0, 0)])
    assert len(validate(source, packages, good).blocks) == 4
    for mutate in (
        lambda p: p["blocks"][0]["metadata"].update(depth=99),
        lambda p: p["blocks"][1]["metadata"].update(depth=2),
        lambda p: p["blocks"][0]["metadata"]["marker_span"].update(start=2, end=3),
    ):
        invalid = json.loads(json.dumps(good))
        mutate(invalid)
        with pytest.raises(ValueError, match="list|marker|depth"):
            validate(source, packages, invalid)

    interior = analyze("<pre>Intro - child</pre>")
    interior_payload = _review_payload(interior, packages_for(interior), [
        _block(["line-000001"], role="list-item", evidence="Intro",
               metadata={"depth": 0,
                         "marker_span": {"line_id": "line-000001", "start": 6, "end": 7}})
    ])
    with pytest.raises(ValueError, match="marker"):
        validate(interior, packages_for(interior), interior_payload)
