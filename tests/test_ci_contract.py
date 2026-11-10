"""Inspect test arguments actually consumed by the existing native CI commands."""
from __future__ import annotations

from pathlib import Path
import re
import shlex

import pytest


WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"


def run_blocks(filename: str) -> list[str]:
    """Read only workflow run scalars, without introducing a YAML dependency."""
    lines = (WORKFLOWS / filename).read_text(encoding="utf-8").splitlines()
    blocks = []
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not match:
            continue
        scalar = match[2]
        if scalar not in {"|", ">-"}:
            blocks.append(scalar)
            continue
        body = []
        for following in lines[index + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= len(match[1]):
                break
            body.append(following.strip())
        blocks.append("\n".join(body) if scalar == "|" else " ".join(body))
    return blocks


def pytest_selections(filename: str) -> list[set[str]]:
    selections = []
    for block in run_blocks(filename):
        logical = block.replace("\\\n", " ").replace("`\n", " ")
        for command in logical.splitlines():
            if not re.match(r'^(?:"\$python"|& \$python|python)\s+(?:-I\s+)?-m\s+pytest\s', command):
                continue
            if "@selectors" in command:
                # PowerShell expands this exact array into the pytest invocation.
                assignment = re.search(r"\$selectors\s*=\s*@\((.*?)\)\s*\|\s*ForEach-Object\s*\{\s*Join-Path \$tests \$_\s*\}", block, re.S)
                assert assignment, "pytest selector array is not resolved from the tests directory"
                selected = set(re.findall(r"'([^']+\.py(?:::[^']+)?)'", assignment[1]))
            else:
                selected = {token.rsplit("/", 1)[-1] for token in shlex.split(command, comments=True)
                            if re.search(r"(?:/|^)test_[^/]+\.py(?:::.*)?$", token)}
            selections.append(selected)
    return selections


@pytest.mark.parametrize("shell_index", [0, 1], ids=["macOS", "Windows"])
def test_native_web_jobs_select_new_integrity_and_workflow_tests(shell_index):
    selections = pytest_selections("web-preformatted.yml")
    assert len(selections) == 2
    assert selections[shell_index] >= {
        "test_preformatted_analysis.py", "test_preformatted_projection.py",
        "test_preformatted_runtime.py", "test_preformatted_pipeline.py",
        "test_anchored_creation.py", "test_cli_contract.py", "test_qa.py",
        "test_pipeline.py", "test_plugin_layout.py", "test_renamed_identity.py", "test_reader.py",
        "test_web_review.py", "test_web_content.py", "test_render_workflow.py",
        "test_review_skill_contract.py", "test_ci_contract.py",
    }


def test_native_pdf_jobs_select_process_cleanup_tests():
    selections = pytest_selections("pdf-cross-platform.yml")
    assert len(selections) == 1
    assert selections[0] >= {
        "test_pdf_pipeline.py", "test_plugin_layout.py", "test_renamed_identity.py",
        "test_pdf_utf8_fixtures.py", "test_pdf_render.py", "test_poppler_bootstrap.py",
        "test_pdf_media.py",
        "test_pdf_acquire.py::test_windows_run_anchor_requests_only_directory_list_access",
        "test_pdf_acquire.py::test_windows_run_anchor_closes_handle_when_path_validation_fails",
        "test_pdf_pipeline.py::test_windows_root_anchor_enumerates_exact_unicode_children",
        "test_pdf_assemble.py::test_windows_native_relative_rename_moves_to_held_destination",
        "test_pdf_assemble.py::test_windows_native_relative_rename_never_clobbers_existing_destination",
        "test_pdf_assemble.py::test_windows_relative_mutation_directory_requests_delete_without_write",
        "test_pdf_assemble.py::test_anchored_acquisition_keeps_successful_handle_during_outer_exception",
        "test_pdf_qa.py::test_windows_qa_directory_mutation_verifies_identity_and_closes_handle",
        "test_pdf_qa.py::test_prior_qa_descendant_release_retains_original_snapshot",
        "test_pdf_qa.py::test_remove_qa_pages_uses_windows_held_handle_to_remove_empty_directory",
        "test_pdf_qa.py::test_remove_qa_pages_uses_windows_held_handle_move_and_closes_anchors",
        "test_pdf_qa.py::test_prepare_pdf_qa_regenerates_safe_prior_evidence_and_preserves_unrelated_files",
        "test_pdf_qa.py::test_prepare_pdf_qa_cleans_post_publication_base_exception_by_identity",
        "test_pdf_qa.py::test_prepare_pdf_qa_closes_new_record_before_restoring_prior_evidence",
        "test_pdf_qa.py::test_prepare_pdf_qa_restores_prior_evidence_after_interrupted_relocation",
        "test_pdf_qa.py::test_prepare_figure_free_master_review_races_fail_closed",
        "test_pdf_qa.py::test_prepare_figure_free_review_unchanged_finalizes_exact_artifacts",
        "test_pdf_qa.py::test_windows_publishes_nonempty_qa_directory_after_releasing_descendant_handles",
        "test_pdf_qa.py::test_windows_nonempty_qa_directory_publication_never_clobbers_destination",
        "test_pdf_pipeline.py::test_windows_finalize_durably_publishes_exact_reviewed_output",
        "test_pdf_pipeline.py::test_windows_finalize_failure_cleanup_preserves_error_and_retries_immediately",
    }
