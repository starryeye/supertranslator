"""Explicit, review-bound reading editions of already translated HTML bundles.

This is a derivative export, not a second translation or a replacement for source QA.
No site-specific selectors or language heuristics decide what content to discard.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
import copy
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from supertranslator import __version__
from supertranslator.assemble import (
    AssemblyError, _CSP, _copy_assets, _is_executable_url,
    _is_link_or_reparse, _reject_source_output_overlap, _reject_unsafe_output_ancestors,
)
from supertranslator.paths import validate_public_url


class ReaderError(ValueError):
    """The review or source cannot safely produce a reading edition."""


_FIELDS = {"schema_version", "input_html_sha256", "content_selector", "title",
           "removals", "joins", "heading_levels", "list_items"}
_DROP = {"script", "style", "noscript", "iframe", "object", "embed", "base", "link", "meta"}
_ATTRS = {"id", "href", "src", "alt", "title", "lang", "dir", "colspan", "rowspan",
          "scope", "role", "aria-label", "aria-labelledby", "width", "height", "name",
          "start", "value", "type", "reversed", "hidden"}
_SVG_ATTRS = _ATTRS | set("viewbox d x y x1 x2 y1 y2 cx cy r rx ry points transform fill fill-rule stroke stroke-width stroke-linecap stroke-linejoin opacity fill-opacity stroke-opacity preserveaspectratio xmlns xmlns:xlink marker-start marker-mid marker-end offset stop-color stop-opacity gradientunits gradienttransform patternunits patterntransform font-size font-family text-anchor dominant-baseline".split())


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes:
    _reject_unsafe_output_ancestors(path)
    if _is_link_or_reparse(path) or not path.is_file():
        raise ReaderError(f"missing or linked input: {path}")
    return path.read_bytes()


def _one(root: Tag | BeautifulSoup, selector: str) -> Tag:
    if not isinstance(selector, str) or not selector.strip():
        raise ReaderError("selector must be a nonempty string")
    try:
        found = root.select(selector)
    except Exception as error:
        raise ReaderError(f"invalid selector: {selector}") from error
    if len(found) != 1:
        raise ReaderError(f"selector must identify exactly one element: {selector}")
    return found[0]


def _local_asset(value: str) -> str:
    parsed = urlsplit(value)
    decoded = unquote(parsed.path)
    path = PurePosixPath(decoded)
    if parsed.scheme or parsed.netloc or path.is_absolute() or ".." in path.parts or "\\" in decoded or not path.parts or path.parts[0] != "assets":
        raise ReaderError("reader media/links must use captured local assets")
    return path.as_posix()


def _canonical_link(value: str, source_url: str) -> str:
    if value.startswith("assets/"):
        _local_asset(value)
        return value
    return value if value.startswith("#") else urljoin(source_url, value)


def _is_live_html_anchor(tag: Tag) -> bool:
    if tag.name != "a" or not tag.get("name") or tag.find_parent("template") is not None:
        return False
    # lxml's HTML parser does not expose foreign namespaces. Track HTML
    # integration points within the nearest SVG or MathML ancestor.
    html_contexts = set()
    for ancestor in tag.parents:
        if ancestor.name in {"svg", "math"}:
            return ancestor.name in html_contexts
        if ancestor.name in {"desc", "title"}:
            html_contexts.add("svg")
        if ancestor.name in {"mi", "mo", "mn", "ms", "mtext"} or (
            ancestor.name == "annotation-xml"
            and ancestor.get("encoding", "").lower() in {"text/html", "application/xhtml+xml"}
        ):
            html_contexts.add("math")
    return True


def _legacy_anchor_names(root: Tag) -> Counter[str]:
    return Counter(
        str(tag["name"]) for tag in [root, *root.select("a[name]")]
        if _is_live_html_anchor(tag)
    )


def _preserved(root: Tag, source_url: str) -> dict[str, object]:
    return {
        "ids": Counter(str(t["id"]) for t in [root, *root.select("[id]")] if t.has_attr("id")),
        "anchor_names": _legacy_anchor_names(root),
        "literals": Counter(t.get_text() for t in root.select("pre") if t.get_text().strip()),
        "links": Counter((_canonical_link(str(t.get("href")), source_url), t.get_text()) for t in root.select("a[href]")),
        "images": Counter((str(t.get("src")), str(t.get("alt", ""))) for t in root.select("img")),
        "svg": Counter(str(t) for t in root.select("svg")),
        "numbering": Counter((t.name, str(t.get("start")), str(t.get("value")), str(t.get("type")), str(t.get("reversed"))) for t in root.select("ol,li")),
    }


def _anchor_spacer(tag: Tag) -> bool:
    return tag.name == "span" and not tag.get_text().strip() and all(
        child.name in {"span", "a"} and not child.has_attr("href")
        for child in tag.find_all(True)
    )


def _group_reviewed_lists(article: Tag) -> None:
    """Give reviewed items an owning list without rewriting source blocks."""
    factory = BeautifulSoup("", "html.parser")
    for first in list(article.select('[data-reader-list="true"]')):
        owned = False
        for ancestor in first.parents:
            if ancestor is article or ancestor.name == "li" or ancestor.get("role") == "listitem":
                break
            if ancestor.name in {"ul", "ol"} or ancestor.get("role") == "list":
                owned = True
                break
        if owned:
            continue
        members = [first]
        spacers = []
        for following in first.next_siblings:
            if isinstance(following, Tag) and following.get("data-reader-list") == "true":
                members.extend(spacers)
                members.append(following)
                spacers = []
            elif (isinstance(following, NavigableString) and not following.strip()
                  or isinstance(following, Tag) and _anchor_spacer(following)):
                spacers.append(following)
            else:
                break
        owner = factory.new_tag("div", role="list")
        first.insert_before(owner)
        for member in members:
            owner.append(member.extract())


def rendering_digest(manifest: dict) -> str:
    """Bind visual approval to all bytes that determine the rendered edition."""
    value = {name: manifest[name] for name in ("html_sha256", "article_sha256", "stylesheet_sha256", "asset_sha256")}
    return _digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _replace_file(path: Path, data: bytes) -> None:
    """Replace this directory entry atomically, never follow a destination link."""
    _reject_unsafe_output_ancestors(path)
    if _is_link_or_reparse(path) or path.exists() and not path.is_file():
        raise ReaderError(f"unsafe reader evidence destination: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=".reader-evidence-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _transform(soup: BeautifulSoup, review: dict) -> Tag:
    selected = _one(soup, review["content_selector"])
    if selected.name in {"html", "head", "script", "style", "nav"} or selected.find_parent("head"):
        raise ReaderError("content selector must identify a document body region")
    article = soup.new_tag("article", attrs={"class": "st-reader", "lang": "ko"})
    article.append(copy.deepcopy(selected))
    # Internal review markers are not trusted when inherited from source HTML.
    for tag in article.select('[data-reader-list]'):
        del tag["data-reader-list"]
    notes = soup.new_tag("details", attrs={"class": "st-source-notes"})
    summary = soup.new_tag("summary")
    summary.string = "원문 페이지 표기"
    notes.append(summary)
    for item in review["removals"]:
        if not isinstance(item, dict) or set(item) != {"selector", "text_sha256", "reason"} or not item["reason"]:
            raise ReaderError("invalid source-furniture review")
        element = _one(article, item["selector"])
        if element.name not in {"pre", "table", "header", "footer"} or _digest(element.get_text().encode()) != item["text_sha256"]:
            raise ReaderError("source-furniture type/text digest mismatch")
        notes.append(element.extract())
    for element in list(article.select("pre")):
        if not element.get_text().strip():
            # Keep destinations without leaving preformatted blank-line spacers.
            element.name = "span"
            for child in list(element.find_all(string=True)):
                if not child.strip():
                    child.extract()
    for group in review["joins"]:
        if not isinstance(group, dict) or set(group) != {"selectors"}:
            raise ReaderError("invalid paragraph join")
        selectors = group["selectors"]
        if not isinstance(selectors, list) or len(selectors) < 2:
            raise ReaderError("paragraph join requires at least two parts")
        parts = [_one(article, value) for value in selectors]
        if len({id(t) for t in parts}) != len(parts) or any(t.name != "p" for t in parts):
            raise ReaderError("paragraph joins require distinct prose paragraphs")
        first = parts[0]
        for following in parts[1:]:
            sibling = first.next_sibling
            while sibling is not None and (isinstance(sibling, NavigableString) and not sibling.strip()
                    or isinstance(sibling, Tag) and _anchor_spacer(sibling)):
                sibling = sibling.next_sibling
            if sibling is not following or following.parent is not first.parent:
                raise ReaderError("paragraph join crosses unreviewed content")
            # The old paragraph ID is retained at its original text boundary.
            boundary = soup.new_tag("span")
            if following.has_attr("id"):
                boundary["id"] = following["id"]
                del following["id"]
            first.append(NavigableString(" "))
            first.append(boundary)
            for child in list(following.contents):
                first.append(child.extract())
            following.decompose()
    for selector, level in review["heading_levels"].items():
        heading = _one(article, selector)
        if heading.name not in {"h1", "h2", "h3", "h4", "h5", "h6"} or type(level) is not int or not 1 <= level <= 6:
            raise ReaderError("heading review must map headings to levels 1..6")
        heading.name = f"h{level}"
    for selector in review["list_items"]:
        item = _one(article, selector)
        if item.name not in {"p", "div"}:
            raise ReaderError("list review must select prose/list blocks")
        item["data-reader-list"] = "true"
        item["role"] = "listitem"
    if len(notes.contents) > 1:
        article.append(notes)
    return article


def _sanitize(article: Tag, source_url: str) -> None:
    for comment in list(article.find_all(string=lambda s: isinstance(s, Comment))):
        comment.extract()
    for tag in list(article.find_all(True)):
        if tag.name in _DROP:
            tag.decompose()
            continue
        if tag.name in {"form", "input", "button", "select", "textarea", "foreignobject"}:
            raise ReaderError(f"interactive/embedded content is not a supported reading region: {tag.name}")
        is_list = tag.get("data-reader-list") == "true" or tag.get("role") == "listitem"
        is_notes = tag.name == "details" and "st-source-notes" in tag.get("class", [])
        is_permalink = tag.name == "a" and tag.get_text().strip() == "¶" and str(tag.get("href", "")).startswith("#")
        in_svg = tag.name == "svg" or tag.find_parent("svg") is not None
        if in_svg and any(name not in _SVG_ATTRS for name in tag.attrs):
            raise ReaderError("inline SVG with styling/unsupported attributes needs a captured static image")
        for name in list(tag.attrs):
            if name not in (_SVG_ATTRS if in_svg else _ATTRS):
                del tag[name]
        if is_list:
            tag["class"] = "st-list-item"
        if is_notes:
            tag["class"] = "st-source-notes"
        if is_permalink:
            tag["class"] = "st-permalink"
            if not tag.has_attr("aria-label"):
                tag["aria-label"] = "문단 링크"
        for name in ("href", "src"):
            if name not in tag.attrs:
                continue
            value = str(tag[name])
            parsed = urlsplit(value)
            if _is_executable_url(value) or parsed.scheme.lower() not in {"", "https", "http", "mailto", "tel"}:
                raise ReaderError("executable or unsupported content URL")
            if name == "src":
                _local_asset(value)
            else:
                tag[name] = _canonical_link(value, source_url)


def export_reader(input_dir: Path, review_path: Path, output_dir: Path) -> Path:
    """Export a reviewed local bundle without editing it or approving its meaning."""
    try:
        return _export_reader(Path(input_dir).absolute(), Path(review_path).absolute(), Path(output_dir).absolute())
    except (OSError, UnicodeError, KeyError, TypeError, json.JSONDecodeError, AssemblyError) as error:
        raise ReaderError(str(error)) from error


def _export_reader(input_dir: Path, review_path: Path, output_dir: Path) -> Path:
    _reject_source_output_overlap(input_dir, output_dir)
    _reject_unsafe_output_ancestors(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise ReaderError("reader output already exists")
    input_bytes = _read(input_dir / "index.html")
    manifest_bytes = _read(input_dir / "manifest.json")
    report_bytes = _read(input_dir / "review-report.md")
    review_bytes = _read(review_path)
    review = json.loads(review_bytes)
    manifest = json.loads(manifest_bytes)
    if not isinstance(review, dict) or not _FIELDS <= set(review) or set(review) - _FIELDS - {"text_edits", "presentation", "structure"} or review["schema_version"] != "1.0":
        raise ReaderError("invalid reader review schema")
    if not isinstance(manifest, dict) or not isinstance(review["title"], str) or not review["title"].strip() or not isinstance(review["removals"], list) or not isinstance(review["joins"], list) or not isinstance(review["heading_levels"], dict) or not isinstance(review["list_items"], list):
        raise ReaderError("invalid reader review field types")
    if review["input_html_sha256"] != _digest(input_bytes):
        raise ReaderError("input HTML digest does not match reader review")
    if manifest.get("qa_status") != "passed" or manifest.get("required_findings") != []:
        raise ReaderError("input translation has not passed QA")
    from supertranslator.models import WebIntegrity
    try:
        integrity = WebIntegrity.from_dict(manifest.get("web_integrity"))
    except ValueError as error:
        raise ReaderError(f"missing or malformed web_integrity; fresh AI semantic review and QA are required: {error}") from error
    if integrity.html_sha256 != _digest(input_bytes):
        raise ReaderError("web_integrity HTML digest mismatch; fresh AI semantic review and QA are required")
    source_url = str(validate_public_url(manifest["source_url"]))
    soup = BeautifulSoup(input_bytes.decode("utf-8"), "lxml")
    original = _one(soup, review["content_selector"])
    original_facts = _preserved(original, source_url)
    article = _transform(soup, review)
    if _preserved(article, source_url) != original_facts:
        raise ReaderError("reader transformation lost IDs, links, images or literal text")
    from supertranslator.reader_editing import apply_text_edits
    apply_text_edits(article, review.get("text_edits", []))
    if _preserved(article, source_url) != original_facts:
        raise ReaderError("reader text edit changed protected document structure")
    groups = None
    if "presentation" in review:
        from supertranslator.reader_layout import apply_presentation, resolve_presentation
        groups = resolve_presentation(article, review["presentation"])
    from supertranslator.reader_structure import apply_structure, resolve_structure
    structure = resolve_structure(article, review)
    # All source-bound selectors resolve before wrappers change sibling positions.
    _group_reviewed_lists(article)
    _sanitize(article, source_url)
    apply_structure(article, structure)
    if _preserved(article, source_url) != original_facts:
        raise ReaderError("reader sanitization changed content structure")
    if "presentation" in review:
        apply_presentation(article, review["presentation"], groups)
        if any(value - _preserved(article, source_url)[key] for key, value in original_facts.items()):
            raise ReaderError("reader presentation lost protected source content")
    footer = soup.new_tag("footer", attrs={"class": "st-attribution"})
    footer.append("비공식 AI 한국어 번역 · ")
    link = soup.new_tag("a", href=source_url)
    link.string = "공식 원문"
    footer.append(link)
    article.append(footer)
    fragment = str(article)
    doc = BeautifulSoup('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title></title><link rel="stylesheet" href="assets/reader.css"></head><body class="st-reader-page"><main></main></body></html>', "lxml")
    doc.title.string = review["title"]
    csp = doc.new_tag("meta", attrs={"http-equiv": "Content-Security-Policy", "content": _CSP})
    doc.head.append(csp)
    doc.main.append(article)
    html = str(doc).encode()
    css = files("supertranslator").joinpath("web_assets", "reader.css").read_bytes()
    output_parent = output_dir.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".reader-", dir=output_parent))
    try:
        _copy_assets(input_dir / "assets", staging / "assets", staging)
        (staging / "assets").mkdir(exist_ok=True)
        (staging / "assets" / "reader.css").write_bytes(css)
        (staging / "index.html").write_bytes(html)
        (staging / "article.html").write_bytes(fragment.encode("utf-8"))
        (staging / "input-manifest.json").write_bytes(manifest_bytes)
        (staging / "input-review-report.md").write_bytes(report_bytes)
        (staging / "reader-review.json").write_bytes(review_bytes)
        for tag in article.select("[src], a[href]"):
            value = str(tag.get("src", tag.get("href", "")))
            if value.startswith("assets/"):
                _read(staging / _local_asset(value))
        asset_digests = {path.relative_to(staging).as_posix(): _digest(_read(path))
                         for path in (staging / "assets").rglob("*") if path.is_file()}
        output_manifest = {
            "schema_version": "1.0", "format": "reviewed-reading-edition",
            "tool": {"name": "supertranslator", "version": __version__},
            "source_url": source_url, "qa_status": "pending-visual-review",
            "input_html_sha256": _digest(input_bytes), "input_manifest_sha256": _digest(manifest_bytes),
            "reader_review_sha256": _digest(review_bytes), "html_sha256": _digest(html),
            "article_sha256": _digest(fragment.encode()), "stylesheet_sha256": _digest(css),
            "asset_sha256": asset_digests,
            "transformations": {key: review[key] for key in ("removals", "joins", "heading_levels", "list_items")},
            "text_edits": review.get("text_edits", []),
            "presentation": review.get("presentation"),
        }
        if "structure" in review:
            output_manifest["structure"] = review["structure"]
        output_manifest["render_input_sha256"] = rendering_digest(output_manifest)
        (staging / "manifest.json").write_text(json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
        (staging / "review-report.md").write_text(
            "# 읽기용 번역본\n\n기존 AI 번역에서 생성한 파생본입니다. 번역 의미 검토를 새로 승인한 것이 아닙니다.\n\n"
            "- 입력 HTML·편집 검토: SHA256 결합\n- 코드·도식·그림·링크·ID: 편집 전후 보존 검사\n"
            "- 페이지 표기: 문서 말미 접힌 원문 표기로 이동\n- 브라우저·시각 검토: 아직 미완료\n",
            encoding="utf-8", newline="",
        )
        if _read(input_dir / "index.html") != input_bytes or _read(input_dir / "manifest.json") != manifest_bytes or _read(review_path) != review_bytes:
            raise ReaderError("input evidence changed during export")
        # Atomic no-replace publication reuses the existing cross-platform primitive.
        from supertranslator.pdf_assemble import _open_directory_anchor
        from supertranslator.pdf_qa import _rename_anchored_directory_no_replace
        with closing(_open_directory_anchor(output_parent, "reader output parent")) as parent:
            identity = staging.stat()
            _rename_anchored_directory_no_replace(parent, staging.name, (identity.st_dev, identity.st_ino), parent, output_dir.name)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return output_dir / "index.html"
