"""Observe only the synthetic figure producer's exact inventory inputs."""
from __future__ import annotations

import argparse
from importlib.metadata import version
from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import zlib

from PIL import Image

from tests import pdf_fixtures
import supertranslator.pdf_figure_review as figure_review
from supertranslator.pdf_media import find_poppler


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_record(root: Path, path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes_len": len(payload), "sha256": _sha256(payload),
    }


def capture_figure_fixture_inventory(output_dir: Path) -> dict[str, Any]:
    """Retain real builder inputs/output without changing review or fixture bytes.

    The temporary module-boundary wrapper is restored even when generation fails.
    An existing output directory is refused before any producer work or write.
    This test-only diagnostic is intended for sequential use, not concurrent runs.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    committed = Path(__file__).parent / "fixtures/pdf/figures-captions-v1"
    generated = output_dir / "generated/figures-captions-v1"
    generated.mkdir(parents=True, exist_ok=False)
    pdf_fixtures._make_figures_captions(generated / "source.pdf")
    pdf_fixtures._write_acceptance_sidecars(generated, "figures-captions-v1")
    original_builder = figure_review.build_pdf_figure_text_input
    summary: dict[str, Any] = {}

    def observe_builder(document, *, document_bytes, source_pdf_bytes, media_payloads):
        inventory = original_builder(
            document, document_bytes=document_bytes, source_pdf_bytes=source_pdf_bytes,
            media_payloads=media_payloads,
        )
        retained = output_dir / "producer-inputs"
        retained.mkdir(exist_ok=False)
        for name, payload, key in (
            ("source.pdf", source_pdf_bytes, "source"),
            ("document.json", document_bytes, "document"),
            ("figure-text-input.json", figure_review.canonical_figure_text_input_bytes(inventory), "inventory"),
        ):
            path = retained / name
            path.write_bytes(payload)
            summary[key] = _file_record(output_dir, path, payload)
        summary["document"]["crlf_count"] = document_bytes.count(b"\r\n")
        summary["inventory"]["value"] = inventory
        summary["media"] = []
        for figure in inventory["figures"]:
            block_id = figure["block_id"]
            payload = media_payloads[block_id]
            path = retained / (block_id.replace(":", "-") + ".png")
            path.write_bytes(payload)
            record = _file_record(output_dir, path, payload)
            record.update({
                "block_id": block_id, "page_number": figure["page_number"],
                "bbox": figure["bbox"], "characters": figure["characters"],
            })
            with Image.open(BytesIO(payload)) as image:
                image.load()
                record.update({
                    "mode": image.mode, "size": list(image.size),
                    "pixels_sha256": _sha256(image.tobytes()),
                })
            summary["media"].append(record)
        return inventory

    figure_review.build_pdf_figure_text_input = observe_builder
    try:
        pdf_fixtures._write_known_fixture_translations(generated)
    finally:
        figure_review.build_pdf_figure_text_input = original_builder

    expected_review = (committed / "review.json").read_bytes()
    expected_path = output_dir / "expected-review.json"
    expected_path.write_bytes(expected_review)
    actual_path = generated / "review.json"
    actual_review = actual_path.read_bytes()
    summary["review"] = {
        "expected": _file_record(output_dir, expected_path, expected_review),
        "actual": _file_record(output_dir, actual_path, actual_review),
        "strict_equal": expected_review == actual_review,
        "expected_inventory_sha256": json.loads(expected_review)["figure_text_review"]["inventory_sha256"],
    }
    summary["generated_file_comparisons"] = []
    for path in sorted(generated.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(generated)
        expected = (committed / relative).read_bytes()
        actual = path.read_bytes()
        summary["generated_file_comparisons"].append({
            "path": relative.as_posix(), "expected_sha256": _sha256(expected),
            "actual_sha256": _sha256(actual), "strict_equal": expected == actual,
        })
    summary["dependencies"] = {
        name: version(name)
        for name in ("pypdf", "reportlab", "pdfplumber", "Pillow", "pdfminer.six", "fonttools")
    }
    summary["python"] = sys.version
    summary["zlib_version"] = zlib.ZLIB_VERSION
    summary["zlib_runtime_version"] = zlib.ZLIB_RUNTIME_VERSION
    tools = find_poppler()
    summary["poppler"] = {
        name: subprocess.run(
            [str(path), "-v"], capture_output=True, encoding="utf-8", check=True,
        ).stderr.strip()
        for name, path in (("pdfinfo", tools.pdfinfo), ("pdftoppm", tools.pdftoppm))
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    summary = capture_figure_fixture_inventory(arguments.output_dir)
    # ASCII terminal output also works under the native Windows default locale.
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
