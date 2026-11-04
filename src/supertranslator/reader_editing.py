"""Source-reviewed prose corrections; no translation or token rewriting."""
from __future__ import annotations

from collections import Counter
import re

from bs4 import BeautifulSoup, Tag

from supertranslator.protection import protect_fragment
from supertranslator.reader import ReaderError, _digest, _one


_FIELDS = {"selector", "input_html_sha256", "replacement_html", "source_text", "evidence"}
_INLINE = {"a", "span", "code", "em", "strong", "b", "i", "sup", "sub", "br", "samp", "var", "kbd", "abbr"}


def _atoms(element: Tag | BeautifulSoup) -> Counter:
    # English nouns/identifiers and numeric facts are not translation targets here.
    return Counter(re.findall(r"[A-Za-z_][A-Za-z0-9_./+-]*|[-+−]?\d+(?:[.,]\d+)*(?:[eE][-+−]?\d+)?", element.get_text()))


def apply_text_edits(article: Tag, edits: list) -> None:
    """Apply only exact-input-bound edits that retain every intact inline subtree."""
    if not isinstance(edits, list):
        raise ReaderError("text_edits must be a list")
    prepared = []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != _FIELDS or any(
            not isinstance(edit[name], str) or not edit[name].strip() for name in _FIELDS
        ):
            raise ReaderError("text edit requires exact input, source text and semantic evidence")
        element = _one(article, edit["selector"])
        if element.name not in {"p", "li"} or element.find_parent("details", class_="st-source-notes"):
            raise ReaderError("text edit must select live prose")
        if any(element is other or element in other.parents or other in element.parents for other, _ in prepared):
            raise ReaderError("overlapping text edits")
        original = element.decode_contents()
        if _digest(original.encode("utf-8")) != edit["input_html_sha256"]:
            raise ReaderError("text edit input HTML digest mismatch")
        replacement = BeautifulSoup(edit["replacement_html"], "html.parser")
        if not replacement.get_text().strip() or any(tag.name not in _INLINE for tag in replacement.find_all(True)):
            raise ReaderError("text edit must contain prose and existing inline markup only")
        # Moving an intact reference or normative span is permitted; changing its
        # text, attributes, children, multiplicity or destination is not.
        if Counter(str(tag) for tag in element.find_all(True)) != Counter(str(tag) for tag in replacement.find_all(True)):
            raise ReaderError("text edit changed an inline subtree")
        _, old_tokens = protect_fragment(original)
        _, new_tokens = protect_fragment(edit["replacement_html"])
        protected = lambda tokens: Counter((token.kind, token.value) for token in tokens if token.kind != "tag")
        if protected(old_tokens) != protected(new_tokens) or _atoms(element) != _atoms(replacement):
            raise ReaderError("text edit changed protected content or English/numeric atoms")
        prepared.append((element, replacement))
    for element, replacement in prepared:
        element.clear()
        for child in list(replacement.contents):
            element.append(child.extract())
