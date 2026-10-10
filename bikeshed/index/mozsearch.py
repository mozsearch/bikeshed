# mozsearch indexing support!
#
#

from . import h, t

parentWildcard = {}

dfnTypeToMozsearchParentKindAndKind = {
    # ## dfn and similar
    "dfn": ("dfn", "spec", "specDfn", "fields"),
    # not sure if abstract-ops can actually have for's?
    "abstract-op": ("dfn", None, "specAbstractOp", None),

    # ## IDL types
    "event": ("idl", "interface", "event", "fields"),
    "interface": ("idl", None, "interface", None),
    "namespace": ("idl", None, "namespace", None),
    "extended-attribute": ("idl", "interface", "field", "fields"),
    "constructor": ("idl", "interface", "method", "methods"),
    "method": ("idl", "interface", "method", "methods"),
    "argument": ("idl", "method", "parameter", "args"), # parent is method or constructor
    "attribute": ("idl", "interface", "field", "fields"),
    "callback": ("idl", None, "callback", None),
    "dictionary": ("idl", None, "struct", None),
    "dict-member": ("idl", "struct", "field", "fields"), # parent is dictionary
    "enum": ("idl", None, "enum", None),
    # "fields" should ideally be "values" here if we add that support to our clang indexer, etc.
    "enum-value": ("idl", "enum", "enumConstant", "fields"), # parent is enum
    "exception": ("idl", None, "interface", None),
    "const": ("idl", "interface", "const", "fields"), # would this be "values" if we had it?
    # XXX maybe try and normalize with the clang indexer `TA_` synthetic symbol?
    "typedef": ("idl", None, "typedef", None),
    # It makes sense to model these as methods:
    "stringifier": ("idl", "interface", "method", "methods"),
    "serializer": ("idl", "interface", "method", "methods"),
    "iterator": ("idl", "interface", "method", "methods"),
    # These are basically templated classes or structs...
    "maplike": ("idl", "interface", "struct", "fields"),
    "setlike": ("idl", "interface", "struct", "fields"),
    "permission": ("idl", None, "permission", None),

    # ## Markup types
    "element": ("markup", None, "element", None),
    "element-attr": ("markup", "element", "elementAttr", "fields"),
    # XXX should this just be a field?
    "element-state": ("markup", "element", "elementState", "fields"),
    # This is interesting, the expected "for" looks like "button/type" where
    # we're naming values for the attribute.
    "attr-value": ("markup", "elementAttr", "elementAttrValue", "fields"), # "fields" should be "values"

    # ## CDDL "Concise Data Definition Language" rfom RFC8610
    # Per bikeshed docs, all CDDL definitions in a spec belong to a single namespace,
    # so there is no "for" expected, I think (beyond the spec forming part of the
    # namespace).
    #
    # Because gecko doesn't do anything with CDDL so we won't have actual IDL
    # bindings for CDDL, we put everything as its own new structured kind, but
    # this could be revisited.
    "cddl-module": ("cddl", None, "cddlModule", None),
    "cddl-type": ("cddl", None, "cddlType", None),
    "cddl-key": ("cddl", None, "cddlKey", None),
    "cddl-parameter": ("cddl", None, "cddlParameter", None),
    "cddl-value": ("cddl", None, "cddlValue", None),

    # ## Misc
    "grammar": ("grammar", None, "specGrammar", None),
    "scheme": ("url", None, "urlScheme", None),

    "http-header": ("http", None, "httpHeader", None),

    # ## CSS types
    "property": ("css", None, "cssProperty", None),
    "descriptor": ("css", "cssAtRule", "cssDescriptor", "fields"),
    # bikeshed says: "property, at-rule, etc." so we introduce parentWildcard
    "value": ("css", parentWildcard, "cssValue", "fields"),
    "type": ("css", None, "cssType", None),
    "at-rule": ("css", None, "cssAtRule", None),
    "function": ("css", None, "cssFunction", None),
    "selector": ("css", None, "cssSelector", None),

    # ## Weird undefined things
    # These exist in `dfnClassToType` as values but the bikeshed docs don't
    # explain what they are.
    "state": None,
    "mode": None,
    "context": None,
    "facet": None,
}

