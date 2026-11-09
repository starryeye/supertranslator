"""Synthetic exact-input runs; no semantic approval or network is involved."""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path

from supertranslator.cli import main
from supertranslator.models import read_segments
from supertranslator.preformatted_contract import canonical_bytes, canonical_sha256


def make_reviewable_web_run(root: Path, *, preformatted: bool = False) -> Path:
    run = root / "작업 공간" / ".supertranslator/runs/검토 run"
    run.mkdir(parents=True)
    (run.parents[2] / "translated-pages").mkdir()
    (run / "assets").mkdir()
    source = (b"<html><head></head><body><pre>Read this manual.\nContinue reading.</pre></body></html>"
              if preformatted else b"<html><head></head><body><p>Accept the request.</p></body></html>")
    (run / "source.html").write_bytes(source)
    (run / "assets/theme.css").write_bytes(b"body { color: black; }")
    capture = {"requested_url": "https://example.com/", "final_url": "https://example.com/",
               "captured_at": "2026-11-09T00:00:00Z", "asset_map": {"https://example.com/theme.css": "assets/theme.css"},
               "critical_assets": ["assets/theme.css"], "optional_assets": [], "missing_optional_assets": [],
               "fingerprints": {name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                                for name in ("source.html", "assets/theme.css")}}
    (run / "capture.json").write_bytes(canonical_bytes(capture))

    def command(name):
        with redirect_stdout(io.StringIO()):
            assert main([name, "--run-dir", str(run)]) == 0

    if preformatted:
        command("prepare-preformatted")
        analysis = json.loads((run / "preformatted/analysis.json").read_bytes())
        packages = {path.stem: canonical_sha256(json.loads(path.read_bytes()))
                    for path in (run / "preformatted/packages").glob("*.json")}
        (run / "preformatted/review.json").write_bytes(canonical_bytes({
            "schema_version": "1.0", "source_sha256": analysis["source_sha256"],
            "analysis_sha256": canonical_sha256(analysis), "package_sha256": packages,
            "blocks": [{"id": "block-000001", "pre_id": "pre-000001",
                        "line_ids": ["line-000001", "line-000002"], "role": "prose",
                        "evidence": "Read this manual.", "metadata": {}, "literal_spans": []}],
            "unresolved_required": []}))
        command("materialize-preformatted")
    command("extract")
    command("plan-zones")
    (run / "glossary.json").write_bytes(b"{}\n")
    (run / "document-summary.txt").write_text("Synthetic request acceptance or manual prose.", encoding="utf-8")
    command("prepare-assignments")
    segments = {item.id: item for item in read_segments(run / "segments.jsonl")}
    (run / "translations").mkdir()
    for path in (run / "zones").glob("*.json"):
        zone = json.loads(path.read_bytes())
        records = [{"segment_id": sid, "text": "검토: " + segments[sid].source_text,
                    "notes": "TEST ONLY authored fixture", "glossary_observations": {}}
                   for sid in zone["target_ids"]]
        (run / "translations" / (path.stem + ".jsonl")).write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    return run
