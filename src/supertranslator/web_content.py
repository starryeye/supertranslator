"""Pure approved-input preparation and independent final-DOM content checking."""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
from html.parser import HTMLParser
import json
import re
import warnings

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning, NavigableString, Tag

from supertranslator.extract import TRANSLATABLE_ATTRIBUTES
from supertranslator.models import ApprovedWebContent, Finding, Segment, Translation
from supertranslator.paths import validate_public_url
from supertranslator.protection import ProtectionError, restore_tokens
from supertranslator.terminology import TerminologyError, normalize_first_use


def _parse(markup: str) -> BeautifulSoup:
    # BeautifulSoup otherwise collapses whitespace-only text nodes, even in a
    # fragment with no tags. The document sentinel preserves every character.
    with warnings.catch_warnings():
        # A translation may be a URL-looking string, not a request to fetch it.
        warnings.simplefilter("ignore", MarkupResemblesLocatorWarning)
        return BeautifulSoup(markup, "html.parser", preserve_whitespace_tags={"[document]"})


class _AttributeUniqueness(HTMLParser):
    """Reject duplicate attrs before parser-specific first/last value choices."""

    def handle_starttag(self, tag, attrs):
        names = [name for name, _value in attrs]
        if len(names) != len(set(names)):
            raise ValueError("duplicate-attributes")

    handle_startendtag = handle_starttag


def prepare_approved_web_content(
    source_html: str, segments: Mapping[str, Segment],
    translations: Mapping[str, Translation], glossary: Mapping[str, str],
) -> dict[str, ApprovedWebContent]:
    """Transform only approved inputs; never render or read a final output.

    The assembler's pure input validators and location decoder remain the one
    contract for marker IDs and located payloads. Final-DOM matching below does
    not use the assembler's replacement or shape routines.
    """
    from supertranslator.assemble import (
        AssemblyError, _parse_location_payload, _validate_markers,
        _validate_segments, _validate_translations,
    )
    segment_map = _validate_segments(segments)
    translation_map = _validate_translations(translations, segment_map)
    marked = _validate_markers(_parse(source_html), segment_map)
    ordered_ids = [str(node["data-wt-segment"]) for node in marked]
    try:
        normalized = normalize_first_use(
            [translation_map[sid] for sid in ordered_ids], glossary,
            protected_by_segment={sid: segment_map[sid].protected for sid in ordered_ids},
        )
        result = {}
        for sid, record in zip(ordered_ids, normalized, strict=True):
            restored = restore_tokens(record.text, segment_map[sid].protected)
            attributes, content = (_parse_location_payload(restored, segment_map[sid])
                                   if segment_map[sid].semantic_type.startswith("located:")
                                   else ({}, restored))
            result[sid] = ApprovedWebContent(attributes, content)
        return result
    except ProtectionError as error:
        raise AssemblyError(f"cannot restore approved web content: {error}") from error
    except TerminologyError as error:
        raise AssemblyError(f"terminology normalization failed: {error}") from error


def _finding(code, location, expected=None, actual=None):
    details = {"location": location}
    if expected is not None:
        details["expected_sha256"] = _digest(expected)
    if actual is not None:
        details["actual_sha256"] = _digest(actual)
    return Finding(code, "required", "Final HTML does not match its approved content contract.", details)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _tags(node):
    return [child for child in node.children if isinstance(child, Tag)]


def _paths(root):
    result = {}
    def walk(node, path):
        result[path] = node
        for index, child in enumerate(_tags(node)):
            walk(child, path + (index,))
    walk(root, ())
    return result


def _attrs(node, ignored=()):
    return tuple(sorted((key, tuple(value) if isinstance(value, list) else value)
                        for key, value in node.attrs.items()
                        if key != "data-wt-segment" and key not in ignored))


def _signature(node, owners, expected, path=(), *, inner=False):
    """Exact DOM values, with separately checked ownership slots masked.

    Paths come exclusively from the source, never output markers or prose.
    HTML entities are decoded once by the parser; text, comments and literal
    whitespace are otherwise left intact, including CRLF in opaque blocks.
    """
    sid = owners.get(path)
    payload = expected.get(sid) if sid is not None else None
    if payload is not None and payload.content_html is not None:
        children = (("owned-content", sid),)
    else:
        children = []
        tag_index = 0
        for child in node.children:
            if isinstance(child, Tag):
                children.append(_signature(child, owners, expected, path + (tag_index,)))
                tag_index += 1
            elif isinstance(child, NavigableString):
                value = (type(child).__name__, str(child))
                # Adjacent ordinary text nodes are one DOM text stream after
                # serialization; do not collapse or strip their characters.
                if children and value[0] == "NavigableString" and children[-1][0] == value[0]:
                    children[-1] = (value[0], children[-1][1] + value[1])
                else:
                    children.append(value)
        children = tuple(children)
    if inner:
        return children
    return (node.name, _attrs(node, payload.attributes if payload else ()), children)


