"""Independent rerender preparation over real PDFs; approvals are TEST ONLY."""
from __future__ import annotations

import errno
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from pypdf import PdfReader

from supertranslator.cli import main
from supertranslator.pdf_review import build_pdf_semantic_review_input
from tests.pdf_unit_fixtures import run_native_unit_pipeline


def api():
    return importlib.import_module("supertranslator.pdf_render")


def inventory(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in root.rglob("*")}


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    return run_native_unit_pipeline(tmp_path_factory.mktemp("render-native"))


@pytest.fixture
def source_run(tmp_path, completed):
    run, output = completed
    source = tmp_path / "old run 원본"
    shutil.copytree(run, source)
    old_output = tmp_path / "old output 결과"
    shutil.copytree(output, old_output)
    return source, old_output


def destination(root, name="새 렌더 with spaces"):
    run = root / ".supertranslator" / "runs" / name
    output = root / "translated-pdfs" / name
    run.mkdir(parents=True)
    output.parent.mkdir(exist_ok=True)
    return run, output


@pytest.mark.parametrize("name", ["fresh-render", "새 렌더 with spaces"])
def test_prepares_completed_pdf_for_new_render_without_changing_old_run(tmp_path, source_run, name):
    source, old_output = source_run
    # Unknown original children are neither consumed nor inherited.
    (source / "unrelated.txt").write_bytes(b"keep original")
    before = inventory(source), inventory(old_output)
    digest = build_pdf_semantic_review_input(source).semantic_input_sha256
    run, output = destination(tmp_path, name)
    assert main(["prepare-pdf-render", "--input-run-dir", str(source),
                 "--run-dir", str(run), "--output-dir", str(output)]) == 0
    assert build_pdf_semantic_review_input(run).semantic_input_sha256 == digest
    for name in ("review.json", "source.pdf", "assignments/.pdf-unit-binding.json"):
        assert (run / name).read_bytes() == (source / name).read_bytes()
    for name in ("staged-output", "layout.json", "pdf-qa.json", "pdf-layout-review.json", "qa-pages", "unrelated.txt", "document-summary.txt"):
        assert not (run / name).exists()
    assert main(["pdf-assemble", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    pdf = run / "staged-output/translated.pdf"
    assert pdf.read_bytes().startswith(b"%PDF-")
    assert "첫 번째" in "".join(p.extract_text() for p in PdfReader(pdf).pages)
    assert main(["pdf-qa", "finalize", "--run-dir", str(run), "--output-dir", str(output)]) != 0
    assert not output.exists()
    assert main(["pdf-qa", "prepare", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    assert main(["pdf-qa", "finalize", "--run-dir", str(run), "--output-dir", str(output)]) != 0
    assert not output.exists()
    from tests.test_pdf_qa import _write_passing_layout_review
    _write_passing_layout_review(run)  # TEST ONLY new all-page visual approval.
    rendered_bytes = pdf.read_bytes()
    assert main(["pdf-qa", "finalize", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    assert (output / "translated.pdf").read_bytes() == rendered_bytes
    assert (inventory(source), inventory(old_output)) == before


def test_prepares_figure_media_and_consumes_real_renderer(tmp_path):
    from tests.test_pdf_figure_review import publication_case
    from tests.test_pdf_qa import _write_passing_layout_review
    source, _ = publication_case(tmp_path / "source")
    old = source.run_dir
    assert main(["pdf-assemble", "--run-dir", str(old), "--output-dir", str(source.output_dir)]) == 0
    assert main(["pdf-qa", "prepare", "--run-dir", str(old), "--output-dir", str(source.output_dir)]) == 0
    _write_passing_layout_review(old)
    assert main(["pdf-qa", "finalize", "--run-dir", str(old), "--output-dir", str(source.output_dir)]) == 0
    (old / "media/unrelated.bin").write_bytes(b"not a required figure")
    before = inventory(old), inventory(source.output_dir)
    run, output = destination(tmp_path / "destination")
    assert api().prepare_pdf_render(old, run, output) == run
    assert (run / "media/figure-0001.png").read_bytes() == (old / "media/figure-0001.png").read_bytes()
    assert (run / "source.pdf").read_bytes() == (old / "source.pdf").read_bytes()
    assert (run / "review.json").read_bytes() == (old / "review.json").read_bytes()
    assert {path.name for path in (run / "media").iterdir()} == {"figure-0001.png"}
    assert build_pdf_semantic_review_input(run).semantic_input_sha256 == build_pdf_semantic_review_input(old).semantic_input_sha256
    assert main(["pdf-assemble", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    assert PdfReader(run / "staged-output/translated.pdf").pages[0].images
    assert (inventory(old), inventory(source.output_dir)) == before


@pytest.mark.parametrize("change", ["translations/zone-001.jsonl", "document.json", "assignments/.pdf-unit-binding.json",
    "glossary.json", "review.json", "source.pdf", "figure-inventory", "figure-media", "figure-source"])
def test_prepare_refuses_changed_approved_inputs(tmp_path, source_run, change):
    source, _ = source_run
    if change.startswith("figure-"):
        from tests.test_pdf_figure_review import publication_case
        source = publication_case(tmp_path / "figure")[0].run_dir
        change = {"figure-inventory": "figure-text-input.json", "figure-media": "media/figure-0001.png", "figure-source": "source.pdf"}[change]
    path = source / change
    if change == "review.json":
        value = json.loads(path.read_bytes())
        value["section_findings"] = {}
        path.write_text(json.dumps(value), encoding="utf-8")
    else:
        path.write_bytes(path.read_bytes() + b" ")
    before = inventory(source)
    run, output = destination(tmp_path)
    with pytest.raises(api().PdfRenderError):
        api().prepare_pdf_render(source, run, output)
    assert inventory(source) == before
    assert not (run / "review.json").exists()
    assert not output.exists()


def test_prepare_refuses_unresolved_review(tmp_path, source_run):
    source, _ = source_run
    path = source / "review.json"
    value = json.loads(path.read_bytes())
    value["section_findings"]["zone-001"][0]["verdict"] = "required-fix"
    value["unresolved_required"] = ["zone-001:semantic_fidelity"]
    path.write_text(json.dumps(value), encoding="utf-8")
    run, output = destination(tmp_path)
    assert main(["prepare-pdf-render", "--input-run-dir", str(source), "--run-dir", str(run), "--output-dir", str(output)]) == 4


@pytest.mark.parametrize("case", ["nonempty", "equal", "nested-source", "source-nested", "output-collision", "output-in-source", "output-in-run", "run-in-output"])
def test_prepare_refuses_nonempty_or_overlapping_destination(tmp_path, source_run, case):
    source, _ = source_run
    run, output = destination(tmp_path)
    if case == "nonempty": (run / "sentinel").write_bytes(b"unrelated")
    elif case == "equal": run = source
    elif case == "nested-source": run = source / "child"; run.mkdir()
    elif case == "source-nested": run = source.parent
    elif case == "output-collision": output.mkdir(); (output / "sentinel").write_bytes(b"unrelated")
    elif case == "output-in-source": output = source / "new-output"
    elif case == "output-in-run": output = run / "new-output"
    elif case == "run-in-output": output = run.parent
    before = inventory(tmp_path)
    with pytest.raises(api().PdfRenderError):
        api().prepare_pdf_render(source, run, output)
    assert inventory(tmp_path) == before


def link_directory(link, target):
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if result.returncode: pytest.skip("native junction creation unavailable")
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("location", ["source", "destination", "output"])
@pytest.mark.parametrize("entry", ["direct", "cli"])
def test_prepare_refuses_parent_traversal_after_link(tmp_path, source_run, location, entry):
    """Do not turn a linked/../ request into a different approved input or target."""
    source, _ = source_run
    run, output = destination(tmp_path)
    requested = {"source": source, "destination": run, "output": output}
    original = requested[location]
    other = tmp_path / "other tree" / "nested"
    other.mkdir(parents=True)
    (other / "sentinel").write_bytes(b"unrelated link target")
    linked = original.parent / "linked"
    link_directory(linked, other)
    requested[location] = linked / ".." / original.name
    before = inventory(tmp_path)
    if entry == "cli":
        assert main(["prepare-pdf-render", "--input-run-dir", str(requested["source"]),
                     "--run-dir", str(requested["destination"]),
                     "--output-dir", str(requested["output"])]) == 4
    else:
        with pytest.raises(api().PdfRenderError):
            api().prepare_pdf_render(requested["source"], requested["destination"], requested["output"])
    assert not (run / "review.json").exists()
    assert not output.exists()
    assert inventory(tmp_path) == before


@pytest.mark.parametrize("case", ["source-ancestor", "destination-ancestor", "output-ancestor", "input-child", "replacement", "review-content"])
def test_prepare_rejects_linked_inputs_and_replacement(tmp_path, source_run, monkeypatch, case):
    source, _ = source_run
    run, output = destination(tmp_path)
    if case == "replacement":
        _check_replacement_refusal(source, run, output, monkeypatch)
        return
    before = inventory(source)
    if case.endswith("ancestor"):
        target = tmp_path / "linked"
        if case == "source-ancestor":
            link_directory(target, source.parent); source = target / source.name
        elif case == "destination-ancestor":
            link_directory(target, run.parent); run = target / run.name
        else:
            link_directory(target, output.parent); output = target / output.name
    elif case == "input-child":
        path = source / "translations"
        path.rename(source / "original-translations")
        link_directory(path, source / "original-translations")
    else:
        import supertranslator.pdf_assemble as anchored
        original = anchored._publish_new_file
        changed = False
        def replace_during_publication(*args):
            nonlocal changed
            if not changed:
                changed = True
                path = source / "review.json"
                path.write_bytes(path.read_bytes() + b" ")
            return original(*args)
        monkeypatch.setattr(anchored, "_publish_new_file", replace_during_publication)
    with pytest.raises(api().PdfRenderError):
        api().prepare_pdf_render(source, run, output)
    if case not in {"input-child", "review-content"}: assert inventory(source) == before


def _check_replacement_refusal(source, run, output, monkeypatch, *, windows=None):
    """Exercise publication with a real directory replacement attempt."""
    import supertranslator.pdf_assemble as anchored
    windows = os.name == "nt" if windows is None else windows
    before = inventory(source)
    initial = run.stat()
    identity = (initial.st_dev, initial.st_ino)
    held = run.with_name("held-original")
    original = anchored._publish_new_file
    attempted = replaced = False
    rename_error = None
    def replace_during_publication(*args):
        nonlocal attempted, replaced, rename_error
        if not attempted:
            attempted = True
            try:
                run.rename(held)
            except OSError as error:
                rename_error = error
                raise
            run.mkdir()
            (run / "sentinel").write_bytes(b"foreign")
            replaced = True
        return original(*args)
    monkeypatch.setattr(anchored, "_publish_new_file", replace_during_publication)
    with pytest.raises(api().PdfRenderError) as caught:
        api().prepare_pdf_render(source, run, output)
    assert attempted, "replacement attempt was not reached"
    if rename_error is not None:
        # Do not treat an arbitrary refusal as attack protection. Windows may
        # refuse this directory rename while its descendants have open handles;
        # require the exact native access-denied exception from that syscall.
        assert windows, repr(rename_error)
        assert isinstance(rename_error, PermissionError), repr(rename_error)
        assert rename_error.errno == errno.EACCES, repr(rename_error)
        assert rename_error.winerror == 5, repr(rename_error)
        assert rename_error.filename == str(run), repr(rename_error)
        assert rename_error.filename2 == str(held), repr(rename_error)
        cause = caught.value
        while cause.__cause__ is not None:
            cause = cause.__cause__
        assert cause is rename_error
        assert str(caught.value) == f"cannot prepare approved PDF render inputs: {rename_error}"
        assert not replaced
        current = run.stat()
        assert (current.st_dev, current.st_ino) == identity
        assert not held.exists()
        assert not list(run.iterdir())  # Owned staging/public children rolled back.
    else:
        assert replaced, "replacement did not complete"
        assert (run / "sentinel").read_bytes() == b"foreign"
        assert {path.name for path in run.iterdir()} == {"sentinel"}
        original_run = held.stat()
        assert (original_run.st_dev, original_run.st_ino) == identity
        assert not list(held.iterdir())
    assert not (run / "review.json").exists()
    assert not output.exists()
    assert inventory(source) == before


def test_replacement_refusal_checks_native_denial_rollback(tmp_path, source_run, monkeypatch):
    """Model only the unavailable Windows rename syscall, not preparation."""
    source, _ = source_run
    run, output = destination(tmp_path)
    original = Path.rename
    def deny_held_run(path, target):
        if path == run:
            error = PermissionError(errno.EACCES, "Access is denied", str(path))
            error.winerror = 5
            error.filename2 = str(target)
            raise error
        return original(path, target)
    monkeypatch.setattr(Path, "rename", deny_held_run)
    _check_replacement_refusal(source, run, output, monkeypatch, windows=True)


def test_replacement_refusal_cannot_pass_before_attack(tmp_path, source_run, monkeypatch):
    """An unrelated early contract error must never count as a blocked attack."""
    source, _ = source_run
    run, output = destination(tmp_path)
    def unrelated_failure(*args):
        raise api().PdfRenderError("unrelated failure before publication")
    monkeypatch.setattr(api(), "prepare_pdf_render", unrelated_failure)
    with pytest.raises(AssertionError, match="replacement attempt was not reached"):
        _check_replacement_refusal(source, run, output, monkeypatch, windows=True)


@pytest.mark.parametrize("phase", ["copy", "publication", "interrupt"])
def test_prepare_failure_leaves_no_usable_partial_run(tmp_path, source_run, monkeypatch, phase):
    import supertranslator.pdf_assemble as anchored
    source, _ = source_run
    run, output = destination(tmp_path)
    sentinel = tmp_path / "sentinel"; sentinel.write_bytes(b"unrelated")
    before = inventory(source)
    original = anchored._create_anchored_binary_file if phase == "copy" else anchored._publish_new_file
    count = 0
    def fail(*args):
        nonlocal count
        count += 1
        if count == 3:
            (run / "foreign-sentinel").write_bytes(b"foreign")
            if phase == "interrupt": raise KeyboardInterrupt("injected interruption")
            raise OSError("injected failure")
        return original(*args)
    monkeypatch.setattr(anchored, "_create_anchored_binary_file" if phase == "copy" else "_publish_new_file", fail)
    with pytest.raises(KeyboardInterrupt if phase == "interrupt" else api().PdfRenderError):
        api().prepare_pdf_render(source, run, output)
    assert not (run / "review.json").exists()
    assert main(["pdf-assemble", "--run-dir", str(run), "--output-dir", str(output)]) != 0
    assert sentinel.read_bytes() == b"unrelated"
    assert (run / "foreign-sentinel").read_bytes() == b"foreign"
    assert inventory(source) == before
    assert set(p.name for p in run.iterdir()) == {"foreign-sentinel"}


def test_prepare_cli_retains_exact_allocated_destination_contract(tmp_path, source_run):
    source, _ = source_run
    run = tmp_path / "arbitrary-empty-run"; run.mkdir()
    output = tmp_path / "translated-pdfs" / run.name; output.parent.mkdir()
    assert main(["prepare-pdf-render", "--input-run-dir", str(source), "--run-dir", str(run), "--output-dir", str(output)]) == 4
    assert not list(run.iterdir())


@pytest.mark.parametrize("boundary", ["owned-return", "syscall"])
def test_prepare_cleans_interruption_after_real_review_publication(tmp_path, source_run, monkeypatch, boundary):
    """A late interruption must not leave the final approval marker behind."""
    import supertranslator.pdf_assemble as anchored
    source, _ = source_run
    run, output = destination(tmp_path)
    before = inventory(source)
    primary = KeyboardInterrupt("after real render publication")
    if boundary == "owned-return":
        original = anchored._publish_new_file
        def publish_then_interrupt(*args):
            result = original(*args)
            if args[3] == "review.json":
                try:
                    raise primary
                finally:
                    anchored._close_published_file(result)
            return result
        monkeypatch.setattr(anchored, "_publish_new_file", publish_then_interrupt)
    else:
        target = anchored if anchored._IS_WINDOWS else anchored.os
        name = "_windows_rename_open_file" if anchored._IS_WINDOWS else "link"
        original = getattr(target, name)
        def interrupt_syscall(*args, **kwargs):
            result = original(*args, **kwargs)
            if (args[2] if anchored._IS_WINDOWS else args[1]) == "review.json":
                raise primary
            return result
        monkeypatch.setattr(target, name, interrupt_syscall)
    with pytest.raises(KeyboardInterrupt) as caught:
        api().prepare_pdf_render(source, run, output)
    assert caught.value is primary
    assert not list(run.iterdir())
    assert inventory(source) == before


@pytest.mark.parametrize("collision", ["published-file", "reserved-output"])
def test_prepare_preserves_foreign_publication_collision(tmp_path, source_run, monkeypatch, collision):
    import supertranslator.pdf_assemble as anchored
    source, _ = source_run
    run, output = destination(tmp_path)
    before = inventory(source)
    original = anchored._publish_new_file
    foreign = run / "review.json" if collision == "published-file" else output
    fired = False
    def inject_collision(*args):
        nonlocal fired
        if args[3] == "review.json":
            fired = True
            foreign.write_bytes(b"foreign bytes never owned by this transaction")
        return original(*args)
    monkeypatch.setattr(anchored, "_publish_new_file", inject_collision)
    with pytest.raises(api().PdfRenderError):
        api().prepare_pdf_render(source, run, output)
    assert fired
    assert foreign.read_bytes() == b"foreign bytes never owned by this transaction"
    assert inventory(source) == before
    assert set(p.name for p in run.iterdir()) == ({"review.json"} if collision == "published-file" else set())
