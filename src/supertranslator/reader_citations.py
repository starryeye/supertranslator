"""Move exactly reviewed citation text into native, script-free disclosures."""
from __future__ import annotations

from dataclasses import dataclass
import re

from bs4 import BeautifulSoup, NavigableString, Tag

from supertranslator.reader import ReaderError, _canonical_link, _digest, _one, _preserved


_PROTECTED = {
    "pre", "code", "kbd", "samp", "svg", "math", "template", "noscript",
    "details", "summary", "textarea", "script", "style", "iframe", "object",
    "embed", "select", "option", "optgroup", "datalist", "input", "button", "form", "var",
    "head", "title", "xmp", "plaintext", "noembed", "noframes", "frameset",
}
_TABLE_CONTEXT = {"table", "thead", "tbody", "tfoot", "tr", "colgroup", "col"}
_TABLE_CONTENT = {"td", "th", "caption"}
_CONTROL_ATTRS = {"popover", "popovertarget", "popovertargetaction", "command", "commandfor",
                  "contenteditable", "tabindex"}
_LABEL_TAGS = {"span", "em", "strong", "b", "i", "u", "s", "small", "sub", "sup",
               "abbr", "bdi", "bdo", "mark", "cite", "del", "ins"}


@dataclass
class _Citation:
    anchor: Tag
    spans: list[Tag]
    label: str
    detail: str


def _fail(reason: str) -> None:
    raise ReaderError(f"reader citation details: {reason}")


def _blocked(tag: Tag) -> bool:
    return (tag.name in _PROTECTED or {"hidden", "inert", "style"} & tag.attrs.keys()
            or tag.get("aria-hidden", "").lower() == "true"
            or bool(_CONTROL_ATTRS & tag.attrs.keys())
            or tag.get("role") not in {None, "link", "listitem"})


def _foster_parented(anchor: Tag) -> bool:
    # HTML browsers move misnested phrasing content outside restricted table
    # containers, even if the source parser represents it inside them. Ordinary
    # citations inside a cell or caption are not in this insertion mode.
    for parent in anchor.parents:
        if parent.name in _TABLE_CONTENT:
            return False
        if parent.name in _TABLE_CONTEXT:
            return True
    return False


def resolve_citation_details(article: Tag, selections: list) -> list[_Citation]:
    """Validate reviewed source identities and exact text before wrapping."""
    if not isinstance(selections, list):
        _fail("citation_details must be an array")
    resolved = []
    seen = set()
    for item in selections:
        if (not isinstance(item, dict) or set(item) != {"selector", "detail_selector", "detail_sha256"}
                or not isinstance(item["detail_selector"], str) or not item["detail_selector"].strip()
                or not isinstance(item["detail_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["detail_sha256"])):
            _fail("invalid review record")
        try:
            anchor = _one(article, item["selector"])
            spans = anchor.select(item["detail_selector"])
        except Exception as error:
            raise ReaderError(f"reader citation details: invalid source selection: {error}") from error
        if anchor.name != "a" or not anchor.get("href") or id(anchor) in seen:
            _fail("expected a unique anchor with a destination")
        if (_foster_parented(anchor)
                or any(_blocked(tag) or (tag is not anchor and tag.name == "a")
                       for tag in [anchor, *anchor.find_all(True), *anchor.parents])):
            _fail("selection intersects protected, hidden, or interactive content")
        if not spans or any(span.name != "span" or span.parent is not anchor
                            or set(span.attrs) - {"class"} or not span.contents
                            or any(type(child) is not NavigableString for child in span.contents)
                            for span in spans):
            _fail("detail must consist of direct plain-text spans with only optional classes")
        selected = {id(span) for span in spans}
        children = anchor.contents
        start = next(i for i, child in enumerate(children) if id(child) in selected)
        if any(id(child) not in selected for child in children[start:]):
            _fail("detail span selection must be trailing and contiguous")
        if any(tag.name not in _LABEL_TAGS for tag in anchor.find_all(True) if id(tag) not in selected):
            _fail("citation label must be plain text or static inline markup")
        label = "".join(child.get_text() if isinstance(child, Tag) else str(child)
                        for child in children[:start] if isinstance(child, Tag) or type(child) is NavigableString)
        detail = "".join(span.get_text() for span in spans)
        if not label.strip() or not detail.strip() or _digest(detail.encode("utf-8")) != item["detail_sha256"]:
            _fail("citation needs a visible label and matching exact detail text digest")
        seen.add(id(anchor))
        resolved.append(_Citation(anchor, spans, label, detail))
    return resolved


def apply_citation_details(article: Tag, resolved: list[_Citation], source_url: str) -> None:
    """Create generated controls after sanitization; enforce the preservation delta."""
    if not resolved:
        return
    soup = BeautifulSoup("", "html.parser")
    expected = _preserved(article, source_url)
    original_text = article.get_text()
    ids = set(expected["ids"]) | set(expected["anchor_names"])
    reviewed = {id(entry.anchor) for entry in resolved}
    untouched = [str(link) for link in article.select("a") if id(link) not in reviewed]
    sequence = 0
    controls = set()
    for entry in resolved:
        anchor, spans = entry.anchor, entry.spans
        if (not any(parent is article for parent in anchor.parents)
                or any(span.parent is not anchor for span in spans)
                or any(tag.name in _PROTECTED for tag in anchor.parents)
                or _foster_parented(anchor)
                or "".join(span.get_text() for span in spans) != entry.detail):
            _fail("the original selection changed during reader layout")
        destination = _canonical_link(anchor["href"], source_url)
        old_key = (destination, anchor.get_text())
        expected["links"][old_key] -= 1
        original_attrs = dict(anchor.attrs)
        selected = {id(span) for span in spans}
        retained = "".join(child.get_text() if isinstance(child, Tag) else str(child)
                           for child in anchor.contents if id(child) not in selected
                           and (isinstance(child, Tag) or type(child) is NavigableString))
        for span in spans:
            span.extract()
        expected["links"][(destination, retained)] += 1
        if dict(anchor.attrs) != original_attrs or anchor.get_text() != retained:
            _fail("citation destination or label changed")
        while True:
            sequence += 1
            identifier = f"st-citation-{sequence:04d}"
            if identifier not in ids:
                break
        ids.add(identifier)
        expected["ids"][identifier] += 1
        button = soup.new_tag("button", attrs={
            "class": "st-citation-toggle", "type": "button", "popovertarget": identifier,
            "aria-label": f"{' '.join(entry.label.split())} 인용 상세",
        })
        button.string = "ⓘ"
        controls.add(id(button))
        detail = soup.new_tag("span", attrs={
            "class": "st-citation-detail", "id": identifier, "popover": "auto",
        })
        detail.string = entry.detail
        anchor.insert_after(button, detail)
        if detail.get_text() != entry.detail:
            _fail("exact disclosure text changed")
    if (_preserved(article, source_url) != expected
            or "".join(string for string in article.strings if id(string.parent) not in controls) != original_text
            or [str(link) for link in article.select("a") if id(link) not in reviewed] != untouched):
        _fail("disclosures changed other protected content")
