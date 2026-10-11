"""`bikeshed index`: a spec's definitions, references, headings, and
algorithms, with their positions in its source, as neutral JSON for tools that
cross-reference specs' sources (ex: searchfox, editors).

The index is taken from the document as it is once Bikeshed has linked it,
just before its final cleanup (which removes, ex: `bs-autolink-syntax`), so
that links have their resolved `href`s and the syntax they were written with.
Elements without a source position (`bs-line-number`) are generated (ex: the
index and table of contents sections, dfn panels), and left out, but for those
in IDL blocks, whose positions are recovered from the block's source text,
which they are verbatim substrings of.

Positions are 1-based lines and 1-based columns in characters, as
`bs-line-number`'s.  The JSON (see `INDEX_VERSION`):

    {
      "bikeshed-index": 1,
      "spec": {"shortname", "level", "title", "url"},
      "dfns": [{"line", "col", "id", "type", "for": [...], "lt": [...],
                "export", "noexport", "text", "idl"}],
      "links": [{"line", "col", "href", "type", "for": [...], "lt", "spec",
                 "syntax", "text", "idl"}],
      "headings": [{"line", "col", "id", "level", "text"}],
      "algorithms": [{"line", "col", "name", "for"}],
      "steps": [{"line", "col", "path"}]
    }

where a link's `syntax` is the autolink syntax it was written with (ex:
`[=tree=]`, `{{Node}}`, `[[!DOM]]`), if any, and `steps` are the items of
ordered lists (ex: algorithms' steps, whether or not they're in an
`algorithm` container), whose `path` is their numbers in their nested lists,
from the outermost (ex: "2.3").
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .. import config, h, unsortedJunk

if TYPE_CHECKING:
    from .. import t

INDEX_VERSION = 1


def indexSpec(doc: t.SpecT) -> dict[str, Any]:
    """Preprocess `doc`, returning its index, from just before its final
    cleanup."""
    captured: dict[str, Any] = {}
    cleanup = unsortedJunk.cleanupHTML

    def captureThenCleanup(d: t.SpecT) -> None:
        captured["index"] = extractIndex(d)
        cleanup(d)

    unsortedJunk.cleanupHTML = captureThenCleanup
    try:
        doc.preprocess()
    finally:
        unsortedJunk.cleanupHTML = cleanup
    return captured["index"]


def position(el: t.ElementT) -> tuple[int, int] | None:
    value = el.get("bs-line-number")
    if not value:
        return None
    line, _, col = value.partition(":")
    try:
        return int(line), int(col or 1)
    except ValueError:
        return None


def words(text: str) -> str:
    return " ".join(text.split())


def splitFors(value: str | None) -> list[str]:
    return config.splitForValues(value) or [] if value else []


def splitLts(value: str | None) -> list[str]:
    return [lt for lt in (value or "").split("|") if lt]


def headingText(el: t.ElementT) -> str:
    # (Bikeshed wraps a heading's own text, after its section number.)
    content = h.find(".content", el)
    return words(h.textContent(content if content is not None else el))


class IdlPositions:
    """The positions of the names in IDL blocks, which widlparser's markup
    doesn't have, from the blocks' source text, in which each name is found
    after the previous one."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.lineStarts = [0] + [m.end() for m in re.finditer("\n", source)]
        self.blocks: dict[t.ElementT, list[int]] = {}

    def offset(self, line: int, col: int) -> int | None:
        if not 1 <= line <= len(self.lineStarts):
            return None
        return self.lineStarts[line - 1] + col - 1

    def toPosition(self, offset: int) -> tuple[int, int]:
        lo, hi = 0, len(self.lineStarts)
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if self.lineStarts[mid] <= offset:
                lo = mid
            else:
                hi = mid
        return lo + 1, offset - self.lineStarts[lo] + 1

    def find(self, block: t.ElementT, el: t.ElementT) -> tuple[int, int] | None:
        """The position of `el`'s text in the IDL `block`."""
        if block not in self.blocks:
            start = position(block)
            at = self.offset(*start) if start else None
            if at is None:
                self.blocks[block] = []
                return None
            contentStart = self.source.find(">", at) + 1
            contentEnd = self.source.find("</pre>", contentStart)
            self.blocks[block] = [contentStart, contentEnd if contentEnd >= 0 else len(self.source)]
        bounds = self.blocks[block]
        if not bounds:
            return None
        text = h.textContent(el).strip()
        if not text:
            return None
        found = self.source.find(text, bounds[0], bounds[1])
        if found < 0:
            return None
        bounds[0] = found + len(text)
        return self.toPosition(found)


