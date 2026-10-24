"""Deterministic command-line orchestration for translation runs."""

from __future__ import annotations

import argparse
import base64
import binascii
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from typing import Any
from urllib.parse import unquote_to_bytes

from langdetect import DetectorFactory, PROFILES_DIRECTORY
from langdetect.lang_detect_exception import LangDetectException

from supertranslator import __version__
from supertranslator.assemble import AssemblyError, assemble_page
from supertranslator.assets import atomic_write
from supertranslator.capture import MAX_DATA_CSS_BYTES, CaptureError, capture_page
from supertranslator.extract import ExtractionError, extract_segments
from supertranslator.models import (
    MasterReview,
    ManifestAsset,
    ManifestProvenance,
    QAInputs,
    QAResult,
    Segment,
    SegmentContractError,
    SemanticReviewFinding,
    Translation,
    read_segments,
    read_segments_stream,
)
from supertranslator.paths import hold_allocated_run_paths, validate_public_url
from supertranslator.pdf_acquire import PdfAcquireError, acquire_pdf
from supertranslator.pdf_assemble import PdfAssemblyError, assemble_pdf
from supertranslator.pdf_extract import PdfExtractionError, extract_pdf
from supertranslator.pdf_extract_transaction import extract_pdf_transaction
from supertranslator.pdf_figure_review import PdfFigureReviewError, write_pdf_figure_review_input
from supertranslator.pdf_models import PdfContractError, PdfSourceRecord
from supertranslator.pdf_qa import PdfQAFailure, finalize_pdf_output, prepare_pdf_qa
from supertranslator.pdf_review import (
    PdfSemanticReviewError,
    build_pdf_semantic_review_input,
    hold_pdf_semantic_inputs,
    validate_pdf_semantic_review,
    validate_pdf_semantic_review_snapshot,
)
from supertranslator.pdf_unit_bindings import (
    PDF_UNIT_BINDING_NAME, PdfUnitBindingError, _hold_pdf_unit_inputs,
    _publish_pdf_unit_assignments, hold_pdf_unit_binding, require_assignable_pdf,
)
from supertranslator.pdf_units import require_pdf_unit_budget
from supertranslator.qa import run_qa, _has_preformatted_state, _hold_preformatted_output, _prepare_preformatted_screenshots
from supertranslator.report import write_manifest, write_review_report, render_manifest, render_review_report
from supertranslator.preformatted_runtime import (
    prepare_preformatted_run, materialize_preformatted_run, extract_preformatted_run,
    hold_processing_source, verify_preformatted_output,
)
from supertranslator.translations import TranslationContractError, merge_translations
from supertranslator.zones import (
    MAX_TARGET_ZONES,
    Zone,
    ZoneContractError,
    build_zones,
)


EXIT_INVALID_ARGUMENTS = 2
EXIT_CAPTURE_FAILURE = 3
EXIT_CONTRACT_FAILURE = 4
EXIT_ASSEMBLY_FAILURE = 5
EXIT_QA_FAILURE = 6
_REPARSE_POINT = 0x400
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_UTC_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_CAPTURE_FIELDS = {
    "asset_map",
    "captured_at",
    "critical_assets",
    "final_url",
    "fingerprints",
    "missing_optional_assets",
    "optional_assets",
    "requested_url",
}
_REVIEW_DIMENSIONS = (
    "semantic_fidelity",
    "qualification_preservation",
    "naturalness",
    "terminology",
    "boundary_consistency",
    "protected_content",
)
_REVIEW_FINDING_FIELDS = {"dimension", "verdict", "evidence"}
_TARGET_LANGUAGE = "ko"
_TERMINOLOGY_POLICY_ID = "english-technical-first-use-ko-gloss"
_TERMINOLOGY_POLICY_VERSION = "1.0"


class CLIContractError(ValueError):
    """A documented run file is missing, malformed, or inconsistent."""


class InvalidArgumentsError(ValueError):
    """A command argument passed parsing but violates its public contract."""


class QAFailure(RuntimeError):
    """QA completed and wrote evidence, but required checks failed."""


Handler = Callable[[argparse.Namespace], None]


class _CommandArgumentParser(argparse.ArgumentParser):
    """Keep subcommand help human-readable without polluting status stdout."""

    def print_help(self, file: Any = None) -> None:
        super().print_help(file=sys.stderr if file is None else file)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicit pipeline command and return its stable exit code."""
    arguments = list(argv) if argv is not None else sys.argv[1:]
    command_hint = arguments[0] if arguments and not arguments[0].startswith("-") else "cli"
    parser = _build_parser()
    try:
        namespace = parser.parse_args(arguments)
    except SystemExit as error:
        code = int(error.code)
        if code:
            _emit_status(command_hint, "error", EXIT_INVALID_ARGUMENTS)
            return EXIT_INVALID_ARGUMENTS
        if command_hint != "cli":
            _emit_status(command_hint, "ok", 0)
        return 0

    command = str(namespace.command)
    handler: Handler = namespace.handler
    try:
        with _hold_command_run_contract(namespace) as run_contract:
            handler(namespace)
            try:
                run_contract.verify()
            except ValueError as error:
                raise CLIContractError(str(error)) from error
    except InvalidArgumentsError as error:
        return _fail(command, EXIT_INVALID_ARGUMENTS, error)
    except (CaptureError, PdfAcquireError) as error:
        return _fail(command, EXIT_CAPTURE_FAILURE, error)
    except (CLIContractError, PdfExtractionError, TranslationContractError) as error:
        return _fail(command, EXIT_CONTRACT_FAILURE, error)
    except (AssemblyError, PdfAssemblyError) as error:
        return _fail(command, EXIT_ASSEMBLY_FAILURE, error)
    except (QAFailure, PdfQAFailure) as error:
        return _fail(command, EXIT_QA_FAILURE, error)

    _emit_status(command, "ok", 0)
    return 0


@contextmanager
def _hold_command_run_contract(args: argparse.Namespace) -> Iterator[object]:
    """Retain the allocator's exact workspace, run, and output-root identities."""
    run_dir = Path(os.path.abspath(os.fspath(args.run_dir)))
    try:
        workspace = run_dir.parents[2]
    except IndexError as error:
        raise CLIContractError(
            "run directory is not an exact allocator child"
        ) from error
    output_root = _command_output_root(args, run_dir)
    output_dir = Path(
        os.path.abspath(
            os.fspath(
                getattr(args, "output_dir", workspace / output_root / run_dir.name)
            )
        )
    )
    yield_started = False
    try:
        with hold_allocated_run_paths(
            workspace,
            run_dir,
            output_dir,
            output_root=output_root,
        ) as contract:
            yield_started = True
            with _hold_command_pdf_units(args, contract.run):
                yield contract
    except ValueError as error:
        if yield_started:
            raise
        raise CLIContractError(str(error)) from error


def _command_output_root(args: argparse.Namespace, run_dir: Path) -> str:
    command = str(args.command)
    if command in {"pdf-acquire", "pdf-extract", "pdf-review-input", "pdf-figure-review-input", "pdf-assemble", "pdf-qa"}:
        return "translated-pdfs"
    if command in {"capture", "prepare-preformatted", "materialize-preformatted", "extract", "assemble", "qa"}:
        return "translated-pages"
    # Shared stages run only after acquisition/capture. The exact source marker is
    # checked again by the stage while the run root remains held.
    return "translated-pdfs" if (run_dir / "source.json").exists() or (run_dir / "source.pdf").is_file() else "translated-pages"


@contextmanager
def _hold_command_pdf_units(args: argparse.Namespace, run_anchor: Any) -> Iterator[None]:
    """Use the validated source record, never a filename extension, for shared stages."""
    import supertranslator.pdf_assemble as anchored
    args._pdf_unit_inputs = None
    if args.command not in {"plan-zones", "prepare-assignments", "validate-translations"}:
        yield
        return
    names = anchored._anchored_directory_names(run_anchor)
    if "source.json" not in names:
        if "source.pdf" in names:
            raise CLIContractError("PDF source record is missing")
        yield
        return
    directories = () if args.command == "plan-zones" else ("zones",)
    try:
        with ExitStack() as stack:
            inputs = stack.enter_context(_hold_pdf_unit_inputs(run_anchor, directories))
            require_assignable_pdf(inputs.document)
            args._pdf_unit_inputs = inputs
            if args.command == "validate-translations":
                stack.enter_context(hold_pdf_unit_binding(run_anchor))
            yield
    except (PdfUnitBindingError, PdfContractError) as error:
        raise CLIContractError(str(error)) from error