class MozsearchRecordCollector:
    def __init__(
        self,
        doc: t.Spec,
    ):
        self.doc = doc
        #
        self.refHints = doc.extraJC.scripts['ref-hints'].data[1]

        # Our symbol scheme is `SPEC_{spec shortname}_{dfn-type}_{hash identifier}`
        # Since the hash identifier is required to be unique within a spec,
        # including the dfn-type isn't necessary for uniqeuness but is currently
        # intended to help with debugging/inspection.  Note that some specs like
        # ServiceWorkers manually included a "dfn-" prefix into their definition
        # hash identifiers, but that isn't required or automatic.
        self.symPrefix = f'SPEC_{doc.md.shortname}_'

        self.records = []
        # the current stack of contents; this is mutated as we process
        self.contexts = []
        # structured records keyed by tuples of (dfn type, pretty)
        self.structured = {}

    def bsLineToMozsearchLoc(self, bsLineNumber):
        '''Convert a bikeshed bs-line-number to an equivalent mozsearch loc.
        Currently bs-line-number ends up being a 1-based line number and a
        1-based column, where mozsearch uses a 1-based line number and a 0-based
        column, so we need to decrement the column value.'''
        if bsLineNumber is None:
            return None
        pieces = bsLineNumber.split(':')
        pieces[1] = str(int(pieces[1], 10) - 1)
        return ':'.join(pieces)

    def makeSymbol(self, dfnType, id):
        return f'{self.symPrefix}_{dfnType}_{id}'

    def emitSource(self, loc, syntax, pretty_prefix, pretty, sym):
        '''Emit AnalysisSource record.'''

        rec = {
            'loc': loc,
            'source': 1,
            'syntax': syntax,
            'pretty': f'IDL {pretty_prefix} {pretty}',
            'sym': sym,
        }

        self.records.append(rec)


    def emitTarget(self, loc, kind, pretty, sym):
        '''Emit AnalysisTarget record.'''
        rec = {
            'loc': loc,
            'target': 1,
            'kind': kind,
            'pretty': pretty,
            'sym': sym,
        }
        self.records.append()

    def noteStructuredDfn(self, loc, parentFor, dfnType, pretty, sym, isExported):
        # We explicitly put None entries in for things we don't want to support,
        # so an "in" check is not sufficient, although we could distinguish for
        # warning purposes for unexpected dfnTypes.
        if dfnTypeToMozsearchParentKindAndKind.get(dfnType) is None:
            return
        (namespace, parentKind, dfnKind, slot) = dfnTypeToMozsearchParentKindAndKind[dfnType]
        if parentFor:
            parent = self.structured.get((namespace, parentFor))
            if parent is not None and slot is not None:
                if not slot in parent:
                    parent[slot] = []
                parent[slot].append({
                    'pretty': foo,
                    'sym': foo
                })



        record = {
            'loc': loc,
            'structured': 1,
            'pretty': pretty,
            'sym': sym,
            'kind': dfnKind,
            'implKind': 'spec',
        }
        self.structured[(namespace, )]

    def flushStructured(self):
        pass


    def emitStructured(self, loc, kind, pretty, sym,
                        slots=None, supers=None,
                        methods=None, fields=None):
        '''Emit AnalysisStructured record.'''

        if slots:
            record['bindingSlots'] = slots
        if supers:
            record['supers'] = supers
        if methods:
            record['methods'] = methods
        if fields:
            record['fields']= fields

        self.records.append(record)

    def collect(self):
        # All the content lives in the "main" element, bypassing the nav#toc, etc.
        # (Note this is using the etree Element API, not `h.find`)
        root = h.find('main', self.doc.body)
        self.traverse(root)
        self.flushStructured()

        return self.records


    def traverse(
        self,
        node: t.ElementT,
    ):
        kids = h.childNodes(node)
        pushContext = None
        firstTraverseIndex = 0

        loc = self.bsLineToMozsearchLoc(node.get('bs-line-number'))
        id = node.get('id')

        if node.tag == 'section':
            # We want to find the heading that names this section.  It seems like
            # for bikeshed the heading is always just the first child, which is
            # nice.
            header = kids.get(0)
            if header:
                firstTraverseIndex = 1
                pushContext = []
            pass
        elif node.tag == 'a':
            # links are uses, they have:
            # - href - If this is a reference local to this spec, this will just
            #   be the hash identifier of the definition tag.  But if this is an
            #   external spec (like HTML), this will be an absolute URL for the
            #   spec page.
            # - data-link-type - This is the dfn-type of what they are referencing,
            #   defined at https://speced.github.io/bikeshed/#dfn-types
            # - id - This is the hash identifier of this specific use, which will
            #   look like `ref-for-{identifier sans hash of the referenced thing}{uniqueifier}`.
            #   Where if there are a multiple references to a definition, the first reference
            #   will have an empty uniqueifier, but every subsequent uniqueifier will use the
            #   "circled digit" unicode characters (U+2460 - U+2469 for 1-9 and
            #   U+24EA for 0 I think).
            #
            # The main complexity here is that for cross-spec references we want
            # to know the shortname of the referenced spec.  `unsortedjunk.processAutolinks`
            # populates the `refsJSON` dict from URL to `RefWrapper`, with
            # collisions handled by adding a `data-refhint-key` attr to the
            # element.  `refsJSON` ends up as the `refsData` object in the
            # `script-ref-hints` script tag that gets emitted, but we can gain
            # access to it via `doc.extraJC.scripts["ref-hints"].data[1]`; we
            # cached that as `self.refHints` in the constructor.

            # Impl details to consult:
            # -  for some impl context.
            linkType = node.get('data-link-type')
            # XXX ReferenceManager.addLocalDdfns
            pretty = h.textContent(node)
            pretty = h.linkTextsFromElement(node)
            if linkType:
                sym = self.makeSymbol(linkType, id)
                self.emitSource(loc, 'link', linkType, pretty, sym)
                self.emitTarget(loc, 'use', pretty, sym)

        elif node.tag == 'dfn':
            # dfn nodes are the actual definitions, they have:
            # - data-dfn-type - https://speced.github.io/bikeshed/#dfn-types
            # - data-dfn-for - The namespace, effectively the parent sym.
            # - data-export / data-noexport - Is this exported or not.
            # - id - The hash identifier for this definition.  This will look like
            #   `#{dfn-type}-{}`
            linkType = node.get('data-dfn-type')
            namespace = node.get('data-dfn-for')
            isExported = 'data-export' in node
            pretty = h.textContent(node)

            sym = self.makeSymbol(linkType, id)
            self.emitSource(loc, 'def', linkType, pretty, sym)
            self.emitTarget(loc, 'def', pretty, sym)
            self.noteStructuredDfn(loc, namespace, linkType, pretty, sym, isExported)


        if pushContext:
            self.contexts.append(pushContext)
        for kid in kids[firstTraverseIndex:]:
            # We only use text nodes via
            if isinstance(kid, str):
                continue
            pass
        if pushContext:
            self.contexts.pop()

def generateMozsearchRecords(doc: t.Spec) -> str:
    collector = MozsearchRecordCollector(doc)
    return collector.collect()


