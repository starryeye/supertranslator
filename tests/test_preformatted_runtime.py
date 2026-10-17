"""Held preformatted lifecycle and acceptance-fence behavior."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from web_translator.preformatted_analysis import analyze_preformatted, build_classification_packages
from web_translator.preformatted_contract import canonical_bytes, canonical_sha256


SOURCE = (b'<html><head></head><body><pre id="manual">Read this manual.\r\n'
          b'+---+\r\n| A |</pre><pre><code>A\r\nB</code></pre></body></html>')


def _api():
    assert importlib.util.find_spec("web_translator.preformatted_runtime") is not None, "held runtime is missing"
    from web_translator import preformatted_runtime
    return preformatted_runtime


def _run(tmp_path, source=SOURCE):
    run = tmp_path / "run"
    run.mkdir()
    (run / "assets").mkdir()
    (run / "source.html").write_bytes(source)
    (run / "assets/theme.css").write_bytes(b"body { color: black; }")
    capture = {"requested_url": "https://example.com/", "final_url": "https://example.com/",
               "captured_at": "2026-10-17T00:00:00Z", "asset_map": {"https://example.com/theme.css": "assets/theme.css"},
               "critical_assets": ["assets/theme.css"], "optional_assets": [], "missing_optional_assets": [],
               "fingerprints": {name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                                for name in ("source.html", "assets/theme.css")}}
    (run / "capture.json").write_bytes(canonical_bytes(capture))
    return run


def _review(run):
    analysis = analyze_preformatted((run / "source.html").read_bytes().decode())
    packages = build_classification_packages(analysis)
    payload = {"schema_version": "1.0", "source_sha256": analysis.source_sha256,
               "analysis_sha256": canonical_sha256(analysis.to_dict()),
               "package_sha256": {p.id: canonical_sha256(p.to_dict()) for p in packages},
               "blocks": [{"id": "block-000001", "pre_id": "pre-000001", "line_ids": ["line-000001"],
                           "role": "prose", "evidence": "Read", "metadata": {}, "literal_spans": []},
                          {"id": "block-000002", "pre_id": "pre-000001", "line_ids": ["line-000002", "line-000003"],
                           "role": "literal-table", "evidence": "+---+", "metadata": {}, "literal_spans": []}],
               "unresolved_required": []}
    (run / "preformatted/review.json").write_bytes(canonical_bytes(payload))


def _project(run, api):
    assert api.prepare_preformatted_run(run)
    _review(run)
    api.materialize_preformatted_run(run)


def _snapshot(run):
    return {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob("*") if p.is_file()}


def test_processing_source_selects_legacy_only_without_preformatted_state(tmp_path):
    # Removing the state fence would incorrectly select raw capture after analysis.
    api = _api()
    run = _run(tmp_path, b"<html><body><p>Ordinary page</p></body></html>")
    before = _snapshot(run)
    assert api.prepare_preformatted_run(run) is False
    assert _snapshot(run) == before
    for phase in ("extract", "assemble", "qa"):
        with api.hold_processing_source(run, phase=phase) as source:
            assert source.path == run / "source.html"
            assert source.normalization is None
            assert source.generated_critical_assets == ()
            source.verify()
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="translate"):
            pass


def test_preformatted_lifecycle_never_mutates_raw_capture(tmp_path):
    # Catches extraction of raw source, missing transport, or premature assembly.
    api = _api()
    run = _run(tmp_path)
    raw = _snapshot(run)
    assert api.prepare_preformatted_run(run)
    for phase in ("extract", "assemble", "qa"):
        with pytest.raises(ValueError):
            with api.hold_processing_source(run, phase=phase):
                pass
    _review(run)
    api.materialize_preformatted_run(run)
    projected = _snapshot(run)
    assert api.prepare_preformatted_run(run)
    api.materialize_preformatted_run(run)
    assert _snapshot(run) == projected
    for phase in ("assemble", "qa"):
        with pytest.raises(ValueError):
            with api.hold_processing_source(run, phase=phase):
                pass
    with api.hold_processing_source(run, phase="extract") as source:
        assert source.path == run / "preformatted-source.html"
        assert source.normalization.translated_blocks == 1
        assert source.generated_critical_assets[0]["path"].startswith("assets/wt-preformatted-")
    api.extract_preformatted_run(run)
    extracted = _snapshot(run)
    api.extract_preformatted_run(run)
    assert _snapshot(run) == extracted
    for name, data in raw.items():
        assert (run / name).read_bytes() == data
    record = json.loads((run / "preformatted/provenance.json").read_bytes())
    assert record["phase"] == "extracted"
    assert record["marked_sha256"] == hashlib.sha256((run / "preformatted-source.html").read_bytes()).hexdigest()
    assert record["segments_sha256"] == hashlib.sha256((run / "segments.jsonl").read_bytes()).hexdigest()
    assert "Read this manual." in (run / "segments.jsonl").read_text()
    marked = (run / "preformatted-source.html").read_bytes()
    assert b"A&#13;\nB" in marked
    output = tmp_path / "index.html"
    output.write_bytes(marked)
    for phase in ("extract", "assemble", "qa"):
        with api.hold_processing_source(run, phase=phase) as source:
            api.verify_preformatted_output(source, output)
            assert BeautifulSoup(marked, "html.parser").find("code").text == "A\r\nB"
            output.write_bytes(marked.replace(b"A&#13;\nB", b"A\nB"))
            with pytest.raises(ValueError):
                api.verify_preformatted_output(source, output)
            output.write_bytes(marked)


@pytest.mark.parametrize("damage", ["orphan-source", "orphan-css", "missing-review", "analysis", "package", "review",
                                     "source", "capture", "projection", "segments", "css", "extra-state", "extra-package", "extra-css", "extra-asset"])
def test_stale_or_partial_state_never_falls_back(tmp_path, damage):
    # Every protected byte/set participates in acceptance; nothing falls back to raw.
    api = _api()
    run = _run(tmp_path)
    if damage == "orphan-source":
        (run / "preformatted-source.html").write_bytes(b"orphan")
    elif damage == "orphan-css":
        (run / "assets/wt-preformatted-0000000000000000.css").write_bytes(b"orphan")
    else:
        _project(run, api)
        api.extract_preformatted_run(run)
        css = next((run / "assets").glob("wt-preformatted-*.css"))
        paths = {"analysis": run / "preformatted/analysis.json", "package": run / "preformatted/packages/package-000001.json",
                 "review": run / "preformatted/review.json", "source": run / "source.html", "capture": run / "capture.json",
                 "projection": run / "preformatted-source.html", "segments": run / "segments.jsonl", "css": css,
                 "extra-state": run / "preformatted/unclaimed.json", "extra-package": run / "preformatted/packages/extra.json",
                 "extra-css": run / "assets/wt-preformatted-0000000000000000.css", "extra-asset": run / "assets/unclaimed.css"}
        if damage == "missing-review":
            (run / "preformatted/review.json").unlink()
        elif damage == "capture":
            payload = json.loads(paths[damage].read_bytes())
            payload["fingerprints"]["source.html"] = "0" * 64
            paths[damage].write_bytes(canonical_bytes(payload))
        else:
            target = paths[damage]
            target.write_bytes(target.read_bytes() + b" " if target.exists() else b"extra")
    for action in (api.prepare_preformatted_run, api.materialize_preformatted_run, api.extract_preformatted_run):
        with pytest.raises(ValueError):
            action(run)
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="qa"):
            pass


@pytest.mark.parametrize("operation,steps", [("prepare", 2), ("materialize", 3), ("extract", 3)])
@pytest.mark.parametrize("exception", [OSError, KeyboardInterrupt])
def test_publication_failure_restores_only_owned_artifacts(tmp_path, monkeypatch, operation, steps, exception):
    # Failure at each publication boundary must restore prior bytes, never a false fence.
    api = _api()
    for step in range(1, steps + 1):
        parent = tmp_path / str(step)
        parent.mkdir()
        run = _run(parent)
        if operation != "prepare":
            api.prepare_preformatted_run(run)
            _review(run)
        if operation == "extract":
            api.materialize_preformatted_run(run)
        before = _snapshot(run)
        before_directories = {p.relative_to(run) for p in run.rglob("*") if p.is_dir()}
        original = api.anchored._publish_new_file
        counter = 0
        publications = []

        def fail_once(*args):
            nonlocal counter
            counter += 1
            publications.append((args[1], args[3]))
            if counter == step:
                raise exception("injected publication failure")
            return original(*args)

        with monkeypatch.context() as patch:
            patch.setattr(api.anchored, "_publish_new_file", fail_once)
            with pytest.raises((ValueError, exception)) as failure:
                getattr(api, f"{operation}_preformatted_run")(run)
        assert _snapshot(run) == before, f"step {step}: {failure.value}; {publications}"
        assert {p.relative_to(run) for p in run.rglob("*") if p.is_dir()} == before_directories
        assert not any(p.name.startswith(".preformatted-") for p in run.iterdir())


@pytest.mark.parametrize("mutation", ["replace", "ancestor", "symlink", "hardlink", "edit"])
def test_held_inputs_reject_replacement_and_reparse(tmp_path, mutation):
    # A matching digest does not authorize a replaced inode or changed ancestry.
    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    api.extract_preformatted_run(run)
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="qa") as source:
            path = run / "preformatted/review.json"
            data = path.read_bytes()
            if mutation == "ancestor":
                run.rename(tmp_path / "moved")
                run.mkdir()
            elif mutation == "edit":
                path.write_bytes(data + b" ")
            elif mutation == "hardlink":
                os.link(path, tmp_path / "alias")
            else:
                path.unlink()
                alternate = tmp_path / "alternate"
                alternate.write_bytes(data)
                if mutation == "symlink":
                    path.symlink_to(alternate)
                else:
                    path.write_bytes(data)
            source.verify()


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows held-handle rename/reparse semantics")
def test_native_windows_held_inputs_reject_rename(tmp_path):
    test_held_inputs_reject_replacement_and_reparse(tmp_path, "ancestor")


def test_captured_css_reserved_selectors_rejected_before_analysis(tmp_path):
    # HTML-only collision checks miss separately captured stylesheets.
    api = _api()
    run = _run(tmp_path)
    css = run / "assets/theme.css"
    css.write_bytes(b"[data-wt-preformatted-root] { display: none; }")
    capture = json.loads((run / "capture.json").read_bytes())
    capture["fingerprints"]["assets/theme.css"] = hashlib.sha256(css.read_bytes()).hexdigest()
    (run / "capture.json").write_bytes(canonical_bytes(capture))
    with pytest.raises(ValueError, match="reserved"):
        api.prepare_preformatted_run(run)
    assert not (run / "preformatted").exists()


@pytest.mark.parametrize("operation", ["prepare", "materialize", "extract"])
def test_publication_rechecks_child_sets_after_last_publish(tmp_path, monkeypatch, operation):
    # New unbound files added during publication must invalidate the final fence.
    api = _api()
    run = _run(tmp_path)
    if operation != "prepare":
        api.prepare_preformatted_run(run)
        _review(run)
    if operation == "extract":
        api.materialize_preformatted_run(run)
    original = api.anchored._publish_new_file
    injected = False

    def add_foreign_file(*args):
        nonlocal injected
        result = original(*args)
        if not injected and args[3] in {"analysis.json", "provenance.json"}:
            injected = True
            (run / "preformatted/packages/foreign.json").write_bytes(b"foreign")
        return result

    monkeypatch.setattr(api.anchored, "_publish_new_file", add_foreign_file)
    with pytest.raises(ValueError):
        getattr(api, f"{operation}_preformatted_run")(run)
    assert (run / "preformatted/packages/foreign.json").read_bytes() == b"foreign"
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="qa"):
            pass


@pytest.mark.parametrize("relative", ["capture.json", "source.html", "assets/theme.css", "preformatted/analysis.json",
                                      "preformatted/review.json", "preformatted/packages/package-000001.json",
                                      "preformatted/provenance.json", "preformatted-source.html", "segments.jsonl"])
def test_each_held_input_is_byte_and_identity_bound(tmp_path, relative):
    # The lease must not merely protect the selected HTML file.
    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    api.extract_preformatted_run(run)
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="qa") as source:
            path = run / relative
            path.write_bytes(path.read_bytes() + b" ")
            source.verify()


@pytest.mark.parametrize("damage", ["extra-key", "phase", "phase-type", "missing-marked", "css-path", "summary", "evidence", "package"])
def test_projection_record_is_strict_and_source_bound(tmp_path, damage):
    # A modified wire field cannot manufacture a valid processing source.
    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    api.extract_preformatted_run(run)
    path = run / "preformatted/provenance.json"
    record = json.loads(path.read_bytes())
    if damage == "extra-key":
        record["unexpected"] = True
    elif damage == "phase":
        record["phase"] = "approved"
    elif damage == "phase-type":
        record["phase"] = []
    elif damage == "missing-marked":
        record["marked_sha256"] = None
    elif damage == "css-path":
        record["css_path"] = "../outside.css"
    elif damage == "summary":
        record["summary"]["translated_blocks"] = True
    elif damage == "evidence":
        record["evidence"]["blocks"] = []
    else:
        record["package_sha256"] = {"package-000002": "0" * 64}
    path.write_bytes(canonical_bytes(record))
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="qa"):
            pass


def test_review_file_bytes_are_locked_independently_of_canonical_digest(tmp_path):
    # Pretty review JSON is valid; any later byte edit requires a fresh run.
    api = _api()
    run = _run(tmp_path)
    api.prepare_preformatted_run(run)
    _review(run)
    path = run / "preformatted/review.json"
    review = json.loads(path.read_bytes())
    path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    api.materialize_preformatted_run(run)
    record = json.loads((run / "preformatted/provenance.json").read_bytes())
    assert record["review_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record["summary"]["review_sha256"] == canonical_sha256(review)
    assert record["review_sha256"] != record["summary"]["review_sha256"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        api.materialize_preformatted_run(run)


def test_failed_publication_does_not_remove_foreign_replacement(tmp_path, monkeypatch):
    # Ownership cleanup must not overwrite/delete a raced different inode.
    api = _api()
    run = _run(tmp_path)
    api.prepare_preformatted_run(run)
    _review(run)
    original = api.anchored._publish_new_file

    def replace_after_publication(*args):
        result = original(*args)
        if args[3] == "preformatted-source.html":
            target = run / "preformatted-source.html"
            target.unlink()
            target.write_bytes(b"foreign replacement")
            api.anchored._close_published_file(result)
            raise KeyboardInterrupt("outer interruption after publish")
        return result

    monkeypatch.setattr(api.anchored, "_publish_new_file", replace_after_publication)
    with pytest.raises(KeyboardInterrupt):
        api.materialize_preformatted_run(run)
    assert (run / "preformatted-source.html").read_bytes() == b"foreign replacement"
    assert not (run / "preformatted/provenance.json").exists()


def test_analyzed_state_rejects_orphan_segments(tmp_path):
    api = _api()
    run = _run(tmp_path)
    api.prepare_preformatted_run(run)
    _review(run)
    (run / "segments.jsonl").write_bytes(b"stale segments")
    with pytest.raises(ValueError):
        api.materialize_preformatted_run(run)
    assert not (run / "preformatted/provenance.json").exists()


@pytest.mark.parametrize("fail_publication", [False, True])
def test_all_literal_extraction_preserves_exact_empty_segments(tmp_path, monkeypatch, fail_publication):
    # Zero targets is a valid extraction shape, not permission to invent bytes.
    api = _api()
    run = _run(tmp_path)
    api.prepare_preformatted_run(run)
    _review(run)
    review_path = run / "preformatted/review.json"
    review = json.loads(review_path.read_bytes())
    review["blocks"][0]["role"] = "literal-layout"
    review_path.write_bytes(canonical_bytes(review))
    api.materialize_preformatted_run(run)
    before = _snapshot(run)
    if fail_publication:
        original = api.anchored._publish_new_file
        failed = False

        def fail_segments(*args):
            nonlocal failed
            if args[3] == "segments.jsonl" and not failed:
                failed = True
                raise OSError("injected empty-segment publication failure")
            return original(*args)

        monkeypatch.setattr(api.anchored, "_publish_new_file", fail_segments)
        with pytest.raises(ValueError, match="injected empty-segment"):
            api.extract_preformatted_run(run)
        assert _snapshot(run) == before
        return
    api.extract_preformatted_run(run)
    assert (run / "segments.jsonl").read_bytes() == b""
    record = json.loads((run / "preformatted/provenance.json").read_bytes())
    assert record["phase"] == "extracted"
    assert record["segments_sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    with api.hold_processing_source(run, phase="qa") as source:
        assert source.normalization.translated_blocks == 0
        source.verify()


def test_held_output_verification_preserves_real_assembly_crlf(tmp_path):
    # The verifier must decode held bytes, not normalize newlines with read_text.
    from web_translator.assemble import assemble_page
    from web_translator.models import Translation, read_segments

    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    api.extract_preformatted_run(run)
    segments = read_segments(run / "segments.jsonl")
    with api.hold_processing_source(run, phase="assemble") as source:
        output = assemble_page(source.path, {item.id: item for item in segments},
                               {item.id: Translation(item.id, item.source_text) for item in segments},
                               {}, tmp_path / "output", "https://example.com/")
        api.verify_preformatted_output(source, output)
        assert BeautifulSoup(output.read_bytes().decode("utf-8"), "html.parser").find("code").text == "A\r\nB"
    with pytest.raises(ValueError, match="closed"):
        source.verify()


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows anchored publication and replacement handles")
def test_native_windows_lifecycle_and_replacement(tmp_path):
    # No mocked platform flag: the complete lifecycle uses actual NT handles.
    test_preformatted_lifecycle_never_mutates_raw_capture(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows directory reparse points")
def test_native_windows_reparse_directory_rejected(tmp_path):
    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    original = run / "preformatted"
    alternate = tmp_path / "outside"
    original.rename(alternate)
    try:
        original.symlink_to(alternate, target_is_directory=True)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("native Windows symlink privilege unavailable")
        raise
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="extract"):
            pass


def test_legacy_source_does_not_apply_preformatted_css_policy(tmp_path):
    # No eligible pre means no generated annotation or new source-CSS policy.
    api = _api()
    run = _run(tmp_path, b"<html><body><p>Ordinary page</p></body></html>")
    css = run / "assets/theme.css"
    css.write_bytes(b"[data-wt-preformatted-root] { color: black; }")
    path = run / "capture.json"
    capture = json.loads(path.read_bytes())
    capture["fingerprints"]["assets/theme.css"] = hashlib.sha256(css.read_bytes()).hexdigest()
    path.write_bytes(canonical_bytes(capture))
    before = _snapshot(run)
    assert api.prepare_preformatted_run(run) is False
    with api.hold_processing_source(run, phase="qa") as source:
        assert source.normalization is None
    assert _snapshot(run) == before


@pytest.mark.parametrize("name", ["source.html", "segments.jsonl"])
@pytest.mark.parametrize("mutation", ["replacement", "hardlink"])
def test_staged_extraction_never_adopts_replaced_or_linked_outputs(tmp_path, monkeypatch, name, mutation):
    # Equal bytes do not establish ownership of a different inode after extraction.
    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    before = _snapshot(run)
    real_extract = api.extract_segments
    observed = {}

    def change_after_real_extraction(source_path, segments_path):
        result = real_extract(source_path, segments_path)
        target = source_path.parent / name
        payload = target.read_bytes()
        foreign = tmp_path / "foreign-output"
        if mutation == "replacement":
            foreign.write_bytes(payload)
            foreign_identity = (foreign.stat().st_dev, foreign.stat().st_ino)
            assert foreign_identity != (target.stat().st_dev, target.stat().st_ino)
            os.replace(foreign, target)
            observed["foreign"] = target
            observed["identity"] = foreign_identity
        else:
            os.link(target, foreign)
            observed["foreign"] = foreign
            observed["identity"] = (foreign.stat().st_dev, foreign.stat().st_ino)
        observed["bytes"] = payload
        return result

    monkeypatch.setattr(api, "extract_segments", change_after_real_extraction)
    with pytest.raises(ValueError):
        api.extract_preformatted_run(run)
    foreign = observed["foreign"]
    assert foreign.read_bytes() == observed["bytes"]
    assert (foreign.stat().st_dev, foreign.stat().st_ino) == observed["identity"]
    assert {key: value for key, value in _snapshot(run).items() if not key.startswith(".preformatted-")} == before
    assert json.loads((run / "preformatted/provenance.json").read_bytes())["phase"] == "projected"
    if mutation == "replacement":
        # Foreign staging survives cleanup and therefore cannot become a usable run.
        with pytest.raises(ValueError):
            with api.hold_processing_source(run, phase="extract"):
                pass
    else:
        assert not any(p.name.startswith(".preformatted-") for p in run.iterdir())


@pytest.mark.parametrize("after_extraction", [False, True])
@pytest.mark.parametrize("interrupt", [False, True])
def test_staged_extraction_exception_cleans_only_preowned_outputs(tmp_path, monkeypatch, after_extraction, interrupt):
    # Outputs must be owned before extraction can raise, not registered afterward.
    from web_translator.extract import ExtractionError

    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    before = _snapshot(run)
    real_extract = api.extract_segments
    failure = KeyboardInterrupt("extraction interrupted") if interrupt else ExtractionError("extraction failed")

    def fail_extraction(source_path, segments_path):
        if after_extraction:
            real_extract(source_path, segments_path)
        raise failure

    monkeypatch.setattr(api, "extract_segments", fail_extraction)
    with pytest.raises(type(failure)) as caught:
        api.extract_preformatted_run(run)
    assert caught.value is failure
    assert _snapshot(run) == before
    assert not any(p.name.startswith(".preformatted-") for p in run.iterdir())


@pytest.mark.parametrize("name", ["source.html", "segments.jsonl"])
def test_staged_foreign_replacement_survives_extractor_interruption(tmp_path, monkeypatch, name):
    # Exceptional exit before validation cannot promote or delete a foreign output.
    api = _api()
    run = _run(tmp_path)
    _project(run, api)
    before = _snapshot(run)
    real_extract = api.extract_segments
    failure = KeyboardInterrupt("interrupted after foreign replacement")
    observed = {}

    def replace_and_interrupt(source_path, segments_path):
        real_extract(source_path, segments_path)
        target = source_path.parent / name
        foreign = tmp_path / "foreign-output"
        foreign.write_bytes(target.read_bytes())
        observed["identity"] = (foreign.stat().st_dev, foreign.stat().st_ino)
        observed["bytes"] = foreign.read_bytes()
        os.replace(foreign, target)
        observed["target"] = target
        raise failure

    monkeypatch.setattr(api, "extract_segments", replace_and_interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        api.extract_preformatted_run(run)
    assert caught.value is failure
    target = observed["target"]
    assert target.read_bytes() == observed["bytes"]
    assert (target.stat().st_dev, target.stat().st_ino) == observed["identity"]
    assert {key: value for key, value in _snapshot(run).items() if not key.startswith(".preformatted-")} == before


def test_legacy_extract_source_alias_is_a_read_only_held_input(tmp_path):
    # Existing legacy extraction replaces a private copy, never writes this inode.
    api = _api()
    run = _run(tmp_path, b"<html><body><p>Ordinary page</p></body></html>")
    alias = tmp_path / "outside.html"
    os.link(run / "source.html", alias)
    original = _snapshot(run)
    original_identity = (alias.stat().st_dev, alias.stat().st_ino)
    with api.hold_processing_source(run, phase="extract") as source:
        assert source.path == run / "source.html"
        assert source.normalization is None
        assert source.path.read_bytes() == b"<html><body><p>Ordinary page</p></body></html>"
        source.verify()
    assert _snapshot(run) == original
    assert alias.read_bytes() == b"<html><body><p>Ordinary page</p></body></html>"
    assert (alias.stat().st_dev, alias.stat().st_ino) == original_identity


@pytest.mark.parametrize("operation", ["assemble", "qa", "prepare"])
def test_legacy_source_alias_is_not_permitted_outside_extract_selection(tmp_path, operation):
    # Compatibility is not a general waiver for linked input evidence.
    api = _api()
    run = _run(tmp_path)
    alias = tmp_path / "outside.html"
    os.link(run / "source.html", alias)
    before = _snapshot(run)
    with pytest.raises(ValueError, match="hardlinks"):
        if operation == "prepare":
            api.prepare_preformatted_run(run)
        else:
            with api.hold_processing_source(run, phase=operation):
                pass
    assert _snapshot(run) == before
    assert alias.read_bytes() == SOURCE


@pytest.mark.parametrize("state", ["analyzed", "projected", "extracted", "orphan-source", "orphan-css", "partial", "staging"])
def test_preformatted_state_never_gains_legacy_source_alias_permission(tmp_path, state):
    api = _api()
    run = _run(tmp_path)
    if state in {"analyzed", "projected", "extracted"}:
        api.prepare_preformatted_run(run)
        if state != "analyzed":
            _review(run)
            api.materialize_preformatted_run(run)
        if state == "extracted":
            api.extract_preformatted_run(run)
    elif state == "orphan-source":
        (run / "preformatted-source.html").write_bytes(b"orphan")
    elif state == "orphan-css":
        (run / "assets/wt-preformatted-0000000000000000.css").write_bytes(b"orphan")
    elif state == "partial":
        (run / "preformatted").mkdir()
    else:
        (run / ".preformatted-interrupted").mkdir()
    alias = tmp_path / "outside.html"
    os.link(run / "source.html", alias)
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="extract"):
            pass
    assert alias.read_bytes() == SOURCE


@pytest.mark.parametrize("relative", ["capture.json", "assets/theme.css"])
def test_legacy_extract_alias_permission_never_applies_to_other_inputs(tmp_path, relative):
    api = _api()
    run = _run(tmp_path)
    original = (run / relative).read_bytes()
    alias = tmp_path / "outside"
    os.link(run / relative, alias)
    with pytest.raises(ValueError, match="hardlinks"):
        with api.hold_processing_source(run, phase="extract"):
            pass
    assert alias.read_bytes() == original


@pytest.mark.parametrize("mutation", ["source-rebind", "capture-rebind", "alias-edit", "state-directory",
                                      "derived", "generated-css", "staging", "assets-rebind"])
def test_legacy_extract_alias_lease_rejects_rebinding_content_and_state_changes(tmp_path, mutation):
    # The read-only alias exception must retain all identity/content/state fences.
    api = _api()
    run = _run(tmp_path)
    alias = tmp_path / "outside.html"
    os.link(run / "source.html", alias)
    entered = False
    with pytest.raises(ValueError):
        with api.hold_processing_source(run, phase="extract") as source:
            entered = True
            if mutation in {"source-rebind", "capture-rebind"}:
                target = run / ("source.html" if mutation == "source-rebind" else "capture.json")
                replacement = tmp_path / "replacement"
                replacement.write_bytes(target.read_bytes())
                os.replace(replacement, target)
            elif mutation == "alias-edit":
                alias.write_bytes(SOURCE + b"changed through alias")
            elif mutation == "state-directory":
                (run / "preformatted").mkdir()
            elif mutation == "derived":
                (run / "preformatted-source.html").write_bytes(b"new state")
            elif mutation == "generated-css":
                (run / "assets/wt-preformatted-0000000000000000.css").write_bytes(b"new state")
            elif mutation == "staging":
                (run / ".preformatted-interrupted").mkdir()
            else:
                (run / "assets").rename(tmp_path / "old-assets")
                (run / "assets").mkdir()
                (run / "assets/theme.css").write_bytes((tmp_path / "old-assets/theme.css").read_bytes())
            source.verify()
    assert entered, "the valid read-only alias lease must enter before testing its verification fence"
    if mutation != "alias-edit":
        assert alias.read_bytes() == SOURCE