def console_main() -> None:
    """Expose :func:`main` as a console-script entry point."""
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="supertranslator")
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=_CommandArgumentParser
    )

    capture = subparsers.add_parser("capture", help="Capture a public web page.")
    capture.add_argument("url")
    _add_run_dir(capture)
    capture.set_defaults(handler=_capture_command)

    for name, handler, help_text in (
        ('prepare-preformatted', _prepare_preformatted_command, 'Inventory preformatted source for explicit review.'),
        ('materialize-preformatted', _materialize_preformatted_command, 'Materialize a source-bound reviewed projection.'),
    ):
        command = subparsers.add_parser(name, help=help_text)
        _add_run_dir(command)
        command.set_defaults(handler=handler)

    pdf_acquire = subparsers.add_parser(
        "pdf-acquire", help="Acquire one local or public PDF."
    )
    pdf_acquire.add_argument("source")
    _add_run_dir(pdf_acquire)
    pdf_acquire.set_defaults(handler=_pdf_acquire_command)

    pdf_extract = subparsers.add_parser(
        "pdf-extract", help="Extract PDF logical blocks and translation segments."
    )
    _add_run_dir(pdf_extract)
    pdf_extract.set_defaults(handler=_pdf_extract_command)

    pdf_review_input = subparsers.add_parser(
        "pdf-review-input",
        help="Bind the finalized PDF semantic-review inputs to one digest.",
    )
    _add_run_dir(pdf_review_input)
    pdf_review_input.set_defaults(handler=_pdf_review_input_command)

    figure_review_input = subparsers.add_parser(
        "pdf-figure-review-input", help="Inventory exact source glyphs for artwork label review."
    )
    _add_run_dir(figure_review_input)
    figure_review_input.set_defaults(handler=_pdf_figure_review_input_command)

    extract = subparsers.add_parser("extract", help="Extract translation segments.")
    _add_run_dir(extract)
    extract.set_defaults(handler=_extract_command)

    plan = subparsers.add_parser("plan-zones", help="Create translation zones.")
    _add_run_dir(plan)
    plan.add_argument("--max-chars", type=int, default=12_000)
    plan.add_argument("--target-zones", type=int)
    plan.set_defaults(handler=_plan_zones_command)

    assignments = subparsers.add_parser(
        "prepare-assignments", help="Build immutable translator assignment packages."
    )
    _add_run_dir(assignments)
    assignments.set_defaults(handler=_prepare_assignments_command)

    validate = subparsers.add_parser(
        "validate-translations", help="Validate reviewed zone results."
    )
    _add_run_dir(validate)
    validate.add_argument("--zone-id")
    validate.set_defaults(handler=_validate_translations_command)

    assemble = subparsers.add_parser("assemble", help="Assemble the offline page.")
    _add_run_dir(assemble)
    _add_output_dir(assemble)
    assemble.set_defaults(handler=_assemble_command)

    pdf_assemble = subparsers.add_parser(
        "pdf-assemble", help="Assemble a reviewed PDF into private staging."
    )
    _add_run_dir(pdf_assemble)
    _add_output_dir(pdf_assemble)
    pdf_assemble.set_defaults(handler=_pdf_assemble_command)

    pdf_qa = subparsers.add_parser(
        "pdf-qa", help="Prepare or finalize rendered PDF QA evidence."
    )
    pdf_qa_actions = pdf_qa.add_subparsers(
        dest="pdf_qa_action", required=True, parser_class=_CommandArgumentParser
    )
    pdf_qa_prepare = pdf_qa_actions.add_parser("prepare")
    _add_run_dir(pdf_qa_prepare)
    _add_output_dir(pdf_qa_prepare)
    pdf_qa_prepare.set_defaults(handler=_pdf_qa_prepare_command)
    pdf_qa_finalize = pdf_qa_actions.add_parser("finalize")
    _add_run_dir(pdf_qa_finalize)
    _add_output_dir(pdf_qa_finalize)
    pdf_qa_finalize.set_defaults(handler=_pdf_qa_finalize_command)

    qa = subparsers.add_parser("qa", help="Run deterministic and browser QA.")
    _add_run_dir(qa)
    _add_output_dir(qa)
    qa.set_defaults(handler=_qa_command)
    return parser


def _add_run_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", required=True, type=Path)


def _add_output_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", required=True, type=Path)


def _capture_command(args: argparse.Namespace) -> None:
    try:
        url = str(validate_public_url(args.url))
    except (TypeError, ValueError) as error:
        raise InvalidArgumentsError(str(error)) from error
    try:
        _validate_run_root(args.run_dir)
        if args.run_dir.exists() and any(args.run_dir.iterdir()):
            raise CLIContractError(
                f"capture run directory must be empty: {args.run_dir}"
            )
        _reject_if_link(args.run_dir / "source.html")
        _reject_if_link(args.run_dir / "capture.json")
    except (CLIContractError, OSError) as error:
        raise CaptureError(str(error)) from error
    result = capture_page(url, args.run_dir)
    payload = {
        "asset_map": result.asset_map,
        "captured_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "critical_assets": result.critical_assets,
        "final_url": result.final_url,
        "fingerprints": result.fingerprints,
        "missing_optional_assets": result.missing_optional_assets,
        "optional_assets": result.optional_assets,
        "requested_url": result.requested_url,
    }
    try:
        _write_json_atomic(args.run_dir / "capture.json", payload)
    except OSError as error:
        raise CaptureError(f"cannot write capture metadata: {error}") from error


def _pdf_acquire_command(args: argparse.Namespace) -> None:
    def write_metadata(record: PdfSourceRecord, path: Path) -> None:
        _write_json_atomic(path, record.to_dict())

    try:
        acquire_pdf(
            str(args.source),
            args.run_dir,
            metadata_writer=write_metadata,
        )
    except (CLIContractError, OSError) as error:
        raise PdfAcquireError(str(error)) from error


def _pdf_extract_command(args: argparse.Namespace) -> None:
    try:
        extract_pdf_transaction(Path(args.run_dir), extractor=extract_pdf)
    except PdfExtractionError:
        raise
    except (CLIContractError, OSError, UnicodeError) as error:
        raise CLIContractError(f"cannot extract PDF source: {error}") from error


def _pdf_figure_review_input_command(args: argparse.Namespace) -> None:
    _validate_run_root(Path(args.run_dir))
    try:
        write_pdf_figure_review_input(Path(args.run_dir))
    except PdfFigureReviewError as error:
        raise CLIContractError(str(error)) from error


