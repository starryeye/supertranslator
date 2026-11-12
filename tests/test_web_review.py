"""Exact byte binding and read-only web review preparation contracts."""

import hashlib
import importlib.util
import json
import os
import re
import shlex
from contextlib import ExitStack
from pathlib import Path

import pytest

from supertranslator.cli import main
from tests.web_review_fixtures import make_reviewable_web_run, approve_web_run


@pytest.mark.parametrize("preformatted", [False, True])
@pytest.mark.parametrize("damage", ["legacy", "digest", "unresolved", "extra", "duplicate"])
def test_web_assembly_and_qa_refuse_unbound_or_stale_approval(tmp_path, capsys, preformatted, damage):
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted)
    review = approve_web_run(run)
    path = run / "web-review.json"
    if damage == "legacy":
        path.rename(run / "review.json")
    elif damage == "digest":
        review["semantic_input_sha256"] = "0" * 64
        path.write_text(json.dumps(review), encoding="utf-8")
    elif damage == "unresolved":
        review["section_findings"]["zone-001"][0]["verdict"] = "required-fix"
        review["unresolved_required"] = ["zone-001:semantic_fidelity"]
        path.write_text(json.dumps(review), encoding="utf-8")
    elif damage == "extra":
        review["extra"] = True
        path.write_text(json.dumps(review), encoding="utf-8")
    else:
        path.write_text(path.read_text().replace('{', '{"retries":{},', 1), encoding="utf-8")
    before = inventory(run)
    output = run.parents[2] / "translated-pages" / run.name
    assert main(["assemble", "--run-dir", str(run), "--output-dir", str(output)]) != 0
    assert not output.exists()
    assert inventory(run) == before
    output.mkdir()
    (output / "index.html").write_bytes(b"<html><body>Old output</body></html>")
    old = {"manifest.json": b'{"qa_status":"passed"}', "review-report.md": b"**PASS** old"}
    for name, payload in old.items():
        (output / name).write_bytes(payload)
    assert main(["qa", "--run-dir", str(run), "--output-dir", str(output)]) != 0
    assert not (output / "manifest.json").exists()
    assert not (output / "review-report.md").exists()
    for name, payload in old.items():
        assert any(p.read_bytes() == payload for p in output.glob(f".qa-evidence-*/prior-{name}"))
    assert {name: value for name, value in inventory(run).items() if not name.startswith("qa-screenshots/")} == before


@pytest.mark.parametrize("preformatted", [False, True])
def test_web_approval_is_held_and_excluded_from_semantic_digest(tmp_path, preformatted):
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted)
    review = approve_web_run(run)
    with pytest.raises(api().WebReviewError, match="changed"):
        with api().hold_web_semantic_inputs(run) as snapshot:
            assert snapshot.review_input.semantic_input_sha256 == review["semantic_input_sha256"]
            with api().hold_web_semantic_approval(snapshot) as approval:
                assert approval.review.unresolved_required == []
                assert approval.approval_sha256 == hashlib.sha256((run / "web-review.json").read_bytes()).hexdigest()
                path = run / "web-review.json"
                path.write_bytes(path.read_bytes() + b" ")
                approval.verify()


