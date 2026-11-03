"""Digest and browser checks for derivative reading editions."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError, sync_playwright

from supertranslator.assemble import _is_link_or_reparse
from supertranslator.reader import ReaderError, _digest, _read, _replace_file, _local_asset, rendering_digest


def _check_bytes(output: Path, manifest: dict) -> None:
    if not isinstance(manifest, dict) or manifest.get("render_input_sha256") != rendering_digest(manifest):
        raise ReaderError("render-input digest mismatch")
    for name, key in [("index.html", "html_sha256"), ("article.html", "article_sha256"),
                      ("assets/reader.css", "stylesheet_sha256"), ("reader-review.json", "reader_review_sha256"),
                      ("input-manifest.json", "input_manifest_sha256")]:
        if _digest(_read(output / name)) != manifest[key]:
            raise ReaderError(f"reading edition digest changed: {name}")
    for name, digest in manifest.get("asset_sha256", {}).items():
        if not name.startswith("assets/") or ".." in Path(name).parts or "\\" in name:
            raise ReaderError("invalid asset evidence path")
        if _digest(_read(output / name)) != digest:
            raise ReaderError(f"reading edition asset digest changed: {name}")


def qa_reader(output_dir: Path, visual_review: Path | None = None) -> dict:
    """Check bytes/browser; only exact-byte-bound human/AI visual review can finalize."""
    output = Path(output_dir).absolute()
    manifest = json.loads(_read(output / "manifest.json"))
    _check_bytes(output, manifest)
    for name in ["manifest.json", "browser-qa.json", "visual-review.json", "review-report.md"]:
        target = output / name
        if _is_link_or_reparse(target) or target.exists() and not target.is_file():
            raise ReaderError(f"unsafe reader evidence destination: {name}")
    html = BeautifulSoup(_read(output / "index.html"), "lxml")
    article = html.select_one(".st-reader")
    fragment = BeautifulSoup(_read(output / "article.html"), "lxml").select_one(".st-reader")
    if article is None or str(article) != str(fragment):
        raise ReaderError("standalone and reusable article differ")
    ids = {str(tag["id"]) for tag in article.select("[id]")}
    missing = sorted({unquote(str(a["href"])[1:]) for a in article.select('a[href^="#"]')
                      if len(str(a["href"])) > 1 and unquote(str(a["href"])[1:]) not in ids})
    if missing:
        raise ReaderError(f"missing article anchor destinations: {missing}")
    for tag in article.select("[src],a[href]"):
        value = str(tag.get("src", tag.get("href", "")))
        if value.startswith("assets/") or tag.has_attr("src"):
            _read(output / _local_asset(value))
    screenshots = output / "reader-screenshots"
    if screenshots.is_symlink() or screenshots.exists() and not screenshots.is_dir():
        raise ReaderError("unsafe reader screenshot directory")
    screenshots.mkdir(exist_ok=True)
    for path in screenshots.iterdir():
        if _is_link_or_reparse(path):
            raise ReaderError("linked reader screenshot")
    metrics = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for width in [1440, 768, 390]:
                    context = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block")
                    context.route("**/*", lambda route: route.continue_() if urlsplit(route.request.url).scheme in {"file", "data"} else route.abort())
                    page = context.new_page()
                    page.goto((output / "index.html").as_uri(), wait_until="load")
                    page.evaluate("document.fonts.ready")
                    result = page.evaluate('''() => {
                      const prose = [...document.querySelectorAll('.st-reader p, .st-reader li')];
                      const visible = prose.filter(p => p.getClientRects().length);
                      return {
                        minFont: Math.min(...visible.map(p => parseFloat(getComputedStyle(p).fontSize))),
                        minLineRatio: Math.min(...visible.map(p => parseFloat(getComputedStyle(p).lineHeight)/parseFloat(getComputedStyle(p).fontSize))),
                        articleWidth: document.querySelector('.st-reader').getBoundingClientRect().width,
                        documentOverflow: document.documentElement.scrollWidth > innerWidth + 1,
                        brokenImages: [...document.images].filter(i => !i.complete || !i.naturalWidth).length,
                        literals: [...document.querySelectorAll('.st-reader pre')].filter(p => p.getClientRects().length).map(p => ({font: parseFloat(getComputedStyle(p).fontSize),whiteSpace: getComputedStyle(p).whiteSpace,overflow: getComputedStyle(p).overflowX}))
                      };
                    }''')
                    if result["minFont"] < 16 or result["minLineRatio"] < 1.6 or result["articleWidth"] > 800 or result["documentOverflow"] or result["brokenImages"]:
                        raise ReaderError(f"unreadable reader layout at {width}: {result}")
                    if any(p["font"] < 13 or p["whiteSpace"] != "pre" or p["overflow"] != "auto" for p in result["literals"]):
                        raise ReaderError(f"unreadable literal layout at {width}")
                    _replace_file(screenshots / f"{width}.png", page.screenshot(full_page=True))
                    metrics[str(width)] = result
                    context.close()
            finally:
                browser.close()
    except PlaywrightError as error:
        raise ReaderError(f"reader browser QA failed: {error}") from error
    _check_bytes(output, manifest)
    result = {"html_sha256": manifest["html_sha256"], "render_input_sha256": manifest["render_input_sha256"], "automated_status": "passed",
              "visual_status": "pending", "viewports": metrics}
    if visual_review is not None:
        raw = _read(Path(visual_review).absolute())
        visual = json.loads(raw)
        if not isinstance(visual, dict) or set(visual) != {"render_input_sha256", "verdict", "evidence"} or visual["render_input_sha256"] != manifest["render_input_sha256"] or visual["verdict"] != "pass" or not isinstance(visual["evidence"], str) or not visual["evidence"].strip():
            raise ReaderError("visual review must approve these exact reader bytes")
        result["visual_status"] = "passed"
        result["visual_review_sha256"] = _digest(raw)
        _replace_file(output / "visual-review.json", raw)
        manifest["qa_status"] = "passed"
    else:
        manifest["qa_status"] = "pending-visual-review"
    _replace_file(output / "browser-qa.json", (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    manifest["browser_qa_sha256"] = _digest(_read(output / "browser-qa.json"))
    _replace_file(output / "manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
    _replace_file(output / "review-report.md", (
        "# 읽기용 번역본 검토\n\n기존 AI 번역에서 생성한 파생본입니다. 원래 의미 검토는 input-review-report.md에 보존했습니다.\n\n"
        f"- HTML SHA256: `{manifest['html_sha256']}`\n"
        "- 코드·도식·그림·링크·ID: 편집 전후 보존 검사\n"
        "- 원문 페이지 표기: 삭제하지 않고 문서 말미 접힌 영역에 보존\n"
        "- 브라우저: 1440 / 768 / 390px 자동 검사 통과\n"
        f"- 전체 시각 검토: {result['visual_status']}\n"
    ).encode())
    return result
