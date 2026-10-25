"""TEST ONLY synthetic composite artwork approval and publication contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex

from PIL import Image
import pdfplumber
from pypdf import PdfReader
import pytest

from supertranslator.cli import main
from supertranslator.models import Translation, read_segments
from supertranslator.pdf_assemble import PdfAssemblyError, assemble_pdf
from supertranslator.pdf_figure_review import (
    canonical_figure_text_input_bytes,
    write_pdf_figure_review_input,
)
from supertranslator.pdf_models import PdfDocument
from supertranslator.pdf_qa import PdfQAFailure, finalize_pdf_output, prepare_pdf_qa
from supertranslator.pdf_review import build_pdf_semantic_review_input
from supertranslator.protection import restore_tokens
from tests.pdf_composite_figure_fixtures import make_composite_figure_pdf
from tests.pdf_unit_fixtures import rebind_native_fixture
from tests.test_pdf_qa import PdfQARun, _write_passing_layout_review, _write_review


BODY_KO = "독립적인 관찰은 그림 밖에서 선택 가능한 본문으로 남습니다."
CAPTION_KO = "그림 7. 구리 용기와 신호 저장실."


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def _publication_case(root: Path) -> tuple[PdfQARun, dict[str, Translation]]:
    """TEST ONLY literal translations/visual decisions, never auto-approval."""
    run = root / ".supertranslator" / "runs" / "합성 그림 with spaces"
    output = root / "translated-pdfs" / run.name
    run.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    fixture = make_composite_figure_pdf(root / "합성 source with spaces.pdf")
    for args in (("pdf-acquire", str(fixture.source)), ("pdf-extract",), ("plan-zones",)):
        assert main([*args, "--run-dir", str(run)]) == 0
    _write_json(run / "glossary.json", {})
    (run / "document-summary.txt").write_text("TEST ONLY synthetic vessel artwork", encoding="utf-8")
    assert main(["prepare-assignments", "--run-dir", str(run)]) == 0
    targets = [segment for segment in read_segments(run / "segments.jsonl") if segment.target]
    # Literal source-to-translation decisions, not an artwork/prose classifier.
    decisions = {fixture.body_text: BODY_KO, fixture.caption_text: CAPTION_KO}
    assert len(targets) == 2
    assert {restore_tokens(segment.source_text, segment.protected) for segment in targets} == set(decisions)
    translations = {}
    for segment in targets:
        text = decisions[restore_tokens(segment.source_text, segment.protected)]
        for token in segment.protected:
            assert text.count(token.value) == 1
            text = text.replace(token.value, token.token, 1)
        translations[segment.id] = Translation(segment.id, text, "TEST ONLY", {})
    (run / "translations").mkdir()
    (run / "translations/zone-001.jsonl").write_text(
        "".join(json.dumps(value.to_dict(), ensure_ascii=False) + "\n"
                for value in translations.values()), encoding="utf-8",
    )
    write_pdf_figure_review_input(run)
    _write_review(run)  # TEST ONLY fixed master decisions from existing QA helper.
    inventory_bytes = (run / "figure-text-input.json").read_bytes()
    inventory = json.loads(inventory_bytes)
    assert len(inventory["figures"]) == 1
    figure = inventory["figures"][0]
    # Hand-declared visual roles; retrieve exact source indexes from the native inventory.
    label_lines = (
        ("The copper vessel sends a measured pulse",
         "TEST ONLY upper in-frame vessel annotation next to the blue chamber artwork."),
        ("while a second chamber stores the returning signal.",
         "TEST ONLY lower in-frame signal-chamber annotation, not independent body or caption."),
    )
    groups = []
    remaining = list(figure["characters"])
    for text, reason in label_lines:
        expected = text.replace(" ", "")
        characters, remaining = remaining[:len(expected)], remaining[len(expected):]
        assert "".join(char["text"] for char in characters) == expected
        groups.append({"character_indexes": [char["index"] for char in characters],
                       "text": expected, "reason": reason})
    assert not remaining
    master_path = run / "review.json"
    master = json.loads(master_path.read_bytes())
    master["figure_text_review"] = {
        "schema_version": "1.0",
        "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "figures": {figure["block_id"]: {
            "verdict": "pass", "labels": groups,
            "evidence": "TEST ONLY inspected blue chamber, connector and two in-frame annotations; independent body above and Figure 7 caption below are translation targets.",
        }},
    }
    _write_json(master_path, master)
    return PdfQARun(run, output), translations


def _mutate_evidence(run: Path, mutation: str) -> None:
    master_path = run / "review.json"
    inventory_path = run / "figure-text-input.json"
    master = json.loads(master_path.read_bytes())
    inventory = json.loads(inventory_path.read_bytes())
    figure = inventory["figures"][0]
    approval = master["figure_text_review"]["figures"][figure["block_id"]]
    if mutation == "missing-inventory":
        inventory_path.unlink()
    elif mutation == "missing-review":
        master.pop("figure_text_review")
    elif mutation == "stale-inventory":
        master["figure_text_review"]["inventory_sha256"] = "f" * 64
    elif mutation == "stale-source":
        path = run / "source.pdf"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "stale-media":
        document = PdfDocument.from_dict(json.loads((run / "document.json").read_bytes()))
        block = next(block for block in document.blocks if block.id == figure["block_id"])
        path = run / block.media_path
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "foreign-index":
        with pdfplumber.open(run / "source.pdf") as pdf:
            source_chars = pdf.pages[0].chars
            owned = {char["index"] for char in figure["characters"]}
            foreign = next(index for index, char in enumerate(source_chars)
                           if index not in owned and char["text"].strip())
        label = approval["labels"][0]
        label["character_indexes"] = sorted([*label["character_indexes"], foreign])
        label["text"] = "".join(pdf_char["text"] for index, pdf_char in
                                 enumerate(source_chars) if index in label["character_indexes"])
    elif mutation == "omitted-character":
        label = approval["labels"][0]
        label["character_indexes"] = label["character_indexes"][1:]
        label["text"] = label["text"][1:]
    elif mutation == "required-fix":
        approval["verdict"] = "required-fix"
    elif mutation in {"body-overlap", "caption-overlap"}:
        document_path = run / "document.json"
        document = json.loads(document_path.read_bytes())
        kind = "paragraph" if mutation == "body-overlap" else "caption"
        block = next(block for block in document["blocks"] if block["kind"] == kind)
        block["bbox"] = figure["bbox"]
        _write_json(document_path, document)
        rebind_native_fixture(run)
        inventory["document_sha256"] = hashlib.sha256(document_path.read_bytes()).hexdigest()
        payload = canonical_figure_text_input_bytes(inventory)
        inventory_path.write_bytes(payload)
        master["figure_text_review"]["inventory_sha256"] = hashlib.sha256(payload).hexdigest()
    else:
        raise AssertionError(mutation)
    # Rebind outer semantic approval so independent inner checks must still refuse.
    if mutation != "missing-inventory":
        master["semantic_input_sha256"] = build_pdf_semantic_review_input(run).semantic_input_sha256
    _write_json(master_path, master)


def _publication_evidence(run: Path) -> dict[str, bytes | None]:
    """Snapshot exact staging/QA names and bytes, including absent evidence."""
    names = ("staged-output", "layout.json", "pdf-qa.json", "qa-pages", "pdf-layout-review.json")
    result: dict[str, bytes | None] = {}
    for name in names:
        path = run / name
        result[name] = path.read_bytes() if path.is_file() else None
        if path.is_dir():
            result[name + "/"] = None
            for child in path.rglob("*"):
                result[child.relative_to(run).as_posix()] = child.read_bytes() if child.is_file() else None
    return result


# Catches bypassing exact inventory/source/media/label checks at any publication gate.
@pytest.mark.parametrize("stage", ["assembly", "prepare", "finalize"])
@pytest.mark.parametrize("mutation", [
    "missing-inventory", "missing-review", "stale-inventory", "stale-source", "stale-media",
    "foreign-index", "omitted-character", "required-fix", "body-overlap", "caption-overlap",
])
def test_composite_publication_requires_exact_current_approval(tmp_path: Path, stage: str, mutation: str) -> None:
    run, translations = _publication_case(tmp_path)
    if stage != "assembly":
        assemble_pdf(run.run_dir, translations, {}, run.output_dir)
        prepare_pdf_qa(run.run_dir, run.output_dir)
        _write_passing_layout_review(run.run_dir)  # TEST ONLY fixed visual decisions.
    retained = _publication_evidence(run.run_dir)
    _mutate_evidence(run.run_dir, mutation)
    error = PdfAssemblyError if stage == "assembly" else PdfQAFailure
    with pytest.raises(error):
        if stage == "assembly":
            assemble_pdf(run.run_dir, translations, {}, run.output_dir)
        else:
            (prepare_pdf_qa if stage == "prepare" else finalize_pdf_output)(run.run_dir, run.output_dir)
    assert not run.output_dir.exists()
    assert _publication_evidence(run.run_dir) == retained


# Catches dropping original artwork, rasterizing external text or rejecting exact approval.
def test_composite_exact_explicit_approval_reaches_prepared_qa(tmp_path: Path) -> None:
    run, translations = _publication_case(tmp_path)
    document = PdfDocument.from_dict(json.loads((run.run_dir / "document.json").read_bytes()))
    figure = next(block for block in document.blocks if block.kind == "figure")
    inventory_bytes = (run.run_dir / "figure-text-input.json").read_bytes()
    approval_bytes = (run.run_dir / "review.json").read_bytes()
    staged = assemble_pdf(run.run_dir, translations, {}, run.output_dir)
    result = prepare_pdf_qa(run.run_dir, run.output_dir)
    assert result.passed
    assert not run.output_dir.exists()
    finding = next(item for item in result.findings if item.code == "publication.text_image_separation")
    assert "inventory_sha256=" + hashlib.sha256(inventory_bytes).hexdigest() in finding.evidence
    assert "review_sha256=" + hashlib.sha256(approval_bytes).hexdigest() in finding.evidence
    reader = PdfReader(staged)
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert text.count(BODY_KO) == text.count(CAPTION_KO) == 1
    assert "The copper vessel" not in text  # Intrinsic annotations remain only in artwork.
    images = [image.image.convert("RGB") for page in reader.pages for image in page.images]
    assert len(images) == 1
    with Image.open(run.run_dir / figure.media_path) as source:
        assert images[0].size == source.size
        assert images[0].tobytes() == source.convert("RGB").tobytes()


# Catches native CI silently leaving the new ownership/publication contracts unselected.
def test_native_workflow_selects_composite_modules() -> None:
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/pdf-cross-platform.yml").read_text(encoding="utf-8")
    # Parse the workflow's folded pytest command into actual argument selectors.
    command = re.search(r"^      - run: >-\n((?:          .+\n)+)", workflow, re.MULTILINE)
    assert command is not None
    argv = shlex.split(" ".join(line.strip() for line in command[1].splitlines()))
    assert argv[:3] == ["python", "-m", "pytest"]
    selectors = {arg for arg in argv[3:] if not arg.startswith("-")}
    required = {
        "tests/test_pdf_caption_evidence.py", "tests/test_pdf_composite_figures.py",
        "tests/test_pdf_composite_figure_pipeline.py",
        "tests/test_pdf_pipeline.py", "tests/test_plugin_layout.py", "tests/test_renamed_identity.py",
        "tests/test_pdf_utf8_fixtures.py", "tests/test_poppler_bootstrap.py",
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
    assert required <= selectors, f"native PDF job misses selectors: {sorted(required - selectors)}"
    matrix = re.search(r"^        os: (\[.+\])$", workflow, re.MULTILINE)
    assert matrix is not None
    assert {item.strip() for item in matrix[1][1:-1].split(",")} == {"macos-15", "windows-2025"}
    assert "    runs-on: ${{ matrix.os }}" in workflow