def extractIndex(doc: t.SpecT) -> dict[str, Any]:
    try:
        source = doc.inputSource.read().content
    except Exception:
        source = ""
    idl = IdlPositions(source)
    parents = {child: parent for parent in doc.document.iter() for child in parent}

    def idlBlock(el: t.ElementT) -> t.ElementT | None:
        e = parents.get(el)
        while e is not None:
            if isinstance(e.tag, str) and e.tag == "pre" and "idl" in (e.get("class") or "").split():
                return e
            e = parents.get(e)
        return None

    def located(el: t.ElementT) -> tuple[tuple[int, int], bool] | None:
        """The element's position, and whether it was recovered from an IDL
        block."""
        pos = position(el)
        if pos:
            return pos, False
        block = idlBlock(el)
        if block is not None:
            pos = idl.find(block, el)
            if pos:
                return pos, True
        return None

    dfns: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    algorithms: list[dict[str, Any]] = []
    for el in doc.document.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag
        if el.get("data-dfn-type") is not None and el.get("id"):
            where = located(el)
            if where:
                (line, col), inIdl = where
                dfns.append(
                    {
                        "line": line,
                        "col": col,
                        "id": el.get("id"),
                        "type": el.get("data-dfn-type"),
                        "for": splitFors(el.get("data-dfn-for")),
                        "lt": splitLts(el.get("data-lt")),
                        "export": el.get("data-export") is not None,
                        "noexport": el.get("data-noexport") is not None,
                        "text": words(h.textContent(el)),
                        "idl": inIdl,
                    },
                )
        if tag == "a" and el.get("href") and "self-link" not in (el.get("class") or "").split():
            where = located(el)
            if where:
                (line, col), inIdl = where
                links.append(
                    {
                        "line": line,
                        "col": col,
                        "href": el.get("href"),
                        "type": el.get("data-link-type"),
                        "for": splitFors(el.get("data-link-for")),
                        "lt": el.get("data-lt"),
                        "spec": el.get("data-link-spec"),
                        "syntax": el.get("bs-autolink-syntax"),
                        "text": words(h.textContent(el)),
                        "idl": inIdl,
                    },
                )
        if tag in ("h2", "h3", "h4", "h5", "h6") and el.get("id"):
            pos = position(el)
            if pos:
                headings.append(
                    {"line": pos[0], "col": pos[1], "id": el.get("id"), "level": int(tag[1]), "text": headingText(el)},
                )
        if el.get("data-algorithm") is not None:
            pos = position(el)
            if pos:
                algorithms.append(
                    {
                        "line": pos[0],
                        "col": pos[1],
                        "name": el.get("data-algorithm") or None,
                        "for": el.get("data-algorithm-for") or None,
                    },
                )
    return {
        "bikeshed-index": INDEX_VERSION,
        "spec": {
            "shortname": doc.md.shortname,
            "level": doc.md.level,
            "title": doc.md.title,
            "url": doc.md.canonicalURL or doc.md.ED or doc.md.TR,
        },
        "dfns": dfns,
        "links": links,
        "headings": headings,
        "algorithms": algorithms,
        "steps": listSteps(doc.document),
    }


def listSteps(root: t.ElementT) -> list[dict[str, Any]]:
    """The items of ordered lists (which have positions), by their numbers in
    their nested lists."""
    steps: list[dict[str, Any]] = []

    def walk(el: t.ElementT, path: list[str]) -> None:
        for child in el:
            if not isinstance(child.tag, str):
                continue
            if child.tag == "ol":
                number = intOr(child.get("start"), 1) - 1
                for item in child:
                    if not isinstance(item.tag, str) or item.tag != "li":
                        continue
                    number = intOr(item.get("value"), number + 1)
                    itemPath = [*path, str(number)]
                    pos = position(item)
                    if pos:
                        steps.append({"line": pos[0], "col": pos[1], "path": ".".join(itemPath)})
                    walk(item, itemPath)
            else:
                walk(child, path)

    walk(root, [])
    return steps


def intOr(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default