def _strip_backend(soup, *, output):
    """Permit only the backend's fixed metadata/attribution, not arbitrary prose."""
    from supertranslator.assemble import _CSP
    removed_charset = removed_csp = 0
    for meta in list(soup.find_all("meta")):
        if meta.has_attr("charset") or str(meta.get("http-equiv", "")).lower() == "content-type":
            if output:
                removed_charset += 1
                if (removed_charset != 1 or meta.parent is not soup.head
                        or dict(meta.attrs) != {"charset": "utf-8"}):
                    raise ValueError("metadata")
            meta.decompose()
        elif output and meta.has_attr("data-wt-csp"):
            removed_csp += 1
            if (removed_csp != 1 or meta.parent is not soup.head or
                    dict(meta.attrs) != {"data-wt-csp": "offline", "http-equiv": "Content-Security-Policy", "content": _CSP}):
                raise ValueError("metadata")
            meta.decompose()
    attributions = soup.select("[data-wt-attribution]")
    if attributions:
        if not output or len(attributions) != 1:
            raise ValueError("attribution")
        footer = attributions[0]
        link = footer.find("a")
        if (footer.name != "footer" or footer.parent is not soup.body
                or footer.attrs != {"data-wt-attribution": "source"} or link is None
                or link.attrs != {"href": link.get("href"), "rel": ["noopener", "noreferrer"]}
                or len(footer.contents) != 2 or str(footer.contents[0]) != "AI 번역본 · "
                or footer.contents[1] is not link
                or len(link.contents) != 1 or str(link.contents[0]) != "원문 보기"):
            raise ValueError("attribution")
        validate_public_url(link["href"])
        footer.decompose()


def check_approved_web_content(
    source_html: str, output_html: str, segments: Mapping[str, Segment] | None,
    expected: Mapping[str, ApprovedWebContent] | None,
) -> list[Finding]:
    """Compare approved owners and untouched source content at real DOM paths."""
    contract = "approved-content-contract"
    integrity = "approved-content-integrity"
    if (not isinstance(segments, Mapping) or not isinstance(expected, Mapping)
            or set(segments) != set(expected)
            or any(not isinstance(s, Segment) or sid != s.id or not s.target
                   or s.locator != f"[data-wt-segment='{sid}']"
                   for sid, s in segments.items())
            or any(not isinstance(p, ApprovedWebContent) or not isinstance(p.attributes, dict)
                   or any(a not in TRANSLATABLE_ATTRIBUTES or not isinstance(v, str)
                          for a, v in p.attributes.items())
                   or (p.content_html is not None and not isinstance(p.content_html, str))
                   or (p.content_html is None and not p.attributes) for p in expected.values())):
        return [_finding(contract, "target-coverage")]
    try:
        _AttributeUniqueness(convert_charrefs=False).feed(output_html)
    except ValueError:
        return [_finding(integrity, "duplicate-attributes")]
    source = _parse(source_html)
    output = _parse(output_html)
    markers = source.select("[data-wt-segment]")
    ids = [str(node["data-wt-segment"]) for node in markers]
    if len(ids) != len(set(ids)) or set(ids) != set(segments):
        return [_finding(contract, "source-ownership")]
    try:
        _strip_backend(source, output=False)
        _strip_backend(output, output=True)
    except (ValueError, TypeError):
        return [_finding(integrity, "backend-metadata-or-attribution")]
    source_paths, output_paths = _paths(source), _paths(output)
    owners = {path: str(node["data-wt-segment"]) for path, node in source_paths.items()
              if node.has_attr("data-wt-segment")}
    if set(owners.values()) != set(segments):
        return [_finding(contract, "source-ownership")]
    findings = []
    if output.select("[data-wt-segment]"):
        findings.append(_finding(integrity, "unconsumed-marker"))
    left = _signature(source, owners, expected)
    right = _signature(output, owners, expected)
    if left != right:
        findings.append(_finding(integrity, "unowned-source-content", left, right))
    for path, sid in owners.items():
        original, actual = source_paths[path], output_paths.get(path)
        payload = expected[sid]
        if actual is None or actual.name != original.name:
            findings.append(_finding(integrity, f"{sid}:owner"))
            continue
        # A partial located payload must never turn untranslated attributes or
        # source content into an exemption from comparison.
        required_attributes = {
            match.group(1) for token in segments[sid].protected
            if token.kind == "location"
            and (match := re.fullmatch(r"<!--wt-location:attribute:([a-z][a-z0-9-]*)-->", token.value))
        }
        located = segments[sid].semantic_type.startswith("located:")
        required_content = any(token.kind == "location" and token.value == "<!--wt-location:content-->"
                               for token in segments[sid].protected)
        if (located != bool(required_attributes)
                or not required_attributes.issubset(original.attrs)
                or set(payload.attributes) != required_attributes
                or (located and required_content != (payload.content_html is not None))
                or (payload.content_html is None) != (segments[sid].semantic_type == "located:attributes")):
            findings.append(_finding(contract, f"{sid}:locations"))
            continue
        for attribute, value in payload.attributes.items():
            if actual.get(attribute) != value:
                findings.append(_finding(integrity, f"{sid}:attribute:{attribute}", value, actual.get(attribute)))
        if payload.content_html is not None:
            fragment = _parse(payload.content_html)
            nested = {p[len(path):]: child for p, child in owners.items()
                      if len(p) > len(path) and p[:len(path)] == path}
            fragment_paths = _paths(fragment)
            fragment_owners = {p: str(node["data-wt-segment"]) for p, node in fragment_paths.items()
                               if node.has_attr("data-wt-segment")}
            if fragment_owners != nested:
                findings.append(_finding(contract, f"{sid}:nested-ownership"))
                continue
            wanted = _signature(fragment, nested, expected, inner=True)
            got = _signature(actual, nested, expected, inner=True)
            if wanted != got:
                findings.append(_finding(integrity, f"{sid}:content", wanted, got))
    return findings
