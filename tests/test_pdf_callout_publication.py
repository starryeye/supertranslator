"""TEST ONLY native callout publication decisions; never production approval."""

import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from copy import deepcopy
from dataclasses import replace

import pytest

from supertranslator.cli import main
from supertranslator.models import Translation, read_segments
from tests.test_pdf_callout_units import _continued_source
from tests.test_pdf_qa import _write_review, _write_passing_layout_review


CALLOUT_MODULES = {
    f"tests/test_pdf_callout_{name}.py"
    for name in ("contracts", "detection", "extract", "units", "render", "publication")
}
PRIOR_PDF_SELECTORS = {
    "tests/test_pdf_pipeline.py", "tests/test_plugin_layout.py", "tests/test_renamed_identity.py",
    "tests/test_pdf_utf8_fixtures.py", "tests/test_poppler_bootstrap.py", "tests/test_pdf_caption_evidence.py",
    "tests/test_pdf_composite_figures.py", "tests/test_pdf_composite_figure_pipeline.py",
    "tests/test_pdf_acquire.py::test_windows_run_anchor_requests_only_directory_list_access",
    "tests/test_pdf_acquire.py::test_windows_run_anchor_closes_handle_when_path_validation_fails",
    "tests/test_pdf_pipeline.py::test_windows_root_anchor_enumerates_exact_unicode_children",
    "tests/test_pdf_assemble.py::test_windows_native_relative_rename_moves_to_held_destination",
    "tests/test_pdf_assemble.py::test_windows_native_relative_rename_never_clobbers_existing_destination",
    "tests/test_pdf_assemble.py::test_windows_relative_mutation_directory_requests_delete_without_write",
    "tests/test_pdf_assemble.py::test_anchored_acquisition_keeps_successful_handle_during_outer_exception",
    "tests/test_pdf_qa.py::test_windows_qa_directory_mutation_verifies_identity_and_closes_handle",
    "tests/test_pdf_qa.py::test_prior_qa_descendant_release_retains_original_snapshot",
    "tests/test_pdf_qa.py::test_remove_qa_pages_uses_windows_held_handle_to_remove_empty_directory",
    "tests/test_pdf_qa.py::test_remove_qa_pages_uses_windows_held_handle_move_and_closes_anchors",
    "tests/test_pdf_qa.py::test_prepare_pdf_qa_regenerates_safe_prior_evidence_and_preserves_unrelated_files",
    "tests/test_pdf_qa.py::test_prepare_pdf_qa_cleans_post_publication_base_exception_by_identity",
    "tests/test_pdf_qa.py::test_prepare_pdf_qa_closes_new_record_before_restoring_prior_evidence",
    "tests/test_pdf_qa.py::test_prepare_pdf_qa_restores_prior_evidence_after_interrupted_relocation",
    "tests/test_pdf_qa.py::test_prepare_figure_free_master_review_races_fail_closed",
    "tests/test_pdf_qa.py::test_prepare_figure_free_review_unchanged_finalizes_exact_artifacts",
    "tests/test_pdf_qa.py::test_windows_publishes_nonempty_qa_directory_after_releasing_descendant_handles",
    "tests/test_pdf_qa.py::test_windows_nonempty_qa_directory_publication_never_clobbers_destination",
    "tests/test_pdf_pipeline.py::test_windows_finalize_durably_publishes_exact_reviewed_output",
    "tests/test_pdf_pipeline.py::test_windows_finalize_failure_cleanup_preserves_error_and_retries_immediately",
}


def _workflow_steps(text):
    """Read this workflow's step scalars without an undeclared YAML dependency."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"\s+- (uses|run|name|if|shell):", line)]
    steps = []
    for start, end in zip(starts, starts[1:] + [len(lines)]):
        indent = len(lines[start]) - len(lines[start].lstrip())
        fields = {}
        i = start
        while i < end:
            line = lines[i][indent + 2:]
            match = re.match(r"(run|if|shell):\s*(.*)$", line)
            if match:
                key, value = match.groups()
                if value in {">-", ">", "|-", "|"}:
                    parts = []
                    i += 1
                    while i < end and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent + 2):
                        parts.append(lines[i].strip())
                        i += 1
                    fields[key] = (" " if value.startswith(">") else "\n").join(parts)
                    continue
                fields[key] = value
            i += 1
        steps.append(fields)
    return steps


@pytest.mark.parametrize(("platform", "runner_os"), [("macos-15", "macOS"), ("windows-2025", "Windows")])
def test_pdf_workflow_collects_native_callout_contracts_on_each_platform(platform, runner_os):
    """Dropping or platform-gating a selector must lose real collected cases."""
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/pdf-cross-platform.yml").read_text("utf-8")
    matrix = re.search(r"(?m)^\s*os:\s*\[([^]]+)\]", workflow)
    assert matrix is not None and platform in [item.strip().strip("\"'") for item in matrix[1].split(",")]
    commands = []
    for step in _workflow_steps(workflow):
        args = shlex.split(step.get("run", ""))
        if args[:3] != ["python", "-m", "pytest"]:
            continue
        condition = step.get("if")
        if condition:
            allowed = {"runner.os == 'macOS'": "macOS", "runner.os == 'Windows'": "Windows"}
            assert condition in allowed, f"Unsupported pytest workflow condition: {condition}"
            if allowed[condition] != runner_os:
                continue
        commands.append(args[3:])
    assert commands, f"No pytest command runs on {platform}"
    selectors = {arg for args in commands for arg in args if arg.startswith("tests/")}
    assert PRIOR_PDF_SELECTORS <= selectors, f"Lost existing selectors: {PRIOR_PDF_SELECTORS - selectors}"
    collected = set()
    for args in commands:
        result = subprocess.run([sys.executable, "-m", "pytest", *args, "--collect-only"],
                                cwd=root, env=os.environ.copy(), text=True, encoding="utf-8",
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        assert result.returncode == 0, result.stdout
        collected.update(line.strip() for line in result.stdout.splitlines() if line.startswith("tests/") and "::" in line)
    selected_modules = {node.split("::", 1)[0] for node in collected}
    assert CALLOUT_MODULES <= selected_modules, f"Uncollected callout modules on {platform}: {CALLOUT_MODULES - selected_modules}"


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_inspected_synthetic_visual_review(run):
    """TEST ONLY: invoked after actual inspection of the retained three PNGs."""
    _write_passing_layout_review(run)
    path = run / "pdf-layout-review.json"
    review = json.loads(path.read_bytes())
    assert review["pages_reviewed"] == [1, 2, 3]
    observations = {
        "heading_hierarchy": "Page 1 has one bold callout title above its first body line; pages 2/3 do not repeat it.",
        "text_legibility": "All three PNGs have readable Korean text, regular line spacing and visible protected URL/numerals.",
        "table_legibility": "No independent table exists in this fixture; callout shading and borders enclose only callout text.",
        "figure_caption_pairing": "No figure or caption exists; no text has been converted into an image.",
        "footnote_placement": "Page 3 has the terminal * marker and its single source-note line below a separator on that same page.",
        "page_transitions": "The long list item continues on pages 2/3 without another title or list marker; no empty page.",
        "clipping_overlap": "All three full-page PNGs show intact glyphs inside the borders and no collision with the outside body or footnote.",
        "glyph_rendering": "Korean glyphs, Arabic numerals, URL punctuation and the note asterisk are visible without missing-glyph boxes.",
        "semantic_structure": "One title, one continued item, then an independent outside paragraph; page 3 note remains separate.",
        "toc_navigation": "This synthetic source has no table of contents; no invented TOC is present.",
        "reference_formatting": "This synthetic source has no reference list; the source URL remains in the item.",
        "text_image_separation": "The selectable callout text stays inside its shaded box; the independent prose and source note stay outside, with no image-text capture.",
        "terminology_readability": "Korean observation terminology reads consistently across the item; the protected source URL is intact without an invented English gloss.",
    }
    assert set(review["findings"]) == set(observations)
    for dimension, evidence in observations.items():
        review["findings"][dimension]["evidence"] = "TEST ONLY actual inspection of page-001.png through page-003.png: " + evidence
    _json(path, review)


def _publication_case(root, *, origin=False, list_item=False, note=False, outside=False, long=False, groups=1,
                      boundary_case=None, last_complete=False):
    """Actual acquisition, extraction and immutable assignment preparation."""
    root.mkdir(parents=True, exist_ok=True)
    source, _ = _continued_source(root / "synthetic-source.pdf", list_item=list_item)
    if boundary_case is not None:
        from tests.pdf_callout_fixtures import make_uncalibrated_callout_pdf
        source, _ = make_uncalibrated_callout_pdf(root / "uncalibrated-source.pdf", case=boundary_case)
    if groups > 1:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(source)
        writer = PdfWriter()
        for index in range(groups):
            if last_complete and index == groups - 1:
                complete_source, _ = _continued_source(root / "complete-source.pdf", complete=True)
                writer.append(PdfReader(complete_source))
            else:
                writer.append(reader)
        with source.open("wb") as stream:
            writer.write(stream)
    if note or outside:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen.canvas import Canvas
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(source))
        overlay = io.BytesIO()
        canvas = Canvas(overlay, pagesize=(600, 760))
        if note:
            canvas.setFont("Helvetica", 8)
            canvas.drawString(467, 654, "*")
            canvas.drawString(75, 70, "* A measured source note.")
        if outside:
            canvas.setFont("Helvetica", 10)
            canvas.drawString(75, 220, "Following independent account ends here.")
        canvas.save()
        writer.pages[-1].merge_page(PdfReader(overlay).pages[0])
        with source.open("wb") as stream:
            writer.write(stream)
    if origin:
        from pypdf import PdfReader, PdfWriter, Transformation
        from pypdf.generic import RectangleObject
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(source))
        for page in writer.pages:
            page.add_transformation(Transformation().translate(-100, 50))
            page.mediabox = RectangleObject((-100, 50, 500, 810))
            page.cropbox = RectangleObject((-100, 50, 500, 810))
        with source.open("wb") as stream:
            writer.write(stream)
    run = root / ".supertranslator/runs/callout"
    run.mkdir(parents=True)
    output = root / "translated-pdfs/callout"
    output.parent.mkdir()
    for arguments in (("pdf-acquire", str(source)), ("pdf-extract",), ("plan-zones",)):
        assert main([*arguments, "--run-dir", str(run)]) == 0
    _json(run / "glossary.json", {})
    (run / "document-summary.txt").write_text("TEST ONLY independent callout fixture", encoding="utf-8")
    assert main(["prepare-assignments", "--run-dir", str(run)]) == 0
    segments = [segment for segment in read_segments(run / "segments.jsonl") if segment.target]
    assert len(segments) == (int(boundary_case == "one-line-title") + 1 if boundary_case else
                             2 * groups + int(note) + int(outside) + int(last_complete))
    translations = {}
    document = json.loads((run / "document.json").read_bytes())
    units = {unit["segment_id"]: unit for unit in document["translation_units"]}
    for segment in segments:
        unit = units[segment.id]
        if unit["semantic_role"] == "callout-title": decision = "독립적으로 측정한 관측"
        elif unit["semantic_role"] == "callout-body":
            decision = "처음 관측한 12개 측정값과 https://example.org/data 출처를 보존하고 경계를 넘어 이어지는 24개 관측을 하나의 완전한 기록으로 검토합니다."
            if long: decision += " 관측의 순서를 보존하며 충분한 간격으로 기록을 검토합니다." * 150
            if list_item: decision = "1. " + decision
            if note: decision += " *"
        elif unit["kind"] == "footnote": decision = "* 이어지는 관측의 출처 각주"
        else: decision = "상자 다음의 독립 본문"
        for token in segment.protected:
            decision = decision.replace(token.value, token.token, 1)
        translations[segment.id] = Translation(segment.id, decision, "TEST ONLY fixed Korean decision", {})
    (run / "translations").mkdir()
    (run / "translations/zone-001.jsonl").write_text("".join(json.dumps(item.to_dict(), ensure_ascii=False) + "\n" for item in translations.values()), encoding="utf-8")
    assert main(["validate-translations", "--run-dir", str(run)]) == 0
    _write_review(run)  # TEST ONLY canonical semantic review of this synthetic fixture.
    return run, output, translations


@pytest.mark.parametrize("case", ["body-only", "one-line-title", "one-line-body", "one-line-tail", "hanging-only"])
def test_uncalibrated_native_group_publishes_selectable_provenance(tmp_path, case):
    # Requiring a fabricated title, local pitch prose or marker-edge calibration breaks this pipeline.
    import pdfplumber
    from supertranslator.pdf_assemble import assemble_pdf, _anchor_name
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output
    run, output, translations = _publication_case(tmp_path, boundary_case=case, list_item=case == "hanging-only")
    document = json.loads((run / "document.json").read_bytes())
    assert not document["flow_findings"]
    bodies = [u for u in document["translation_units"] if u["semantic_role"] == "callout-body"]
    assert len(bodies) == 1 and len(bodies[0]["source_block_ids"]) == 2
    assemble_pdf(run, translations, {}, output)
    prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)  # TEST ONLY automated fixture; retained renders inspected separately.
    finalize_pdf_output(run, output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["schema_version"] == "1.2"
    group, = manifest["callout_groups"]
    assert [f["page_number"] for f in group["source_fragments"]] == [1, 2]
    assert group["unit_ids"] == [u["id"] for u in document["translation_units"]]
    layout = json.loads((run / "layout.json").read_bytes())
    anchors = dict(layout["anchor_pages"])
    assert all(_anchor_name(member) in anchors for f in document["callout_groups"][0]["fragments"] for member in f["source_block_ids"])
    with pdfplumber.open(output / "translated.pdf") as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert text.count("처음") == 1 and text.count("24") == 1
    assert text.count("독립적으로") == int(case == "one-line-title")
    if case == "hanging-only":
        assert text.count("1.") == 1
    assert {p.name for p in output.iterdir()} == {"translated.pdf", "manifest.json", "review-report.md"}


@pytest.mark.parametrize("entry", ["assembly", "prepare", "finalize"])
def test_omitted_last_singleton_group_refuses_rebound_publication(tmp_path, entry):
    from supertranslator.pdf_assemble import assemble_pdf, PdfAssemblyError
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output, PdfQAFailure
    from supertranslator.pdf_models import PdfDocument
    run, output, translations = _publication_case(tmp_path, groups=2, last_complete=True)
    if entry != "assembly":
        assemble_pdf(run, translations, {}, output)
        prepare_pdf_qa(run, output)
        _write_passing_layout_review(run)
    before = _evidence(run)
    _mutate_source(run, "omitted-group")
    forged = PdfDocument.from_dict(json.loads((run / "document.json").read_bytes()))
    assert [len(u.source_block_ids) for u in forged.translation_units] == [1, 2, 1, 1, 1]
    with pytest.raises((PdfAssemblyError, PdfQAFailure), match="callout source chains"):
        if entry == "assembly": assemble_pdf(run, translations, {}, output)
        elif entry == "prepare": prepare_pdf_qa(run, output)
        else: finalize_pdf_output(run, output)
    assert not output.exists()
    assert _evidence(run) == before


@pytest.mark.parametrize("list_items", [False, True])
def test_independent_source_focus_finds_omitted_singleton_paragraphs_or_items(tmp_path, list_items):
    from pypdf import PdfReader, PdfWriter
    from supertranslator.pdf_extract import extract_pdf
    from supertranslator.pdf_models import PdfDocument, PdfContractError
    from supertranslator.pdf_callout_validation import validate_callout_source
    writer = PdfWriter()
    first, _ = _continued_source(tmp_path / "first.pdf")
    last, _ = _continued_source(tmp_path / "last.pdf", complete=True,
                                list_item=list_items, new_marker=list_items)
    writer.append(PdfReader(first))
    writer.append(PdfReader(last))
    source = tmp_path / "combined.pdf"
    with source.open("wb") as stream:
        writer.write(stream)
    document = extract_pdf(source, tmp_path / "document.json", tmp_path / "segments.jsonl", tmp_path / "media")
    assert not document.flow_findings
    assert [len(u.source_block_ids) for u in document.translation_units] == [1, 2, 1, 1, 1]
    assert [u.kind for u in document.translation_units[-2:]] == (["list-item"] * 2 if list_items else ["paragraph"] * 2)
    forged = document.to_dict()
    forged["callout_groups"].pop()
    with pytest.raises(PdfContractError, match="source chains"):
        validate_callout_source(PdfDocument.from_dict(forged), source_pdf_bytes=source.read_bytes())


@pytest.mark.parametrize("mutation", ["multiple-titles", "no-body"])
def test_optional_title_still_requires_unique_title_and_real_body(tmp_path, mutation):
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_models import PdfDocument, PdfContractError
    from supertranslator.pdf_flowables import PdfAssemblyLayout
    from supertranslator.pdf_callout_validation import validate_callout_layout
    run, output, translations = _publication_case(tmp_path)
    assemble_pdf(run, translations, {}, output)
    document = PdfDocument.from_dict(json.loads((run / "document.json").read_bytes()))
    layout = PdfAssemblyLayout.from_dict(json.loads((run / "layout.json").read_bytes()))
    body = document.translation_units[1]
    document.translation_units[1] = replace(body, semantic_role="callout-title")
    if mutation == "no-body":
        document.translation_units[0] = replace(document.translation_units[0], semantic_role="body")
    with pytest.raises(PdfContractError):
        validate_callout_layout(document, layout)


@pytest.mark.parametrize("empty_inventory", [False, True])
def test_native_callout_pipeline_requires_matching_versions_and_bindings(tmp_path, empty_inventory):
    # A closed 1.3 capability gate or loss of actual groups must break this real pipeline.
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output
    run, output, translations = _publication_case(tmp_path)
    if empty_inventory:
        assert main(["pdf-figure-review-input", "--run-dir", str(run)]) == 0
        inventory = (run / "figure-text-input.json").read_bytes()
        assert json.loads(inventory)["figures"] == []
        _write_review(run)  # TEST ONLY renew semantic input after inventory creation.
        review = json.loads((run / "review.json").read_bytes())
        review["figure_text_review"] = {"schema_version": "1.0",
            "inventory_sha256": hashlib.sha256(inventory).hexdigest(), "figures": {}}
        _json(run / "review.json", review)
    assemble_pdf(run, translations, {}, output)
    qa = prepare_pdf_qa(run, output)
    assert qa.schema_version == "1.1"
    _write_passing_layout_review(run)  # TEST ONLY; representative PNG inspected separately.
    finalize_pdf_output(run, output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["schema_version"] == "1.2"
    assert len(manifest["callout_groups"]) == 1
    assert manifest["callout_groups"][0]["unit_ids"] == ["pdf:unit-000001", "pdf:unit-000002"]
    assert ("figure-text-input.json" in {f["path"] for f in manifest["semantic_input"]["files"]}) is empty_inventory
    assert {p.name for p in output.iterdir()} == {"translated.pdf", "manifest.json", "review-report.md"}


def _renew_outer_digests(run):
    """TEST ONLY adversary renewal; deliberately does not call source validators."""
    from tests.test_pdf_unit_bindings import manual_binding
    from supertranslator.pdf_review import _semantic_digest
    _json(run / "assignments/.pdf-unit-binding.json", manual_binding(run))
    payloads = {name: (run / name).read_bytes() for name in
                ("document.json", "source.json", "source.pdf", "segments.jsonl", "glossary.json")
                if (run / name).exists()}
    for directory in ("zones", "assignments", "translations"):
        payloads.update({f"{directory}/{path.name}": path.read_bytes() for path in (run / directory).iterdir()})
    review = json.loads((run / "review.json").read_bytes())
    review["semantic_input_sha256"] = _semantic_digest(payloads)
    _json(run / "review.json", review)


def _evidence(run):
    return {path.relative_to(run).as_posix(): path.read_bytes()
            for name in ("staged-output", "qa-pages") for path in (run / name).rglob("*") if path.is_file()} | {
        name: (run / name).read_bytes() for name in ("pdf-qa.json", "pdf-layout-review.json") if (run / name).exists()}


SOURCE_MUTATIONS = ["missing-groups", "missing-source", "foreign-group-id", "foreign-member", "omitted-member",
    "reordered-member", "duplicate-member", "foreign-glyph", "omitted-glyph", "reordered-glyph",
    "duplicate-glyph", "duplicate-group", "forged-cap", "forged-border", "forged-page-origin",
    "changed-text", "forged-join", "stale-source", "foreign-source", "stale-document", "stale-binding",
    "stale-review", "required-flow", "wrong-version", "old-origin", "omitted-group", "reordered-group",
    "captured-body", "captured-table", "captured-figure"]


def _mutate_source(run, case):
    path = run / "document.json"
    document = json.loads(path.read_bytes())
    group = document["callout_groups"][0]
    fragment = group["fragments"][0]
    if case == "missing-groups": document["callout_groups"] = []
    elif case == "foreign-group-id": group["id"] = "pdf:callout-999999"
    elif case == "missing-source": (run / "source.pdf").unlink()
    elif case == "foreign-member": fragment["source_block_ids"][0] = "pdf:page-0001:block-9999"
    elif case == "omitted-member": fragment["source_block_ids"].pop()
    elif case == "reordered-member": fragment["source_block_ids"].reverse()
    elif case == "duplicate-member": fragment["source_block_ids"].append(fragment["source_block_ids"][0])
    elif case == "foreign-glyph": fragment["character_indexes"][-1] += 1000
    elif case == "omitted-glyph": fragment["character_indexes"].pop()
    elif case == "reordered-glyph": fragment["character_indexes"].reverse()
    elif case == "duplicate-glyph": fragment["character_indexes"].append(fragment["character_indexes"][0])
    elif case == "duplicate-group": document["callout_groups"].append(deepcopy(group))
    elif case == "omitted-group": document["callout_groups"].pop()
    elif case == "reordered-group": document["callout_groups"].reverse()
    elif case == "captured-body": document["blocks"][0]["semantic_role"] = "body"
    elif case == "captured-table": document["blocks"][0]["kind"] = "table-cell"
    elif case == "captured-figure": document["blocks"][0]["kind"] = "figure"
    elif case == "forged-cap": fragment["open_top"] = True
    elif case == "forged-border": fragment["border_bbox"][0] -= 1
    elif case == "forged-page-origin":
        for part in group["fragments"]:
            part["page_bbox"][0] -= 10
            part["page_bbox"][2] -= 10
    elif case == "changed-text": document["blocks"][0]["source_text"] = document["blocks"][0]["source_text"].replace("Independent", "Counterfeit", 1)
    elif case == "forged-join": document["translation_units"][1]["joins"][0]["evidence"]["left"]["text_indent"] += 1
    elif case == "stale-source": (run / "source.pdf").write_bytes((run / "source.pdf").read_bytes() + b"\n")
    elif case == "foreign-source":
        from tests.pdf_callout_fixtures import make_page_spanning_callout_pdf
        foreign = make_page_spanning_callout_pdf(run / "foreign.pdf").source.read_bytes()
        (run / "source.pdf").write_bytes(foreign)
        source = json.loads((run / "source.json").read_bytes())
        source.update(sha256=hashlib.sha256(foreign).hexdigest(), byte_length=len(foreign))
        document["source_sha256"] = source["sha256"]
        _json(run / "source.json", source)
    elif case == "required-flow":
        document["flow_findings"] = [{"code": "ambiguous-page-continuation", "left_block_id": document["blocks"][1]["id"],
            "right_block_id": document["blocks"][2]["id"], "severity": "required", "message": "TEST ONLY required source ambiguity."}]
        from supertranslator.pdf_models import PdfDocument
        assert PdfDocument.from_dict(document).flow_findings[0].severity == "required"
    elif case == "wrong-version": document["schema_version"] = "1.2"
    elif case == "old-origin": document["extracted_schema_version"] = "1.2"
    elif case == "stale-document":
        path.write_bytes(path.read_bytes() + b" ")
        return
    elif case == "stale-binding":
        binding = json.loads((run / "assignments/.pdf-unit-binding.json").read_bytes())
        binding["document_sha256"] = "f" * 64
        _json(run / "assignments/.pdf-unit-binding.json", binding)
        return
    elif case == "stale-review":
        review = json.loads((run / "review.json").read_bytes())
        review["semantic_input_sha256"] = "f" * 64
        _json(run / "review.json", review)
        return
    else: raise AssertionError(case)
    _json(path, document)
    _renew_outer_digests(run)


@pytest.mark.parametrize("entry", ["assembly", "prepare", "finalize"])
@pytest.mark.parametrize("case", SOURCE_MUTATIONS)
def test_callout_publication_refuses_rebound_foreign_group(tmp_path, entry, case):
    # Accepting outer renewal without independent held source proof is the bug.
    from supertranslator.pdf_assemble import assemble_pdf, PdfAssemblyError
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output, PdfQAFailure
    run, output, translations = _publication_case(tmp_path, groups=2 if case in {"omitted-group", "reordered-group"} else 1)
    if entry != "assembly":
        assemble_pdf(run, translations, {}, output)
        prepare_pdf_qa(run, output)
        _write_passing_layout_review(run)
    before = _evidence(run)
    _mutate_source(run, case)
    with pytest.raises((PdfAssemblyError, PdfQAFailure)):
        if entry == "assembly": assemble_pdf(run, translations, {}, output)
        elif entry == "prepare": prepare_pdf_qa(run, output)
        else: finalize_pdf_output(run, output)
    assert not output.exists()
    assert _evidence(run) == before


def test_callout_source_window_preserves_later_group_identity_and_neighbor_context(tmp_path, monkeypatch):
    # Regenerating IDs from sparse ordinal or focusing an incomplete neighboring
    # chain fails this complete three-group source without extra book scanning.
    from pypdf import PdfReader, PdfWriter
    from supertranslator.pdf_extract import extract_pdf
    import supertranslator.pdf_callout_validation as validation
    writer = PdfWriter()
    for index in range(3):
        source, _ = _continued_source(tmp_path / f"chain-{index}.pdf")
        for page in PdfReader(source).pages:
            writer.add_page(page)
    source = tmp_path / "three-source-chains.pdf"
    with source.open("wb") as stream:
        writer.write(stream)
    document = extract_pdf(source, tmp_path / "document.json", tmp_path / "segments.jsonl", tmp_path / "media")
    assert [group.id for group in document.callout_groups] == ["pdf:callout-000001", "pdf:callout-000002", "pdf:callout-000003"]
    original = validation.discover_callout_chains
    calls = []
    def discover(pages, *, focus_pages):
        calls.append((tuple(page.page_number for page in pages), tuple(focus_pages)))
        return original(pages, focus_pages=focus_pages)
    monkeypatch.setattr(validation, "discover_callout_chains", discover)
    validation.validate_callout_source(document, source_pdf_bytes=source.read_bytes())
    assert calls == [((1, 2, 3), (1, 2)), ((2, 3, 4, 5), (3, 4)), ((4, 5, 6), (5, 6))]


def test_callout_source_window_accepts_actual_shared_page_groups(tmp_path, monkeypatch):
    # Focusing A alone sees B's open start on the shared page without B's end.
    # Real extraction accepts both chains; validation must retain that proof.
    from pypdf import PdfReader, PdfWriter, Transformation
    from supertranslator.pdf_extract import extract_pdf
    import supertranslator.pdf_callout_validation as validation
    seed, _ = _continued_source(tmp_path / "seed.pdf")
    reader, writer = PdfReader(seed), PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=1200, height=760)
    writer.pages[0].merge_page(reader.pages[0])
    writer.pages[1].merge_page(reader.pages[1])
    writer.pages[1].merge_transformed_page(reader.pages[0], Transformation().translate(600, 0))
    writer.pages[2].merge_transformed_page(reader.pages[1], Transformation().translate(600, 0))
    source = tmp_path / "shared-page.pdf"
    with source.open("wb") as stream:
        writer.write(stream)
    document = extract_pdf(source, tmp_path / "document.json", tmp_path / "segments.jsonl", tmp_path / "media")
    assert [[f.page_number for f in g.fragments] for g in document.callout_groups] == [[1, 2], [2, 3]]
    assert document.flow_findings == []
    original, calls = validation.discover_callout_chains, []
    def discover(pages, *, focus_pages):
        calls.append((tuple(p.page_number for p in pages), tuple(focus_pages)))
        return original(pages, focus_pages=focus_pages)
    monkeypatch.setattr(validation, "discover_callout_chains", discover)
    validation.validate_callout_source(document, source_pdf_bytes=source.read_bytes())
    assert calls == [((1, 2, 3), (1, 2, 3))]


def test_native_callout_negative_origin_publication_and_out_of_page_rejection(tmp_path):
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output, PdfQAFailure
    from supertranslator.pdf_report import PdfFinalManifest, PdfManifestUnit
    run, output, translations = _publication_case(tmp_path, origin=True)
    assemble_pdf(run, translations, {}, output)
    prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    finalize_pdf_output(run, output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["translation_units"][0]["source_bboxes"][0][0] == -25
    assert PdfFinalManifest.from_dict(manifest).to_dict() == manifest
    with pytest.raises(PdfQAFailure):
        PdfManifestUnit.from_dict(manifest["translation_units"][0])
    forged = deepcopy(manifest)
    forged["translation_units"][0]["source_bboxes"][0][0] = -101
    with pytest.raises(PdfQAFailure):
        PdfFinalManifest.from_dict(forged)


LAYOUT_MUTATIONS = ["dropped-unit", "duplicate-unit", "foreign-group", "detached-title", "detached-anchor",
                    "captured-body", "forged-bounds", "duplicate-part", "omitted-part", "stale-layout", "detached-title-gap"]


def _mutate_layout(layout, case):
    records = layout["flowables"]
    if case == "dropped-unit": records.pop()
    elif case == "duplicate-unit": records.append(deepcopy(records[-1]))
    elif case == "foreign-group": records[-1]["callout_group_id"] = "pdf:callout-999999"
    elif case == "detached-title": records[0]["page_number"] += 1
    elif case == "detached-anchor": layout["anchor_pages"][next(iter(layout["anchor_pages"]))] += 1
    elif case == "captured-body": records[-1]["callout_group_id"] = None
    elif case == "forged-bounds": layout["callout_parts"][0]["bounds"][2] = 1
    elif case == "duplicate-part": layout["callout_parts"].append(deepcopy(layout["callout_parts"][0]))
    elif case == "omitted-part": layout["callout_parts"] = []
    elif case == "stale-layout": layout["schema_version"] = "1.2"
    elif case == "detached-title-gap":
        records[1]["bounds"][1] -= 100
        layout["callout_parts"][0]["bounds"][3] += 100
    else: raise AssertionError(case)


@pytest.mark.parametrize("entry", ["prepare", "finalize"])
@pytest.mark.parametrize("case", LAYOUT_MUTATIONS)
def test_callout_publication_refuses_detached_output_preserving_evidence(tmp_path, entry, case):
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output, PdfQAFailure
    run, output, translations = _publication_case(tmp_path)
    assemble_pdf(run, translations, {}, output)
    prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    before = _evidence(run)
    layout = json.loads((run / "layout.json").read_bytes())
    _mutate_layout(layout, case)
    _json(run / "layout.json", layout)
    with pytest.raises(PdfQAFailure):
        (prepare_pdf_qa if entry == "prepare" else finalize_pdf_output)(run, output)
    assert not output.exists()
    assert _evidence(run) == before


@pytest.mark.parametrize("entry", ["assembly", "prepare", "finalize"])
@pytest.mark.parametrize("filename", ["source.pdf", "review.json"])
@pytest.mark.parametrize("mutation", ["content", "identity"])
def test_callout_held_source_and_review_replacement_races(tmp_path, monkeypatch, entry, filename, mutation):
    # Reopening visible paths or omitting through-exit verification would publish
    # after the reviewed source/review changed while the real consumer ran.
    import supertranslator.pdf_assemble as assembly
    import supertranslator.pdf_qa as qa
    import supertranslator.pdf_report as report
    run, output, translations = _publication_case(tmp_path)
    if entry != "assembly":
        assembly.assemble_pdf(run, translations, {}, output)
        qa.prepare_pdf_qa(run, output)
        _write_passing_layout_review(run)
    before = _evidence(run)
    path = run / filename
    original_bytes = path.read_bytes()
    saved = run / ("held-original-" + filename)
    fired = False
    module, name = ((assembly, "_build_rich_document") if entry == "assembly" else
                    (qa, "render_pdf_pages") if entry == "prepare" else
                    (report, "write_pdf_review_report"))
    original = getattr(module, name)
    def run_then_race(*args, **kwargs):
        nonlocal fired
        value = original(*args, **kwargs)
        if not fired:
            fired = True
            if mutation == "identity": path.rename(saved)
            path.write_bytes(original_bytes + (b" " if mutation == "content" else b""))
        return value
    monkeypatch.setattr(module, name, run_then_race)
    with pytest.raises((assembly.PdfAssemblyError, qa.PdfQAFailure)):
        if entry == "assembly": assembly.assemble_pdf(run, translations, {}, output)
        elif entry == "prepare": qa.prepare_pdf_qa(run, output)
        else: qa.finalize_pdf_output(run, output)
    assert fired and not output.exists()
    assert _evidence(run) == before
    assert path.read_bytes() == original_bytes + (b" " if mutation == "content" else b"")
    if mutation == "identity": assert saved.read_bytes() == original_bytes


@pytest.mark.parametrize("holder", ["unit", "semantic"])
def test_callout_source_is_held_through_context_exit(tmp_path, holder):
    from supertranslator.pdf_unit_bindings import _hold_pdf_unit_inputs, PdfUnitBindingError
    from supertranslator.pdf_review import hold_pdf_semantic_inputs, PdfSemanticReviewError
    run, _output, _translations = _publication_case(tmp_path)
    context = (_hold_pdf_unit_inputs(run, ("zones", "assignments")) if holder == "unit"
               else hold_pdf_semantic_inputs(run))
    with pytest.raises((PdfUnitBindingError, PdfSemanticReviewError)):
        with context as snapshot:
            assert snapshot.payloads["source.pdf"] == (run / "source.pdf").read_bytes()
            (run / "source.pdf").rename(run / "held-source.pdf")
            (run / "source.pdf").write_bytes(snapshot.payloads["source.pdf"])


@pytest.mark.parametrize("entry", ["prepare", "finalize"])
@pytest.mark.parametrize("mutation", ["content", "identity"])
def test_callout_late_source_holder_exit_preserves_prior_publication(tmp_path, monkeypatch, entry, mutation):
    # The actual holder's last exit check must run while prior QA/final rename
    # can still roll back, not after completed=True in caller cleanup.
    from contextlib import contextmanager
    import supertranslator.pdf_assemble as assembly
    import supertranslator.pdf_qa as qa
    run, output, translations = _publication_case(tmp_path)
    assembly.assemble_pdf(run, translations, {}, output)
    qa.prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    record = run / "pdf-qa.json"
    record.write_bytes(record.read_bytes() + b"\n ")  # Distinguish exact prior bytes.
    before = _evidence(run)
    source = run / "source.pdf"
    source_bytes = source.read_bytes()
    source_identity = source.stat().st_ino
    original = qa.hold_pdf_semantic_inputs
    exits = []
    @contextmanager
    def race_at_actual_exit(*args, **kwargs):
        with original(*args, **kwargs) as snapshot:
            yield snapshot
            exits.append(output.exists())
            if mutation == "identity":
                source.rename(run / "held-original-source.pdf")
            source.write_bytes(source_bytes + (b" " if mutation == "content" else b""))
            assert (source.stat().st_ino == source_identity) is (mutation == "content")
            # No injected exception: the real source holder detects this change.
    monkeypatch.setattr(qa, "hold_pdf_semantic_inputs", race_at_actual_exit)
    with pytest.raises(qa.PdfQAFailure, match="source.pdf"):
        (qa.prepare_pdf_qa if entry == "prepare" else qa.finalize_pdf_output)(run, output)
    assert exits == [entry == "finalize"]  # Final exit really occurs post-rename.
    assert not output.exists()
    after = _evidence(run)
    assert {name: after[name] for name in before} == before
    # Existing final rollback intentionally preserves newly authored reports in
    # private staging, alongside the exact original translated PDF.
    assert set(after) - set(before) == (
        {"staged-output/manifest.json", "staged-output/review-report.md"} if entry == "finalize" else set())
    assert source.read_bytes() == source_bytes + (b" " if mutation == "content" else b"")
    if mutation == "identity":
        assert (run / "held-original-source.pdf").read_bytes() == source_bytes


@pytest.mark.parametrize("entry", ["validator", "assembly"])
def test_callout_in_bounds_title_body_gap_is_rejected(tmp_path, monkeypatch, entry):
    import supertranslator.pdf_assemble as assembly
    from supertranslator.pdf_flowables import PdfAssemblyLayout
    from supertranslator.pdf_models import PdfDocument
    from supertranslator.pdf_qa import validate_pdf_unit_layout, PdfQAFailure
    run, output, translations = _publication_case(tmp_path, long=True)
    def detach(records):
        records = list(records)
        title = next(record for record in records if record.semantic_role == "callout-title")
        index = next(i for i, record in enumerate(records) if record.semantic_role == "callout-body")
        body = records[index]
        x, y, width, height = body.bounds
        assert height > 100 and title.page_number == body.page_number
        assert title.bounds[1] - (y + height) == pytest.approx(6)
        records[index] = replace(body, bounds=(x, y, width, height - 100))
        assert title.bounds[1] - (y + records[index].bounds[3]) == pytest.approx(106)
        return records
    if entry == "validator":
        assembly.assemble_pdf(run, translations, {}, output)
        document = PdfDocument.from_dict(json.loads((run / "document.json").read_bytes()))
        layout = PdfAssemblyLayout.from_dict(json.loads((run / "layout.json").read_bytes()))
        validate_pdf_unit_layout(document, layout)
        detached = replace(layout, flowables=tuple(detach(layout.flowables)))
        # Exact normal parser accepts all bounds/containment/order. The missing
        # adjacency contract, rather than an incidental parse error, must refuse.
        PdfAssemblyLayout.from_dict(detached.to_dict())
        with pytest.raises(PdfQAFailure, match="title is detached"):
            validate_pdf_unit_layout(document, detached)
    else:
        original = assembly._build_rich_document
        def build_then_detach(*args, **kwargs):
            return detach(original(*args, **kwargs))
        monkeypatch.setattr(assembly, "_build_rich_document", build_then_detach)
        with pytest.raises(assembly.PdfAssemblyError, match="title is detached"):
            assembly.assemble_pdf(run, translations, {}, output)
        assert not output.exists() and not (run / "staged-output").exists()
        assert not (run / "layout.json").exists()


@pytest.mark.parametrize("case", ["dropped-unit", "duplicate-unit", "foreign-group", "detached-title", "detached-anchor", "captured-body", "forged-bounds", "duplicate-part", "omitted-part"])
def test_callout_assembly_rejects_invalid_actual_composer_records(tmp_path, monkeypatch, case):
    import supertranslator.pdf_assemble as assembly
    run, output, translations = _publication_case(tmp_path)
    original = assembly._build_rich_document
    def build_then_mutate(*args, **kwargs):
        records = original(*args, **kwargs)
        evidence = kwargs["publication_evidence"]
        if case == "dropped-unit": records.pop()
        elif case == "duplicate-unit": records.append(records[-1])
        elif case == "foreign-group": records[-1] = replace(records[-1], callout_group_id="pdf:callout-999999")
        elif case == "detached-title": records[0] = replace(records[0], page_number=records[0].page_number + 1)
        elif case == "detached-anchor": evidence["anchor_pages"][next(iter(evidence["anchor_pages"]))] += 1
        elif case == "captured-body": records[-1] = replace(records[-1], callout_group_id=None)
        elif case == "forged-bounds":
            part = evidence["callout_parts"][0]
            evidence["callout_parts"][0] = replace(part, bounds=(*part.bounds[:2], 1, part.bounds[3]))
        elif case == "duplicate-part": evidence["callout_parts"].append(evidence["callout_parts"][0])
        elif case == "omitted-part": evidence["callout_parts"] = []
        return records
    monkeypatch.setattr(assembly, "_build_rich_document", build_then_mutate)
    with pytest.raises(assembly.PdfAssemblyError):
        assembly.assemble_pdf(run, translations, {}, output)
    assert not output.exists() and not (run / "staged-output").exists()
    assert not (run / "layout.json").exists()


@pytest.mark.parametrize("list_item,note,long", [(True, False, False), (False, True, False), (True, True, True)])
def test_callout_publication_preserves_list_markers_notes_and_outside_body(tmp_path, list_item, note, long):
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output
    import pdfplumber
    run, output, translations = _publication_case(tmp_path, list_item=list_item, note=note, outside=True, long=long)
    assemble_pdf(run, translations, {}, output)
    prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    finalize_pdf_output(run, output)
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert len(manifest["callout_groups"][0]["output_parts"]) > (1 if long else 0)
    with pdfplumber.open(output / "translated.pdf") as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    for phrase in ("독립적으로 측정한 관측", "처음 관측한", "상자 다음의 독립 본문"):
        assert text.count(phrase) == 1
    if note: assert text.count("이어지는 관측의 출처 각주") == 1
    if list_item: assert text.count("1.") == 1


@pytest.mark.parametrize("entry", ["assembly", "prepare", "finalize"])
def test_callout_publication_rejects_detached_note_marker(tmp_path, monkeypatch, entry):
    import supertranslator.pdf_assemble as assembly
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output, PdfQAFailure
    run, output, translations = _publication_case(tmp_path, note=True)
    if entry == "assembly":
        original = assembly._build_rich_document
        def build_then_detach(*args, **kwargs):
            records = original(*args, **kwargs)
            return [replace(record, footnote_owner_id=records[0].block_id) if record.kind == "footnote" else record for record in records]
        monkeypatch.setattr(assembly, "_build_rich_document", build_then_detach)
    else:
        assembly.assemble_pdf(run, translations, {}, output)
        prepare_pdf_qa(run, output)
        _write_passing_layout_review(run)
        layout = json.loads((run / "layout.json").read_bytes())
        for record in layout["flowables"]:
            if record["kind"] == "footnote": record["footnote_owner_id"] = layout["flowables"][0]["block_id"]
        _json(run / "layout.json", layout)
    before = _evidence(run)
    with pytest.raises((assembly.PdfAssemblyError, PdfQAFailure)):
        if entry == "assembly": assembly.assemble_pdf(run, translations, {}, output)
        elif entry == "prepare": prepare_pdf_qa(run, output)
        else: finalize_pdf_output(run, output)
    assert not output.exists() and _evidence(run) == before


@pytest.mark.parametrize("kind", ["paragraph", "table-cell", "figure"])
def test_callout_source_rejects_captured_peer_without_trusting_role(tmp_path, kind):
    # An unbound forged peer cannot hide behind a callout role or an outer hash.
    from supertranslator.pdf_models import PdfDocument, PdfContractError
    from supertranslator.pdf_callout_validation import validate_callout_source
    run, _output, _translations = _publication_case(tmp_path)
    document = PdfDocument.from_dict(json.loads((run / "document.json").read_bytes()))
    peer = replace(document.blocks[1], id="pdf:page-0001:block-9999", kind=kind,
                   semantic_role="body", order=len(document.blocks), segment_id=None)
    forged = replace(document, blocks=[*document.blocks, peer])
    with pytest.raises(PdfContractError, match="physical callout members|member glyph"):
        validate_callout_source(forged, source_pdf_bytes=(run / "source.pdf").read_bytes())


@pytest.mark.parametrize("case", ["coherent-layout", "review-whitespace", "review-renewed", "source-rebound"])
def test_callout_finalization_requires_exact_prepared_provenance(tmp_path, case):
    # Individually valid replacement evidence must not borrow an older visual QA.
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_qa import prepare_pdf_qa, finalize_pdf_output, PdfQAFailure
    run, output, translations = _publication_case(tmp_path)
    assemble_pdf(run, translations, {}, output)
    prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    before = _evidence(run)
    if case == "coherent-layout":
        layout = json.loads((run / "layout.json").read_bytes())
        for item in [*layout["flowables"], *layout["callout_parts"]]: item["bounds"][0] += 1
        _json(run / "layout.json", layout)
    elif case == "review-whitespace":
        path = run / "review.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif case == "review-renewed":
        review = json.loads((run / "review.json").read_bytes())
        review["section_findings"]["zone-001"][0]["evidence"] += " TEST ONLY changed review after QA."
        _json(run / "review.json", review)
    else:
        path = run / "source.pdf"
        path.write_bytes(path.read_bytes() + b"\n")
        source = json.loads((run / "source.json").read_bytes())
        source.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), byte_length=path.stat().st_size)
        document = json.loads((run / "document.json").read_bytes())
        document["source_sha256"] = source["sha256"]
        _json(run / "source.json", source)
        _json(run / "document.json", document)
        _renew_outer_digests(run)
    with pytest.raises(PdfQAFailure):
        finalize_pdf_output(run, output)
    assert not output.exists() and _evidence(run) == before


def test_callout_source_rejects_invalid_focus_before_discovery(tmp_path, monkeypatch):
    from supertranslator.pdf_models import PdfDocument, PdfContractError
    import supertranslator.pdf_callout_validation as validation
    run, _output, _translations = _publication_case(tmp_path)
    document = PdfDocument.from_dict(json.loads((run / "document.json").read_bytes()))
    group = document.callout_groups[0]
    invalid = replace(document, callout_groups=[replace(group, fragments=(
        group.fragments[0], replace(group.fragments[1], page_number=3)))])
    def unexpected_discovery(*args, **kwargs):
        raise AssertionError("invalid focus reached source discovery")
    monkeypatch.setattr(validation, "discover_callout_chains", unexpected_discovery)
    with pytest.raises(PdfContractError, match="consecutive|page"):
        validation.validate_callout_source(invalid, source_pdf_bytes=(run / "source.pdf").read_bytes())


@pytest.mark.parametrize("case", ["positive", "missing-layout", "missing-review", "mismatched-layout", "mismatched-review", "stale-layout-bytes", "stale-review-bytes"])
def test_callout_direct_report_helper_requires_captured_prepared_bytes(tmp_path, case):
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_flowables import PdfAssemblyLayout
    from supertranslator.pdf_qa import prepare_pdf_qa, read_pdf_layout_review, PdfQAFailure
    from supertranslator.pdf_report import build_pdf_report_evidence, _read_pdf_report_evidence
    from supertranslator.pdf_review import hold_pdf_semantic_inputs
    run, output, translations = _publication_case(tmp_path)
    assemble_pdf(run, translations, {}, output)
    qa = prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    assert _read_pdf_report_evidence(run).document.schema_version == "1.3"
    with hold_pdf_semantic_inputs(run) as snapshot:
        payloads = snapshot.payloads
        arguments = dict(source_pdf=payloads["source.pdf"], source_value=json.loads(payloads["source.json"]),
            document_value=json.loads(payloads["document.json"]), segments_text=payloads["segments.jsonl"].decode("utf-8"),
            glossary_value=json.loads(payloads["glossary.json"]), review_value=json.loads((run / "review.json").read_bytes()),
            zone_values={Path(name).stem: json.loads(payload) for name, payload in payloads.items() if name.startswith("zones/")},
            layout=PdfAssemblyLayout.from_dict(json.loads((run / "layout.json").read_bytes())), qa=qa,
            visual_review=read_pdf_layout_review(run / "pdf-layout-review.json", run / "pdf-qa.json"),
            semantic_snapshot=snapshot, layout_bytes=(run / "layout.json").read_bytes(), review_bytes=(run / "review.json").read_bytes())
        if case == "missing-layout": arguments.pop("layout_bytes")
        elif case == "missing-review": arguments.pop("review_bytes")
        elif case == "mismatched-layout": arguments["layout_bytes"] = b"{}"
        elif case == "mismatched-review": arguments["review_bytes"] = b"{}"
        elif case == "stale-layout-bytes": arguments["layout_bytes"] += b" "
        elif case == "stale-review-bytes": arguments["review_bytes"] += b" "
        if case == "positive":
            assert build_pdf_report_evidence(**arguments).document.schema_version == "1.3"
        else:
            with pytest.raises(PdfQAFailure): build_pdf_report_evidence(**arguments)
    assert not output.exists()


@pytest.mark.parametrize("filename", ["layout.json", "review.json"])
def test_callout_report_reader_holds_exact_extra_inputs_through_exit(tmp_path, monkeypatch, filename):
    import supertranslator.pdf_report as report
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_qa import prepare_pdf_qa, PdfQAFailure
    run, output, translations = _publication_case(tmp_path)
    assemble_pdf(run, translations, {}, output)
    prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    original = report.build_pdf_report_evidence
    path = run / filename
    before = path.read_bytes()
    def build_then_replace(**kwargs):
        result = original(**kwargs)
        path.rename(run / ("held-report-" + filename))
        path.write_bytes(before)
        return result
    monkeypatch.setattr(report, "build_pdf_report_evidence", build_then_replace)
    with pytest.raises(PdfQAFailure): report._read_pdf_report_evidence(run)
    assert not output.exists() and path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["content", "identity"])
def test_callout_prepare_holds_layout_bytes_through_qa_publication(tmp_path, monkeypatch, mutation):
    import supertranslator.pdf_qa as qa
    from supertranslator.pdf_assemble import assemble_pdf
    run, output, translations = _publication_case(tmp_path)
    assemble_pdf(run, translations, {}, output)
    qa.prepare_pdf_qa(run, output)
    before = _evidence(run)
    original = qa.render_pdf_pages
    path = run / "layout.json"
    payload = path.read_bytes()
    def render_then_replace(*args, **kwargs):
        result = original(*args, **kwargs)
        if mutation == "identity": path.rename(run / "held-original-layout.json")
        path.write_bytes(payload + (b" " if mutation == "content" else b""))
        return result
    monkeypatch.setattr(qa, "render_pdf_pages", render_then_replace)
    with pytest.raises(qa.PdfQAFailure): qa.prepare_pdf_qa(run, output)
    assert not output.exists() and _evidence(run) == before


@pytest.mark.parametrize("case", ["foreign-unit", "omitted-member", "duplicate-group", "wrong-output-page", "legacy-schema", "foreign-output-group", "outside-source"])
def test_callout_manifest_cross_checks_source_units_and_output_parts(tmp_path, case):
    from supertranslator.pdf_assemble import assemble_pdf
    from supertranslator.pdf_qa import prepare_pdf_qa, PdfQAFailure
    from supertranslator.pdf_report import build_pdf_manifest, PdfFinalManifest
    run, output, translations = _publication_case(tmp_path)
    assemble_pdf(run, translations, {}, output)
    prepare_pdf_qa(run, output)
    _write_passing_layout_review(run)
    manifest = build_pdf_manifest(run)
    assert PdfFinalManifest.from_dict(manifest).to_dict() == manifest
    group = manifest["callout_groups"][0]
    if case == "foreign-unit": group["unit_ids"][-1] = "pdf:unit-999999"
    elif case == "omitted-member": group["source_fragments"][0]["source_block_ids"].pop()
    elif case == "duplicate-group": manifest["callout_groups"].append(deepcopy(group))
    elif case == "wrong-output-page": group["output_parts"][0]["page_number"] += 1
    elif case == "legacy-schema": manifest["schema_version"] = "1.1"
    elif case == "foreign-output-group": group["output_parts"][0]["group_id"] = "pdf:callout-999999"
    elif case == "outside-source": manifest["translation_units"][0]["source_bboxes"][0][0] = -1
    with pytest.raises(PdfQAFailure): PdfFinalManifest.from_dict(manifest)
