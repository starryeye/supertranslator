"""Deterministic structural, offline, and browser QA for translated pages."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import hashlib
from html import unescape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Route, WebSocketRoute, sync_playwright
import tinycss2
from tinycss2.ast import AtRule, FunctionBlock, StringToken, URLToken

from web_translator.extract import TRANSLATABLE_ATTRIBUTES
from web_translator.models import Finding, ProtectedToken, QAInputs, QAResult
from web_translator.protection import _URL_PATTERN, _trim_url_end
import web_translator.pdf_assemble as anchored
from web_translator.preformatted_runtime import hold_processing_source, verify_preformatted_output


_TOKEN_PATTERN = re.compile(r"⟦WT:\d{6}⟧")
_URL_CANDIDATE_PATTERN = re.compile(_URL_PATTERN, re.IGNORECASE)
_VIEWPORTS = (("desktop-1440x900", 1440, 900), ("narrow-390x844", 390, 844))
_BROWSER_METRICS = """(() => {
  const stylesheetFailures = [];
  const visited = new Set();
  function inspectStylesheet(sheet, href) {
    if (!sheet) {
      stylesheetFailures.push({href, reason: 'not-loaded'});
      return;
    }
    if (visited.has(sheet)) return;
    visited.add(sheet);
    let rules;
    try {
      rules = sheet.cssRules;
    } catch (error) {
      stylesheetFailures.push({href, reason: 'rules-inaccessible'});
      return;
    }
    for (const rule of rules) {
      if (rule.type === CSSRule.IMPORT_RULE) {
        const importedHref = rule.href || href;
        if (!rule.styleSheet) {
          stylesheetFailures.push({href: importedHref, reason: 'import-not-loaded'});
        } else {
          inspectStylesheet(rule.styleSheet, importedHref);
        }
      }
    }
  }
  for (const owner of document.querySelectorAll('link[rel~="stylesheet"], style')) {
    const href = owner.getAttribute('href') || '<inline-style>';
    const sheet = [...document.styleSheets].find(item => item.ownerNode === owner);
    inspectStylesheet(sheet, href);
  }
  return {
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    brokenImages: [...document.images].filter(img => !img.complete || img.naturalWidth === 0).map(img => img.src),
    clippedText: [...document.querySelectorAll('main *')].filter(el => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX === 'hidden').length,
    stylesheetFailures
  };
})()"""
_URL_ATTRIBUTES = {
    "a": ("href",),
    "audio": ("src",),
    "embed": ("src",),
    "iframe": ("src",),
    "img": ("src", "srcset"),
    "link": ("href",),
    "object": ("data",),
    "script": ("src",),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
}
_OPTIONAL_TAGS = {"audio", "img", "source", "video"}
_REPARSE_POINT = 0x400
_END_GUARD = "\x00END"
_TAG_BOUNDARY_GUARD = "\x00TAG"


def run_qa(inputs: QAInputs) -> QAResult:
    """Run stable preflight checks, followed by isolated Chromium QA."""
    if not isinstance(inputs, QAInputs):
        raise TypeError("inputs must be QAInputs")
    known_preformatted = _has_preformatted_state(inputs.source_html.parent)
    result = None
    try:
        if inputs.normalization is None and not known_preformatted:
            with _hold_legacy_qa_state(inputs.source_html.parent):
                result = _run_qa(inputs)
            return result
        if inputs.normalization is None:
            raise ValueError('preformatted-provenance: known preformatted source requires normalization evidence')
        _prepare_preformatted_screenshots(inputs.source_html.parent, inputs.screenshot_dir)
        with hold_processing_source(inputs.source_html.parent, phase="qa") as source:
            if source.path != inputs.source_html.absolute() or source.normalization != inputs.normalization:
                raise ValueError("preformatted-provenance: QA normalization/source does not match held provenance")
            with _hold_preformatted_output(source, inputs.output_html) as output:
                output.verify()
                result = _run_qa(inputs)
                output.verify()
    except (ValueError, anchored.PdfAssemblyError, OSError) as error:
        code = 'preformatted-literal-integrity' if str(error).startswith('preformatted-literal-integrity:') else 'preformatted-provenance'
        finding = _required(code, "Preformatted acceptance evidence is invalid.", {'reason': str(error)})
        if result is None:
            return QAResult(False, [finding], [], [], source_url=inputs.source_url,
                            capture_metadata=dict(inputs.capture_metadata), normalization=inputs.normalization)
        return replace(result, passed=False, required_findings=[*result.required_findings, finding])
    return result


@contextmanager
def _hold_legacy_qa_state(run_dir: Path):
    """Bind direct legacy acceptance to a live absence inventory, not capture metadata."""
    with ExitStack() as stack:
        if not os.path.lexists(run_dir):
            # Preserve the ordinary missing-source diagnostic.
            yield
            if os.path.lexists(run_dir):
                raise ValueError('QA source directory appeared during checks')
            return
        anchored._reject_linked_ancestors(run_dir)
        root = anchored._open_directory_anchor(run_dir, 'legacy QA state')
        stack.callback(root.close)
        assets = None
        if 'assets' in anchored._anchored_directory_names(root):
            assets = anchored._open_existing_child_directory(root, 'assets', 'legacy QA assets')
            stack.callback(assets.close)

        def verify():
            root.verify_visible()
            names = anchored._anchored_directory_names(root)
            if ('preformatted' in names or 'preformatted-source.html' in names
                    or any(name.startswith('.preformatted-') for name in names)):
                raise ValueError('preformatted state requires normalization evidence')
            if ('assets' in names) != (assets is not None):
                raise ValueError('QA asset inventory changed during checks')
            if assets is not None:
                assets.verify_visible()
                if any(name.startswith('wt-preformatted-')
                       for name in anchored._anchored_directory_names(assets)):
                    raise ValueError('preformatted assets require normalization evidence')

        verify()
        yield
        verify()


def _has_preformatted_state(run_dir: Path) -> bool:
    """Inventory lexical runtime indicators, never traverse a linked asset tree.

    An unsafe/unreadable inventory cannot establish legacy absence; route it
    through provenance failure handling and leave validation to the runtime.
    """
    if not os.path.lexists(run_dir):
        return False
    root = assets = None
    try:
        anchored._reject_linked_ancestors(run_dir)
        root = anchored._open_directory_anchor(run_dir, 'QA state inventory')
        names = anchored._anchored_directory_names(root)
        if ('preformatted' in names or 'preformatted-source.html' in names
                or any(name.startswith('.preformatted-') for name in names)):
            return True
        if 'assets' not in names:
            return False
        assets = anchored._open_existing_child_directory(root, 'assets', 'QA asset inventory')
        return any(name.startswith('wt-preformatted-')
                   for name in anchored._anchored_directory_names(assets))
    except (ValueError, anchored.PdfAssemblyError, OSError):
        return True
    finally:
        if assets is not None:
            assets.close()
        if root is not None:
            root.close()


def _prepare_preformatted_screenshots(run_dir, screenshot_dir):
    """Create the consumer-owned directory before the immutable run lease."""
    if screenshot_dir.absolute().parent != run_dir.absolute():
        raise ValueError('preformatted-provenance: screenshots must be an immediate run child')
    anchored._reject_linked_ancestors(run_dir)
    root = anchored._open_directory_anchor(run_dir, 'QA screenshot run')
    child = None
    try:
        if screenshot_dir.name in anchored._anchored_directory_names(root):
            child = anchored._open_existing_child_directory(root, screenshot_dir.name, 'QA screenshots')
        else:
            child = anchored._create_child_directory(root, screenshot_dir.name, 'QA screenshots')
        root.verify_visible()
        child.verify_visible()
    finally:
        if child is not None:
            child.close()
        root.close()


@contextmanager
def _hold_preformatted_output(source, output_html):
    """Keep exact output/CSS descriptors live across checks and publication."""
    with ExitStack() as stack:
        root = anchored._open_directory_anchor(output_html.parent, 'preformatted output')
        stack.callback(root.close)
        directories = {'': root}
        files = []
        for relative, digest in [(output_html.name, None),
                                 *((a['path'], a['sha256']) for a in source.generated_critical_assets)]:
            parent, _, name = relative.rpartition('/')
            if parent not in directories:
                directories[parent] = anchored._open_existing_child_directory(root, parent, 'generated assets')
                stack.callback(directories[parent].close)
            directory = directories[parent]
            opened = anchored._open_anchored_input_file(directory, name, 'preformatted output evidence')
            stack.callback(anchored._close_opened_file, opened)
            payload = opened.stream.read()
            files.append((directory, name, opened, payload))
            if digest is not None and hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError('preformatted-provenance: generated critical CSS digest mismatch')

        class Snapshot:
            def verify(self):
                source.verify()
                for directory, name, opened, payload in files:
                    anchored._verify_anchored_evidence(directory, {name: opened})
                    opened.stream.seek(0)
                    if os.fstat(opened.stream.fileno()).st_nlink != 1 or opened.stream.read() != payload:
                        raise ValueError('preformatted-provenance: held output evidence changed')
                try:
                    verify_preformatted_output(source, output_html)
                except ValueError as error:
                    raise ValueError(f'preformatted-literal-integrity: {error}') from error

        snapshot = Snapshot()
        snapshot.verify()
        yield snapshot
        snapshot.verify()


def _run_qa(inputs: QAInputs) -> QAResult:

    required: list[Finding] = []
    warnings: list[Finding] = []
    screenshots: list[Path] = []
    browser_metrics: dict[str, dict[str, object]] = {}

    _check_coverage(inputs, required)
    source_text = _read_utf8(inputs.source_html, "source-html", required, preserve_newlines=inputs.normalization is not None)
    output_text = _read_utf8(inputs.output_html, "output-html", required, preserve_newlines=inputs.normalization is not None)
    if source_text is not None and output_text is not None:
        # lxml normalizes raw CRLF even when byte decoding preserves it. The
        # adapter's parser retains the exact literal/opaque DOM text stream.
        parser = 'html.parser' if inputs.normalization is not None else 'lxml'
        source_soup = BeautifulSoup(source_text, parser)
        output_soup = BeautifulSoup(output_text, parser)
        _check_tokens(inputs, source_soup, output_soup, output_text, required)
        _check_structure(source_soup, output_soup, required)
        _check_anchors(output_soup, inputs.output_html.name, required)
        _check_external_dependencies(inputs, output_soup, required, warnings)

    _check_assets(inputs, required, warnings)
    _check_master_review(inputs, required)
    screenshot_root = _validated_screenshot_dir(inputs, required)

    # Browser evidence is meaningful only after deterministic prerequisites pass.
    if not required and screenshot_root is not None:
        browser_required, browser_warnings, screenshots, browser_metrics = _run_browser_checks(
            inputs.output_html, screenshot_root
        )
        required.extend(browser_required)
        warnings.extend(browser_warnings)

    required = _coalesce_findings(required)
    warnings = _coalesce_findings(warnings)

    return QAResult(
        passed=not required and not inputs.master_review.unresolved_required,
        required_findings=required,
        warnings=warnings,
        screenshots=screenshots,
        source_url=inputs.source_url,
        browser_metrics=browser_metrics,
        capture_metadata=dict(inputs.capture_metadata),
        normalization=inputs.normalization,
    )


def _coalesce_findings(findings: list[Finding]) -> list[Finding]:
    result: list[Finding] = []
    positions: dict[tuple[str, str], int] = {}
    for finding in findings:
        key = (finding.severity, finding.code)
        position = positions.get(key)
        if position is None:
            positions[key] = len(result)
            result.append(finding)
            continue
        previous = result[position]
        evidence = dict(previous.evidence)
        for name, value in finding.evidence.items():
            old_value = evidence.get(name)
            if isinstance(old_value, list) and isinstance(value, list):
                evidence[name] = sorted(set(old_value) | set(value))
            elif old_value is None:
                evidence[name] = value
            elif old_value != value:
                evidence[name] = [old_value, value]
        result[position] = Finding(
            previous.code, previous.severity, previous.message, evidence
        )
    return result


def _required(code: str, message: str, evidence: dict[str, object]) -> Finding:
    return Finding(code, "required", message, evidence)


def _warning(code: str, message: str, evidence: dict[str, object]) -> Finding:
    return Finding(code, "warning", message, evidence)


def _check_coverage(inputs: QAInputs, findings: list[Finding]) -> None:
    missing = sorted(inputs.source_segment_ids - inputs.translated_segment_ids)
    foreign = sorted(inputs.translated_segment_ids - inputs.source_segment_ids)
    if missing or foreign or (inputs.normalization is not None and not inputs.source_segment_ids):
        findings.append(
            _required(
                "translation-coverage",
                "Translated segment IDs do not exactly cover source segment IDs.",
                {"foreign": foreign, "missing": missing},
            )
        )


def _read_utf8(path: Path, label: str, findings: list[Finding], *, preserve_newlines: bool = False) -> str | None:
    try:
        if _is_link_or_reparse(path) or not path.is_file():
            raise OSError("file is missing or unsafe")
        return path.read_bytes().decode('utf-8') if preserve_newlines else path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        findings.append(
            _required(
                f"{label}-unreadable",
                f"{label} must be a safe UTF-8 file.",
                {"path": str(path), "reason": str(error)},
            )
        )
        return None


def _check_tokens(
    inputs: QAInputs,
    source_soup: BeautifulSoup,
    output_soup: BeautifulSoup,
    output_text: str,
    findings: list[Finding],
) -> None:
    changed: set[str] = set()
    for segment_id in sorted(inputs.protected_tokens):
        tokens = inputs.protected_tokens[segment_id]
        text = inputs.translated_texts.get(segment_id)
        if text is None or not _has_exact_tokens(text, tokens):
            changed.add(segment_id)
            continue
        source_elements = source_soup.find_all(
            attrs={"data-wt-segment": segment_id}
        )
        if len(source_elements) != 1:
            changed.add(segment_id)
            continue
        source_element = source_elements[0]
        output_element = _corresponding_output_element(
            source_soup.html, output_soup.html, source_element
        )
        if not isinstance(source_element, Tag) or output_element is None:
            changed.add(segment_id)
            continue
        semantic_text = text
        metadata_kinds = {"location", "segment"}
        guard_tokens = [token for token in tokens if token.kind not in metadata_kinds]
        for token in tokens:
            if token.kind in metadata_kinds:
                semantic_text = semantic_text.replace(token.token, "")
        locations: dict[str, list[ProtectedToken]] = {}
        location = "<!--wt-location:content-->"
        for token in tokens:
            if token.kind == "location":
                location = token.value
                continue
            if token.kind == "segment":
                continue
            locations.setdefault(location, []).append(token)
        for location, owned_tokens in locations.items():
            fragments = _owned_location_fragments(
                source_element, output_element, location, owned_tokens
            )
            if fragments is None:
                changed.add(segment_id)
                break
            source_parts, output_parts, source_markup, output_markup = fragments
            opaque_expected = Counter(
                _normalized_fragment(token.value)
                for token in owned_tokens if token.kind in {"code", "excluded"}
            )
            if source_markup != opaque_expected or output_markup != opaque_expected:
                changed.add(segment_id)
                break
            regular = [token for token in owned_tokens if token.kind not in {"tag", "code", "excluded"}]
            expected: Counter[str] = Counter()
            kinds: dict[str, set[str]] = {}
            guarded: Counter[tuple[str, str, str | None]] = Counter()
            url_contexts = {token.token: _url_token_context(text, token, tokens)
                            for token in regular if token.kind == "url"}
            if any(context is None for context in url_contexts.values()):
                changed.add(segment_id)
                break
            url_literals: dict[str, Counter[tuple[str, tuple[str, str] | None]]] = {}
            for token in regular:
                if token.kind == "url":
                    value, literal, guard, following = url_contexts[token.token]
                    anchor = None
                    if following is not None:
                        if following not in regular:
                            changed.add(segment_id)
                            break
                        next_value = (url_contexts[following.token][0] if following.kind == "url"
                                      else unescape(following.value))
                        anchor = (next_value, following.kind)
                    url_literals.setdefault(value, Counter())[(literal, anchor)] += 1
                else:
                    value = unescape(token.value)
                    guard = _following_token_guard(semantic_text, token.token, guard_tokens)
                if not value:
                    changed.add(segment_id)
                    break
                expected[value] += 1
                kinds.setdefault(value, set()).add(token.kind)
                guarded[(value, token.kind, guard)] += 1
            if segment_id in changed:
                break
            source_matches = _nonoverlapping_protected_matches(source_parts, kinds)
            output_matches = _nonoverlapping_protected_matches(output_parts, kinds, url_literals)
            if (Counter(value for _, _, value in source_matches) != expected
                or Counter(value for _, _, value in output_matches) != expected
                or any(
                    sum(_matches_url_literal(part, end, literal, anchor, output_matches)
                        for part, end, matched_value in output_matches if matched_value == value) != count
                    for value, contexts in url_literals.items()
                    for (literal, anchor), count in contexts.items()
                    if literal and not literal[0].isascii() and not literal[0].isspace()
                )
                or any(
                    sum(
                        _matches_following_guard(part, end, kind, guard)
                        for part, end, matched_value in output_matches
                        if matched_value == value
                    ) != count
                    for (value, kind, guard), count in guarded.items()
                )):
                changed.add(segment_id)
                break
    leaked = sorted(set(_TOKEN_PATTERN.findall(output_text)))
    if changed or leaked:
        findings.append(
            _required(
                "protected-token-integrity",
                "Protected placeholders changed or leaked into the assembled page.",
                {"changed_segments": sorted(changed), "leaked_placeholders": leaked},
            )
        )


def _has_exact_tokens(text: str, tokens: Iterable[ProtectedToken]) -> bool:
    expected: list[str] = []
    for token in tokens:
        if not isinstance(token, ProtectedToken) or _TOKEN_PATTERN.fullmatch(token.token) is None:
            return False
        expected.append(token.token)
    if len(expected) != len(set(expected)):
        return False
    actual = _TOKEN_PATTERN.findall(text)
    return sorted(actual) == sorted(expected) and all(text.count(token) == 1 for token in expected)


def _owned_location_fragments(
    source: Tag, output: Tag, location: str, tokens: list[ProtectedToken]
) -> tuple[list[str], list[str], Counter[str], Counter[str]] | None:
    if location != "<!--wt-location:content-->":
        match = re.fullmatch(r"<!--wt-location:attribute:([a-z][a-z0-9-]*)-->", location)
        if match is None or match.group(1) not in TRANSLATABLE_ATTRIBUTES:
            return None
        source_value = source.get(match.group(1))
        output_value = output.get(match.group(1))
        if not isinstance(source_value, str) or not isinstance(output_value, str):
            return None
        return [source_value], [output_value], Counter(), Counter()

    excluded: set[tuple[int, ...]] = set()
    nested: set[tuple[int, ...]] = set()
    opaque = {_normalized_fragment(token.value) for token in tokens if token.kind in {"code", "excluded"}}

    def mark_excluded(tag: Tag, path: tuple[int, ...] = ()) -> None:
        index = 0
        for child in tag.children:
            if not isinstance(child, Tag):
                continue
            child_path = path + (index,)
            if child.has_attr("data-wt-segment"):
                nested.add(child_path)
                excluded.add(child_path)
            elif _normalized_fragment(str(child)) in opaque:
                excluded.add(child_path)
            else:
                mark_excluded(child, child_path)
            index += 1

    def text_parts(tag: Tag, path: tuple[int, ...] = ()) -> list[str]:
        parts: list[str] = []
        index = 0
        for child in tag.children:
            if isinstance(child, Tag):
                child_path = path + (index,)
                if child_path not in excluded:
                    parts.extend(text_parts(child, child_path))
                index += 1
            elif isinstance(child, NavigableString) and not isinstance(child, Comment):
                parts.append(str(child))
        return parts

    def opaque_counts(tag: Tag, path: tuple[int, ...] = ()) -> Counter[str]:
        counts: Counter[str] = Counter()
        index = 0
        for child in tag.children:
            if not isinstance(child, Tag):
                continue
            child_path = path + (index,)
            if child_path not in nested:
                value = _normalized_fragment(str(child))
                if value in opaque:
                    counts[value] += 1
                else:
                    counts.update(opaque_counts(child, child_path))
            index += 1
        return counts

    mark_excluded(source)
    return text_parts(source), text_parts(output), opaque_counts(source), opaque_counts(output)


def _nonoverlapping_protected_matches(
    parts: list[str], kinds: dict[str, set[str]],
    url_literals: dict[str, Counter[tuple[str, tuple[str, str] | None]]] | None = None,
) -> list[tuple[str, int, str]]:
    selected: list[tuple[str, int, str]] = []
    urls = {value for value, value_kinds in kinds.items() if "url" in value_kinds}
    for part in parts:
        candidates = {
            (match.start(), match.end(), value)
            for value, value_kinds in kinds.items()
            for kind in value_kinds
            if kind != "url"
            for match in re.finditer(_exact_fragment_pattern(value, kind), part)
        }
        # Decoded entities may contain raw-HTML URL delimiters. Continue through
        # one only when the producer protected that exact prefix, then compare
        # the complete candidate so an extension cannot match a shorter value.
        cursor = 0
        while match := _URL_CANDIDATE_PATTERN.search(part, cursor):
            start, end = match.span()
            while end < len(part) and not part[end].isspace():
                if part[end] in "<>\"'" and not any(
                    url.startswith(part[start:end + 1]) for url in urls
                ):
                    break
                end += 1
            cursor = end
            value_end = _trim_url_end(part, start, end)
            value = part[start:value_end]
            if value in urls:
                candidates.add((start, value_end, value))
            else:
                # A non-ASCII character can be URL path data, not a delimiter.
                # Cut only at an exact held token/literal boundary, matching the
                # entire following literal rather than a particle or first letter.
                owned = [
                    url for url, literals in (url_literals or {}).items()
                    if part.startswith(url, start)
                    and any(literal and not literal[0].isascii() and not literal[0].isspace()
                            and _matches_url_literal(part, start + len(url), literal, anchor)
                            for literal, anchor in literals)
                ]
                if owned:
                    url = max(owned, key=len)
                    candidates.add((start, start + len(url), url))
                    # The held literal can be followed immediately by another
                    # URL; do not skip that owned occurrence with the greedy span.
                    cursor = start + len(url)
                elif any(value.startswith(url) for url in urls):
                    # Do not silently discard an altered/duplicate prefix when
                    # another intact occurrence could satisfy the expected count.
                    candidates.add((start, value_end, value))
        previous_end = 0
        for start, end, value in sorted(candidates, key=lambda item: (item[0], -item[1], item[2])):
            if start >= previous_end:
                selected.append((part, end, value))
                previous_end = end
    return selected


def _matches_url_literal(
    part: str, end: int, literal: str, anchor: tuple[str, str] | None,
    matches: list[tuple[str, int, str]] | None = None,
) -> bool:
    if not part.startswith(literal, end):
        return False
    boundary = end + len(literal)
    if anchor is None:
        return boundary == len(part)
    value, kind = anchor
    if matches is not None:
        # The final ownership check uses the selected exact occurrence, not a
        # prefix regex (notably for overlapping non-ASCII URL paths).
        return (part, boundary + len(value), value) in matches
    return bool(value) and re.compile(_exact_fragment_pattern(value, kind)).match(part, boundary) is not None


def _matches_following_guard(part: str, end: int, kind: str, guard: str | None) -> bool:
    if guard in {_END_GUARD, _TAG_BOUNDARY_GUARD}:
        return end == len(part)
    if guard:
        return part.startswith(guard, end)
    if kind == "url":
        return re.match(r"(?![A-Za-z0-9_~:/?#\[\]@!$&'()*+,;=%-])", part[end:]) is not None
    if kind in {"command", "identifier", "keyword"}:
        return re.match(r"(?![A-Za-z0-9_])", part[end:]) is not None
    return True


def _normalized_fragment(value: str) -> str:
    if "<" not in value and "&" not in value:
        return value
    return BeautifulSoup(value, "html.parser").decode_contents()


def _exact_fragment_pattern(value: str, kind: str) -> str:
    lexical = kind in {"command", "identifier", "keyword", "url"}
    prefix = (
        r"(?<![A-Za-z0-9_])"
        if lexical or (value[0].isascii() and value[0].isalnum())
        else ""
    )
    if kind == "url":
        suffix = r"(?![A-Za-z0-9_~:/?#\[\]@!$&'()*+=%_-]|[.,;](?=[A-Za-z0-9]))"
    else:
        suffix = (
            r"(?![A-Za-z0-9_])"
            if lexical or (value[-1].isascii() and value[-1].isalnum())
            else ""
        )
    return prefix + re.escape(value) + suffix


def _following_token_guard(
    text: str, placeholder: str, tokens: Iterable[ProtectedToken]
) -> str | None:
    start = text.index(placeholder) + len(placeholder)
    after = text[start:]
    following: list[tuple[int, ProtectedToken]] = []
    for token in tokens:
        position = after.find(token.token)
        if position >= 0:
            following.append((position, token))
    if following:
        position, next_token = min(following, key=lambda item: item[0])
        literal = unescape(after[:position])
        if literal:
            return literal[0]
        if next_token.kind in {"tag", "code", "excluded"}:
            return _TAG_BOUNDARY_GUARD
        normalized_next = unescape(next_token.value)
        return normalized_next[0] if normalized_next else None
    literal = unescape(after)
    return literal[0] if literal else _END_GUARD


def _url_token_context(
    text: str, token: ProtectedToken, tokens: list[ProtectedToken]
) -> tuple[str, str, str | None, ProtectedToken | None] | None:
    """Decode the complete held URL/literal representation across its boundary."""
    after = text[text.index(token.token) + len(token.token):]
    next_match = _TOKEN_PATTERN.search(after)
    literal = after[:next_match.start()] if next_match else after
    raw = token.value + literal
    boundary = len(token.value)
    # The producer may trim the final semicolon of a character reference.
    # Attribute and body DOM decoding consume that literal into the same entity.
    for match in re.finditer(r"&(?:\#[xX][0-9a-fA-F]+|\#[0-9]+|[A-Za-z][A-Za-z0-9]*);?", raw):
        if match.start() < boundary < match.end() and unescape(match.group()) != match.group():
            boundary = match.end()
            break
    value = unescape(raw[:boundary])
    decoded = unescape(raw)
    if not decoded.startswith(value):
        return None
    literal = decoded[len(value):]
    following = next((t for t in tokens if next_match and t.token == next_match.group()), None)
    next_regular = (following if following is not None
                    and following.kind not in {"location", "segment", "tag", "code", "excluded"} else None)
    if literal:
        return value, literal, literal[0], next_regular
    if following:
        if following.kind in {"location", "segment"}:
            return value, literal, _END_GUARD, next_regular
        if following.kind in {"tag", "code", "excluded"}:
            return value, literal, _TAG_BOUNDARY_GUARD, next_regular
        normalized = unescape(following.value)
        return value, literal, normalized[0] if normalized else None, next_regular
    return value, literal, _END_GUARD, next_regular


def _corresponding_output_element(
    source_root: Tag | None, output_root: Tag | None, source_element: Tag | None
) -> Tag | None:
    if source_root is None or output_root is None or source_element is None:
        return None
    indices: list[int] = []
    current = source_element
    while current is not source_root:
        parent = current.parent
        if not isinstance(parent, Tag):
            return None
        siblings = [child for child in parent.children if isinstance(child, Tag)]
        indices.append(siblings.index(current))
        current = parent
    source_candidate = source_root
    candidate = output_root
    for index in reversed(indices):
        raw_children = [child for child in source_candidate.children if isinstance(child, Tag)]
        if index >= len(raw_children):
            return None
        if source_candidate.name == "head" and candidate.name == "head":
            head_pair = _normalized_head_children(source_candidate, candidate)
            if head_pair is None:
                return None
            source_children, output_children = head_pair
            if raw_children[index] not in source_children:
                return None
            candidate = output_children[source_children.index(raw_children[index])]
        else:
            children = [
                child for child in candidate.children
                if isinstance(child, Tag) and not child.has_attr("data-wt-attribution")
            ]
            if index >= len(children):
                return None
            candidate = children[index]
        source_candidate = raw_children[index]
    return candidate


def _normalized_head_children(source: Tag, output: Tag) -> tuple[list[Tag], list[Tag]] | None:
    original = [child for child in source.children if isinstance(child, Tag)]
    restored = [child for child in output.children if isinstance(child, Tag)]
    source_children = [child for child in original if not _is_removed_head_meta(child)]
    if (len(restored) >= 2 and restored[0].name == "meta"
        and restored[0].get("data-wt-csp") == "offline"
        and str(restored[0].get("http-equiv", "")).lower() == "content-security-policy"
        and restored[1].name == "meta" and str(restored[1].get("charset", "")).lower() == "utf-8"):
        output_children = restored[2:]
    elif any(child.get("data-wt-csp") == "offline" for child in restored):
        return None
    elif len(source_children) != len(original):
        return None
    else:
        output_children = restored
    if len(source_children) != len(output_children):
        return None
    for left, right in zip(source_children, output_children, strict=True):
        if left.name != right.name:
            return None
        left_names = set(left.attrs) - {"data-wt-segment"}
        right_names = set(right.attrs)
        if left_names != right_names:
            return None
        translated = left_names.intersection(TRANSLATABLE_ATTRIBUTES) if left.has_attr("data-wt-segment") else set()
        left_attrs = {name: value for name, value in left.attrs.items()
                      if name != "data-wt-segment" and name not in translated}
        right_attrs = {name: value for name, value in right.attrs.items()
                       if name not in translated}
        if left_attrs != right_attrs:
            return None
    return source_children, output_children


def _is_removed_head_meta(tag: Tag) -> bool:
    return tag.name == "meta" and (
        tag.has_attr("charset") or str(tag.get("http-equiv", "")).strip().lower() == "content-type"
    )


def _check_structure(
    source: BeautifulSoup, output: BeautifulSoup, findings: list[Finding]
) -> None:
    if source.body is None or output.body is None:
        findings.append(
            _required(
                "structural-signature",
                "Source and output must both contain a body element.",
                {"output_body": output.body is not None, "source_body": source.body is not None},
            )
        )
        return
    translated_attribute_paths = _marked_translatable_attribute_paths(source.body)
    source_signature = _tag_signature(
        source.body,
        ignore_attribution_children=False,
        translated_attribute_paths=translated_attribute_paths,
    )
    output_signature = _tag_signature(
        output.body,
        ignore_attribution_children=True,
        translated_attribute_paths=translated_attribute_paths,
    )
    if source_signature != output_signature:
        findings.append(
            _required(
                "structural-signature",
                "Captured content tag hierarchy or structural attributes changed.",
                {
                    "output_signature": repr(output_signature),
                    "source_signature": repr(source_signature),
                },
            )
        )


def _tag_signature(
    tag: Tag,
    *,
    ignore_attribution_children: bool = False,
    translated_attribute_paths: dict[tuple[int, ...], frozenset[str]] | None = None,
    path: tuple[int, ...] = (),
) -> tuple[object, ...]:
    child_tags = [
        child
        for child in tag.children
        if isinstance(child, Tag)
        and not (
            ignore_attribution_children and child.has_attr("data-wt-attribution")
        )
    ]
    children = [
        _tag_signature(
            child,
            ignore_attribution_children=False,
            translated_attribute_paths=translated_attribute_paths,
            path=path + (index,),
        )
        for index, child in enumerate(child_tags)
    ]
    normalized_names = (
        translated_attribute_paths.get(path, frozenset())
        if translated_attribute_paths is not None
        else frozenset()
    )
    attributes = tuple(
        sorted(
            (
                name.lower(),
                "<translated-attribute>"
                if name.lower() in normalized_names
                else tuple(value)
                if isinstance(value, list)
                else str(value),
            )
            for name, value in tag.attrs.items()
            if name.lower() != "data-wt-segment"
        )
    )
    return (tag.name.lower(), attributes, tuple(children))


def _marked_translatable_attribute_paths(
    root: Tag,
) -> dict[tuple[int, ...], frozenset[str]]:
    paths: dict[tuple[int, ...], frozenset[str]] = {}

    def visit(tag: Tag, path: tuple[int, ...]) -> None:
        if tag.has_attr("data-wt-segment"):
            translated = frozenset(
                name for name in TRANSLATABLE_ATTRIBUTES if tag.has_attr(name)
            )
            if translated:
                paths[path] = translated
        children = [child for child in tag.children if isinstance(child, Tag)]
        for index, child in enumerate(children):
            visit(child, path + (index,))

    visit(root, ())
    return paths


def _check_anchors(
    soup: BeautifulSoup, output_name: str, findings: list[Finding]
) -> None:
    identifiers = {
        str(tag.get("id")) for tag in soup.find_all(attrs={"id": True}) if tag.get("id")
    }
    identifiers.update(
        str(tag.get("name"))
        for tag in soup.find_all("a", attrs={"name": True})
        if tag.get("name")
    )
    unresolved: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        parsed = _safe_urlsplit(href)
        if parsed is None or parsed.scheme or parsed.netloc or not parsed.fragment:
            continue
        normalized_path = parsed.path.replace("\\", "/")
        if normalized_path not in {"", ".", "./", output_name, f"./{output_name}"}:
            continue
        fragment = unquote(parsed.fragment)
        if fragment not in identifiers:
            unresolved.add(fragment)
    if unresolved:
        findings.append(
            _required(
                "internal-anchor-unresolved",
                "One or more same-page fragment links have no target.",
                {"fragments": sorted(unresolved)},
            )
        )


def _check_external_dependencies(
    inputs: QAInputs,
    soup: BeautifulSoup,
    required: list[Finding],
    warnings: list[Finding],
) -> None:
    critical_urls: set[str] = set()
    optional_urls: set[str] = set()
    invalid_critical_urls: set[str] = set()
    invalid_optional_urls: set[str] = set()
    unsupported_critical_urls: set[str] = set()
    base_href: str | None = None
    base_tag = soup.find("base", href=True)
    if isinstance(base_tag, Tag):
        candidate = str(base_tag["href"])
        if _is_external_reference(candidate):
            base_href = candidate
    for tag in soup.find_all(True):
        name = tag.name.lower()
        if name == "link":
            classification = _link_dependency_class(tag)
            if classification == "critical" and _is_script_only_preload(tag) and _prior_blocking_script_csp(soup, tag):
                classification = None
        elif name == "script":
            classification = None
        elif name in _OPTIONAL_TAGS:
            classification = "optional"
        elif name == "a":
            classification = None
        else:
            classification = "critical"
        if classification is None:
            continue
        for attribute in _URL_ATTRIBUTES.get(name, ()):
            raw_value = tag.get(attribute)
            if raw_value is None:
                continue
            values = _srcset_urls(str(raw_value)) if attribute == "srcset" else [str(raw_value)]
            for value in values:
                if classification == "critical":
                    resolved, invalid, unsupported = _critical_dependency_reference(
                        value, base_href
                    )
                    if unsupported:
                        unsupported_critical_urls.add(value)
                        continue
                else:
                    resolved, invalid = _resolved_dependency_reference(value, base_href)
                if invalid:
                    if classification == "critical":
                        invalid_critical_urls.add(value)
                    else:
                        invalid_optional_urls.add(value)
                    continue
                if resolved is None:
                    continue
                if classification == "optional":
                    optional_urls.add(resolved)
                else:
                    critical_urls.add(resolved)
    for style in soup.find_all("style"):
        (
            imported,
            resources,
            invalid_imported,
            invalid_resources,
            unsupported_imported,
        ) = _css_external_urls(style.get_text(), base_href=base_href)
        critical_urls.update(imported)
        optional_urls.update(resources)
        invalid_critical_urls.update(invalid_imported)
        invalid_optional_urls.update(invalid_resources)
        unsupported_critical_urls.update(unsupported_imported)
    for tag in soup.find_all(style=True):
        _, resources, _, invalid_resources, _ = _css_external_urls(
            str(tag["style"]), declarations=True, base_href=base_href
        )
        optional_urls.update(resources)
        invalid_optional_urls.update(invalid_resources)
    asset_root = inputs.output_html.parent.resolve(strict=False)
    for candidate in inputs.critical_assets:
        resolved = _asset_path(asset_root, candidate)
        if resolved is None or resolved.suffix.lower() != ".css" or not resolved.is_file():
            continue
        try:
            css = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        (
            imported,
            resources,
            invalid_imported,
            invalid_resources,
            unsupported_imported,
        ) = _css_external_urls(css)
        critical_urls.update(imported)
        optional_urls.update(resources)
        invalid_critical_urls.update(invalid_imported)
        invalid_optional_urls.update(invalid_resources)
        unsupported_critical_urls.update(unsupported_imported)
    if critical_urls:
        required.append(
            _required(
                "external-critical-dependency",
                "Critical layout or content still requires an external network URL.",
                {"urls": sorted(critical_urls)},
            )
        )
    if invalid_critical_urls:
        required.append(
            _required(
                "invalid-critical-dependency-url",
                "A critical dependency contains a malformed URL.",
                {"urls": sorted(invalid_critical_urls)},
            )
        )
    if unsupported_critical_urls:
        required.append(
            _required(
                "unsupported-critical-dependency-scheme",
                "A critical dependency uses a scheme that cannot be loaded offline.",
                {"urls": sorted(unsupported_critical_urls)},
            )
        )
    if optional_urls:
        warnings.append(
            _warning(
                "external-optional-dependency",
                "Optional media still uses an external fallback URL.",
                {"urls": sorted(optional_urls)},
            )
        )
    if invalid_optional_urls:
        warnings.append(
            _warning(
                "invalid-optional-dependency-url",
                "An optional dependency contains a malformed URL.",
                {"urls": sorted(invalid_optional_urls)},
            )
        )


def _srcset_urls(value: str) -> list[str]:
    return [candidate.strip().split()[0] for candidate in value.split(",") if candidate.strip()]


def _css_external_urls(
    css: str, *, declarations: bool = False, base_href: str | None = None
) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    imported: set[str] = set()
    resources: set[str] = set()
    invalid_imported: set[str] = set()
    invalid_resources: set[str] = set()
    unsupported_imported: set[str] = set()
    nodes = (
        tinycss2.parse_declaration_list(css, skip_comments=True, skip_whitespace=True)
        if declarations
        else tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    )
    for node in nodes:
        if isinstance(node, AtRule) and node.lower_at_keyword == "import":
            for token in node.prelude:
                value = _css_url_value(token, allow_string=True)
                if value is None:
                    continue
                resolved, invalid, unsupported = _critical_dependency_reference(
                    value, base_href
                )
                if invalid:
                    invalid_imported.add(value)
                elif unsupported:
                    unsupported_imported.add(value)
                elif resolved is not None:
                    imported.add(resolved)
                break
            if node.content:
                urls, invalid = _external_component_urls(node.content, base_href)
                resources.update(urls)
                invalid_resources.update(invalid)
            continue
        for attribute in ("prelude", "value", "content"):
            tokens = getattr(node, attribute, None)
            if tokens:
                urls, invalid = _external_component_urls(tokens, base_href)
                resources.update(urls)
                invalid_resources.update(invalid)
    return (
        imported,
        resources,
        invalid_imported,
        invalid_resources,
        unsupported_imported,
    )


def _external_component_urls(
    tokens: Iterable[object], base_href: str | None
) -> tuple[set[str], set[str]]:
    urls: set[str] = set()
    invalid_urls: set[str] = set()
    for token in tokens:
        value = _css_url_value(token, allow_string=False)
        if value is not None:
            resolved, invalid = _resolved_dependency_reference(value, base_href)
            if invalid:
                invalid_urls.add(value)
            elif resolved is not None:
                urls.add(resolved)
        if isinstance(token, FunctionBlock):
            nested_urls, nested_invalid = _external_component_urls(token.arguments, base_href)
            urls.update(nested_urls)
            invalid_urls.update(nested_invalid)
        content = getattr(token, "content", None)
        if content:
            nested_urls, nested_invalid = _external_component_urls(content, base_href)
            urls.update(nested_urls)
            invalid_urls.update(nested_invalid)
    return urls, invalid_urls


def _css_url_value(token: object, *, allow_string: bool) -> str | None:
    if isinstance(token, URLToken):
        return token.value
    if isinstance(token, FunctionBlock) and token.lower_name == "url":
        value = tinycss2.serialize(token.arguments).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value
    if allow_string and isinstance(token, StringToken):
        return token.value
    return None


def _safe_urlsplit(value: str) -> Any | None:
    try:
        return urlsplit(value)
    except ValueError:
        return None


def _is_external_reference(value: str) -> bool:
    parsed = _safe_urlsplit(value)
    if parsed is None:
        return False
    return parsed.scheme.lower() in {"http", "https"} or (
        not parsed.scheme and bool(parsed.netloc)
    )


def _resolved_dependency_reference(
    value: str, base_href: str | None
) -> tuple[str | None, bool]:
    parsed = _safe_urlsplit(value)
    if parsed is None:
        return None, True
    if parsed.scheme.lower() in {"http", "https"} or (
        not parsed.scheme and parsed.netloc
    ):
        return value, False
    if parsed.scheme or parsed.netloc or value.startswith("#") or base_href is None:
        return None, False
    try:
        resolved = urljoin(base_href, value)
    except ValueError:
        return None, True
    return (resolved, False) if _is_external_reference(resolved) else (None, False)


def _critical_dependency_reference(
    value: str, base_href: str | None
) -> tuple[str | None, bool, bool]:
    parsed = _safe_urlsplit(value)
    if parsed is None:
        return None, True, False
    if parsed.scheme.lower() in {"http", "https"} or (
        not parsed.scheme and parsed.netloc
    ):
        return value, False, False
    if parsed.scheme or parsed.netloc or value.startswith("#"):
        return None, False, True
    if base_href is None:
        return None, False, False
    try:
        resolved = urljoin(base_href, value)
    except ValueError:
        return None, True, False
    return (
        (resolved, False, False)
        if _is_external_reference(resolved)
        else (None, False, False)
    )


def _link_dependency_class(tag: Tag) -> str | None:
    rel_value = tag.get("rel", [])
    rels = {
        str(value).lower()
        for value in (rel_value if isinstance(rel_value, list) else str(rel_value).split())
    }
    if "stylesheet" in rels or "modulepreload" in rels:
        return "critical"
    if "icon" in rels:
        return "optional"
    if "preload" in rels:
        return "optional" if str(tag.get("as", "")).lower() in {"font", "image", "audio", "video"} else "critical"
    return None


def _is_script_only_preload(tag: Tag) -> bool:
    rel_value = tag.get("rel", [])
    rels = {
        str(value).lower()
        for value in (rel_value if isinstance(rel_value, list) else str(rel_value).split())
    }
    if not rels or not rels <= {"modulepreload", "preload"}:
        return False
    destination = str(tag.get("as", "")).lower()
    return ("modulepreload" in rels and destination in {"", "script"}) or (
        "preload" in rels and destination == "script"
    )


def _prior_blocking_script_csp(soup: BeautifulSoup, preload: Tag) -> bool:
    if soup.head is None:
        return False
    all_tags = list(soup.find_all(True))
    preload_index = all_tags.index(preload)
    for meta in soup.head.find_all("meta", recursive=False):
        if all_tags.index(meta) >= preload_index:
            continue
        if str(meta.get("http-equiv", "")).strip().lower() != "content-security-policy":
            continue
        content = meta.get("content")
        if not isinstance(content, str):
            continue
        directives: dict[str, list[str]] = {}
        malformed = False
        for part in content.split(";"):
            words = re.split(r"[ \t\r\n\f]+", part.strip(" \t\r\n\f")) if part.strip(" \t\r\n\f") else []
            if not words:
                continue
            name = words[0].lower()
            if re.fullmatch(r"[a-z][a-z0-9-]*", name) is None:
                malformed = True
                break
            directives.setdefault(name, words[1:])
        if malformed:
            continue
        for name in ("script-src-elem", "script-src", "default-src"):
            if name in directives:
                if directives[name] == ["'none'"]:
                    return True
                break
    return False


def _check_assets(
    inputs: QAInputs, required: list[Finding], warnings: list[Finding]
) -> None:
    root = inputs.output_html.parent.resolve(strict=False)
    missing_critical: list[str] = []
    unsafe_critical: list[str] = []
    missing_optional: list[str] = []
    unsafe_optional: list[str] = []
    for candidate in inputs.critical_assets:
        resolved = _asset_path(root, candidate)
        if resolved is None:
            unsafe_critical.append(str(candidate))
        elif not resolved.is_file() or _is_link_or_reparse(resolved):
            missing_critical.append(str(candidate))
    for candidate in inputs.optional_assets:
        resolved = _asset_path(root, candidate)
        if resolved is None:
            unsafe_optional.append(str(candidate))
        elif not resolved.is_file() or _is_link_or_reparse(resolved):
            missing_optional.append(str(candidate))
    if missing_critical:
        required.append(
            _required(
                "critical-asset-missing",
                "One or more critical offline assets are unavailable.",
                {"paths": sorted(missing_critical)},
            )
        )
    if unsafe_critical:
        required.append(
            _required(
                "critical-asset-unsafe",
                "A critical asset path escapes the offline bundle.",
                {"paths": sorted(unsafe_critical)},
            )
        )
    if missing_optional:
        warnings.append(
            _warning(
                "optional-asset-missing",
                "One or more optional image or font assets are unavailable.",
                {"paths": sorted(missing_optional)},
            )
        )
    if unsafe_optional:
        warnings.append(
            _warning(
                "optional-asset-unsafe",
                "An optional asset path escapes the offline bundle.",
                {"paths": sorted(unsafe_optional)},
            )
        )


def _asset_path(root: Path, candidate: Path) -> Path | None:
    try:
        path = candidate if candidate.is_absolute() else root / candidate
        resolved = path.resolve(strict=False)
    except OSError:
        return None
    return resolved if resolved.is_relative_to(root) else None


def _check_master_review(inputs: QAInputs, findings: list[Finding]) -> None:
    unresolved = sorted(set(inputs.master_review.unresolved_required))
    if unresolved:
        findings.append(
            _required(
                "master-review-unresolved",
                "The master semantic review still has required fixes.",
                {"items": unresolved},
            )
        )


def _validated_screenshot_dir(inputs: QAInputs, findings: list[Finding]) -> Path | None:
    work_root = inputs.source_html.parent.resolve(strict=False)
    try:
        target = inputs.screenshot_dir.resolve(strict=False)
    except OSError as error:
        target = None
        reason = str(error)
    else:
        reason = "path escapes the run work directory or uses a link/reparse point"
    if (
        target is None
        or not target.is_relative_to(work_root)
        or _has_link_or_reparse_ancestor(target, work_root)
    ):
        findings.append(
            _required(
                "screenshot-directory-unsafe",
                "Browser screenshots must remain under the run work directory.",
                {"path": str(inputs.screenshot_dir), "reason": reason},
            )
        )
        return None
    return target


def _run_browser_checks(
    output_html: Path, screenshot_dir: Path
) -> tuple[list[Finding], list[Finding], list[Path], dict[str, dict[str, object]]]:
    required: list[Finding] = []
    warnings: list[Finding] = []
    screenshots: list[Path] = []
    metrics: dict[str, dict[str, object]] = {}
    stylesheet_failures: dict[str, list[dict[str, str]]] = {}
    blocked: dict[str, set[str]] = {}
    server: _LoopbackServer | None = None
    try:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        if not screenshot_dir.is_dir() or _is_link_or_reparse(screenshot_dir):
            raise OSError("screenshot destination is not a safe directory")
        server = _LoopbackServer(output_html.parent)
        server.start()
        allowed_origin = _origin(server.url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for label, width, height in _VIEWPORTS:
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        service_workers="block",
                    )

                    def websocket_guard(route: WebSocketRoute) -> None:
                        blocked.setdefault(route.url, set()).add("websocket")
                        # A routed socket does not connect unless connect_to_server()
                        # is called. Leaving it unconnected blocks network I/O without
                        # re-entering Chromium's close handshake from this callback.

                    context.route_web_socket("**/*", websocket_guard)

                    def guard(route: Route) -> None:
                        parsed = urlsplit(route.request.url)
                        if parsed.scheme in {"http", "https"} and _origin(route.request.url) != allowed_origin:
                            blocked.setdefault(route.request.url, set()).add(
                                route.request.resource_type
                            )
                            route.abort()
                        else:
                            route.continue_()

                    context.route("**/*", guard)
                    page = context.new_page()
                    try:
                        stylesheet_network_failures: list[dict[str, str]] = []

                        def observe_response(response: Any) -> None:
                            if (
                                response.request.resource_type == "stylesheet"
                                and not response.ok
                            ):
                                stylesheet_network_failures.append(
                                    {
                                        "href": response.url,
                                        "reason": f"http-{response.status}",
                                    }
                                )

                        def observe_request_failure(request: Any) -> None:
                            if request.resource_type == "stylesheet":
                                stylesheet_network_failures.append(
                                    {
                                        "href": request.url,
                                        "reason": str(request.failure or "request-failed"),
                                    }
                                )

                        page.on("response", observe_response)
                        page.on("requestfailed", observe_request_failure)
                        response = page.goto(server.url, wait_until="networkidle", timeout=15_000)
                        if response is None or not response.ok:
                            status = None if response is None else response.status
                            raise RuntimeError(f"loopback page returned status {status}")
                        observed = page.evaluate(_BROWSER_METRICS)
                        viewport_stylesheet_failures = [
                            {
                                "href": str(item["href"]),
                                "reason": str(item["reason"]),
                            }
                            for item in observed["stylesheetFailures"]
                        ]
                        viewport_stylesheet_failures.extend(
                            stylesheet_network_failures
                        )
                        if viewport_stylesheet_failures:
                            unique_stylesheet_failures = sorted(
                                {
                                    (item["href"], item["reason"])
                                    for item in viewport_stylesheet_failures
                                },
                                key=lambda item: item,
                            )
                            stylesheet_failures[label] = [
                                {"href": href, "reason": reason}
                                for href, reason in unique_stylesheet_failures
                            ]
                        normalized = {
                            "brokenImages": sorted(str(item) for item in observed["brokenImages"]),
                            "clippedText": int(observed["clippedText"]),
                            "horizontalOverflow": bool(observed["horizontalOverflow"]),
                        }
                        metrics[label] = normalized
                        screenshot = screenshot_dir / f"{label}.png"
                        if screenshot.exists() and _is_link_or_reparse(screenshot):
                            raise OSError(f"screenshot target is unsafe: {screenshot}")
                        _publish_screenshot(page, screenshot)
                        screenshots.append(screenshot)
                    finally:
                        context.close()
            finally:
                browser.close()
    except (OSError, PlaywrightError, RuntimeError, KeyError, TypeError, ValueError) as error:
        required.append(
            _required(
                "browser-qa-failed",
                "Chromium could not complete isolated visual QA.",
                {"reason": str(error)},
            )
        )
    finally:
        if server is not None:
            try:
                server.close()
            except (OSError, RuntimeError) as error:
                required.append(
                    _required(
                        "browser-cleanup-failed",
                        "The isolated QA server did not shut down cleanly.",
                        {"reason": str(error)},
                    )
                )

    overflow = sorted(label for label, value in metrics.items() if value["horizontalOverflow"])
    clipped = {label: value["clippedText"] for label, value in metrics.items() if value["clippedText"]}
    broken = {
        label: value["brokenImages"]
        for label, value in metrics.items()
        if value["brokenImages"]
    }
    if overflow:
        required.append(
            _required(
                "viewport-horizontal-overflow",
                "The page has unintended horizontal overflow.",
                {"viewports": overflow},
            )
        )
    if clipped:
        required.append(
            _required(
                "viewport-clipped-text",
                "Required text is clipped at one or more viewports.",
                {"viewports": clipped},
            )
        )
    if broken:
        warnings.append(
            _warning(
                "viewport-broken-images",
                "One or more optional images did not render offline.",
                {"viewports": broken},
            )
        )
    if stylesheet_failures:
        required.append(
            _required(
                "critical-stylesheet-unavailable",
                "One or more critical stylesheets did not load or expose accessible rules.",
                {"viewports": stylesheet_failures},
            )
        )

    blocked_critical = sorted(
        url for url, resource_types in blocked.items()
        if any(item not in {"image", "font", "media"} for item in resource_types)
    )
    blocked_optional = sorted(
        url for url, resource_types in blocked.items()
        if resource_types and all(item in {"image", "font", "media"} for item in resource_types)
    )
    if blocked_critical:
        required.append(
            _required(
                "external-critical-dependency",
                "Browser rendering attempted a critical external network request.",
                {"urls": blocked_critical},
            )
        )
    if blocked_optional:
        warnings.append(
            _warning(
                "external-optional-dependency",
                "Browser rendering attempted an optional external network request.",
                {"urls": blocked_optional},
            )
        )
    return required, warnings, screenshots, metrics


def _publish_screenshot(page: Any, destination: Path) -> None:
    """Render to a fresh inode, then replace the fixed screenshot name."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp.png", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        page.screenshot(path=str(temporary), full_page=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _origin(value: str) -> tuple[str, str, int | None] | None:
    parsed = _safe_urlsplit(value)
    if parsed is None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


class _QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, directory: str, **kwargs: object) -> None:
        self._safe_root = Path(directory).resolve(strict=True)
        self._blocked_path = False
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: object) -> None:
        return

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path))
        self._blocked_path = (
            not translated.resolve(strict=False).is_relative_to(self._safe_root)
            or _has_link_or_reparse_ancestor(translated, self._safe_root)
        )
        return str(translated)

    def send_head(self) -> Any:
        self.translate_path(self.path)
        if self._blocked_path:
            self.send_error(404, "Unsafe path")
            return None
        return super().send_head()