def _pdf_review_input_command(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    _validate_run_root(run_dir)
    destination = run_dir / "semantic-review-input.json"
    _reject_if_link(destination)
    try:
        semantic_input = build_pdf_semantic_review_input(run_dir)
        _write_json_atomic(destination, semantic_input.to_dict())
    except PdfSemanticReviewError as error:
        raise CLIContractError(str(error)) from error
    except OSError as error:
        raise CLIContractError(
            f"cannot write PDF semantic review input: {error}"
        ) from error


def _prepare_preformatted_command(args: argparse.Namespace) -> None:
    try:
        prepare_preformatted_run(args.run_dir)
    except (ValueError, OSError) as error:
        raise CLIContractError(str(error)) from error


def _materialize_preformatted_command(args: argparse.Namespace) -> None:
    try:
        materialize_preformatted_run(args.run_dir)
    except (ValueError, OSError) as error:
        raise CLIContractError(str(error)) from error


def _extract_command(args: argparse.Namespace) -> None:
    _validate_run_root(args.run_dir)
    try:
        # Selection is immutable; extraction intentionally changes its own outputs.
        # Each transaction owns that mutation, not an expired selector lease.
        with hold_processing_source(args.run_dir, phase='extract') as source:
            preformatted = source.normalization is not None
            source.verify()
        if preformatted:
            extract_preformatted_run(args.run_dir)
        else:
            _extract_legacy_command(args)
        with hold_processing_source(args.run_dir, phase='extract') as source:
            source.verify()
    except (ValueError, ExtractionError, OSError) as error:
        raise CLIContractError(f'cannot extract captured source: {error}') from error


def _extract_legacy_command(args: argparse.Namespace) -> None:
    try:
        _validate_run_root(args.run_dir)
        source = args.run_dir / "source.html"
        segments = args.run_dir / "segments.jsonl"
        capture_path = args.run_dir / "capture.json"
        _require_safe_file(source)
        if segments.exists():
            _require_safe_file(segments)
            original_segments: bytes | None = segments.read_bytes()
        else:
            _reject_if_link(segments)
            original_segments = None
        capture = _read_capture(args.run_dir)
        original_source = source.read_bytes()
        original_capture = capture_path.read_bytes()
        with tempfile.TemporaryDirectory(
            prefix=".extracting-", dir=args.run_dir
        ) as temporary_name:
            temporary = Path(temporary_name)
            temporary_source = temporary / "source.html"
            temporary_segments = temporary / "segments.jsonl"
            temporary_source.write_bytes(source.read_bytes())
            extract_segments(temporary_source, temporary_segments)
            capture["fingerprints"]["source.html"] = _sha256_file(
                temporary_source
            )
            try:
                os.replace(temporary_source, source)
                os.replace(temporary_segments, segments)
                _replace_json_atomic(capture_path, capture)
            except BaseException as publish_error:
                try:
                    _replace_bytes_atomic(source, original_source)
                    if original_segments is None:
                        segments.unlink(missing_ok=True)
                    else:
                        _replace_bytes_atomic(segments, original_segments)
                    _replace_bytes_atomic(capture_path, original_capture)
                except OSError as rollback_error:
                    raise CLIContractError(
                        "extraction publication and rollback both failed: "
                        f"publish={publish_error}; rollback={rollback_error}"
                    ) from publish_error
                raise
    except (CLIContractError, ExtractionError, OSError) as error:
        raise CLIContractError(f"cannot extract captured source: {error}") from error


def _plan_zones_command(args: argparse.Namespace) -> None:
    if args.max_chars <= 0:
        raise InvalidArgumentsError("max-chars must be a positive integer")
    if args.target_zones is not None and not 1 <= args.target_zones <= MAX_TARGET_ZONES:
        raise InvalidArgumentsError(
            f"target-zones must be from 1 through {MAX_TARGET_ZONES}"
        )
    _validate_run_root(args.run_dir)
    inputs = args._pdf_unit_inputs
    segments = _read_segments(args.run_dir, inputs)
    try:
        if inputs is not None:
            require_pdf_unit_budget(inputs.document, segments, args.max_chars)
        zones = build_zones(
            segments,
            max_chars=args.max_chars,
            target_zones=args.target_zones,
        )
    except (ZoneContractError, PdfContractError) as error:
        raise CLIContractError(str(error)) from error
    zone_dir = args.run_dir / "zones"
    if zone_dir.exists():
        raise CLIContractError(f"zone directory already exists: {zone_dir}")
    try:
        if inputs is not None:
            inputs.verify()
        zone_dir.mkdir(parents=False)
        for zone in zones:
            _write_json_atomic(zone_dir / f"{zone.id}.json", _zone_payload(zone))
    except OSError as error:
        raise CLIContractError(f"cannot write zone assignments: {error}") from error


def _validate_translations_command(args: argparse.Namespace) -> None:
    _validate_run_root(args.run_dir)
    segments = _read_segments(args.run_dir, args._pdf_unit_inputs)
    zones = _read_zones(args.run_dir, args._pdf_unit_inputs)
    if args.zone_id is not None:
        matches = [zone for zone in zones if zone.id == args.zone_id]
        if len(matches) != 1:
            raise CLIContractError(f"unknown zone ID: {args.zone_id}")
        zone = matches[0]
        result_dir = _validate_partial_translation_files(args.run_dir, zones, zone)
        target_ids = set(zone.target_ids)
        merge_translations(
            [segment for segment in segments if segment.id in target_ids],
            [zone],
            result_dir,
        )
        return
    result_dir = _validate_translation_files(args.run_dir, zones)
    merge_translations(segments, zones, result_dir)


def _prepare_assignments_command(args: argparse.Namespace) -> None:
    _validate_run_root(args.run_dir)
    inputs = args._pdf_unit_inputs
    segments = _read_segments(args.run_dir, inputs)
    zones = _read_zones(args.run_dir, inputs)
    glossary = _read_glossary(args.run_dir / "glossary.json")
    summary_path = args.run_dir / "document-summary.txt"
    try:
        _require_safe_file(summary_path)
        summary = summary_path.read_text(encoding="utf-8").strip()
    except (CLIContractError, OSError, UnicodeError) as error:
        raise CLIContractError(f"cannot read document summary {summary_path}: {error}") from error
    if not summary or len(summary) > 4_000:
        raise CLIContractError(
            "document summary must contain from 1 through 4000 characters"
        )

    by_id = {segment.id: segment for segment in segments}
    if len(by_id) != len(segments):
        raise CLIContractError("assignment source contains duplicate segment IDs")
    assigned = [segment_id for zone in zones for segment_id in zone.target_ids]
    expected = [segment.id for segment in segments if segment.target]
    if assigned != expected or len(assigned) != len(set(assigned)):
        raise CLIContractError(
            "assignment zones must exactly partition source targets in order"
        )

    destination = args.run_dir / "assignments"
    if destination.exists() or destination.is_symlink():
        raise CLIContractError(f"assignment directory already exists: {destination}")
    _reject_if_link(destination)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".assignments-", dir=args.run_dir
        ) as temporary_name:
            temporary = Path(temporary_name) / "assignments"
            temporary.mkdir()
            for zone in zones:
                if set(zone.target_ids) & set(
                    zone.context_before_ids + zone.context_after_ids
                ):
                    raise CLIContractError(
                        f"assignment context overlaps targets: {zone.id}"
                    )
                payload = {
                    "context_after": _assignment_records(
                        zone.context_after_ids, by_id, zone.id
                    ),
                    "context_before": _assignment_records(
                        zone.context_before_ids, by_id, zone.id
                    ),
                    "document_summary": summary,
                    "glossary": glossary,
                    "schema_version": "1.0",
                    "targets": _assignment_records(zone.target_ids, by_id, zone.id),
                    "zone_id": zone.id,
                }
                _write_json_atomic(temporary / f"{zone.id}.json", payload)
            if inputs is not None:
                with _publish_pdf_unit_assignments(inputs, temporary) as binding:
                    _write_json_atomic(temporary / PDF_UNIT_BINDING_NAME, binding.to_dict())
            else:
                os.replace(temporary, destination)
    except CLIContractError:
        raise
    except OSError as error:
        raise CLIContractError(f"cannot publish assignment packages: {error}") from error


def _assignment_records(
    segment_ids: Sequence[str], by_id: Mapping[str, Segment], zone_id: str
) -> list[dict[str, Any]]:
    if len(segment_ids) != len(set(segment_ids)):
        raise CLIContractError(f"assignment contains duplicate segment IDs: {zone_id}")
    missing = [segment_id for segment_id in segment_ids if segment_id not in by_id]
    if missing:
        raise CLIContractError(
            f"assignment references missing segments in {zone_id}: {', '.join(missing)}"
        )
    records: list[dict[str, Any]] = []
    for segment_id in segment_ids:
        segment = by_id[segment_id]
        records.append(
            {
                "heading_path": segment.heading_path,
                "id": segment.id,
                "protected": [token.to_dict() for token in segment.protected],
                "semantic_type": segment.semantic_type,
                "source_text": segment.source_text,
            }
        )
    return records


