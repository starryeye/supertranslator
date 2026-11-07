"""Explicit source-reviewed structure; no inferred labels, numbering or translation."""
from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from supertranslator.reader import ReaderError, _anchor_spacer, _one
from supertranslator.reader_editing import _INLINE


@dataclass
class ResolvedStructure:
    definitions: list[tuple[Tag, int]] = field(default_factory=list)
    lists: list[list[tuple[Tag, int, list[Tag | NavigableString]]]] = field(default_factory=list)


def _fail(message: str) -> None:
    raise ReaderError(f"reader structure: {message}")


def _record(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        _fail("invalid review fields")
    if "evidence" in fields and (not isinstance(value["evidence"], str) or not value["evidence"].strip()):
        _fail("nonempty source-review evidence is required")
    return value


def _select(article: Tag, selector: object, selected: list[Tag], excluded: list[Tag]) -> Tag:
    try:
        element = _one(article, selector)
    except ReaderError as error:
        _fail(str(error))
    if (element is article or element.name not in {"p", "div"}
            or any(tag.name not in _INLINE for tag in element.find_all(True))
            or any(parent.name in {"pre", "dl", "dt", "dd", "ul", "ol", "li"}
                   or parent.get("role") in {"list", "listitem"}
                   or parent.get("data-reader-list") == "true"
                   or parent.name == "details" and "st-source-notes" in parent.get("class", [])
                   for parent in element.parents)
            or element.get("data-reader-list") == "true"
            or element.get("role") not in {None, "listitem"}):
        _fail("selection must be a live flat-inline block outside existing list owners")
    if any(element is other or element in other.parents or other in element.parents
           for other in selected + excluded):
        _fail("overlapping structure or presentation selections")
    selected.append(element)
    return element


def _boundary(element: Tag, offset: object) -> None:
    text = element.get_text()
    if type(offset) is not int or not 0 < offset < len(text) or not text[:offset].strip() or not text[offset:].strip():
        _fail("definition needs an integer boundary with a nonempty term and description")
    cursor = 0
    for node in element.contents:
        if isinstance(node, Comment):
            continue
        length = len(node.get_text()) if isinstance(node, Tag) else len(str(node))
        if cursor < offset < cursor + length and isinstance(node, Tag):
            _fail("definition boundary splits an inline subtree")
        cursor += length


def resolve_structure(article: Tag, review: dict) -> ResolvedStructure:
    """Validate exact review decisions before list wrappers change selectors."""
    resolved = ResolvedStructure()
    if "structure" not in review:
        return resolved
    data = _record(review["structure"], {"definitions", "lists"})
    if not isinstance(data["definitions"], list) or not isinstance(data["lists"], list):
        _fail("definitions and lists must be arrays")
    selected: list[Tag] = []
    excluded = [_one(article, selector) for kind, selectors in review.get("presentation", {}).items()
                if kind != "navigation" for selector in selectors]
    for record in data["definitions"]:
        record = _record(record, {"selector", "term_end", "evidence"})
        element = _select(article, record["selector"], selected, excluded)
        _boundary(element, record["term_end"])
        resolved.definitions.append((element, record["term_end"]))
    for record in data["lists"]:
        record = _record(record, {"items", "evidence"})
        if not isinstance(record["items"], list) or not record["items"]:
            _fail("list items must be a nonempty array")
        members = []
        previous = None
        previous_depth = -1
        for item in record["items"]:
            item = _record(item, {"selector", "depth"})
            depth = item["depth"]
            if type(depth) is not int or not 0 <= depth <= previous_depth + 1:
                _fail("list must start at depth zero and increase at most one level")
            element = _select(article, item["selector"], selected, excluded)
            spacers = []
            if previous is not None:
                if element.parent is not previous.parent:
                    _fail("list items must have the same parent")
                following = previous.next_sibling
                while following is not None and following is not element:
                    if (isinstance(following, NavigableString) and not following.strip()
                            or isinstance(following, Tag) and _anchor_spacer(following)):
                        spacers.append(following)
                        following = following.next_sibling
                    else:
                        _fail("list crosses unreviewed or reordered content")
                if following is not element:
                    _fail("list items must follow document order")
            members.append((element, depth, spacers))
            previous, previous_depth = element, depth
        resolved.lists.append(members)
    return resolved


def apply_structure(article: Tag, resolved: ResolvedStructure) -> None:
    """Move intact reviewed content into trusted layout after source sanitation."""
    before = article.get_text()
    soup = BeautifulSoup("", "html.parser")
    for element, offset in resolved.definitions:
        # A direct text node may be split; an existing inline subtree never is.
        term = soup.new_tag("dt", attrs={"class": "st-definition-term"})
        description = soup.new_tag("dd", attrs={"class": "st-definition-description"})
        cursor = 0
        for node in list(element.contents):
            length = len(node.get_text()) if isinstance(node, Tag) else len(str(node))
            if cursor + length <= offset:
                term.append(node.extract())
            elif cursor >= offset:
                description.append(node.extract())
            else:
                term.append(NavigableString(str(node)[:offset - cursor]))
                description.append(NavigableString(str(node)[offset - cursor:]))
                node.extract()
            cursor += length
        definition = soup.new_tag("dl", attrs={"class": "st-definition"})
        definition.append(term)
        definition.append(description)
        element.name = "div"
        element.append(definition)
    for members in resolved.lists:
        root = soup.new_tag("div", attrs={"role": "list", "class": "st-structured-list"})
        members[0][0].insert_before(root)
        owners = [root]
        last_item = None
        for element, depth, spacers in members:
            if depth == len(owners):
                nested = soup.new_tag("div", attrs={"role": "list", "class": "st-structured-list"})
                last_item.append(nested)
                owners.append(nested)
            else:
                owners = owners[:depth + 1]
            for spacer in spacers:
                owners[-1].append(spacer.extract())
            wrapper = soup.new_tag("div", attrs={"role": "listitem", "class": "st-structured-item"})
            # The new wrapper owns list semantics, not a duplicate inner item.
            if element.get("role") == "listitem":
                del element["role"]
                element.attrs.pop("class", None)
            wrapper.append(element.extract())
            owners[-1].append(wrapper)
            last_item = wrapper
    if article.get_text() != before:
        _fail("structure changed exact document text or order")
