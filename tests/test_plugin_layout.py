import json
from importlib.resources import files
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from supertranslator import __version__
from supertranslator.cli import main


ROOT = Path(__file__).parents[1]


def test_manifest_discovers_both_translator_skills() -> None:
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text("utf-8"))
    assert manifest["name"] == "supertranslator"
    assert manifest["version"] == __version__
    assert manifest["skills"] == "./skills/"
    assert manifest["interface"]["displayName"] == "supertranslator"
    assert (ROOT / "skills/supertranslator-web").is_dir()
    assert (ROOT / "skills/supertranslator-pdf").is_dir()
    assert {
        path.name for path in (ROOT / "skills").iterdir() if path.is_dir()
    } == {"supertranslator-web", "supertranslator-pdf"}

    searchable_metadata = " ".join(
        (
            manifest["description"],
            manifest["interface"]["shortDescription"],
            manifest["interface"]["longDescription"],
            *manifest["interface"]["defaultPrompt"],
        )
    ).lower()
    assert "html" in searchable_metadata
    assert "pdf" in searchable_metadata
    assert "public" in searchable_metadata
    assert "local" in searchable_metadata


def test_cli_help_returns_success(capsys) -> None:
    assert main(["--help"]) == 0
    assert "capture" in capsys.readouterr().out


def test_pdf_fonts_are_exposed_as_package_resources() -> None:
    assets = files("supertranslator").joinpath("font_assets")

    assert assets.joinpath("NotoSansKR-Regular.ttf").is_file()
    assert assets.joinpath("NotoSansKR-Bold.ttf").is_file()
    assert assets.joinpath("OFL.txt").is_file()
    assert assets.joinpath("PROVENANCE.json").is_file()


def test_preformatted_flow_css_is_exposed_as_package_resource() -> None:
    packaged = files("supertranslator").joinpath("web_assets", "preformatted-flow.css")
    source = ROOT / "src/supertranslator/web_assets/preformatted-flow.css"

    assert packaged.is_file()
    assert packaged.read_bytes() == source.read_bytes()
    assert b"[data-wt-preformatted-literal]" in packaged.read_bytes()


def test_installed_web_resources_are_consumed_without_checkout_fallback(tmp_path) -> None:
    """Missing wheel CSS or source-tree module fallback must fail the installed gate."""
    import supertranslator
    from supertranslator.preformatted_analysis import analyze_preformatted, build_classification_packages, validate_review
    from supertranslator.preformatted_contract import canonical_sha256
    from supertranslator.preformatted_projection import project_preformatted

    checkout = os.environ.get("SUPERTRANSLATOR_FORBID_SOURCE_ROOT")
    module = Path(supertranslator.__file__).resolve()
    resource = Path(str(files("supertranslator").joinpath("web_assets", "preformatted-flow.css"))).resolve()
    if checkout:
        forbidden = Path(checkout).resolve()
        installed = Path(sysconfig.get_paths()['purelib']).resolve()
        assert not module.is_relative_to(forbidden), module
        assert not resource.is_relative_to(forbidden), resource
        assert not Path.cwd().resolve().is_relative_to(forbidden), Path.cwd()
        assert module.is_relative_to(installed), module
        assert resource.is_relative_to(installed), resource
    # Real projection consumes the installed resource; finding a filename is not enough.
    source = '<html><body><pre>Inspect the observatory.</pre></body></html>'
    analysis = analyze_preformatted(source)
    packages = build_classification_packages(analysis)
    review = validate_review(analysis, packages, {
        'schema_version': '1.0', 'source_sha256': analysis.source_sha256,
        'analysis_sha256': canonical_sha256(analysis.to_dict()),
        'package_sha256': {p.id: canonical_sha256(p.to_dict()) for p in packages},
        'blocks': [{'id': 'block-000001', 'pre_id': 'pre-000001',
                    'line_ids': ['line-000001'], 'role': 'prose',
                    'evidence': 'Inspect the observatory.', 'metadata': {}, 'literal_spans': []}],
        'unresolved_required': [],
    })
    artifact = project_preformatted(source, analysis, review)
    assert artifact.css_bytes == resource.read_bytes()
    assert artifact.css_path.startswith('assets/wt-preformatted-')
    assert 'Inspect the observatory.' in artifact.unmarked_html
    print(json.dumps({'python': sys.executable, 'module': str(module), 'css': str(resource)}))


def test_font_license_is_marked_binary_to_preserve_pinned_bytes_on_windows() -> None:
    assert "src/supertranslator/font_assets/OFL.txt -text" in (
        ROOT / ".gitattributes"
    ).read_text("utf-8")


def test_windows_poppler_install_pins_dependency_complete_archive() -> None:
    workflow = (ROOT / ".github/workflows/pdf-cross-platform.yml").read_text("utf-8")

    assert "python scripts/install_pinned_poppler.py --destination-root $extractRoot" in workflow
    assert "Invoke-WebRequest" not in workflow
    assert "Expand-Archive" not in workflow
    assert "Get-FileHash" not in workflow
    assert "choco install poppler --version=22.11.0.20240421 -y" not in workflow
    assert "choco install poppler -y" not in workflow


def test_windows_poppler_install_gates_both_executables_before_path_export() -> None:
    workflow = (ROOT / ".github/workflows/pdf-cross-platform.yml").read_text("utf-8")

    pdfinfo_gate = workflow.index("& $pdfinfo -v")
    pdftoppm_gate = workflow.index("& $pdftoppm -v")
    path_export = workflow.index("$env:GITHUB_PATH")

    assert pdfinfo_gate < pdftoppm_gate < path_export


def test_windows_workflow_runs_live_nonempty_directory_publication_contracts() -> None:
    workflow = (ROOT / ".github/workflows/pdf-cross-platform.yml").read_text("utf-8")

    for node in (
        "tests/test_pdf_qa.py::test_windows_publishes_nonempty_qa_directory_after_releasing_descendant_handles",
        "tests/test_pdf_qa.py::test_windows_nonempty_qa_directory_publication_never_clobbers_destination",
        "tests/test_pdf_pipeline.py::test_windows_finalize_durably_publishes_exact_reviewed_output",
    ):
        assert node in workflow


@pytest.mark.skipif(os.name != "nt", reason="requires Windows Poppler executables")
@pytest.mark.parametrize("command", ["pdfinfo", "pdftoppm"])
def test_windows_poppler_commands_load_with_all_runtime_dependencies(command: str) -> None:
    """Executable discovery alone must not pass when a dependent DLL is absent."""
    completed = subprocess.run(
        [command, "-v"],
        shell=False,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
