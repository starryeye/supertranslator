"""Explicit synthetic master approvals must survive the real PDF consumers."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pdfplumber
import pytest

from tests.pdf_unit_fixtures import make_render_unit_run, rebind_native_fixture
from tests.test_pdf_qa import _write_json, _write_review, _write_passing_layout_review
from tests.test_pdf_review import _reviewed_run, _write
from web_translator.models import ProtectedToken, Translation
from web_translator.pdf_assemble import assemble_pdf, PdfAssemblyError
import web_translator.pdf_assemble as assembly
from web_translator.pdf_qa import prepare_pdf_qa, finalize_pdf_output, PdfQAFailure
import web_translator.pdf_qa as qa
from web_translator.pdf_review import (
    preserved_name_pattern, build_pdf_semantic_review_input,
    validate_pdf_semantic_review, PdfSemanticReviewError,
)


def approved_run(tmp_path, *, notes=False):
    run, document, segments, translations = make_render_unit_run(
        tmp_path, case="multiple-note" if notes else "preserved-names")
    if notes:
        first = segments[0]
        translations[first.id] = replace(translations[first.id], text=
            translations[first.id].text.replace("첫째표식", "First member") + " member와 member 용어입니다.")
        names = ["First member *"]
        glossary = {"member": "구성원"}
    else:
        # Overlapping approvals are deliberately ordered short-before-long.
        names = ["Orion Cache", "Cache Engine", "Orion Cache Engine", "Vega Cache Engine"]
        glossary = {"Cache": "캐시"}
    from web_translator.cli import _zone_payload
    from web_translator.zones import build_zones
    for zone in build_zones(segments):
        _write_json(run / "zones" / f"{zone.id}.json", _zone_payload(zone))
    rebind_native_fixture(run)
    _write_json(run / "glossary.json", glossary)
    (run / "translations").mkdir()
    (run / "translations/zone-001.jsonl").write_text("".join(
        json.dumps(record.to_dict(), ensure_ascii=False) + "\n" for record in translations.values()),
        encoding="utf-8", newline="\n")
    _write_review(run)
    review = json.loads((run / "review.json").read_bytes())
    review["preserved_names"] = {segments[0].id: [
        {"text": name, "reason": "TEST ONLY explicit source-backed master name."} for name in names]}
    _write_json(run / "review.json", review)
    return run, document, segments, translations, glossary, review


@pytest.mark.parametrize("name,text,accepted", [
    ("François", "François는", True), ("Andre", "Andre와", True),
    ("François", "(François).", True), ("Andre\u0301", "Andre\u0301는", True),
    ("François", "Françoisé", False), ("François", "éFrançois", False),
    ("Andre", "Andre\u0301", False), ("Andre", "\u0301Andre", False),
    ("Andre", "Andre\u1ab0", False), ("Andre", "Andre\u20dd", False),
    ("Andre", "Andreᵉ", False), ("Andre", "AndreK", False),
    ("Andre", "Andre_", False), ("Andre", "3Andre", False),
    ("André", "Andre\u0301", False),
])
def test_exact_name_boundaries(name, text, accepted):
    assert (preserved_name_pattern(name).search(text) is not None) is accepted


@pytest.mark.parametrize("side", ["source", "translation"])
def test_semantic_review_rejects_changed_unicode_name(side, tmp_path):
    run, review = _reviewed_run(tmp_path, names=True)
    name = "Alice Brown"
    if side == "source":
        value = json.loads((run / "segments.jsonl").read_text())
        value["source_text"] = value["source_text"].replace(name, name + "é")
        _write(run / "segments.jsonl", json.dumps(value) + "\n")
        rebind_native_fixture(run)
    else:
        value = json.loads((run / "translations/zone-001.jsonl").read_text())
        value["text"] = value["text"].replace(name, name + "\u0301")
        _write(run / "translations/zone-001.jsonl", json.dumps(value) + "\n")
    review["semantic_input_sha256"] = build_pdf_semantic_review_input(run).semantic_input_sha256
    review["preserved_names"] = {"seg-000001": [{"text": name, "reason": "Source name."}]}
    with pytest.raises(PdfSemanticReviewError, match="not exact"):
        validate_pdf_semantic_review(run, review)


@pytest.mark.parametrize("notes", [False, True])
def test_direct_pdf_assembly_and_qa_preserve_names_without_consuming_outside_gloss(tmp_path, notes):
    run, document, segments, translations, glossary, review = approved_run(tmp_path, notes=notes)
    output = tmp_path / "output"
    pdf = assemble_pdf(run, translations, glossary, output)
    with pdfplumber.open(pdf) as rendered:
        visible = " ".join((page.extract_text() or "").replace("\n", " ") for page in rendered.pages)
    if notes:
        assert "First member *" in visible
        assert "구성원(member)와 구성원 용어입니다." in visible
        from pypdf import PdfReader
        destinations = [annot.get_object()["/Dest"] for page in PdfReader(pdf).pages
                        for annot in page.get("/Annots", []) if "/Dest" in annot.get_object()]
        assert len(destinations) == 2 and destinations[0] != destinations[1]
    else:
        assert visible.count("Orion Cache Engine") == 2
        assert "Vega Cache Engine" in visible
        assert "캐시(Cache)는 이름 밖의 용어이고 캐시는 나중 용어입니다." in visible
    result = prepare_pdf_qa(run, output)
    assert result.metrics["translation_unit_count"] == len(document.translation_units)
    _write_passing_layout_review(run)
    finalize_pdf_output(run, output)
    assert sorted(path.name for path in output.iterdir()) == ["manifest.json", "review-report.md", "translated.pdf"]
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["translation"]["master_semantic_review"]["preserved_names"] == review["preserved_names"]


@pytest.mark.parametrize("damage", ["foreign", "stale", "unresolved"])
def test_direct_figure_free_assembly_rejects_unvalidated_name_review(tmp_path, damage):
    run, _document, _segments, translations, glossary, review = approved_run(tmp_path)
    if damage == "foreign":
        review["preserved_names"]["seg-000001"][0]["text"] = "Foreign Cache Engine"
    elif damage == "stale":
        review["semantic_input_sha256"] = "0" * 64
    else:
        review["unresolved_required"] = ["Name requires master correction."]
    _write_json(run / "review.json", review)
    with pytest.raises((PdfAssemblyError, PdfSemanticReviewError)):
        assemble_pdf(run, translations, glossary, tmp_path / "output")
    assert not (run / "staged-output/translated.pdf").exists()


@pytest.mark.parametrize("stage", ["render", "publish"])
@pytest.mark.parametrize("mutation", ["identity", "content"])
def test_direct_name_assembly_keeps_master_review_bound_through_publication(tmp_path, monkeypatch, stage, mutation):
    run, _document, _segments, translations, glossary, _review = approved_run(tmp_path)
    path = run / "review.json"
    payload = path.read_bytes()
    fired = False
    hook = "_build_rich_document" if stage == "render" else "_publish_new_file"
    original = getattr(assembly, hook)
    def raced(*args, **kwargs):
        nonlocal fired
        result = original(*args, **kwargs)
        if not fired:
            fired = True
            if mutation == "identity":
                path.rename(path.with_name("saved-review.json"))
                path.write_bytes(payload)
            else:
                path.write_bytes(payload + b" ")
        return result
    monkeypatch.setattr(assembly, hook, raced)
    with pytest.raises(PdfAssemblyError):
        assemble_pdf(run, translations, glossary, tmp_path / "output")
    assert fired
    assert not (run / "staged-output/translated.pdf").exists()


def test_density_requires_exact_name_survival_even_in_korean_prose():
    block = SimpleNamespace(id="block", segment_id="seg-000001", page_number=1,
        kind="paragraph", semantic_role="body", source_text="Orion Cache Engine")
    with pytest.raises(PdfQAFailure, match="preserved name"):
        qa._validate_latin_density(SimpleNamespace(blocks=[block]),
            {"block": "Orion 캐시 Engine " + "충분히 긴 한국어 설명입니다. " * 20},
            segments={}, glossary={}, preserved_names={"seg-000001": [
                {"text": "Orion Cache Engine", "reason": "Explicit source name."}]})


def test_names_do_not_consume_glossary_first_use_in_later_record(tmp_path):
    _run, _document, segments, _translations, glossary, _review = approved_run(tmp_path)
    first = replace(segments[0], source_text="Orion Cache Engine")
    second = replace(first, id="seg-000002", source_text="Cache and Cache")
    normalized = assembly._normalized_unit_records([first, second], {
        first.id: Translation(first.id, "Orion Cache Engine는 이름입니다."),
        second.id: Translation(second.id, "Cache와 Cache 용어입니다."),
    }, glossary, preserved_names={first.id: [{"text": "Orion Cache Engine", "reason": "Source name."}]})
    assert [record.text for record in normalized] == [
        "Orion Cache Engine는 이름입니다.", "캐시(Cache)와 캐시 용어입니다."]


def test_names_cross_original_number_placeholder_and_keep_opaque_name_identity(tmp_path):
    _run, _document, segments, _translations, _glossary, _review = approved_run(tmp_path)
    number = ProtectedToken("⟦WT:000000⟧", "number", "2025")
    opaque = ProtectedToken("⟦WT:000001⟧", "identifier", "Orion Cache Engine")
    raw = "QRY:" + number.token + " " + opaque.token + " QRY QRY Cache"
    segment = replace(segments[0], source_text=raw, protected=[number, opaque])
    normalized = assembly._normalized_unit_records([segment], {
        segment.id: Translation(segment.id, raw)}, {"QRY": "질의", "Cache": "캐시"},
        preserved_names={segment.id: [
            {"text": "QRY:2025", "reason": "Explicit standard identifier."},
            {"text": "Orion Cache Engine", "reason": "Opaque source name."}]})
    assert normalized[0].text == ("QRY:⟦WT:000000⟧ ⟦WT:000001⟧ 질의(QRY) 질의 캐시(Cache)")
    from web_translator.protection import restore_tokens
    assert restore_tokens(normalized[0].text, segment.protected) == (
        "QRY:2025 Orion Cache Engine 질의(QRY) 질의 캐시(Cache)")


@pytest.mark.parametrize("legacy", [False, True])
def test_normalized_name_protection_is_pdf_local_and_preserves_document_first_use(tmp_path, legacy):
    _run, document, segments, translations, glossary, review = approved_run(tmp_path)
    names = review["preserved_names"]
    if legacy:
        # Use the declared joined source as a single legacy physical block.
        block = replace(document.blocks[0], source_text=segments[0].source_text)
        document = replace(document, schema_version="1.1", blocks=[block], translation_units=[])
        records = assembly._normalize_pdf_translations(document, segments, translations, glossary, preserved_names=names)
        visible = records[0][2]
    else:
        units = assembly.normalize_pdf_units(document, segments, translations, glossary, preserved_names=names)
        visible = units[0].text
        markup, _links = assembly._unit_markups(document, units, translations, glossary, preserved_names=names)
        assert "Orion Cache Engine" in markup[units[0].source_blocks[0].id]
        assert "캐시(Cache)는" in markup[units[0].source_blocks[0].id]
    assert visible == ("Orion Cache Engine와 Vega Cache Engine, Orion Cache Engine는 이름입니다. "
                       "캐시(Cache)는 이름 밖의 용어이고 캐시는 나중 용어입니다.")
    from web_translator.terminology import normalize_terminology
    html = normalize_terminology(list(translations.values()), glossary, policy="korean-first")
    assert "Orion 캐시(Cache) Engine" in html[0].text