def _assemble_command(args: argparse.Namespace) -> None:
    _validate_run_root(args.run_dir)
    # Retain the legacy capture-contract diagnostic before the stricter lease.
    _read_capture(args.run_dir)
    try:
        with hold_processing_source(args.run_dir, phase='assemble') as source:
            _assemble_selected_command(args, source)
            source.verify()
    except ValueError as error:
        raise CLIContractError(str(error)) from error


def _assemble_selected_command(args: argparse.Namespace, source) -> None:
    _validate_run_root(args.run_dir)
    capture = _read_capture(args.run_dir)
    segments = _read_segments(args.run_dir)
    if source.normalization is not None and not any(segment.target for segment in segments):
        raise CLIContractError('preformatted extraction has no translation targets')
    zones = _read_zones(args.run_dir)
    result_dir = _validate_translation_files(args.run_dir, zones)
    translations = merge_translations(segments, zones, result_dir)
    glossary = _read_glossary(args.run_dir / "glossary.json")
    source.verify()
    assemble_page(
        source.path,
        {segment.id: segment for segment in segments if segment.target},
        translations,
        glossary,
        args.output_dir,
        capture["final_url"],
    )
    source.verify()
    if source.normalization is not None:
        try:
            with _hold_preformatted_output(source, args.output_dir / 'index.html') as output:
                output.verify()
        except (ValueError, PdfAssemblyError, OSError) as error:
            raise AssemblyError(str(error)) from error


def _pdf_assemble_command(args: argparse.Namespace) -> None:
    _validate_run_root(args.run_dir)
    try:
        with hold_pdf_semantic_inputs(args.run_dir) as snapshot:
            segments, zones, translations, glossary = _semantic_snapshot_values(snapshot)
            review = _read_pdf_review(
                args.run_dir / "review.json", zones, semantic_snapshot=snapshot
            )
            if review.unresolved_required:
                raise PdfAssemblyError(
                    "semantic review has unresolved required findings: "
                    + ", ".join(review.unresolved_required)
                )
            assemble_pdf(
                args.run_dir,
                translations,
                glossary,
                args.output_dir,
                semantic_snapshot=snapshot,
            )
            snapshot.verify()
    except PdfSemanticReviewError as error:
        raise PdfAssemblyError(str(error)) from error


def _pdf_qa_prepare_command(args: argparse.Namespace) -> None:
    prepare_pdf_qa(args.run_dir, args.output_dir)


def _pdf_qa_finalize_command(args: argparse.Namespace) -> None:
    finalize_pdf_output(args.run_dir, args.output_dir)


def _qa_command(args: argparse.Namespace) -> None:
    preformatted = _has_preformatted_state(args.run_dir)
    try:
        if preformatted:
            with _preformatted_qa_evidence(args.output_dir) as transaction:
                _prepare_preformatted_screenshots(args.run_dir, args.run_dir / 'qa-screenshots')
                with hold_processing_source(args.run_dir, phase='qa') as source:
                    with _hold_preformatted_output(source, args.output_dir / 'index.html') as output:
                        _qa_selected_command(args, source, transaction, output.verify)
                        output.verify()
        else:
            try:
                _prepare_preformatted_screenshots(args.run_dir, args.run_dir / 'qa-screenshots')
            except (ValueError, PdfAssemblyError, OSError) as error:
                raise QAFailure(f'screenshot-directory-unsafe: {error}') from error
            with hold_processing_source(args.run_dir, phase='qa') as source:
                if source.normalization is not None:
                    # The released inventory is only a routing hint. A new
                    # normalized source cannot enter legacy publication.
                    preformatted = True
                    with _preformatted_qa_evidence(args.output_dir):
                        raise ValueError('preformatted state appeared after QA inventory')
                _qa_selected_command(args, source)
    except (ValueError, PdfAssemblyError, OSError) as error:
        failure = error
    else:
        return
    if not preformatted and _has_preformatted_state(args.run_dir):
        # New pending/invalid state may fail before the selector can yield.
        # Quarantine prior evidence too, outside the active exception handler
        # so recovery creation retains its normal anchored lifecycle.
        preformatted = True
        try:
            with _preformatted_qa_evidence(args.output_dir):
                raise failure
        except (ValueError, PdfAssemblyError, OSError) as error:
            failure = error
    if preformatted:
        code = 'preformatted-literal-integrity' if str(failure).startswith('preformatted-literal-integrity:') else 'preformatted-provenance'
        raise QAFailure(f'{code}: {failure}') from failure
    raise CLIContractError(str(failure)) from failure


def _qa_selected_command(args, source, transaction=None, revalidate=None) -> None:
    _validate_run_root(args.run_dir)
    _reject_if_link(args.run_dir / "source.html")
    try:
        _validate_qa_output_path(args.output_dir)
    except CLIContractError as error:
        raise QAFailure(str(error)) from error
    capture = _read_capture(args.run_dir)
    segments = _read_segments(args.run_dir)
    if source.normalization is not None and not any(segment.target for segment in segments):
        raise QAFailure('translation-coverage: preformatted extraction has no translation targets')
    zones = _read_zones(args.run_dir)
    result_dir = _validate_translation_files(args.run_dir, zones)
    translations = merge_translations(segments, zones, result_dir)
    review = _read_review(args.run_dir / "review.json", zones)
    result = run_qa(
        QAInputs(
            source_html=source.path,
            output_html=args.output_dir / "index.html",
            source_url=capture["final_url"],
            source_segment_ids={segment.id for segment in segments if segment.target},
            translated_segment_ids=set(translations),
            critical_assets=[Path(path) for path in capture["critical_assets"]]
                            + [Path(asset['path']) for asset in source.generated_critical_assets],
            optional_assets=[Path(path) for path in capture["optional_assets"]],
            screenshot_dir=args.run_dir / "qa-screenshots",
            master_review=review,
            protected_tokens={segment.id: segment.protected for segment in segments},
            translated_texts={key: value.text for key, value in translations.items()},
            capture_metadata=dict(capture),
            normalization=source.normalization,
        )
    )
    provenance = _build_manifest_provenance(
        result=result,
        capture=capture,
        segments=segments,
        zones=zones,
        translated_segment_ids=set(translations),
        review=review,
    )
    source.verify()
    if revalidate is not None:
        revalidate()
    if transaction is None:
        _publish_qa_evidence(result, review, args.output_dir, provenance)
    else:
        _publish_qa_evidence(result, review, args.output_dir, provenance, _transaction=transaction)
        revalidate()
        transaction.verify()
    if not result.passed:
        codes = ", ".join(finding.code for finding in result.required_findings)
        raise QAFailure(f"required QA checks failed: {codes or 'unknown finding'}")


def _read_segments(run_dir: Path, unit_inputs: Any = None) -> list[Segment]:
    path = run_dir / "segments.jsonl"
    try:
        if unit_inputs is not None:
            return read_segments_stream(io.StringIO(unit_inputs.payloads["segments.jsonl"].decode("utf-8")))
        _require_safe_file(path)
        return read_segments(path)
    except (CLIContractError, SegmentContractError, OSError, UnicodeError) as error:
        raise CLIContractError(f"cannot read segment manifest {path}: {error}") from error


