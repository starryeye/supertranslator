"""Exercise render-only recipes over real artifacts; approvals here are TEST ONLY."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex

from bs4 import BeautifulSoup
from supertranslator.cli import main
from supertranslator.paths import create_pdf_run_paths
from supertranslator.pdf_review import build_pdf_semantic_review_input
from tests.pdf_unit_fixtures import run_native_unit_pipeline
from tests.test_reader import bundle  # Reuse the source-bound reader fixture.


def render_commands(format_name: str, values: dict[str, str]) -> dict[str, list[str]]:
    """Execute guide examples so an invalid flag or stage cannot silently drift."""
    reference = Path(__file__).parents[1] / f"skills/supertranslator-render/references/{format_name}.md"
    commands = [
        [values.get(arg, arg) for arg in shlex.split(line)[3:]]
        for line in reference.read_text("utf-8").splitlines()
        if line.startswith("<python> -m supertranslator ")
    ]
    return {" ".join(args[:2]) if args[0] == "pdf-qa" else args[0]: args for args in commands}


def inventory(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_html_render_reuses_bound_bundle_once(bundle, tmp_path):
    """Blindly replaying the review on the derivative loses its bound source."""
    source, review_path, first = bundle
    review = json.loads(review_path.read_bytes())
    # This is historical semantic evidence, not a new render-time wording edit.
    original = "   o  목록의 내용이 여러 줄로 표시됩니다."
    review["text_edits"] = [{
        "selector": "#item",
        "input_html_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "replacement_html": "   o  목록의 내용은 여러 줄로 표시됩니다.",
        "source_text": "The list content is displayed across multiple lines.",
        "evidence": "TEST ONLY historical reviewed Korean sentence correction.",
    }]
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    source_before, review_before = inventory(source), review_path.read_bytes()
    values = {"<bound-bundle>": str(source), "<reader-review>": str(review_path),
              "<new-output>": str(first), "<new-visual-review>": str(tmp_path / "fresh-visual.json")}
    assert main(render_commands("html", values)["export-reader"]) == 0
    first_before = inventory(first)
    second = tmp_path / "second reader 새 판"
    # A final reader is not the original input bound by its copied review.
    assert main(["export-reader", "--input-dir", str(first), "--review", str(first / "reader-review.json"),
                 "--output-dir", str(second)]) == 4
    assert not second.exists()
    saved_review = json.loads((first / "reader-review.json").read_bytes())
    assert hashlib.sha256((source / "index.html").read_bytes()).hexdigest() == saved_review["input_html_sha256"]
    values.update({"<reader-review>": str(first / "reader-review.json"), "<new-output>": str(second)})
    assert main(render_commands("html", values)["export-reader"]) == 0
    for output in (first, second):
        soup = BeautifulSoup((output / "article.html").read_bytes(), "lxml")
        assert soup.find(id="item").get_text() == "   o  목록의 내용은 여러 줄로 표시됩니다."
        assert soup.get_text().count("목록의 내용은") == 1
        assert soup.find(id="left").get_text() == "클라이언트는 접근을 허용해야 합니다(MUST). 이 조건은 두 요청 모두에 적용됩니다."
        assert soup.find(id="code").get_text() == "GET /?a=1&b=2 HTTP/1.1\n+------------------------------+\n| Client             Server    |\n+------------------------------+"
        assert soup.select_one("a[href='#section-1']").get_text() == "허용"
        assert soup.find(id="right") is not None
        assert (output / "assets/picture.svg").read_bytes() == source_before["assets/picture.svg"]
        manifest = json.loads((output / "manifest.json").read_bytes())
        assert manifest["text_edits"] == review["text_edits"]
        assert manifest["qa_status"] == "pending-visual-review"
    assert (second / "article.html").read_bytes() == (first / "article.html").read_bytes()
    assert inventory(source) == source_before
    assert review_path.read_bytes() == review_before
    assert inventory(first) == first_before


def test_pdf_render_reuses_exact_semantic_approval_but_requires_fresh_visual_review(tmp_path):
    """Preparation must preserve approvals but cannot inherit output acceptance."""
    from datetime import UTC, datetime
    from tests.test_pdf_qa import _write_passing_layout_review

    source, old_output = run_native_unit_pipeline(tmp_path / "original")
    source_before, output_before = inventory(source), inventory(old_output)
    paths = create_pdf_run_paths(tmp_path / "revision", "rerender.pdf", datetime.now(UTC))
    run, output = paths.work_dir, paths.output_dir
    commands = render_commands("pdf", {"<approved-run>": str(source), "<new-run>": str(run), "<new-output>": str(output)})
    assert main(commands["prepare-pdf-render"]) == 0
    assert build_pdf_semantic_review_input(run).semantic_input_sha256 == build_pdf_semantic_review_input(source).semantic_input_sha256
    for relative in ("review.json", "source.pdf", "document.json", "segments.jsonl", "glossary.json",
                     "assignments/.pdf-unit-binding.json", "translations/zone-001.jsonl"):
        assert (run / relative).read_bytes() == source_before[relative]
    assert not (run / "pdf-layout-review.json").exists()
    assert not (run / "pdf-qa.json").exists()
    assert main(commands["pdf-assemble"]) == 0
    assert main(commands["pdf-qa prepare"]) == 0
    assert main(commands["pdf-qa finalize"]) != 0
    assert not output.exists()
    # Explicitly TEST ONLY: simulate newly inspected all-page evidence, not acceptance.
    _write_passing_layout_review(run)
    qa = json.loads((run / "pdf-qa.json").read_bytes())
    visual = json.loads((run / "pdf-layout-review.json").read_bytes())
    assert visual["staged_pdf_sha256"] == qa["staged_pdf_sha256"]
    assert main(commands["pdf-qa finalize"]) == 0
    assert set(inventory(output)) == {"translated.pdf", "manifest.json", "review-report.md"}
    assert inventory(source) == source_before
    assert inventory(old_output) == output_before
