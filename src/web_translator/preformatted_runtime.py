"""Held preformatted lifecycle, using the existing anchored publication primitives.

The raw capture never participates in a write transaction. Provenance is removed
first when extracting and published last; an interrupted intermediate state is
not a usable source. All filesystem names below are backend-owned constants or
validated capture asset names, never reviewer/source-page paths.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import io
import os
from pathlib import Path
from typing import Iterator, Mapping

import web_translator.pdf_assemble as anchored
from web_translator.pdf_extract_transaction import _write_private_file
from web_translator.extract import extract_segments
from web_translator.models import read_segments_stream
from web_translator.preformatted_analysis import (
    analyze_preformatted, build_classification_packages, validate_review,
)
from web_translator.preformatted_contract import (
    RESERVED, NormalizationSummary, PreformattedAnalysis, PreformattedContractError,
    ProjectionArtifact, ProjectionRecord, canonical_bytes, canonical_loads,
)
from web_translator.preformatted_projection import (
    encode_projection_transport, project_preformatted, verify_projection, verify_projected_output,
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _fail(message: str) -> None:
    raise PreformattedContractError(message)


class _HeldRun:
    def __init__(self, path: Path):
        self.path = Path(path).absolute()
        self.directories: dict[str, anchored._DirectoryAnchor] = {}
        self.files: dict[str, tuple[anchored._OpenedFile, bytes]] = {}
        self.sets: dict[str, list[str]] = {}
        self.artifact: ProjectionArtifact | None = None
        self.record: ProjectionRecord | None = None
        self.analysis: PreformattedAnalysis | None = None
        self.packages = ()
        self.review = None
        self.closed = False

    def directory(self, relative: str) -> anchored._DirectoryAnchor:
        if relative not in self.directories:
            if not relative:
                anchored._reject_linked_ancestors(self.path)
                anchor = anchored._open_directory_anchor(self.path, "preformatted run")
            else:
                parent, _, name = relative.rpartition("/")
                anchor = anchored._open_existing_child_directory(self.directory(parent), name, relative)
            self.directories[relative] = anchor
        return self.directories[relative]

    def names(self, relative: str) -> list[str]:
        return anchored._anchored_directory_names(self.directory(relative))

    def read(self, relative: str) -> bytes:
        if relative not in self.files:
            parent, _, name = relative.rpartition("/")
            opened = anchored._open_anchored_input_file(self.directory(parent), name, relative)
            # Retain even if the read fails, so all handles close on BaseException.
            self.files[relative] = (opened, b"")
            opened.stream.seek(0)
            payload = opened.stream.read()
            self.files[relative] = (opened, payload)
            self._verify_file(relative)
        return self.files[relative][1]

    def _verify_file(self, relative: str) -> None:
        opened, payload = self.files[relative]
        parent, _, name = relative.rpartition("/")
        anchored._verify_anchored_input_identity(self.directory(parent), name, opened.identity)
        if os.fstat(opened.stream.fileno()).st_nlink != 1:
            _fail(f"held input has hardlinks: {relative}")
        opened.stream.seek(0)
        if opened.stream.read() != payload:
            _fail(f"held input content changed: {relative}")

    def verify(self) -> None:
        if self.closed:
            _fail("processing source lease is closed")
        anchored._reject_linked_ancestors(self.path)
        for anchor in self.directories.values():
            anchor.verify_visible()
        for relative in self.files:
            self._verify_file(relative)
        for relative, expected in self.sets.items():
            if self.names(relative) != expected:
                _fail(f"held directory child set changed: {relative or 'run'}")

    def close(self) -> None:
        self.closed = True
        for opened, _ in self.files.values():
            anchored._close_opened_file(opened)
        for anchor in reversed(tuple(self.directories.values())):
            anchor.close()


@contextmanager
def _hold_run(run_dir: Path) -> Iterator[_HeldRun]:
    held = _HeldRun(run_dir)
    try:
        held.directory("")
        _load(held)
        held.verify()
        yield held
    except (anchored.PdfAssemblyError, OSError, UnicodeError) as error:
        raise PreformattedContractError(str(error)) from error
    finally:
        held.close()


def _load(held: _HeldRun) -> None:
    root_names = held.names("")
    if any(name.startswith(".preformatted-") for name in root_names):
        _fail("interrupted preformatted transaction requires a fresh run")
    source = held.read("source.html")
    capture = canonical_loads(held.read("capture.json").decode("utf-8"))
    # Reuse the established lexical asset-path contract; never open a URL/path
    # from source markup or a classification/review record.
    from web_translator.cli import _validate_asset_path
    if not isinstance(capture, dict) or not isinstance(capture.get("asset_map"), dict):
        _fail("invalid capture asset_map")
    asset_paths = set(capture["asset_map"].values())
    fingerprints = capture.get("fingerprints")
    if not isinstance(fingerprints, dict) or set(fingerprints) != {"source.html", *asset_paths}:
        _fail("capture fingerprints must exactly cover source and captured assets")
    for relative, digest in fingerprints.items():
        if relative != "source.html":
            _validate_asset_path(relative, held.path / "capture.json")
        if _digest(held.read(relative)) != digest:
            _fail(f"capture fingerprint mismatch: {relative}")
    asset_names = held.names("assets") if "assets" in root_names else []
    generated = [name for name in asset_names if name.startswith("wt-preformatted-")]
    if any(Path(path).name.startswith("wt-preformatted-") for path in asset_paths):
        _fail("captured asset uses reserved generated CSS path")
    if "preformatted" not in root_names:
        if "preformatted-source.html" in root_names or generated:
            _fail("orphan preformatted source or CSS")
        held.sets[""] = root_names
        if "assets" in root_names:
            held.sets["assets"] = asset_names
        return
    _reject_captured_css_collisions(held, asset_paths)
    if set(asset_names) != {*(Path(path).name for path in asset_paths), *generated}:
        _fail("preformatted assets contain unbound entries")
    names = held.names("preformatted")
    expected = {"analysis.json", "packages"}
    expected.update(name for name in ("review.json", "provenance.json") if name in names)
    if set(names) != expected:
        _fail("preformatted state has missing or extra entries")
    analysis_bytes = held.read("preformatted/analysis.json")
    analysis = PreformattedAnalysis.from_dict(canonical_loads(analysis_bytes.decode("utf-8")))
    actual = analyze_preformatted(source.decode("utf-8"))
    if not analysis.roots or analysis_bytes != canonical_bytes(actual.to_dict()):
        _fail("analysis differs from captured source")
    held.analysis = analysis
    held.packages = build_classification_packages(analysis)
    expected_packages = [f"{package.id}.json" for package in held.packages]
    if held.names("preformatted/packages") != expected_packages:
        _fail("classification package set mismatch")
    for package in held.packages:
        if held.read(f"preformatted/packages/{package.id}.json") != canonical_bytes(package.to_dict()):
            _fail("classification package changed")
    if "review.json" in names:
        held.review = validate_review(analysis, held.packages, held.read("preformatted/review.json").decode("utf-8"))
    if "provenance.json" not in names:
        if "preformatted-source.html" in root_names or generated or "segments.jsonl" in root_names:
            _fail("partial materialization without provenance")
    else:
        if held.review is None:
            _fail("locked projection is missing review")
        record = ProjectionRecord.from_dict(canonical_loads(held.read("preformatted/provenance.json").decode("utf-8")))
        artifact = project_preformatted(source.decode("utf-8"), analysis, held.review)
        expected_record = _record(held, artifact, phase=record.phase,
                                  marked=record.marked_sha256, segments=record.segments_sha256)
        if record.to_dict() != expected_record.to_dict():
            _fail("locked projection provenance changed; a fresh run is required")
        verify_projection(source.decode("utf-8"), analysis, held.review, artifact)
        if generated != [Path(record.css_path).name]:
            _fail("generated CSS set mismatch")
        if held.read(record.css_path) != artifact.css_bytes:
            _fail("generated CSS bytes changed")
        derived = held.read("preformatted-source.html")
        if _digest(derived) != (record.marked_sha256 or record.unmarked_sha256):
            _fail("derived source changed")
        if record.phase == "extracted":
            segments = held.read("segments.jsonl")
            if _digest(segments) != record.segments_sha256:
                _fail("segments changed")
            read_segments_stream(io.StringIO(segments.decode("utf-8")))
        elif "segments.jsonl" in root_names:
            _fail("projected run has orphan extraction segments")
        verify_projected_output(artifact, derived.decode("utf-8"))
        held.record, held.artifact = record, artifact
    held.sets.update({"": root_names, "preformatted": names,
                      "preformatted/packages": expected_packages})
    if "assets" in root_names:
        held.sets["assets"] = asset_names


def _reject_captured_css_collisions(held: _HeldRun, asset_paths: set[str]) -> None:
    for relative in asset_paths:
        if relative.lower().endswith(".css"):
            css = held.read(relative).decode("utf-8").lower()
            if any(marker in css for marker in RESERVED):
                _fail(f"captured CSS uses reserved selector: {relative}")


def _record(held: _HeldRun, artifact: ProjectionArtifact, *, phase: str = "projected",
            marked: str | None = None, segments: str | None = None) -> ProjectionRecord:
    return ProjectionRecord.from_dict({
        "schema_version": "1.0", "phase": phase,
        "source_sha256": _digest(held.read("source.html")),
        "analysis_sha256": _digest(held.read("preformatted/analysis.json")),
        "review_sha256": _digest(held.read("preformatted/review.json")),
        "package_sha256": {p.id: _digest(held.read(f"preformatted/packages/{p.id}.json")) for p in held.packages},
        "unmarked_sha256": _digest(artifact.unmarked_html.encode("utf-8")),
        "marked_sha256": marked, "segments_sha256": segments,
        "css_path": artifact.css_path, "css_sha256": _digest(artifact.css_bytes),
        "evidence": artifact.to_dict()["evidence"], "summary": artifact.summary.to_dict(),
    })


@dataclass(frozen=True, slots=True)
class ProcessingSource:
    """Valid only inside hold_processing_source; verify before/after consumers."""

    path: Path
    normalization: NormalizationSummary | None
    generated_critical_assets: tuple[Mapping[str, str], ...]
    _held: _HeldRun

    def verify(self) -> None:
        try:
            self._held.verify()
        except (anchored.PdfAssemblyError, OSError) as error:
            raise PreformattedContractError(str(error)) from error


@contextmanager
def hold_processing_source(run_dir: Path, *, phase: str) -> Iterator[ProcessingSource]:
    if phase not in {"extract", "assemble", "qa"}:
        _fail("processing phase must be extract, assemble or qa")
    with _hold_run(run_dir) as held:
        if held.analysis is not None and held.record is None:
            _fail("preformatted analysis is pending review/materialization")
        if held.record is not None and phase != "extract" and held.record.phase != "extracted":
            _fail("preformatted source must be extracted before assembly or QA")
        summary = held.artifact.summary if held.artifact else None
        source = ProcessingSource(held.path / ("preformatted-source.html" if summary else "source.html"),
                                  summary, summary.generated_assets if summary else (), held)
        yield source
        source.verify()


def verify_preformatted_output(source: ProcessingSource, output_html: Path) -> None:
    source.verify()
    if source._held.artifact is None:
        return
    path = Path(output_html).absolute()
    output = _HeldRun(path.parent)
    try:
        payload = output.read(path.name)
        verify_projected_output(source._held.artifact, payload.decode("utf-8"))
        output.verify()
        source.verify()
    except (anchored.PdfAssemblyError, OSError, UnicodeError) as error:
        raise PreformattedContractError(str(error)) from error
    finally:
        output.close()


@contextmanager
def _staging(held: _HeldRun):
    name, stage = anchored._create_unique_child_directory(held.directory(""), ".preformatted-", "private preformatted staging")
    try:
        yield stage
    finally:
        for child, identity in tuple(stage.owned_files.items()):
            anchored._remove_owned_file(stage, child, anchored._PublishedFile(identity))
        anchored._remove_owned_directory(held.directory(""), name, stage.identity, child=stage)
        stage.close()


def _publish(held: _HeldRun, payloads: list[tuple[str, bytes]], *, replace_paths: tuple[str, ...] = ()) -> None:
    """Stage every byte, invalidate old fence first, publish new fence last.

    Rollback is no-clobber and identity-checked. If a foreign entry wins a race,
    leave it alone and do not restore the acceptance fence over partial state.
    """
    held.verify()
    created_dirs: list[tuple[str, anchored._DirectoryAnchor]] = []
    published: list[tuple[str, anchored._PublishedFile]] = []
    removed: list[str] = []
    backups: dict[str, str] = {}
    complete = False
    failure: BaseException | None = None
    final_sets = {key: set(names) for key, names in held.sets.items()}
    with _staging(held) as stage:
        try:
            for index, (relative, payload) in enumerate(payloads):
                if relative == "segments.jsonl" and payload == b"":
                    # The web extractor legitimately emits an empty JSONL file
                    # for zero targets. The PDF nonempty finalizer is unchanged.
                    opened = anchored._create_anchored_binary_file(stage, f"new-{index}")
                    try:
                        opened.stream.flush()
                        os.fsync(opened.stream.fileno())
                        anchored._verify_anchored_input_identity(stage, f"new-{index}", opened.identity)
                        opened.stream.seek(0)
                        if opened.stream.read() != b"":
                            _fail("empty staged segments changed")
                    finally:
                        anchored._close_opened_file(opened)
                else:
                    _write_private_file(stage, f"new-{index}", payload)
                if relative in replace_paths:
                    backup = f"old-{index}"
                    _write_private_file(stage, backup, held.read(relative))
                    backups[relative] = backup
            # Ignore only our exact private directory during input verification.
            held.sets[""] = sorted([*held.sets[""], stage.path.name])
            final_sets[""].add(stage.path.name)
            held.verify()
            for relative, _ in payloads:
                parent, _, _ = relative.rpartition("/")
                ancestors = list(reversed(Path(parent).parents)) + [Path(parent)] if parent else []
                for ancestor in ancestors:
                    directory = ancestor.as_posix()
                    if directory == "." or directory in held.directories:
                        continue
                    grandparent, _, name = directory.rpartition("/")
                    child = anchored._create_child_directory(held.directory(grandparent), name, directory)
                    held.directories[directory] = child
                    created_dirs.append((directory, child))
                    final_sets.setdefault(grandparent, set()).add(name)
                    final_sets[directory] = set()
            for relative in replace_paths:
                opened, _ = held.files[relative]
                held._verify_file(relative)
                parent, _, name = relative.rpartition("/")
                # Closing the read lease is necessary for native Windows delete
                # completion; the saved identity still gates the exact removal.
                anchored._close_opened_file(opened)
                removed.append(relative)
                anchored._remove_owned_file(held.directory(parent), name, anchored._PublishedFile(opened.identity))
                anchored._require_anchored_name_absent(held.directory(parent), name)
                del held.files[relative]
            for index, (relative, _) in enumerate(payloads):
                parent, _, name = relative.rpartition("/")
                destination = held.directory(parent)
                # Register identity before publication, including outer BaseException.
                owned = anchored._PublishedFile(stage.owned_files[f"new-{index}"])
                published.append((relative, owned))
                result = anchored._publish_new_file(stage, f"new-{index}", destination, name)
                published[-1] = (relative, result)
                anchored._remove_owned_file(stage, f"new-{index}", anchored._PublishedFile(owned.identity))
                final_sets.setdefault(parent, set()).add(name)
            # Recheck all unchanged held bytes and every newly published byte.
            for relative in held.files:
                held._verify_file(relative)
            for anchor in held.directories.values():
                anchor.verify_visible()
            for relative, payload in payloads:
                if held.read(relative) != payload:
                    _fail(f"published artifact changed: {relative}")
            held.sets = {key: sorted(names) for key, names in final_sets.items()}
            held.verify()
            complete = True
        except BaseException as error:
            failure = error
        # The shared publisher treats an active exception as failed publication.
        # Restore outside the exception handler so a successful rollback publish
        # is not removed by that helper's own BaseException cleanup.
        try:
            if not complete:
                for relative, published_file in reversed(published):
                    if relative in held.files:
                        anchored._close_opened_file(held.files.pop(relative)[0])
                    parent, _, name = relative.rpartition("/")
                    anchored._remove_owned_file(held.directory(parent), name, published_file)
                # Old provenance was removed first: restore it last, only if all
                # prior restorations succeeded without overwriting a foreign file.
                for relative in reversed(removed):
                    parent, _, name = relative.rpartition("/")
                    restored = anchored._publish_new_file(stage, backups[relative], held.directory(parent), name)
                    anchored._close_published_file(restored)
                    anchored._remove_owned_file(stage, backups[relative], anchored._PublishedFile(stage.owned_files[backups[relative]]))
                for relative, child in reversed(created_dirs):
                    parent, _, name = relative.rpartition("/")
                    anchored._remove_owned_directory(held.directory(parent), name, child.identity, child=child)
                    # Native Windows deletion completes when this held directory
                    # handle closes, before attempting to remove its parent.
                    child.close()
                    del held.directories[relative]
        finally:
            for _, published_file in published:
                anchored._close_published_file(published_file)
        if failure is not None:
            raise failure


def prepare_preformatted_run(run_dir: Path) -> bool:
    with _hold_run(run_dir) as held:
        if held.analysis is not None:
            return True
        analysis = analyze_preformatted(held.read("source.html").decode("utf-8"))
        if not analysis.roots:
            return False
        if "segments.jsonl" in held.names(""):
            _fail("preformatted preparation requires an unextracted fresh run")
        capture = canonical_loads(held.read("capture.json").decode("utf-8"))
        _reject_captured_css_collisions(held, set(capture["asset_map"].values()))
        if "assets" in held.directories and set(held.names("assets")) != {
                Path(path).name for path in capture["asset_map"].values()}:
            _fail("preformatted assets contain unbound entries")
        packages = build_classification_packages(analysis)
        payloads = [(f"preformatted/packages/{p.id}.json", canonical_bytes(p.to_dict())) for p in packages]
        payloads.append(("preformatted/analysis.json", canonical_bytes(analysis.to_dict())))
        # Parent directories are themselves identity-owned and cleaned on failure.
        _publish(held, payloads)
        return True


def materialize_preformatted_run(run_dir: Path) -> None:
    with _hold_run(run_dir) as held:
        if held.record is not None:
            return
        if held.analysis is None or held.review is None:
            _fail("analysis and fixed preformatted/review.json are required")
        artifact = project_preformatted(held.read("source.html").decode("utf-8"), held.analysis, held.review)
        verify_projection(held.read("source.html").decode("utf-8"), held.analysis, held.review, artifact)
        record = _record(held, artifact)
        _publish(held, [("preformatted-source.html", artifact.unmarked_html.encode("utf-8")),
                        (artifact.css_path, artifact.css_bytes),
                        ("preformatted/provenance.json", canonical_bytes(record.to_dict()))])


def _verify_staged_extraction(
    stage: anchored._DirectoryAnchor,
    staged: Mapping[str, anchored._OpenedFile],
) -> None:
    anchored._verify_anchored_evidence(stage, staged)
    for name, opened in staged.items():
        if opened.identity != stage.owned_files[name]:
            _fail(f"staged extraction output changed identity: {name}")
        if os.fstat(opened.stream.fileno()).st_nlink != 1:
            _fail(f"staged extraction output has hardlinks: {name}")


def extract_preformatted_run(run_dir: Path) -> None:
    with _hold_run(run_dir) as held:
        if held.record is None or held.artifact is None:
            _fail("a materialized preformatted projection is required")
        if held.record.phase == "extracted":
            return
        with _staging(held) as stage:
            _write_private_file(stage, "source.html", held.read("preformatted-source.html"))
            staged = {}
            try:
                # Both extractor writes are in-place. Reserve their identities
                # before invoking it, including empty JSONL and exception paths.
                created = anchored._create_anchored_binary_file(stage, "segments.jsonl")
                anchored._close_opened_file(created)
                for name in ("source.html", "segments.jsonl"):
                    opened = anchored._open_anchored_input_file(stage, name, "staged extraction")
                    staged[name] = opened
                _verify_staged_extraction(stage, staged)
                extract_segments(stage.current_path() / "source.html", stage.current_path() / "segments.jsonl")
                _verify_staged_extraction(stage, staged)
                marked = encode_projection_transport(
                    anchored._read_opened_utf8(staged["source.html"], stage.path / "source.html", "marked projection"), held.artifact)
                staged["segments.jsonl"].stream.seek(0)
                segments = staged["segments.jsonl"].stream.read()
                read_segments_stream(io.StringIO(segments.decode("utf-8")))
                verify_projected_output(held.artifact, marked)
                _verify_staged_extraction(stage, staged)
            finally:
                for opened in staged.values():
                    anchored._close_opened_file(opened)
        record = replace(held.record, phase="extracted", marked_sha256=_digest(marked.encode("utf-8")),
                         segments_sha256=_digest(segments))
        _publish(held, [("preformatted-source.html", marked.encode("utf-8")), ("segments.jsonl", segments),
                        ("preformatted/provenance.json", canonical_bytes(record.to_dict()))],
                 replace_paths=("preformatted/provenance.json", "preformatted-source.html"))