def _semantic_snapshot_values(
    snapshot: Any,
) -> tuple[list[Segment], list[Zone], dict[str, Translation], dict[str, str]]:
    """Parse every PDF semantic consumer value from held exact bytes."""
    try:
        segments = read_segments_stream(
            io.StringIO(snapshot.payloads["segments.jsonl"].decode("utf-8"))
        )
        glossary_value = json.loads(snapshot.payloads["glossary.json"].decode("utf-8"))
        if not isinstance(glossary_value, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in glossary_value.items()
        ):
            raise CLIContractError("held PDF glossary must map strings to strings")
        zones: list[Zone] = []
        translations: dict[str, Translation] = {}
        for relative, payload in sorted(snapshot.payloads.items()):
            label = Path(relative)
            if relative.startswith("zones/"):
                value = json.loads(payload.decode("utf-8"))
                if not isinstance(value, Mapping):
                    raise CLIContractError(f"held PDF zone must be an object: {relative}")
                zones.append(
                    Zone(
                        id=_string(value, "id", label),
                        heading_path=_string_list(value, "heading_path", label),
                        target_ids=_string_list(value, "target_ids", label),
                        context_before_ids=_string_list(value, "context_before_ids", label),
                        context_after_ids=_string_list(value, "context_after_ids", label),
                        attempt=_integer(value, "attempt", label),
                        expected_tokens=_string_sequence_mapping(
                            value, "expected_tokens", label
                        ),
                    )
                )
            elif relative.startswith("translations/"):
                for line_number, line in enumerate(
                    payload.decode("utf-8").splitlines(), start=1
                ):
                    if not line.strip():
                        continue
                    record = Translation.from_dict(json.loads(line))
                    if record.segment_id in translations:
                        raise CLIContractError(
                            f"duplicate held PDF translation ID: {record.segment_id}"
                        )
                    translations[record.segment_id] = record
        if not zones:
            raise CLIContractError("held PDF semantic snapshot contains no zones")
        expected_ids = {segment.id for segment in segments if segment.target}
        if set(translations) != expected_ids:
            raise CLIContractError(
                "held PDF translations do not exactly cover target segments"
            )
        return segments, zones, translations, dict(glossary_value)
    except CLIContractError:
        raise
    except (
        KeyError,
        UnicodeError,
        json.JSONDecodeError,
        SegmentContractError,
        ZoneContractError,
        TypeError,
        ValueError,
    ) as error:
        raise CLIContractError(f"cannot parse held PDF semantic inputs: {error}") from error


def _read_zones(run_dir: Path, unit_inputs: Any = None) -> list[Zone]:
    zone_dir = run_dir / "zones"
    if unit_inputs is None:
        _require_safe_directory(zone_dir)
    try:
        entries = (sorted(zone_dir.iterdir(), key=lambda path: path.name) if unit_inputs is None else
                   [run_dir / name for name in sorted(unit_inputs.payloads) if name.startswith("zones/")])
    except OSError as error:
        raise CLIContractError(f"cannot read zone directory {zone_dir}: {error}") from error
    invalid = [
        path.name
        for path in entries
        if (unit_inputs is None and not path.is_file())
        or not path.name.startswith("zone-")
        or path.suffix != ".json"
    ]
    if invalid:
        raise CLIContractError(f"unexpected zone entries: {', '.join(invalid)}")
    zones: list[Zone] = []
    for path in entries:
        if unit_inputs is None:
            _require_safe_file(path)
            data = _read_json_object(path)
        else:
            try:
                data = json.loads(unit_inputs.payloads[f"zones/{path.name}"])
                if not isinstance(data, Mapping):
                    raise ValueError("zone must be an object")
            except (ValueError, UnicodeError) as error:
                raise CLIContractError(f"invalid held PDF zone: {error}") from error
        try:
            zone = Zone(
                id=_string(data, "id", path),
                heading_path=_string_list(data, "heading_path", path),
                target_ids=_string_list(data, "target_ids", path),
                context_before_ids=_string_list(data, "context_before_ids", path),
                context_after_ids=_string_list(data, "context_after_ids", path),
                attempt=_integer(data, "attempt", path),
                expected_tokens=_string_sequence_mapping(data, "expected_tokens", path),
            )
        except ZoneContractError as error:
            raise CLIContractError(f"invalid zone file {path}: {error}") from error
        if path.stem != zone.id:
            raise CLIContractError(
                f"zone filename {path.name} does not match embedded ID {zone.id}"
            )
        zones.append(zone)
    return zones


