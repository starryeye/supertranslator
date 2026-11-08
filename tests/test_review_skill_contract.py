"""Packaging/fixture invariants, not substitutes for fresh-agent review trials."""

import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
from pypdf import PdfReader
import pytest

from supertranslator.cli import _build_parser
from tests.review_skill_fixtures import make_review_case


ROOT = Path(__file__).parents[1]


def test_review_skill_is_discovered_without_pipeline_hooks() -> None:
    """Removal from discovery or integration as a pipeline step breaks independence."""
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text("utf-8"))
    skill = ROOT / manifest["skills"] / "supertranslator-review"
    assert (skill / "SKILL.md").is_file()
    for reference in ("html.md", "pdf.md", "report.md"):
        assert (skill / "references" / reference).is_file()
    policy = skill / "agents/openai.yaml"
    if policy.exists():
        assert "allow_implicit_invocation: false" not in policy.read_text("utf-8")
    for workflow in ("web", "pdf", "render"):
        for document in (ROOT / f"skills/supertranslator-{workflow}").rglob("*.md"):
            for line in document.read_text("utf-8").splitlines():
                if "supertranslator-review" not in line:
                    continue
                # Independence explanations are permitted; executable hooks are not.
                assert not re.search(r"-m\s+supertranslator\s+review\b", line)
                assert not re.search(r"(?:^|[.!]\s)(?:Use|Invoke|Run|Require)\s+[`$]*supertranslator-review", line)
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["review"])


def test_review_evaluation_fixtures_have_independent_oracles(tmp_path) -> None:
    """A repaired or truncated fixture must not silently weaken the behavioral trial."""
    case = make_review_case(tmp_path)
    source = BeautifulSoup((case.inputs / "original.html").read_text("utf-8"), "html.parser")
    final = BeautifulSoup((case.inputs / "translated.html").read_text("utf-8"), "html.parser")
    assert "MUST allow access only when" in source.select_one("#p1").get_text()
    assert "접근을 거부해야" in final.select_one("#p1").get_text()
    assert "compelling reason" in source.select_one("#p3").get_text()
    assert "불가피한 이유" in final.select_one("#p3").get_text()
    assert source.select_one("#app").find_next_sibling("p")["id"] == "p5"
    assert "MAY retry twice" in source.select_one("#p5").get_text()
    assert final.select_one("#app").find_next_sibling() is None
    assert final.select_one("#p5") is None
    assert [node.get_text() for node in source.select("pre")] == [node.get_text() for node in final.select("pre")]
    assert "32 octet" in final.select_one("#p4").get_text()
    assert "code_verifier" in final.select_one("#p4").get_text()
    assert "@media(max-width:500px){#p4{font-size:7px;height:8px;overflow:hidden}}" in final.style.get_text()
    original_pages = [page.extract_text() for page in PdfReader(case.inputs / "original.pdf").pages]
    final_pages = [page.extract_text() for page in PdfReader(case.inputs / "translated.pdf").pages]
    assert len(original_pages) == 2 and len(final_pages) == 3
    assert "MUST allow access" in original_pages[0]
    assert "MUST deny access" in final_pages[0]
    assert "Appendix A" in original_pages[1] and "retry twice" in original_pages[1]
    assert "Appendix A" not in final_pages[1]
    assert "Appendix A" in final_pages[2] and "retry once" in final_pages[2]
    assert "passed" in (case.inputs / "previous-review.md").read_text("utf-8")
    assert "publication" in (case.inputs / "artifact-note.txt").read_text("utf-8")
    case.assert_unchanged()


@pytest.mark.parametrize("mutation", ["content", "addition", "removal"])
def test_review_fixture_guard_rejects_changed_inputs(tmp_path, mutation) -> None:
    """Hash/inventory guards catch edits, sidecar writes, and removed inputs."""
    case = make_review_case(tmp_path)
    case.assert_unchanged()
    if mutation == "content":
        (case.inputs / "translated.html").write_text("changed", encoding="utf-8")
    elif mutation == "addition":
        (case.inputs / "approval.json").write_text("{}", encoding="utf-8")
    else:
        (case.inputs / "original.pdf").unlink()
    with pytest.raises(AssertionError, match="inputs or inventory changed"):
        case.assert_unchanged()