class _LoopbackServer:
    def __init__(self, root: Path) -> None:
        supplied = root.absolute()
        if _has_link_or_reparse_ancestor_to_root(supplied):
            raise OSError("browser server root uses a link or reparse ancestor")
        resolved = supplied.resolve(strict=True)
        if not resolved.is_dir() or _is_link_or_reparse(resolved):
            raise OSError("browser server root is missing or unsafe")
        handler = lambda *args, **kwargs: _QuietHandler(  # noqa: E731
            *args, directory=str(resolved), **kwargs
        )
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="web-translator-qa-http",
            daemon=True,
        )
        self.url = f"http://127.0.0.1:{self._server.server_port}/index.html"
        parsed = urlsplit(self.url)
        if parsed.hostname != "127.0.0.1":
            self._server.server_close()
            raise OSError("QA HTTP server did not bind to IPv4 loopback")

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        if self._thread.is_alive():
            self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("QA HTTP server thread is still alive after shutdown")


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & _REPARSE_POINT)


def _has_link_or_reparse_ancestor(path: Path, boundary: Path) -> bool:
    current = path
    while True:
        if current.exists() and _is_link_or_reparse(current):
            return True
        if current == boundary:
            return False
        parent = current.parent
        if parent == current or not current.is_relative_to(boundary):
            return True
        current = parent


def _has_link_or_reparse_ancestor_to_root(path: Path) -> bool:
    current = path
    while True:
        if (current.exists() or current.is_symlink()) and _is_link_or_reparse(current):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent
