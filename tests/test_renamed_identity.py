"""The 0.8 boundary has new identities and no executable legacy aliases."""

from datetime import UTC, datetime
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import sysconfig
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _invoke(tmp_path, *arguments):
    env = os.environ.copy()
    if env.get("SUPERTRANSLATOR_FORBID_SOURCE_ROOT"):
        env.pop("PYTHONPATH", None)
        flags = []
    else:
        # Do not process the shared developer interpreter's legacy editable .pth.
        # Load dependencies directly while testing only this checkout's module tree.
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys([
            str(ROOT / "src"), sysconfig.get_paths()["purelib"], sysconfig.get_paths()["platlib"]]))
        flags = ["-S"]
    return subprocess.run([sys.executable, *flags, *arguments], cwd=tmp_path, env=env,
                          text=True, capture_output=True, check=False, timeout=30)


def test_new_module_help_is_available_outside_checkout(tmp_path):
    result = _invoke(tmp_path, "-m", "supertranslator", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: supertranslator" in result.stdout
    assert "pdf-acquire" in result.stdout and "capture" in result.stdout


def test_old_module_is_not_an_executable_alias(tmp_path):
    result = _invoke(tmp_path, "-m", "web_translator", "--help")
    assert result.returncode != 0
    assert "No module named web_translator" in result.stderr


def test_distribution_and_plugin_expose_only_new_identity(tmp_path):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_bytes())
    assert project["name"] == "supertranslator"
    assert project["version"] == manifest["version"] == "0.8.0"
    assert project["scripts"] == {"supertranslator": "supertranslator.cli:console_main"}
    assert manifest["name"] == manifest["interface"]["displayName"] == "supertranslator"
    assert manifest["repository"] == "https://github.com/starryeye/supertranslator"
    result = _invoke(tmp_path, "-c", "from supertranslator.cli import console_main; console_main()", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage: supertranslator" in result.stdout
    if os.environ.get("SUPERTRANSLATOR_FORBID_SOURCE_ROOT"):
        result = _invoke(tmp_path, "-c", "from importlib.metadata import distribution; import shutil; d=distribution('supertranslator'); assert d.version == '0.8.0'; assert {(e.name, e.value) for e in d.entry_points if e.group == 'console_scripts'} == {('supertranslator', 'supertranslator.cli:console_main')}; assert shutil.which('web-translator') is None")
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("kind", ["web", "pdf"])
def test_new_run_allocation_ignores_and_preserves_historical_root(tmp_path, kind):
    # Historical data must not influence root selection or be changed by allocation.
    from supertranslator.paths import create_pdf_run_paths, create_run_paths
    historical = tmp_path / ".web-translator" / "runs"
    historical.mkdir(parents=True)
    sentinel = historical / "unfinished.json"
    sentinel.write_bytes(b'{"immutable":"old unfinished run"}\n')
    before = {p.relative_to(historical): p.read_bytes() for p in historical.rglob("*") if p.is_file()}
    now = datetime(2026, 8, 10, 12, 34, 56, tzinfo=UTC)
    paths = (create_run_paths(tmp_path, "https://example.com/docs", now) if kind == "web"
             else create_pdf_run_paths(tmp_path, "document.pdf", now))
    assert paths.work_dir.parent == tmp_path / ".supertranslator" / "runs"
    assert paths.output_dir.parent == tmp_path / ("translated-pages" if kind == "web" else "translated-pdfs")
    assert {p.relative_to(historical): p.read_bytes() for p in historical.rglob("*") if p.is_file()} == before
    assert sorted(p.name for p in historical.iterdir()) == ["unfinished.json"]


@pytest.mark.parametrize("default_encoding", [None, "cp1252"])
def test_new_package_resources_and_both_skill_reference_graphs_are_readable(monkeypatch, default_encoding):
    if default_encoding:
        original_open = Path.open

        def locale_open(path, *args, **kwargs):
            # Read real Markdown with a Windows-style default decoder, while
            # preserving any explicit encoding selected by the caller.
            if path.suffix == ".md" and kwargs.get("encoding") in (None, "locale"):
                kwargs["encoding"] = default_encoding
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", locale_open)
    assets = files("supertranslator")
    assert assets.joinpath("font_assets", "NotoSansKR-Regular.ttf").read_bytes()[:4] == b"\x00\x01\x00\x00"
    assert assets.joinpath("font_assets", "NotoSansKR-Bold.ttf").read_bytes()[:4] == b"\x00\x01\x00\x00"
    assert b"[data-wt-preformatted-literal]" in assets.joinpath("web_assets", "preformatted-flow.css").read_bytes()
    assert {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()} == {"supertranslator-web", "supertranslator-pdf"}
    for name in ("supertranslator-web", "supertranslator-pdf"):
        skill = ROOT / "skills" / name / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        assert text.startswith(f"---\nname: {name}\n")
        references = re.findall(r"\]\(([^)]+\.md)\)", text)
        assert references
        for reference in references:
            assert (skill.parent / reference).read_text(encoding="utf-8").strip()
