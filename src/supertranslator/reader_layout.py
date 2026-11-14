"""Reviewed reading layout, derived navigation and preserved source information."""
from __future__ import annotations

import re
from urllib.parse import quote

from bs4 import BeautifulSoup, Comment, Tag

from supertranslator.reader import ReaderError, _legacy_anchor_names, _one


_FIELDS = {"toc_selectors", "metadata_selectors", "title_selectors", "navigation"}
_HEADINGS = {f"h{n}" for n in range(1, 7)}


def _text_contained_by(element: Tag, allowed: list[Tag]) -> bool:
    roots = {id(tag) for tag in allowed}
    return all(
        isinstance(text, Comment) or not text.strip() or any(id(parent) in roots for parent in text.parents)
        for text in element.find_all(string=True)
    )


def _safe_selection(element: Tag, kind: str) -> bool:
    if kind == "title_selectors":
        return element.name in _HEADINGS
    if kind == "toc_selectors":
        if element.name in _HEADINGS or element.name == "nav":
            return True
        if element.name == "p":
            return re.search(r"\.{2,}\s*\d+\s*$", element.get_text()) is not None
        return element.name == "div" and element.find("nav") is not None and _text_contained_by(
            element, element.find_all(["nav", *_HEADINGS]) +
            [link for link in element.find_all("a", href="#") if link.get_text().strip() in {"▲", "↑"}]
        )
    if element.name in {"dl", "table", "header"}:
        return True
    if element.name != "div" or element.find("dl") is None:
        return False
    return _text_contained_by(element, element.find_all(["dl", "table"]))


def resolve_presentation(article: Tag, review: dict) -> dict[str, list[Tag]]:
    """Resolve review selectors before source-only classes/data markers are removed."""
    if not isinstance(review, dict) or set(review) != _FIELDS or type(review["navigation"]) is not bool:
        raise ReaderError("invalid reader presentation review")
    groups = {}
    selected = []
    for kind in ["toc_selectors", "metadata_selectors", "title_selectors"]:
        if not isinstance(review[kind], list):
            raise ReaderError("presentation selectors must be lists")
        groups[kind] = []
        for selector in review[kind]:
            element = _one(article, selector)
            if element is article or element.find_parent("details", class_="st-source-notes") or not _safe_selection(element, kind):
                raise ReaderError("unsafe presentation selection")
            if any(element is other or element in other.parents or other in element.parents for other in selected):
                raise ReaderError("overlapping presentation selections")
            selected.append(element)
            groups[kind].append(element)
    return groups


def apply_presentation(article: Tag, review: dict, groups: dict[str, list[Tag]]) -> None:
    """Archive pre-resolved reviewed regions and derive links from live headings."""
    soup = BeautifulSoup("", "html.parser")
    if groups["toc_selectors"]:
        notes = article.select_one("details.st-source-notes")
        if notes is None:
            notes = soup.new_tag("details", attrs={"class": "st-source-notes"})
            label = soup.new_tag("summary"); label.string = "원문 페이지 표기·목차"
            notes.append(label); article.append(notes)
        for element in groups["toc_selectors"]:
            notes.append(element.extract())
    insert_at = 0
    if groups["title_selectors"]:
        header = soup.new_tag("header", attrs={"class": "st-title-block"})
        for element in groups["title_selectors"]:
            element["class"] = "st-document-title"
            header.append(element.extract())
        article.insert(insert_at, header); insert_at += 1
    if groups["metadata_selectors"]:
        info = soup.new_tag("details", attrs={"class": "st-document-info"})
        label = soup.new_tag("summary"); label.string = "문서 정보"
        info.append(label)
        for element in groups["metadata_selectors"]:
            info.append(element.extract())
        article.insert(insert_at, info); insert_at += 1
    if not review["navigation"]:
        return
    headings = [h for h in article.find_all(list(_HEADINGS))
                if "st-document-title" not in h.get("class", []) and not any(
                    parent.name == "details" and set(parent.get_attribute_list("class")) & {"st-source-notes", "st-document-info", "st-toc"}
                    for parent in h.parents
                )]
    if not headings:
        return
    details = soup.new_tag("details", attrs={"class": "st-toc"})
    label = soup.new_tag("summary"); label.string = "목차"
    details.append(label)
    nav = soup.new_tag("nav", attrs={"aria-label": "문서 목차"})
    root = soup.new_tag("ol"); nav.append(root); details.append(nav)
    used = {str(tag["id"]) for tag in article.select("[id]")}
    used.update(_legacy_anchor_names(article))
    number = 1
    stack = [(int(headings[0].name[1]), root)]
    for heading in headings:
        if not heading.has_attr("id"):
            while f"st-heading-{number:04d}" in used:
                number += 1
            heading["id"] = f"st-heading-{number:04d}"
            used.add(heading["id"]); number += 1
        if not str(heading["id"]):
            raise ReaderError("navigation heading has an empty ID")
        level = int(heading.name[1])
        while len(stack) > 1 and level < stack[-1][0]:
            stack.pop()
        if level > stack[-1][0] and stack[-1][1].find("li", recursive=False) is not None:
            nested = soup.new_tag("ol")
            stack[-1][1].find_all("li", recursive=False)[-1].append(nested)
            stack.append((level, nested))
        elif level < stack[0][0]:
            stack[0] = (level, root)
        item = soup.new_tag("li")
        link = soup.new_tag("a", href="#" + quote(str(heading["id"]), safe=""))
        link.string = heading.get_text(" ", strip=True).replace("¶", "").strip()
        item.append(link); stack[-1][1].append(item)
    article.insert(insert_at, details)