def _read_capture(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "capture.json"
    data = _read_json_object(path)
    if set(data) != _CAPTURE_FIELDS:
        raise CLIContractError(f"capture metadata fields must be exactly {sorted(_CAPTURE_FIELDS)}: {path}")
    captured_at = _string(data, "captured_at", path)
    if _UTC_TIMESTAMP_PATTERN.fullmatch(captured_at) is None:
        raise CLIContractError(f"capture timestamp must be ISO-8601 UTC seconds ending in Z: {path}")
    try:
        datetime.fromisoformat(captured_at.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise CLIContractError(f"capture timestamp must be valid ISO-8601 UTC: {path}") from error
    requested_url = _string(data, "requested_url", path)
    final_url = _string(data, "final_url", path)
    try:
        validate_public_url(requested_url)
        validate_public_url(final_url)
    except ValueError as error:
        raise CLIContractError(f"invalid capture metadata {path}: {error}") from error
    asset_map = _string_mapping(data, "asset_map", path)
    for asset_url, local_path in asset_map.items():
        _validate_capture_asset_url(asset_url)
        _validate_asset_path(local_path, path)
    asset_paths = set(asset_map.values())
    critical_assets = _string_list(data, "critical_assets", path)
    optional_assets = _string_list(data, "optional_assets", path)
    if critical_assets != sorted(set(critical_assets)):
        raise CLIContractError(f"capture critical asset list must be sorted and unique: {path}")
    if optional_assets != sorted(set(optional_assets)):
        raise CLIContractError(f"capture optional asset list must be sorted and unique: {path}")
    if set(critical_assets) & set(optional_assets):
        raise CLIContractError(f"capture asset classes overlap: {path}")
    if set(critical_assets) | set(optional_assets) != asset_paths:
        raise CLIContractError(f"capture asset classes must exactly cover asset_map: {path}")
    fingerprints = _string_mapping(data, "fingerprints", path)
    if set(fingerprints) != {"source.html", *asset_paths}:
        raise CLIContractError(f"capture fingerprints must exactly cover source and assets: {path}")
    if any(_SHA256_PATTERN.fullmatch(value) is None for value in fingerprints.values()):
        raise CLIContractError(f"capture fingerprints must be lowercase SHA-256 values: {path}")
    for relative_path, expected_digest in fingerprints.items():
        captured = run_dir / relative_path
        _require_safe_file(captured)
        if _sha256_file(captured) != expected_digest:
            raise CLIContractError(
                f"capture fingerprint does not match file bytes: {relative_path}"
            )
    return {
        "asset_map": asset_map,
        "critical_assets": critical_assets,
        "captured_at": captured_at,
        "final_url": final_url,
        "fingerprints": fingerprints,
        "missing_optional_assets": _string_list(data, "missing_optional_assets", path),
        "optional_assets": optional_assets,
        "requested_url": requested_url,
    }


def _validate_capture_asset_url(asset_url: str) -> None:
    """Accept public HTTP(S), or a narrowly-defined, bounded CSS data URL."""
    if not asset_url.startswith("data:"):
        try:
            validate_public_url(asset_url)
        except ValueError as error:
            raise CLIContractError(
                f"capture asset URL must be public HTTP(S) or strict data:text/css: {asset_url}"
            ) from error
        return

    if len(asset_url.encode("utf-8")) > MAX_DATA_CSS_BYTES:
        raise CLIContractError(
            f"capture asset URL exceeds the capture size limit: {asset_url[:80]}"
        )

    try:
        metadata, encoded = asset_url[5:].split(",", 1)
    except ValueError as error:
        raise CLIContractError(
            f"capture asset URL must be strict data:text/css: {asset_url}"
        ) from error
    parameters = metadata.split(";")
    if not parameters or parameters[0] != "text/css":
        raise CLIContractError(
            f"capture asset URL must be strict data:text/css: {asset_url}"
        )
    options = parameters[1:]
    base64_encoded = bool(options and options[-1] == "base64")
    if base64_encoded:
        options = options[:-1]
    if options not in ([], ["charset=utf-8"], ["charset=us-ascii"]):
        raise CLIContractError(
            f"capture asset URL must be strict data:text/css: {asset_url}"
        )
    charset = options[0].partition("=")[2] if options else "utf-8"
    try:
        if re.search(r"%(?![0-9A-Fa-f]{2})", encoded):
            raise ValueError("invalid percent escape")
        payload = unquote_to_bytes(encoded)
        if base64_encoded:
            payload = base64.b64decode(payload, validate=True)
        decoded = payload.decode(charset)
        if not decoded:
            raise ValueError("empty CSS payload")
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise CLIContractError(
            f"capture asset URL must be strict data:text/css: {asset_url}"
        ) from error
    if len(payload) > MAX_DATA_CSS_BYTES:
        raise CLIContractError(
            f"capture asset URL exceeds the capture size limit: {asset_url[:80]}"
        )


def _read_glossary(path: Path) -> dict[str, str]:
    data = _read_json_object(path)
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in data.items()):
        raise CLIContractError(f"glossary keys and values must be strings: {path}")
    return dict(data)  # type: ignore[return-value]


def _build_manifest_provenance(
    *,
    result: QAResult,
    capture: Mapping[str, object],
    segments: Sequence[Segment],
    zones: Sequence[Zone],
    translated_segment_ids: set[str],
    review: MasterReview,
) -> ManifestProvenance:
    """Cross-check persisted artifacts before emitting typed manifest provenance."""
    captured_at = capture.get("captured_at")
    if not isinstance(captured_at, str) or not captured_at.endswith("Z"):
        raise CLIContractError("capture timestamp must be an ISO-8601 UTC value ending in Z")
    try:
        parsed_time = datetime.fromisoformat(captured_at.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise CLIContractError("capture timestamp must be valid ISO-8601 UTC") from error
    if parsed_time.utcoffset() != UTC.utcoffset(parsed_time):
        raise CLIContractError("capture timestamp must be UTC")

    requested_url = capture.get("requested_url")
    final_url = capture.get("final_url")
    if not isinstance(requested_url, str) or not isinstance(final_url, str):
        raise CLIContractError("capture provenance URLs must be strings")
    if final_url != result.source_url:
        raise CLIContractError("manifest final URL must match QA source URL")

    target_ids = {segment.id for segment in segments if segment.target}
    zone_target_ids = [segment_id for zone in zones for segment_id in zone.target_ids]
    if len(zone_target_ids) != len(set(zone_target_ids)) or set(zone_target_ids) != target_ids:
        raise CLIContractError("manifest zone coverage must exactly cover target segments once")
    if translated_segment_ids != target_ids:
        raise CLIContractError("manifest translation coverage must exactly cover target segments")
    if set(review.retries) != {zone.id for zone in zones}:
        raise CLIContractError("manifest retries must exactly cover zones")

    asset_map = capture.get("asset_map")
    fingerprints = capture.get("fingerprints")
    critical_assets = capture.get("critical_assets")
    optional_assets = capture.get("optional_assets")
    missing_optional = capture.get("missing_optional_assets")
    if not isinstance(asset_map, Mapping) or not isinstance(fingerprints, Mapping):
        raise CLIContractError("manifest asset provenance must be mappings")
    if not isinstance(critical_assets, list) or not isinstance(optional_assets, list):
        raise CLIContractError("manifest asset classifications must be arrays")
    if not isinstance(missing_optional, list) or any(
        not isinstance(item, str) for item in missing_optional
    ):
        raise CLIContractError("manifest missing optional assets must be a string array")
    critical_set = set(critical_assets)
    optional_set = set(optional_assets)
    if critical_set & optional_set or critical_set | optional_set != set(asset_map.values()):
        raise CLIContractError("manifest asset classifications must exactly cover assets")
    assets: list[ManifestAsset] = []
    for source, local_path in sorted(asset_map.items()):
        if not isinstance(source, str) or not isinstance(local_path, str):
            raise CLIContractError("manifest asset provenance keys and paths must be strings")
        digest = fingerprints.get(local_path)
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise CLIContractError("manifest asset fingerprint is missing or invalid")
        assets.append(
            ManifestAsset(
                source=source,
                local_path=local_path,
                sha256=digest,
                classification="critical" if local_path in critical_set else "optional",
            )
        )

    return ManifestProvenance(
        captured_at=captured_at,
        requested_url=requested_url,
        final_url=final_url,
        source_language=_detect_source_language(segments),
        target_language=_TARGET_LANGUAGE,
        terminology_policy_id=_TERMINOLOGY_POLICY_ID,
        terminology_policy_version=_TERMINOLOGY_POLICY_VERSION,
        tool_version=__version__,
        segment_count=len(segments),
        target_segment_count=len(target_ids),
        translated_segment_count=len(translated_segment_ids),
        zone_count=len(zones),
        assets=assets,
        missing_optional_assets=list(missing_optional),
        retries=dict(sorted(review.retries.items())),
        normalization=result.normalization,
    )


def _detect_source_language(segments: Sequence[Segment]) -> str:
    """Detect source language deterministically without mutating langdetect globals."""
    text = "\n".join(segment.source_text for segment in segments if segment.target)
    text = text[:100_000]
    if not text.strip() or re.search(r"[^\W\d_]", text, flags=re.UNICODE) is None:
        return "und"
    try:
        factory = DetectorFactory()
        factory.load_profile(PROFILES_DIRECTORY)
        factory.set_seed(0)
        detector = factory.create()
        detector.append(text)
        return detector.detect()
    except (LangDetectException, OSError, UnicodeError):
        return "und"


def _read_review(path: Path, zones: Sequence[Zone]) -> MasterReview:
    data = _read_json_object(path)
    return _review_from_value(data, path, zones)


def _read_pdf_review(
    path: Path,
    zones: Sequence[Zone],
    *,
    semantic_snapshot: Any | None = None,
) -> MasterReview:
    data = _read_json_object(path)
    try:
        if semantic_snapshot is None:
            validate_pdf_semantic_review(path.parent, data)
        else:
            validate_pdf_semantic_review_snapshot(semantic_snapshot, data)
    except PdfSemanticReviewError as error:
        raise CLIContractError(str(error)) from error
    return _review_from_value(
        {key: value for key, value in data.items() if key not in {"semantic_input_sha256", "preserved_names", "figure_text_review"}},
        path,
        zones,
    )


def _review_from_value(
    data: Mapping[str, Any],
    path: Path,
    zones: Sequence[Zone],
) -> MasterReview:
    if set(data) != {"unresolved_required", "retries", "section_findings"}:
        raise CLIContractError(f"review fields must be exactly unresolved_required, retries, section_findings: {path}")
    retries_raw = _mapping(data, "retries", path)
    findings_raw = _mapping(data, "section_findings", path)
    zone_ids = {zone.id for zone in zones}
    retries: dict[str, int] = {}
    for key, value in retries_raw.items():
        if not isinstance(key, str) or type(value) is not int or not 0 <= value <= 2:
            raise CLIContractError(
                f"review retries must map strings to integers from 0 through 2: {path}"
            )
        retries[key] = value
    if set(retries) != zone_ids:
        raise CLIContractError(
            f"review retries must exactly cover planned zones: {path}"
        )
    foreign_findings = sorted(set(findings_raw) - zone_ids)
    if foreign_findings:
        raise CLIContractError(
            f"review section findings contain foreign zones: {', '.join(foreign_findings)}"
        )
    if set(findings_raw) != zone_ids:
        raise CLIContractError(
            f"review section findings must exactly cover planned zones: {path}"
        )
    semantic_findings: dict[str, list[SemanticReviewFinding]] = {}
    section_findings: dict[str, list[str]] = {}
    for key, value in findings_raw.items():
        if not isinstance(key, str) or not isinstance(value, list):
            raise CLIContractError(
                f"review section findings must map zone IDs to finding arrays: {path}"
            )
        typed: list[SemanticReviewFinding] = []
        seen: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, Mapping) or set(item) != _REVIEW_FINDING_FIELDS:
                raise CLIContractError(
                    f"review finding fields must be exactly dimension, verdict, evidence: {path}:{key}[{index}]"
                )
            dimension = item["dimension"]
            if not isinstance(dimension, str) or dimension not in _REVIEW_DIMENSIONS:
                raise CLIContractError(
                    f"unknown review dimension at {path}:{key}[{index}]"
                )
            verdict = item["verdict"]
            if verdict not in {"pass", "required-fix"}:
                raise CLIContractError(
                    f"review verdict must be 'pass' or 'required-fix': {path}:{key}[{index}]"
                )
            evidence = item["evidence"]
            if not isinstance(evidence, str) or not evidence.strip():
                raise CLIContractError(
                    f"review evidence must be a non-empty string: {path}:{key}[{index}]"
                )
            seen.add(dimension)
            typed.append(
                SemanticReviewFinding(
                    dimension=dimension,  # type: ignore[arg-type]
                    verdict=verdict,  # type: ignore[arg-type]
                    evidence=evidence.strip(),
                )
            )
        if len(typed) != len(_REVIEW_DIMENSIONS) or seen != set(_REVIEW_DIMENSIONS):
            raise CLIContractError(
                f"review findings for {key} must contain each canonical dimension exactly once: {path}"
            )
        semantic_findings[key] = typed
        section_findings[key] = [
            f"{finding.dimension} | {finding.verdict} | evidence: {finding.evidence}"
            for finding in typed
        ]
    unresolved = _string_list(data, "unresolved_required", path)
    if unresolved != sorted(set(unresolved)):
        raise CLIContractError(f"review unresolved_required must be sorted and unique: {path}")
    expected_unresolved = sorted(
        f"{zone_id}:{finding.dimension}"
        for zone_id, findings in semantic_findings.items()
        for finding in findings
        if finding.verdict == "required-fix"
    )
    if unresolved != expected_unresolved:
        raise CLIContractError(
            f"review unresolved_required must exactly match required-fix findings: {path}"
        )
    return MasterReview(
        unresolved_required=unresolved,
        retries=retries,
        section_findings=section_findings,
        semantic_findings=semantic_findings,
    )


def _zone_payload(zone: Zone) -> dict[str, object]:
    return {
        "attempt": zone.attempt,
        "context_after_ids": zone.context_after_ids,
        "context_before_ids": zone.context_before_ids,
        "expected_tokens": {key: list(value) for key, value in zone.expected_tokens.items()},
        "heading_path": zone.heading_path,
        "id": zone.id,
        "target_ids": zone.target_ids,
    }


def _validate_translation_files(run_dir: Path, zones: Sequence[Zone]) -> Path:
    result_dir = run_dir / "translations"
    _require_safe_directory(result_dir)
    try:
        entries = sorted(result_dir.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise CLIContractError(
            f"cannot read translation directory {result_dir}: {error}"
        ) from error
    expected = {f"{zone.id}.jsonl" for zone in zones}
    actual = {path.name for path in entries}
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unexpected:
        raise CLIContractError(
            f"unexpected translation entries: {', '.join(unexpected)}"
        )
    if missing:
        raise CLIContractError(f"missing translation entries: {', '.join(missing)}")
    for path in entries:
        _require_safe_file(path)
    return result_dir


def _validate_partial_translation_files(
    run_dir: Path, zones: Sequence[Zone], requested: Zone
) -> Path:
    result_dir = run_dir / "translations"
    _require_safe_directory(result_dir)
    try:
        entries = sorted(result_dir.iterdir(), key=lambda path: path.name)
    except OSError as error:
        raise CLIContractError(
            f"cannot read translation directory {result_dir}: {error}"
        ) from error
    expected = {f"{zone.id}.jsonl" for zone in zones}
    unexpected = sorted(path.name for path in entries if path.name not in expected)
    if unexpected:
        raise CLIContractError(
            f"unexpected translation entries: {', '.join(unexpected)}"
        )
    for path in entries:
        _require_safe_file(path)
    requested_path = result_dir / f"{requested.id}.jsonl"
    _require_safe_file(requested_path)
    return result_dir


def _validate_asset_path(value: str, source: Path) -> None:
    candidate = PurePosixPath(value)
    if (
        "\\" in value
        or candidate.is_absolute()
        or len(candidate.parts) != 2
        or candidate.parts[0] != "assets"
        or candidate.parts[1] in {"", ".", ".."}
    ):
        raise CLIContractError(
            f"capture asset path must be a safe assets/ path in {source}: {value}"
        )


def _validate_run_root(run_dir: Path) -> None:
    _reject_linked_ancestors(run_dir)
    if run_dir.exists() and not run_dir.is_dir():
        raise CLIContractError(f"run directory path is not a directory: {run_dir}")


def _validate_qa_output_path(output_dir: Path) -> None:
    _reject_linked_ancestors(output_dir)
    if output_dir.exists() and not output_dir.is_dir():
        raise CLIContractError(f"QA output path is not a directory: {output_dir}")
    _reject_if_link(output_dir / "index.html")
    _reject_if_link(output_dir / "manifest.json")
    _reject_if_link(output_dir / "review-report.md")


@contextmanager
def _preformatted_qa_evidence(output_dir):
    """Publish through existing anchored primitives; preserve recovery on failure.

    Prior reports are never assumed to describe the current output. On failure
    they remain only as private recovery copies, never restored as public PASS.
    """
    import supertranslator.pdf_assemble as anchored
    from supertranslator.pdf_extract_transaction import _write_private_file
    from supertranslator.pdf_qa import PdfQAFailure, _open_windows_qa_mutation_directory

    _validate_qa_output_path(output_dir)
    root = anchored._open_directory_anchor(output_dir, 'QA evidence output')
    stage = None
    stage_name = None
    originals = {}
    prior_payloads = {}
    backups = {}
    backup_handles = []
    recovery_stages = []
    published = {}
    payloads = {}
    completed = False
    backups_ready = False
    failure: BaseException | None = None

    def backup_is_exact(name):
        if name not in backups:
            return False
        directory, backup_name, opened = backups[name]
        try:
            anchored._verify_anchored_evidence(directory, {backup_name: opened})
            if opened.identity != directory.owned_files[backup_name]:
                return False
            opened.stream.seek(0)
            return (os.fstat(opened.stream.fileno()).st_nlink == 1
                    and opened.stream.read() == prior_payloads[name])
        except (anchored.PdfAssemblyError, OSError):
            return False

    def secure_backup(directory, name):
        backup_name = 'prior-' + name
        _write_private_file(directory, backup_name, prior_payloads[name])
        opened = anchored._open_anchored_input_file(directory, backup_name, 'QA recovery snapshot')
        backup_handles.append(opened)
        backups[name] = directory, backup_name, opened
        if not backup_is_exact(name):
            raise QAFailure('QA recovery snapshot identity or bytes changed')

    def ensure_recovery(name):
        if backup_is_exact(name):
            return
        # A changed entry is never overwritten/adopted, even with equal bytes.
        # Secure the held original truth under fresh exclusive owned names.
        recovery_name, recovery = anchored._create_unique_child_directory(root, '.qa-evidence-', 'QA exact recovery')
        recovery_stages.append((recovery_name, recovery))
        secure_backup(recovery, name)

    def close_directory(name, directory, *, remove):
        handle = None
        try:
            if not remove:
                return
            directory.verify_visible()
            if anchored._anchored_directory_names(directory):
                return
            if os.name == 'nt':
                handle = _open_windows_qa_mutation_directory(root, name, directory.identity)
                # The checked opener binds the visible identity. Recheck held
                # children too; never recursively delete a foreign entry.
                if not anchored._anchored_directory_names(directory):
                    anchored._windows_delete_open_file(handle)
            else:
                anchored._remove_owned_directory(root, name, directory.identity)
        except (anchored.PdfAssemblyError, PdfQAFailure, OSError, NotImplementedError):
            pass
        finally:
            if handle is not None:
                anchored.pdf_acquire_module._close_windows_handle(handle)
            directory.close()

    try:
        stage_name, stage = anchored._create_unique_child_directory(root, '.qa-evidence-', 'QA evidence recovery')
        names = set(anchored._anchored_directory_names(root))
        for name in ('review-report.md', 'manifest.json'):
            if name in names:
                opened = anchored._open_anchored_input_file(root, name, 'prior QA evidence')
                originals[name] = opened
                payload = opened.stream.read()
                prior_payloads[name] = payload
                if os.fstat(opened.stream.fileno()).st_nlink != 1:
                    raise QAFailure('prior QA evidence has hardlinks')
                secure_backup(stage, name)
        backups_ready = True

        class Transaction:
            def publish(self, result, review, provenance):
                rendered = {'review-report.md': render_review_report(result, review).encode('utf-8'),
                            'manifest.json': render_manifest(result, provenance).encode('utf-8')}
                for name, payload in rendered.items():
                    staged_name = 'new-' + name
                    _write_private_file(stage, staged_name, payload)
                    if name in originals:
                        anchored._verify_anchored_evidence(root, {name: originals[name]})
                        originals[name].stream.seek(0)
                        if originals[name].stream.read() != prior_payloads[name]:
                            raise QAFailure('prior QA evidence changed during publication')
                        ensure_recovery(name)
                        # Exact bytes are secured above; retain the identity, not
                        # a read handle that leaves the Windows name delete-pending.
                        anchored._close_opened_file(originals[name])
                        anchored._remove_owned_file(root, name, anchored._PublishedFile(originals[name].identity))
                    # Register before publication so BaseException never adopts a replacement.
                    published[name] = anchored._PublishedFile(stage.owned_files[staged_name])
                    payloads[name] = payload
                    published[name] = anchored._publish_new_file(stage, staged_name, root, name)
                self.verify()

            def verify(self):
                root.verify_visible()
                stage.verify_visible()
                for name, publication in published.items():
                    anchored._verify_anchored_input_identity(root, name, publication.identity)
                    opened = anchored._open_anchored_input_file(root, name, 'published QA evidence')
                    try:
                        if opened.stream.read() != payloads[name]:
                            raise QAFailure('published QA evidence bytes changed')
                    finally:
                        anchored._close_opened_file(opened)
                for name in originals:
                    ensure_recovery(name)

        transaction = Transaction()
        yield transaction
        transaction.verify()
        completed = True
    except BaseException as error:
        failure = error
    # Existing anchored creators/publishers treat an active exception as failed
    # creation. Fresh recovery must run outside the original exception handler.
    # Never overwrite/delete a raced foreign inode, or delete an unbacked prior.
    if not completed:
        for name, publication in published.items():
            anchored._remove_owned_file(root, name, publication)
        if backups_ready:
            for name, opened in originals.items():
                try:
                    ensure_recovery(name)
                except (QAFailure, anchored.PdfAssemblyError, OSError):
                    continue
                anchored._remove_owned_file(root, name, anchored._PublishedFile(opened.identity))
    for publication in published.values():
        anchored._close_published_file(publication)
    for opened in originals.values():
        anchored._close_opened_file(opened)
    for opened in backup_handles:
        anchored._close_opened_file(opened)
    for recovery_name, recovery in reversed(recovery_stages):
        if completed:
            for name, identity in recovery.owned_files.items():
                anchored._remove_owned_file(recovery, name, anchored._PublishedFile(identity))
        close_directory(recovery_name, recovery, remove=completed)
    if stage is not None:
        for name, identity in stage.owned_files.items():
            if completed or name.startswith('new-'):
                anchored._remove_owned_file(stage, name, anchored._PublishedFile(identity))
        close_directory(stage_name, stage, remove=completed or not originals)
    root.close()
    if failure is not None:
        raise failure


def _publish_qa_evidence(
    result: QAResult,
    review: MasterReview,
    output_dir: Path,
    provenance: ManifestProvenance | None = None,
    *,
    _transaction=None,
) -> None:
    """Publish report first and manifest last, rolling the pair back on failure."""
    if _transaction is not None:
        _transaction.publish(result, review, provenance)
        return
    manifest = output_dir / "manifest.json"
    report = output_dir / "review-report.md"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for destination in (manifest, report):
            if destination.exists():
                _require_safe_file(destination)
            else:
                _reject_if_link(destination)
        original_manifest = manifest.read_bytes() if manifest.exists() else None
        original_report = report.read_bytes() if report.exists() else None
        with tempfile.TemporaryDirectory(
            prefix=".qa-evidence-", dir=output_dir
        ) as temporary_name:
            temporary = Path(temporary_name)
            temporary_manifest = temporary / "manifest.json"
            temporary_report = temporary / "review-report.md"
            write_manifest(result, temporary_manifest, provenance)
            write_review_report(result, review, temporary_report)
            try:
                os.replace(temporary_report, report)
                os.replace(temporary_manifest, manifest)
            except BaseException as publish_error:
                try:
                    _restore_optional_file(report, original_report)
                    _restore_optional_file(manifest, original_manifest)
                except OSError as rollback_error:
                    raise QAFailure(
                        "QA evidence publication and rollback both failed: "
                        f"publish={publish_error}; rollback={rollback_error}"
                    ) from publish_error
                if isinstance(publish_error, OSError):
                    raise QAFailure(
                        f"cannot publish QA evidence: {publish_error}"
                    ) from publish_error
                raise
    except QAFailure:
        raise
    except (CLIContractError, OSError) as error:
        raise QAFailure(f"cannot write QA evidence: {error}") from error


def _restore_optional_file(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
    else:
        _replace_bytes_atomic(path, content)


def _require_safe_directory(path: Path) -> None:
    _reject_linked_ancestors(path)
    if not path.is_dir():
        raise CLIContractError(f"missing or unsafe directory: {path}")


def _require_safe_file(path: Path) -> None:
    _reject_linked_ancestors(path)
    if not path.is_file():
        raise CLIContractError(f"missing or unsafe file: {path}")


def _reject_if_link(path: Path) -> None:
    if _is_link_or_reparse(path):
        raise CLIContractError(f"path is a link or reparse point: {path}")


def _reject_linked_ancestors(path: Path) -> None:
    candidate = path.absolute()
    while not candidate.exists() and not candidate.is_symlink():
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    while True:
        if _is_link_or_reparse(candidate):
            raise CLIContractError(
                f"path contains a link or reparse point: {candidate}"
            )
        parent = candidate.parent
        if parent == candidate:
            return
        candidate = parent


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & _REPARSE_POINT)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        _require_safe_file(path)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (CLIContractError, OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CLIContractError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise CLIContractError(f"JSON document must be an object: {path}")
    return value


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    serialized = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    atomic_write(path, serialized.encode("utf-8"))


def _replace_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    serialized = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _replace_bytes_atomic(path, serialized)


def _replace_bytes_atomic(path: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CLIContractError(f"cannot hash captured file {path}: {error}") from error
    return digest.hexdigest()


def _string(data: Mapping[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise CLIContractError(f"{path.name}.{key} must be a string")
    return value


def _integer(data: Mapping[str, Any], key: str, path: Path) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise CLIContractError(f"{path.name}.{key} must be an integer")
    return value


def _mapping(data: Mapping[str, Any], key: str, path: Path) -> Mapping[object, object]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise CLIContractError(f"{path.name}.{key} must be an object")
    return value


def _string_list(data: Mapping[str, Any], key: str, path: Path) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CLIContractError(f"{path.name}.{key} must be a string array")
    return list(value)


def _string_mapping(data: Mapping[str, Any], key: str, path: Path) -> dict[str, str]:
    value = _mapping(data, key, path)
    if any(
        not isinstance(item_key, str) or not isinstance(item_value, str)
        for item_key, item_value in value.items()
    ):
        raise CLIContractError(f"{path.name}.{key} must map strings to strings")
    return dict(value)  # type: ignore[arg-type]


def _string_sequence_mapping(
    data: Mapping[str, Any], key: str, path: Path
) -> dict[str, tuple[str, ...]]:
    value = _mapping(data, key, path)
    result: dict[str, tuple[str, ...]] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not isinstance(item_value, list) or any(
            not isinstance(entry, str) for entry in item_value
        ):
            raise CLIContractError(f"{path.name}.{key} must map strings to string arrays")
        result[item_key] = tuple(item_value)
    return result


def _fail(command: str, exit_code: int, error: Exception) -> int:
    print(f"{command}: {error}", file=sys.stderr)
    _emit_status(command, "error", exit_code)
    return exit_code


def _emit_status(command: str, status: str, exit_code: int) -> None:
    print(
        json.dumps(
            {"command": command, "exit_code": exit_code, "status": status},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
