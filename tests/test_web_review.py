"""Exact byte binding and read-only web review preparation contracts."""

import hashlib
import importlib.util
import json
import os
from contextlib import ExitStack
from pathlib import Path

import pytest

from supertranslator.cli import main
from tests.web_review_fixtures import make_reviewable_web_run


def api():
    assert importlib.util.find_spec("supertranslator.web_review") is not None, "web semantic input snapshot is missing"
    from supertranslator import web_review
    return web_review


def inventory(run):
    return {p.relative_to(run).as_posix(): p.read_bytes() for p in run.rglob("*") if p.is_file()}


@pytest.mark.parametrize("preformatted", [False, True])
def test_web_review_input_is_read_only_and_canonical(tmp_path, capsys, preformatted):
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted)
    before_inventory = inventory(run)
    assert main(["web-review-input", "--run-dir", str(run)]) == 0
    statuses = capsys.readouterr().out.splitlines()
    assert len(statuses) == 1
    status = json.loads(statuses[0])
    assert set(status) == {"command", "exit_code", "status", "review_input"}
    assert {k: v for k, v in status.items() if k != "review_input"} == {"command": "web-review-input", "exit_code": 0, "status": "ok"}
    prepared = status["review_input"]
    assert set(prepared) == {"schema_version", "semantic_input_sha256", "terminology_policy", "files"}
    assert prepared["schema_version"] == "1.0"
    assert prepared["terminology_policy"] == {"id": "english-technical-first-use-ko-gloss", "version": "1.0"}
    expected_names = sorted(name for name in before_inventory if name != "document-summary.txt")
    assert prepared["files"] == [{"path": name, "byte_length": len(before_inventory[name]), "sha256": hashlib.sha256(before_inventory[name]).hexdigest()} for name in expected_names]
    digest_value = {"domain": "supertranslator:web-semantic-input:1", "terminology_policy": prepared["terminology_policy"], "files": prepared["files"]}
    assert prepared["semantic_input_sha256"] == hashlib.sha256(json.dumps(digest_value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    with api().hold_web_semantic_inputs(run) as snapshot:
        assert snapshot.review_input.to_dict() == prepared
        assert dict(snapshot.payloads) == {name: before_inventory[name] for name in expected_names}
        assert snapshot.capture["final_url"] == "https://example.com/"
        assert snapshot.segments and snapshot.zones and snapshot.translations
        assert snapshot.glossary == {}
        assert (snapshot.processing_source.normalization is not None) == preformatted
        snapshot.verify()
    assert main(["web-review-input", "--run-dir", str(run)]) == 0
    assert json.loads(capsys.readouterr().out)["review_input"] == prepared
    assert before_inventory == inventory(run)
    assert not (run / "web-review.json").exists()


@pytest.mark.parametrize("relative", ["translations/zone-001.jsonl", "glossary.json", "assignments/zone-001.json", "source.html", "capture.json", "assets/theme.css", "preformatted-source.html", "preformatted/provenance.json"])
def test_web_review_input_changes_with_consumed_bytes(tmp_path, relative):
    run = make_reviewable_web_run(tmp_path, preformatted=relative.startswith("preformatted"))
    with api().hold_web_semantic_inputs(run) as snapshot:
        old = snapshot.review_input.to_dict()["semantic_input_sha256"]
    path = run / relative
    path.write_bytes(path.read_bytes() + b" ")
    try:
        with api().hold_web_semantic_inputs(run) as snapshot:
            assert snapshot.review_input.to_dict()["semantic_input_sha256"] != old
    except api().WebReviewError as error:
        assert any(word in str(error) for word in ("fingerprint", "provenance", "derived", "source", "segments"))


@pytest.mark.parametrize("field,value", [("notes", "Different review notes"), ("text", "요청을 거부합니다.")])
def test_translation_record_changes_are_bound(tmp_path, field, value):
    run = make_reviewable_web_run(tmp_path)
    with api().hold_web_semantic_inputs(run) as snapshot:
        old = snapshot.review_input.to_dict()
    path = run / "translations/zone-001.jsonl"
    record = json.loads(path.read_bytes())
    record[field] = value
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with api().hold_web_semantic_inputs(run) as snapshot:
        assert snapshot.review_input.to_dict() != old


@pytest.mark.parametrize("directory,extension", [("zones", "json"), ("assignments", "json"), ("translations", "jsonl")])
@pytest.mark.parametrize("damage", ["missing", "extra"])
def test_exact_child_sets_are_required(tmp_path, directory, extension, damage):
    run = make_reviewable_web_run(tmp_path)
    path = run / directory / f"zone-001.{extension}"
    if damage == "missing":
        path.unlink()
    else:
        (path.parent / f"zone-999.{extension}").write_bytes(path.read_bytes())
    with pytest.raises(api().WebReviewError, match="missing|unexpected|filename|partition|cover"):
        with api().hold_web_semantic_inputs(run):
            pass


@pytest.mark.parametrize("relative", ["capture.json", "glossary.json", "zones/zone-001.json", "assignments/zone-001.json", "translations/zone-001.jsonl", "segments.jsonl"])
def test_duplicate_json_keys_are_rejected(tmp_path, relative):
    run = make_reviewable_web_run(tmp_path)
    path = run / relative
    payload = path.read_bytes()
    path.write_bytes(b'{"duplicate":0,"duplicate":1}\n' if payload.strip() == b"{}"
                     else payload.replace(b"{", b'{"duplicate":0,"duplicate":1,', 1))
    with pytest.raises(api().WebReviewError, match="duplicate JSON key"):
        with api().hold_web_semantic_inputs(run):
            pass


@pytest.mark.parametrize("damage", ["assignment-record", "assignment-zone", "duplicate-segment", "duplicate-translation", "translation-token", "zone-context"])
def test_ambiguous_or_inconsistent_records_are_rejected(tmp_path, damage):
    run = make_reviewable_web_run(tmp_path)
    if damage.startswith("assignment"):
        path = run / "assignments/zone-001.json"
        value = json.loads(path.read_bytes())
        if damage == "assignment-record":
            value["targets"][0]["source_text"] = "A different source"
        else:
            value["zone_id"] = "zone-999"
    elif damage == "zone-context":
        path = run / "zones/zone-001.json"
        value = json.loads(path.read_bytes())
        value["context_before_ids"] = ["missing"]
    else:
        path = run / ("segments.jsonl" if damage == "duplicate-segment" else "translations/zone-001.jsonl")
        if damage.startswith("duplicate"):
            path.write_bytes(path.read_bytes() * 2)
            value = None
        else:
            value = json.loads(path.read_bytes())
            value["text"] += "⟦WT:000001⟧"
    if value is not None:
        path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(api().WebReviewError, match="assignment|duplicate|token|missing"):
        with api().hold_web_semantic_inputs(run):
            pass


@pytest.mark.parametrize("target", ["glossary.json", "assignments", "ancestor"])
def test_linked_inputs_are_rejected(tmp_path, target):
    run = make_reviewable_web_run(tmp_path / "real")
    if target == "ancestor":
        link = tmp_path / "linked"
        link.symlink_to(run.parents[2], target_is_directory=True)
        run = link / ".supertranslator/runs" / run.name
    else:
        path = run / target
        moved = tmp_path / ("moved-" + target)
        path.rename(moved)
        path.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(api().WebReviewError, match="link|reparse"):
        with api().hold_web_semantic_inputs(run):
            pass


def test_snapshot_rejects_same_name_replacement(tmp_path):
    run = make_reviewable_web_run(tmp_path)
    path = run / "glossary.json"
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(path.read_bytes())
    with ExitStack() as outcome:
        with api().hold_web_semantic_inputs(run) as snapshot:
            try:
                os.replace(replacement, path)
            except PermissionError:
                # Native Windows may prevent replacement while the exact input is held.
                assert os.name == "nt"
                assert path.read_bytes() == replacement.read_bytes()
                snapshot.verify()
            else:
                outcome.enter_context(pytest.raises(api().WebReviewError, match="changed|identity|replaced"))
                snapshot.verify()


@pytest.mark.parametrize("preformatted", [False, True])
def test_snapshot_consumers_do_not_reopen_paths(tmp_path, monkeypatch, preformatted):
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted)
    original_open = Path.open

    def no_run_path_open(path, *args, **kwargs):
        if path.is_relative_to(run):
            pytest.fail(f"reopened semantic input pathname: {path.relative_to(run)}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_run_path_open)
    with api().hold_web_semantic_inputs(run) as snapshot:
        assert snapshot.translations
        snapshot.verify()


def test_current_glossary_and_assignment_context_are_independently_bound(tmp_path):
    run = make_reviewable_web_run(tmp_path)
    with api().hold_web_semantic_inputs(run) as snapshot:
        old = snapshot.review_input.to_dict()
    (run / "glossary.json").write_text('{"request":"요청"}', encoding="utf-8")
    with api().hold_web_semantic_inputs(run) as snapshot:
        assert snapshot.glossary == {"request": "요청"}
        changed = snapshot.review_input.to_dict()
        assert changed != old
    path = run / "assignments/zone-001.json"
    value = json.loads(path.read_bytes())
    value["document_summary"] += " Additional reviewer context."
    path.write_text(json.dumps(value), encoding="utf-8")
    with api().hold_web_semantic_inputs(run) as snapshot:
        assert snapshot.review_input.to_dict() != changed


@pytest.mark.parametrize("damage", ["content", "child-set", "root-set", "hardlink"])
def test_snapshot_revalidates_held_bytes_and_sets(tmp_path, damage):
    run = make_reviewable_web_run(tmp_path)
    with pytest.raises(api().WebReviewError, match="changed|hardlink"):
        with api().hold_web_semantic_inputs(run) as snapshot:
            if damage == "content":
                path = run / "glossary.json"
                path.write_bytes(b"{ }\n")
            elif damage == "child-set":
                (run / "translations/zone-999.jsonl").write_bytes(b"{}")
            elif damage == "root-set":
                (run / "unrelated-new-file").write_bytes(b"new")
            else:
                os.link(run / "glossary.json", tmp_path / "alias.json")
            snapshot.verify()


def test_cli_contract_failure_is_one_status_and_read_only(tmp_path, capsys):
    run = make_reviewable_web_run(tmp_path)
    (run / "translations/zone-001.jsonl").unlink()
    before = inventory(run)
    assert main(["web-review-input", "--run-dir", str(run)]) == 4
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"command": "web-review-input", "exit_code": 4, "status": "error"}
    assert "missing translations entries" in captured.err
    assert inventory(run) == before


def test_approvals_and_unused_artifacts_do_not_bind_themselves(tmp_path):
    run = make_reviewable_web_run(tmp_path)
    with api().hold_web_semantic_inputs(run) as snapshot:
        old = snapshot.review_input.to_dict()
    (run / "review.json").write_bytes(b"legacy untouched")
    (run / "web-review.json").write_bytes(b"not an approval")
    (run / "review-input.json").write_bytes(b"not consumed")
    with api().hold_web_semantic_inputs(run) as snapshot:
        assert snapshot.review_input.to_dict() == old
