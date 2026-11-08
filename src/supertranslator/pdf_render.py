"""Prepare exact approved PDF inputs for an independent, freshly reviewed render."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

import supertranslator.pdf_assemble as anchored
from supertranslator.pdf_figure_review import (
    FIGURE_TEXT_INPUT_NAME,
    hold_pdf_figure_inputs,
    validate_current_pdf_figure_review,
)
from supertranslator.pdf_report import _semantic_review_from_value, _zone_snapshot
from supertranslator.pdf_qa import PdfQAFailure
from supertranslator.pdf_review import (
    _master_review_from_bytes,
    hold_pdf_semantic_inputs,
    validate_pdf_semantic_review_snapshot,
)


class PdfRenderError(ValueError):
    """Approved inputs or fresh render destinations are unsafe or inconsistent."""


@dataclass(slots=True)
class _ApprovedInputs:
    semantic: Any
    figures: Any
    review_file: Any
    review_bytes: bytes
    payloads: dict[str, bytes]

    def verify(self) -> None:
        self.semantic.verify()
        self.figures.verify()
        run = self.semantic.run_anchor
        anchored._verify_anchored_evidence(run, {"review.json": self.review_file})
        if anchored._read_opened_bytes(self.review_file, run.path / "review.json", "PDF master review") != self.review_bytes:
            raise PdfRenderError("PDF master review changed content during preparation")


@contextmanager
def _hold_approved_inputs(run: Any) -> Iterator[_ApprovedInputs]:
    """Use existing approval validators over one exact held source snapshot."""
    with ExitStack() as stack:
        semantic = stack.enter_context(hold_pdf_semantic_inputs(run))
        # This also validates source.pdf length/hash when there are no figures.
        figures = stack.enter_context(hold_pdf_figure_inputs(run))
        review_file = anchored._open_anchored_input_file(run, "review.json", "PDF master review")
        stack.callback(anchored._close_opened_file, review_file)
        review_bytes = anchored._read_opened_bytes(review_file, run.path / "review.json", "PDF master review")
        review = _master_review_from_bytes(review_bytes)
        validate_pdf_semantic_review_snapshot(semantic, review)
        zones = {Path(path).stem: json.loads(payload)
                 for path, payload in sorted(semantic.payloads.items()) if path.startswith("zones/")}
        _zone_snapshot(zones)
        _semantic_review_from_value(review, set(zones), None)
        if review["unresolved_required"]:
            raise PdfRenderError("semantic review has unresolved required findings")
        if FIGURE_TEXT_INPUT_NAME in semantic.payloads:
            validate_current_pdf_figure_review(
                figures,
                inventory_bytes=semantic.payloads[FIGURE_TEXT_INPUT_NAME],
                review_value=review["figure_text_review"],
            )
        anchored._semantic_snapshot_assembly_values(semantic, run)
        payloads = dict(semantic.payloads)
        payloads["source.pdf"] = figures.source_pdf_bytes
        payloads["review.json"] = review_bytes
        payloads.update({f"media/{name}": payload for name, payload in figures.media_file_payloads.items()})
        inputs = _ApprovedInputs(semantic, figures, review_file, review_bytes, payloads)
        inputs.verify()
        yield inputs
        inputs.verify()


def _hold_existing_path(path: Path, stack: ExitStack, anchors: list[Any]) -> Any:
    """Open all lexical ancestors without erasing link/reparse evidence."""
    parent = anchored._open_directory_anchor(Path(path.parts[0]), "render filesystem root")
    stack.callback(parent.close)
    anchors.append(parent)
    for name in path.parts[1:]:
        parent = anchored._open_existing_child_directory(parent, name, "render path")
        stack.callback(parent.close)
        anchors.append(parent)
    return parent


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _clean_owned_files(directory: Any) -> None:
    for name, identity in reversed(tuple(directory.owned_files.items())):
        anchored._remove_owned_file(directory, name, anchored._PublishedFile(identity))


def prepare_pdf_render(input_run_dir: Path, run_dir: Path, output_dir: Path) -> Path:
    """Copy approved inputs only; never inherit old layout or visual approvals.

    ``run_dir`` must already be allocated and empty; ``output_dir`` is reserved,
    not created here. The CLI additionally retains the normal allocator contract.
    """
    requested_paths = tuple(Path(path) for path in (input_run_dir, run_dir, output_dir))
    # abspath collapses '..' before the no-follow walk can inspect a preceding
    # link/junction. Refuse traversal while that lexical evidence is still intact.
    if any(".." in path.parts for path in requested_paths):
        raise PdfRenderError("PDF render paths must not contain parent traversal ('..')")
    source_path, run_path, output_path = (
        Path(os.path.abspath(os.fspath(path))) for path in requested_paths
    )
    if any(_overlap(left, right) for left, right in (
        (source_path, run_path), (source_path, output_path), (run_path, output_path)
    )):
        raise PdfRenderError("source run, new run, and reserved output must not overlap")

    staging_name = None
    staging = destination = None
    staged_directories: dict[str, Any] = {}
    published_directories: dict[str, Any] = {}
    published_files: list[tuple[Any, str, Any]] = []
    completed = False
    try:
        with ExitStack() as stack:
            ancestors: list[Any] = []
            source = _hold_existing_path(source_path, stack, ancestors)
            destination = _hold_existing_path(run_path, stack, ancestors)
            output_parent = _hold_existing_path(output_path.parent, stack, ancestors)

            def verify_locations() -> None:
                for ancestor in ancestors:
                    ancestor.verify_visible()
                anchored._require_anchored_name_absent(output_parent, output_path.name)

            verify_locations()
            if anchored._anchored_directory_names(destination):
                raise PdfRenderError("new PDF render run must be empty")

            # Cleanup remains inside the ancestor lifetimes, including on interrupts.
            try:
                with _hold_approved_inputs(source) as inputs:
                    staging_name, staging = anchored._create_unique_child_directory(
                        destination, ".pdf-render-preparing-", "private PDF render inputs"
                    )
                    for relative, payload in sorted(inputs.payloads.items()):
                        parts = relative.split("/")
                        directory = staging
                        if len(parts) == 2:
                            name = parts[0]
                            if name not in staged_directories:
                                staged_directories[name] = anchored._create_child_directory(staging, name, "private PDF render inputs")
                            directory = staged_directories[name]
                        opened = anchored._create_anchored_binary_file(directory, parts[-1])
                        try:
                            opened.stream.write(payload)
                            anchored._finalize_opened_file(opened, f"private PDF render input {relative}")
                        finally:
                            anchored._close_opened_file(opened)

                    with _hold_approved_inputs(staging) as staged:
                        if staged.payloads != inputs.payloads:
                            raise PdfRenderError("staged PDF render inputs differ from approved source bytes")
                        staged.verify()
                    inputs.verify()
                    verify_locations()
                    if anchored._anchored_directory_names(destination) != [staging_name]:
                        raise PdfRenderError("new PDF render run changed child set")
                    for name in sorted(staged_directories):
                        published_directories[name] = anchored._create_child_directory(destination, name, "prepared PDF render inputs")

                    # Without review.json no partial publication can be assembled
                    # through the approval contract. Publish that marker last.
                    ordered = sorted(name for name in inputs.payloads if name != "review.json") + ["review.json"]
                    for relative in ordered:
                        inputs.verify()
                        verify_locations()
                        parts = relative.split("/")
                        private = staged_directories[parts[0]] if len(parts) == 2 else staging
                        public = published_directories[parts[0]] if len(parts) == 2 else destination
                        # Track the exact owned inode before calling publication:
                        # an interrupt after its syscall/return must also roll back.
                        published_files.append((
                            public, parts[-1],
                            anchored._PublishedFile(private.owned_files[parts[-1]]),
                        ))
                        published = anchored._publish_new_file(private, parts[-1], public, parts[-1])
                        published_files[-1] = (public, parts[-1], published)
                    with _hold_approved_inputs(destination) as prepared:
                        if prepared.payloads != inputs.payloads:
                            raise PdfRenderError("published PDF render inputs differ from approved source bytes")
                        inputs.verify()
                        verify_locations()
                completed = True
            finally:
                if not completed:
                    for directory, name, published in reversed(published_files):
                        anchored._remove_owned_file(directory, name, published)
                for _, _, published in published_files:
                    anchored._close_published_file(published)
                for name, directory in reversed(tuple(published_directories.items())):
                    if not completed:
                        anchored._remove_owned_directory(destination, name, directory.identity, child=directory)
                    directory.close()
                for name, directory in reversed(tuple(staged_directories.items())):
                    _clean_owned_files(directory)
                    anchored._remove_owned_directory(staging, name, directory.identity, child=directory)
                    directory.close()
                if staging is not None:
                    _clean_owned_files(staging)
                    anchored._remove_owned_directory(destination, staging_name, staging.identity, child=staging)
                    staging.close()
    except PdfRenderError:
        raise
    except (anchored.PdfAssemblyError, PdfQAFailure, ValueError, OSError, TypeError, KeyError) as error:
        raise PdfRenderError(f"cannot prepare approved PDF render inputs: {error}") from error
    return run_path


__all__ = ["PdfRenderError", "prepare_pdf_render"]
