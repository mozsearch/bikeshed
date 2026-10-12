"""`bikeshed index`: a spec's definitions, references, headings, and
algorithms, with their positions in its source, as neutral JSON for tools that
cross-reference specs' sources (ex: searchfox, editors).

The index is taken from the document as it is once Bikeshed has linked it,
just before its final cleanup (which removes, ex: `bs-autolink-syntax`), so
that links have their resolved `href`s and the syntax they were written with.
Elements without a source position (`bs-line-number`) are generated (ex: the
index and table of contents sections, dfn panels), and left out, but for those
in data blocks (the `<pre>`s Bikeshed transforms, ex: IDL blocks, and
property and descriptor definitions' tables), whose positions are recovered
from the block's source text, which they are verbatim substrings of (and
whose `idl` is true).

Positions are 1-based lines and 1-based columns in characters, as
`bs-line-number`'s, in the spec's source, or, with a "file", in the file it
includes (`<pre class=include>`) by that path (which is relative to the
spec's source, as Bikeshed resolves it).  The JSON (see `INDEX_VERSION`):

    {
      "bikeshed-index": 3,
      "spec": {"shortname", "level", "title", "url"},
      "dfns": [{"line", "col", "file"?, "id", "oldids": [...], "type",
                "for": [...], "lt": [...], "export", "noexport", "text",
                "idl"}],
      "links": [{"line", "col", "file"?, "id", "href", "type", "for": [...],
                 "lt", "spec", "syntax", "text", "idl"}],
      "headings": [{"line", "col", "file"?, "id", "oldids": [...], "level",
                    "text"}],
      "algorithms": [{"line", "col", "file"?, "name", "for"}],
      "steps": [{"line", "col", "file"?, "path"}]
    }

where a definition's or heading's `oldids` are the ids it keeps from before
(its `oldids` attribute's, which Bikeshed gives empty spans in it), a link's
`id` is the one Bikeshed gave it, if any (ex: "ref-for-concept-tree①", as
autolinks get, deduplicated in document order, which dfn panels' "Referenced
in" link to), its `syntax` is the autolink syntax it was written with (ex:
`[=tree=]`, `{{Node}}`, `[[!DOM]]`), if any, and `steps` are the items of
ordered lists (ex: algorithms' steps, whether or not they're in an
`algorithm` container), whose `path` is their numbers in their nested lists,
from the outermost (ex: "2.3").

With `--html`, `bikeshed index` also writes the rendered spec (see
`renderSpec`), whose elements with source positions have them as `bs-pos`
attributes.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, NamedTuple

from .. import config, h, unsortedJunk

if TYPE_CHECKING:
    from .. import t

# (2: positions in included files have their "file".  3: definitions' and
# headings' `oldids`, and links' `id`s.)
INDEX_VERSION = 3

# An included file's elements' `bs-parse-context` (see `includes`), whose path
# is relative to the spec's source.
INCLUDED_CONTEXT = re.compile(r"^file '([^']*)'")


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


def renderSpec(doc: t.SpecT) -> str | None:
    """The rendered spec, once `indexSpec` has preprocessed it, with its
    elements' source positions (see `position`) as `bs-pos` attributes: the
    line ("12"), or the file and the line ("intro.md:12"), for tools that show
    the rendering with the source's history (ex: searchfox's blame of its
    blocks)."""
    for el in doc.document.iter():
        if not isinstance(el.tag, str):
            continue
        pos = position(el)
        if pos is not None:
            el.set("bs-pos", f"{pos.file}:{pos.line}" if pos.file is not None else str(pos.line))
    rendered = h.Serializer(doc.md.opaqueElements, doc.md.blockElements, keptAttrs=["bs-pos"]).serialize(
        doc.document,
    )
    return rendered


class Position(NamedTuple):
    file: str | None
    line: int
    col: int

    def fields(self) -> dict[str, Any]:
        """The position's JSON fields."""
        fields: dict[str, Any] = {"line": self.line, "col": self.col}
        if self.file is not None:
            fields["file"] = self.file
        return fields


