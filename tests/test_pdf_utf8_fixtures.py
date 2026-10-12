"""PDF regression inputs and assertions must not depend on a UTF-8 locale."""

import json
from pathlib import Path

import pytest

from tests import test_pdf_pipeline as pipeline_tests
from tests.test_pdf_figure_review import publication_case
from tests.test_pdf_name_preservation import approved_run


@pytest.fixture
def cp1252_default_in_tmp_root(tmp_path, monkeypatch):
    """Emulate Windows text defaults only inside this test's owned tree."""
    original_open = Path.open

    def open_with_cp1252_default(
        path, mode="r", buffering=-1, encoding=None, errors=None, newline=None,
    ):
        if (
            path.is_relative_to(tmp_path)
            and "b" not in mode
            and encoding in (None, "locale")
        ):
            encoding = "cp1252"
        return original_open(
            path, mode, buffering=buffering, encoding=encoding,
            errors=errors, newline=newline,
        )

    monkeypatch.setattr(Path, "open", open_with_cp1252_default)
    return tmp_path


@pytest.mark.parametrize("shape", ["name-only", "optional-empty"])
def test_pdf_fixture_helpers_write_utf8_when_default_is_cp1252(
    cp1252_default_in_tmp_root, shape,
):
    root = cp1252_default_in_tmp_root
    if shape == "name-only":
        run, _document, _segments, _translations, _glossary, _review = approved_run(root)
        expected_text = (
            "Orion Cache Engine와 Vega Cache Engine, Orion Cache Engine는 이름입니다. "
            "Cache는 이름 밖의 용어이고 Cache는 나중 용어입니다."
        )
    else:
        case, _translations = publication_case(root, case="figure-free", evidence=True)
        run = case.run_dir
        expected_text = "독립적인 본문은 원본 그림 밖에서 선택 가능한 한국어로 보존됩니다."
        master = json.loads((run / "review.json").read_bytes().decode("utf-8"))
        assert master["figure_text_review"]["figures"] == {}

    payload = (run / "translations/zone-001.jsonl").read_bytes()
    records = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    assert [record["text"] for record in records] == [expected_text]
    assert payload.endswith(b"\n") and b"\r" not in payload


@pytest.mark.parametrize("scenario", ["ambiguous-links", "publication-semantics"])
def test_pdf_pipeline_assertions_read_utf8_when_default_is_cp1252(
    cp1252_default_in_tmp_root, scenario,
):
    root = cp1252_default_in_tmp_root
    if scenario == "ambiguous-links":
        pipeline_tests.test_unit_final_report_retains_ambiguous_link_destinations(root)
    else:
        pipeline_tests.test_publication_fixture_publishes_exact_artifacts_with_semantics(root)