@pytest.mark.parametrize("preformatted", [False, True])
@pytest.mark.parametrize("relative", ["source.html", "translations/zone-001.jsonl", "web-review.json"])
@pytest.mark.parametrize("stage", ["before-consumption", "after-report", "after-publication"])
def test_web_snapshot_consumption_rejects_replacement_and_late_mutation(tmp_path, monkeypatch, preformatted, relative, stage):
    import supertranslator.cli as cli
    import supertranslator.qa as qa
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted)
    approve_web_run(run)
    output = run.parents[2] / "translated-pages" / run.name
    assert main(["assemble", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    old = {"manifest.json": b'{"qa_status":"passed"}', "review-report.md": b"**PASS** prior"}
    for name, payload in old.items():
        (output / name).write_bytes(payload)
    foreign = output / "foreign.txt"
    foreign.write_bytes(b"foreign stays")
    monkeypatch.setattr(qa, "_run_browser_checks", lambda *args: ([], [], [], {}))
    path = run / relative
    def mutate():
        if relative == "source.html":
            replacement = tmp_path / "replacement"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        else:
            path.write_bytes(path.read_bytes() + b" ")
    if stage == "before-consumption":
        real = cli.run_qa
        def consume(inputs):
            mutate()
            return real(inputs)
        monkeypatch.setattr(cli, "run_qa", consume)
    elif stage == "after-report":
        real = cli.render_review_report
        def report(*args):
            result = real(*args)
            mutate()
            return result
        monkeypatch.setattr(cli, "render_review_report", report)
    else:
        real = cli._publish_qa_evidence
        def publish(*args, **kwargs):
            real(*args, **kwargs)
            mutate()
        monkeypatch.setattr(cli, "_publish_qa_evidence", publish)
    assert main(["qa", "--run-dir", str(run), "--output-dir", str(output)]) != 0
    assert not (output / "manifest.json").exists()
    assert not (output / "review-report.md").exists()
    assert foreign.read_bytes() == b"foreign stays"
    for name, payload in old.items():
        assert any(p.read_bytes() == payload for p in output.glob(f".qa-evidence-*/prior-{name}"))


@pytest.mark.parametrize("preformatted", [False, True])
def test_production_consumers_parse_held_source_and_bind_exact_html(tmp_path, monkeypatch, preformatted):
    import supertranslator.cli as cli
    import supertranslator.qa as qa
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted)
    review = approve_web_run(run)
    output = run.parents[2] / "translated-pages" / run.name
    real_read_text = Path.read_text
    def no_source_reopen(path, *args, **kwargs):
        assert path.name not in {"source.html", "preformatted-source.html", "index.html"}, "HTML pathname was reopened"
        return real_read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", no_source_reopen)
    assert main(["assemble", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    monkeypatch.setattr(qa, "_run_browser_checks", lambda *args: ([], [], [], {}))
    assert main(["qa", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["web_integrity"] == {"schema_version": "1.0", "semantic_input_sha256": review["semantic_input_sha256"],
        "approval_sha256": hashlib.sha256((run / "web-review.json").read_bytes()).hexdigest(),
        "html_sha256": hashlib.sha256((output / "index.html").read_bytes()).hexdigest()}


@pytest.mark.parametrize("preformatted", [False, True], ids=["ordinary", "preformatted"])
@pytest.mark.parametrize("damage", [
    "wrong-public-url", "no-charset", "no-csp", "no-footer", "late-csp",
    "commented-footer-text", "commented-link-label",
])
def test_production_qa_rejects_changed_backend_contract(tmp_path, monkeypatch, capsys, preformatted, damage):
    import supertranslator.qa as qa

    # The final URL deliberately differs from the requested URL and needs URL
    # normalization and HTML entity encoding before it can become an href.
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted,
        final_url="https://EXAMPLE.com/원문?q=한 글&mode=%2F#절",
        source_head="<style>p { color: black; }</style>")
    approval = approve_web_run(run)
    output = run.parents[2] / "translated-pages" / run.name
    command = ["--run-dir", str(run), "--output-dir", str(output)]
    assert main(["assemble", *command]) == 0
    index = output / "index.html"
    html = index.read_bytes()
    href = b'https://example.com/%EC%9B%90%EB%AC%B8?q=%ED%95%9C%20%EA%B8%80&amp;mode=%2F#%EC%A0%88'
    assert html.count(href) == 1
    browser_calls = []

    def browser(*args):
        browser_calls.append(args)
        return [], [], [], {}

    monkeypatch.setattr(qa, "_run_browser_checks", browser)
    assert main(["qa", *command]) == 0  # unaltered ordinary/preformatted control
    assert len(browser_calls) == 1
    browser_calls.clear()
    old = {name: (output / name).read_bytes() for name in ("manifest.json", "review-report.md")}
    manifest = json.loads(old["manifest.json"])
    assert manifest["qa_status"] == "passed"
    assert manifest["web_integrity"]["semantic_input_sha256"] == approval["semantic_input_sha256"]
    assert manifest["web_integrity"]["html_sha256"] == hashlib.sha256(html).hexdigest()

    if damage == "wrong-public-url":
        altered = html.replace(href, b"https://unrelated.example/different-document")
    elif damage == "no-charset":
        altered, count = re.subn(br'<meta charset="utf-8"\s*/?>', b"", html)
        assert count == 1
    elif damage == "no-footer":
        altered, count = re.subn(br'<footer data-wt-attribution="source">[^\n]*?</footer>', b"", html)
        assert count == 1
    elif damage in {"commented-footer-text", "commented-link-label"}:
        label = ("AI 번역본 · " if damage == "commented-footer-text" else "원문 보기").encode("utf-8")
        assert html.count(label) == 1
        altered = html.replace(label, b"<!--" + label + b"-->")
    else:
        (csp,) = re.findall(br'<meta [^>]*data-wt-csp="offline"[^>]*>', html)
        altered = html.replace(csp, b"")
        if damage == "late-csp":
            assert altered.count(b"</style>") == 1
            altered = altered.replace(b"</style>", b"</style>" + csp)
    assert altered != html
    index.write_bytes(altered)
    capsys.readouterr()
    exit_code = main(["qa", *command])
    status = capsys.readouterr()
    manifest_path, report_path = output / "manifest.json", output / "review-report.md"
    current_qa = json.loads(manifest_path.read_bytes())["qa_status"] if manifest_path.exists() else None
    assert (exit_code, current_qa, len(browser_calls)) == (6, None, 0)
    assert json.loads(status.out) == {"command": "qa", "exit_code": 6, "status": "error"}
    assert "required QA checks failed: approved-content-integrity" in status.err
    assert not report_path.exists()
    for name, payload in old.items():
        assert any(path.read_bytes() == payload for path in output.glob(f".qa-evidence-*/prior-{name}"))


def _assemble_backend_boundary(tmp_path, preformatted, **fixture_options):
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted, **fixture_options)
    approve_web_run(run)
    output = run.parents[2] / "translated-pages" / run.name
    command = ["--run-dir", str(run), "--output-dir", str(output)]
    assert main(["assemble", *command]) == 0
    assert main(["qa", *command]) == 0  # unaltered assembly, real Chromium
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["qa_status"] == "passed"
    assert manifest["web_integrity"]["html_sha256"] == hashlib.sha256((output / "index.html").read_bytes()).hexdigest()
    return output, command


def _assert_backend_boundary_rejected(output, command, capsys):
    capsys.readouterr()
    exit_code = main(["qa", *command])
    status = capsys.readouterr()
    manifest = output / "manifest.json"
    current_qa = json.loads(manifest.read_bytes())["qa_status"] if manifest.exists() else None
    assert (exit_code, current_qa) == (6, None)
    assert json.loads(status.out) == {"command": "qa", "exit_code": 6, "status": "error"}
    assert "required QA checks failed: approved-content-integrity" in status.err
    assert not (output / "review-report.md").exists()


@pytest.mark.parametrize("preformatted", [False, True], ids=["ordinary", "preformatted"])
def test_production_qa_rejects_browser_different_attribution_entity(tmp_path, capsys, preformatted):
    from playwright.sync_api import sync_playwright

    trusted = "https://example.com/%EC%9B%90%EB%AC%B8?q=%ED%95%9C%20%EA%B8%80&mode=%2F&owner=O'Reilly#%EC%A0%88"
    canonical = (b'<a href="https://example.com/%EC%9B%90%EB%AC%B8?q=%ED%95%9C%20%EA%B8%80'
                 b"&amp;mode=%2F&amp;owner=O'Reilly#%EC%A0%88" b'" rel="noopener noreferrer">')
    output, command = _assemble_backend_boundary(tmp_path, preformatted,
        final_url="https://EXAMPLE.com/원문?q=한 글&mode=%2F&owner=O'Reilly#절",
        before_head=f'<!-- Earlier link markup: {canonical.decode("ascii")} -->')
    index = output / "index.html"
    html = index.read_bytes()
    # The genuine formatter keeps the apostrophe; the first exact match is a
    # comment decoy that must not validate the actual footer link.
    assert html.count(canonical) == 2
    before, link, after = html.rpartition(canonical)
    altered = before + link.replace(b"&amp;mode=", b"&ampmode=") + after
    assert altered.count(canonical) == 1

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            for markup, href in ((html, trusted), (altered, trusted.replace("&mode=", "&ampmode="))):
                page.set_content(markup.decode("utf-8"), wait_until="domcontentloaded")
                assert page.locator("footer[data-wt-attribution] > a").get_attribute("href") == href
        finally:
            browser.close()
    index.write_bytes(altered)
    _assert_backend_boundary_rejected(output, command, capsys)


@pytest.mark.parametrize("preformatted", [False, True], ids=["ordinary", "preformatted"])
@pytest.mark.parametrize("offset,decoy", [(1023, False), (1024, False), (1024, True)],
                         ids=["last-valid-byte", "first-invalid-byte", "multibyte-comment-decoy"])
def test_production_qa_enforces_actual_charset_byte_offset(tmp_path, capsys, preformatted, offset, decoy):
    charset = b'<meta charset="utf-8"/>'
    before_head = '<!--앞선 줄\n문자열 <meta charset="utf-8"/> -->' if decoy else ""
    output, command = _assemble_backend_boundary(tmp_path, preformatted, before_head=before_head)
    index = output / "index.html"
    html = index.read_bytes()
    assert html.count(charset) == (2 if decoy else 1)
    start = html.rindex(charset)
    assert start < 1023
    (csp,) = re.findall(br'<meta [^>]*data-wt-csp="offline"[^>]*>', html)
    padded = csp.replace(b"<meta ", b"<meta " + b" " * (offset - start), 1)
    altered = html.replace(csp, padded, 1)
    assert altered.rindex(charset) == offset
    if decoy:
        assert altered.index(charset) < 1024
        assert altered.decode("utf-8").rindex(charset.decode("ascii")) < 1024
    index.write_bytes(altered)
    if offset == 1023:
        assert main(["qa", *command]) == 0
        manifest = json.loads((output / "manifest.json").read_bytes())
        assert manifest["qa_status"] == "passed"
        assert manifest["web_integrity"]["html_sha256"] == hashlib.sha256(altered).hexdigest()
    else:
        _assert_backend_boundary_rejected(output, command, capsys)


@pytest.mark.parametrize("preformatted", [False, True])
@pytest.mark.parametrize("relative", ["source.html", "translations/zone-001.jsonl", "web-review.json"])
@pytest.mark.parametrize("stage", ["before-consumption", "during-staging"])
def test_assembly_revalidates_held_inputs_before_bundle_publication(tmp_path, monkeypatch, preformatted, relative, stage):
    import supertranslator.cli as cli
    import supertranslator.assemble as assembly
    run = make_reviewable_web_run(tmp_path, preformatted=preformatted)
    approve_web_run(run)
    output = run.parents[2] / "translated-pages" / run.name
    def mutate():
        path = run / relative
        path.write_bytes(path.read_bytes() + b" ")
    if stage == "before-consumption":
        real = cli.assemble_page
        def consume(*args, **kwargs):
            mutate()
            return real(*args, **kwargs)
        monkeypatch.setattr(cli, "assemble_page", consume)
    else:
        real = assembly._copy_assets
        def copy(*args):
            real(*args)
            mutate()
        monkeypatch.setattr(assembly, "_copy_assets", copy)
    assert main(["assemble", "--run-dir", str(run), "--output-dir", str(output)]) != 0
    assert not output.exists()
    assert not list(output.parent.glob(".*.assembling-*"))


def test_held_output_retains_safe_utf8_qa_diagnostic(tmp_path, monkeypatch):
    from supertranslator.qa import run_qa
    from supertranslator.models import QAInputs, MasterReview
    source = tmp_path / "source.html"
    source.write_bytes(b"<html><body></body></html>")
    output = tmp_path / "index.html"
    output.write_bytes(b"\xff")
    result = run_qa(QAInputs(source, output, "https://example.com/", set(), set(), [], [],
        tmp_path / "screenshots", MasterReview([], {}, {}),
        source_bytes=source.read_bytes(), output_bytes=output.read_bytes()))
    assert not result.passed
    assert "output-html-unreadable" in {finding.code for finding in result.required_findings}
    assert result.web_integrity is None


def test_documented_web_review_recipe_runs_with_bound_synthetic_inputs(tmp_path, capsys):
    """CLI/API recipe validation only; synthetic approval is not AI quality evidence."""
    run = make_reviewable_web_run(tmp_path)
    output = run.parents[2] / "translated-pages" / run.name
    skill = Path(__file__).parents[1] / "skills/supertranslator-web/SKILL.md"
    commands = {}
    values = {"<work-dir>": str(run), "<output-dir>": str(output)}
    for line in skill.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("<python> -m supertranslator "):
            command = [values.get(arg, arg) for arg in shlex.split(line.strip())[3:]]
            commands[command[0]] = command
    assert main(commands["web-review-input"]) == 0
    prepared = json.loads(capsys.readouterr().out)["review_input"]
    approval = approve_web_run(run)
    assert approval["semantic_input_sha256"] == prepared["semantic_input_sha256"]
    assert main(commands["assemble"]) == 0
    assert main(commands["qa"]) == 0
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["qa_status"] == "passed"
    assert manifest["web_integrity"]["semantic_input_sha256"] == prepared["semantic_input_sha256"]


@pytest.mark.parametrize("failure_point", ["publication-boundary", "report-write", "manifest-publication"])
def test_ordinary_web_qa_publication_io_failure_keeps_qa_exit_class(tmp_path, monkeypatch, capsys, failure_point):
    """An output I/O failure must survive the actual nested semantic leases as QA failure."""
    import supertranslator.cli as cli
    import supertranslator.qa as qa
    import supertranslator.pdf_assemble as storage
    import supertranslator.pdf_extract_transaction as transaction_files
    run = make_reviewable_web_run(tmp_path)
    approve_web_run(run)
    output = run.parents[2] / "translated-pages" / run.name
    assert main(["assemble", "--run-dir", str(run), "--output-dir", str(output)]) == 0
    old = {"manifest.json": b'{"qa_status":"passed"}', "review-report.md": b"**PASS** prior"}
    for name, payload in old.items():
        (output / name).write_bytes(payload)
    (output / "foreign.txt").write_bytes(b"foreign stays")
    monkeypatch.setattr(qa, "_run_browser_checks", lambda *args: ([], [], [], {}))
    marker = "TEST ONLY output publication I/O failure"
    if failure_point == "publication-boundary":
        def fail(*args, **kwargs):
            raise OSError(marker)
        monkeypatch.setattr(cli, "_publish_qa_evidence", fail)
    elif failure_point == "report-write":
        real = transaction_files._write_private_file
        def write(directory, name, payload):
            if name == "new-review-report.md":
                raise OSError(marker)
            return real(directory, name, payload)
        monkeypatch.setattr(transaction_files, "_write_private_file", write)
    else:
        real = storage._publish_new_file
        def publish(source, source_name, destination, destination_name):
            if destination_name == "manifest.json":
                raise OSError(marker)
            return real(source, source_name, destination, destination_name)
        monkeypatch.setattr(storage, "_publish_new_file", publish)
    capsys.readouterr()
    assert main(["qa", "--run-dir", str(run), "--output-dir", str(output)]) == 6
    status = capsys.readouterr()
    assert json.loads(status.out) == {"command": "qa", "exit_code": 6, "status": "error"}
    assert marker in status.err
    assert "fresh AI semantic review" not in status.err
    assert not (output / "manifest.json").exists()
    assert not (output / "review-report.md").exists()
    assert (output / "foreign.txt").read_bytes() == b"foreign stays"
    for name, payload in old.items():
        assert any(p.read_bytes() == payload for p in output.glob(f".qa-evidence-*/prior-{name}"))


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
    message = (r"\Acannot hold web semantic inputs: Windows anchored assembly artifact is not a regular file\Z"
               if os.name == "nt" and target == "glossary.json" else "link|reparse")
    with pytest.raises(api().WebReviewError, match=message):
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