def position(el: t.ElementT) -> Position | None:
    """The element's position in the source, or in the file it's included
    from (ex: "27:22 of file 'intro.md' (included by a block on 117:1)"), but
    not in boilerplate (ex: "1:1 of header.include")."""
    value = el.get("bs-line-number")
    match = re.match(r"(\d+)(?::(\d+))?", value or "")
    if not match:
        return None
    context = el.get("bs-parse-context")
    included = INCLUDED_CONTEXT.match(context or "")
    if context and not included:
        return None
    return Position(included[1] if included else None, int(match[1]), int(match[2] or 1))


def oldIds(el: t.ElementT) -> list[str]:
    """The ids the element keeps from before: those of the spans Bikeshed gave
    it for its `oldids` attribute (see `h.addOldIDs`)."""
    return [
        child.get("id") or ""
        for child in el
        if isinstance(child.tag, str) and "bs-old-id" in (child.get("class") or "").split() and child.get("id")
    ]


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
    doesn't have, from the blocks' source text (of a file: the spec's source,
    or a file it includes), in which each name is found after the previous
    one."""

    def __init__(self, source: str, file: str | None = None) -> None:
        self.source = source
        self.file = file
        self.lineStarts = [0] + [m.end() for m in re.finditer("\n", source)]
        self.blocks: dict[t.ElementT, list[int]] = {}

    def offset(self, line: int, col: int) -> int | None:
        if not 1 <= line <= len(self.lineStarts):
            return None
        return self.lineStarts[line - 1] + col - 1

    def toPosition(self, offset: int) -> Position:
        lo, hi = 0, len(self.lineStarts)
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if self.lineStarts[mid] <= offset:
                lo = mid
            else:
                hi = mid
        return Position(self.file, lo + 1, offset - self.lineStarts[lo] + 1)

    def find(self, block: t.ElementT, el: t.ElementT) -> Position | None:
        """The position of `el`'s text in the IDL `block`."""
        if block not in self.blocks:
            start = position(block)
            at = self.offset(start.line, start.col) if start else None
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
    # The IDL positions in the source and in each included file.
    idls: dict[str | None, IdlPositions] = {}

    def idlPositions(file: str | None) -> IdlPositions:
        if file not in idls:
            try:
                inputSource = doc.inputSource if file is None else doc.inputSource.relative(file)
                source = inputSource.read().content if inputSource is not None else ""
            except Exception:
                source = ""
            idls[file] = IdlPositions(source, file)
        return idls[file]

    parents = {child: parent for parent in doc.document.iter() for child in parent}

    def dataBlock(el: t.ElementT) -> t.ElementT | None:
        """The block `el` is in, if its nearest ancestor with a position is a
        data block (whose source starts with `<pre`, ex: an IDL block, or the
        table Bikeshed made of a `<pre class=propdef>`, with its attributes)."""
        e = parents.get(el)
        while e is not None:
            pos = position(e) if isinstance(e.tag, str) else None
            if pos is not None:
                positions = idlPositions(pos.file)
                at = positions.offset(pos.line, pos.col)
                if at is not None and positions.source[at : at + 4].lower() == "<pre":
                    return e
                return None
            e = parents.get(e)
        return None

    def located(el: t.ElementT) -> tuple[Position, bool] | None:
        """The element's position, and whether it was recovered from a data
        block."""
        pos = position(el)
        if pos:
            return pos, False
        block = dataBlock(el)
        blockPos = position(block) if block is not None else None
        if block is not None and blockPos is not None:
            pos = idlPositions(blockPos.file).find(block, el)
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
                pos, inIdl = where
                dfns.append(
                    {
                        **pos.fields(),
                        "id": el.get("id"),
                        "oldids": oldIds(el),
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
                pos, inIdl = where
                links.append(
                    {
                        **pos.fields(),
                        "id": el.get("id"),
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
                    {
                        **pos.fields(),
                        "id": el.get("id"),
                        "oldids": oldIds(el),
                        "level": int(tag[1]),
                        "text": headingText(el),
                    },
                )
        if el.get("data-algorithm") is not None:
            pos = position(el)
            if pos:
                algorithms.append(
                    {
                        **pos.fields(),
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
                        steps.append({**pos.fields(), "path": ".".join(itemPath)})
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
