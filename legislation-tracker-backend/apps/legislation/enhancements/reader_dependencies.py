"""Exact, scoped source dependencies for bounded full-document review.

Ownership and interpretation are separate. A small legal unit stays complete in
each request that owns part of it; a large unit contributes its introductions,
continuations, referenced provisions and applicable definitions instead of all
of its unrelated siblings. XML ancestry takes precedence over text heuristics.
"""

import re
from collections import defaultdict
from dataclasses import dataclass

from apps.legislation.extraction.federal_structure import parse_federal_structure
from apps.legislation.extraction.types import ExpectedExtractionRejection

CONTEXT_PLANNER_VERSION = 9
UNIT_BYTES = 24_000
CONTAINERS = {
    "legis-body",
    "engrossed-amendment-body",
    "amendment-body",
    "division",
    "title",
    "subtitle",
    "chapter",
    "subchapter",
    "part",
    "subpart",
    "tgroup",
    "tbody",
}
NAVIGATION = {"toc", "table-of-contents"}
LEVELS = (
    "section",
    "subsection",
    "paragraph",
    "subparagraph",
    "clause",
    "subclause",
    "item",
    "subitem",
)
REFERENCE = re.compile(
    r"\b(?P<kind>section|subsection|paragraph|subparagraph|clause|subclause|item|subitem)(?P<plural>s)?\s+"
    r"(?P<label>\d+(?:\.\d+)*[A-Za-z]?(?:-[A-Za-z0-9]+)*|(?:\([A-Za-z0-9]+\))+)"
    r"(?P<suffix>(?:\([A-Za-z0-9]+\))*)",
    re.I,
)
REFERENCE_MEMBER = re.compile(
    r"(?:\d+(?:\.\d+)*[A-Za-z]?(?:-[A-Za-z0-9]+)*(?:\([A-Za-z0-9]+\))*|(?:\([A-Za-z0-9]+\))+)(?![A-Za-z0-9])"
)
REFERENCE_SEPARATOR = re.compile(
    r"\s*(?:(?P<range>through\b|to\b|[-–—])\s*|(?:,\s*(?:(?:and|or)\s+)?|(?:and|or)\s+))",
    re.I,
)
ROMAN_LABEL = re.compile(
    r"(?=[ivxlcdm]+$)m{0,3}(?:cm|cd|d?c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})",
    re.I,
)
SCOPE_NAMES = "|".join(
    (
        "Act",
        "division",
        "title",
        "subtitle",
        "chapter",
        "subchapter",
        "part",
        "subpart",
        *LEVELS,
    )
)
SCOPE = re.compile(rf"\bthis\s+({SCOPE_NAMES})\b", re.I)
LOCAL_SCOPE = re.compile(rf"\s+of\s+this\s+({SCOPE_NAMES})\b", re.I)
QUALIFICATION = re.compile(
    r"\b(?:except|unless|only if|may not|shall not|must not|notwithstanding|"
    r"no (?:funds|amounts)|nothing in|prohibit\w*|limitation\w*|"
    r"(?:shall|may) (?:not )?apply|applies|applicable|remain available|"
    r"effective date|takes? effect|terminat\w*|sunset)\b",
    re.I,
)
DEFINITION = re.compile(
    r"\b(?:the\s+)?term\s+[\"“‘`']*(?P<term>[^\n;:.]{1,120}?)"
    r"[\"”’`']*\s+(?:means|includes|has the meaning|shall mean)\b",
    re.I,
)
QUOTED_DEFINITION = re.compile(
    r"[\"“‘](?P<term>[^\"”’\n]{1,100})[\"”’]\s+(?:means|includes)\b", re.I
)


@dataclass(frozen=True)
class Node:
    start: int
    end: int
    tag: str
    label: str = ""
    heading: str = ""
    parent: int | None = None
    identity: str = ""
    quoted_depth: int = 0
    references: tuple[str, ...] = ()
    table_label_level: int | None = None
    external_references: tuple = ()
    inherited_cell_ranges: tuple = ()


def _label(value):
    return re.sub(r"^(?:Sec\.|Section)\s*", "", value, flags=re.I).strip().rstrip(".")


def _normalize(value):
    return " ".join(value.casefold().split()).strip("‘’“”\"'` .;:")


def _reference_parts(match):
    # An abbreviated section label can hold several levels, e.g. (2)(B).
    # Preserve the numeric section identifier only when the path includes one.
    parts = re.findall(r"\([A-Za-z0-9]+\)", match["label"] + match["suffix"])
    if match["kind"].casefold() == "section" and not match["label"].startswith("("):
        parts.insert(0, match["label"])
    return parts


def _level_accepts(level, label):
    token = label.strip("()")
    if level == "paragraph":
        return token.isdigit()
    if level in {"clause", "subclause"}:
        return bool(ROMAN_LABEL.fullmatch(token)) and (
            token.isupper() == (level == "subclause")
        )
    if level in {"item", "subitem"}:
        return bool(re.fullmatch(r"([a-zA-Z])\1+", token)) and (
            token.isupper() == (level == "subitem")
        )
    return bool(re.fullmatch(r"([a-zA-Z])\1*", token)) and (
        token.isupper() == (level == "subparagraph")
    )


def _continued_reference(kind, value, previous, exists):
    member = REFERENCE.fullmatch(kind + " " + value)
    parts, prior = _reference_parts(member), _reference_parts(previous)
    levels = LEVELS[LEVELS.index(kind.casefold()) :]
    candidates = []
    for depth in reversed(
        range(int(kind.casefold() == "section"), min(len(prior) + 1, len(levels)))
    ):
        suffix = levels[depth : depth + len(parts)]
        if len(suffix) == len(parts) and all(
            _level_accepts(level, part)
            for level, part in zip(suffix, parts, strict=True)
        ):
            candidates.append(
                REFERENCE.fullmatch(kind + " " + "".join(prior[:depth] + parts))
            )
    if len(candidates) > 1:
        # A single i/I can be either an alphabetic label or a Roman numeral.
        # Consult the scoped source tree before accepting either interpretation.
        found = [candidate for candidate in candidates if exists(candidate)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return None
    return candidates[0] if candidates else member


def _reference_group(match, raw, exists):
    """Parse a complete list/range before applying its shared qualification.

    Each member retains its relation to the preceding member, so a successful
    first lookup cannot hide an incomplete range. Unsupported range syntax is
    kept as an unresolved obligation instead of being accepted as a singleton.
    """
    kind, cursor = match["kind"], match.end()
    members, incomplete, compact_literals = [(False, match)], False, []
    # Parenthesized/delimited dashes are handled below. A compact numeric
    # plural ('sections 2-4') is a range as well, not just section '2-4'.
    compact = re.fullmatch(r"(\d+)-(\d+)", match["label"])
    if match["plural"] and compact and not match["suffix"]:
        compact_literals.append(match)
        members = [
            (False, REFERENCE.fullmatch(kind + " " + compact[1])),
            (True, REFERENCE.fullmatch(kind + " " + compact[2])),
        ]
    while True:
        if inclusive := re.match(
            r"(?:,\s*|\s+)(?:inclusive\b|\(inclusive\)),?", raw[cursor:], re.I
        ):
            cursor += inclusive.end()
        separator = REFERENCE_SEPARATOR.match(raw, cursor)
        if separator is None:
            break
        start = separator.end()
        repeated = re.match(r"([A-Za-z]+)\s+", raw[start:])
        explicit = repeated and repeated[1].casefold().rstrip("s") == kind.casefold()
        if explicit:
            start += repeated.end()
        value = REFERENCE_MEMBER.match(raw, start)
        if value is None:
            if separator["range"] and (
                match["plural"]
                or separator["range"].casefold() == "through"
                or raw[start : start + 1] == "("
            ):
                incomplete = True
                cursor = separator.end()
            break
        member = REFERENCE.fullmatch(kind + " " + value[0]) if explicit else value[0]
        compact = re.fullmatch(r"(\d+)-(\d+)", value[0])
        if compact:
            compact_literals.append(REFERENCE.fullmatch(kind + " " + value[0]))
            members.extend(
                [
                    (
                        bool(separator["range"]),
                        REFERENCE.fullmatch(kind + " " + compact[1]),
                    ),
                    (True, REFERENCE.fullmatch(kind + " " + compact[2])),
                ]
            )
        else:
            members.append((bool(separator["range"]), member))
        cursor = value.end()
    if re.match(r"\s+(?:et\s+seq\b|thru\b)", raw[cursor:], re.I):
        incomplete = True
    expanded = []
    previous = None
    for is_range, member in members:
        if isinstance(member, str):
            if member.startswith("("):
                member = (
                    _continued_reference(
                        kind, member, previous, lambda m: exists(m, cursor)
                    )
                    if previous is not None
                    else None
                )
            else:
                member = REFERENCE.fullmatch(kind + " " + member)
        previous = member
        if member is None:
            incomplete = True
        else:
            expanded.append((is_range, member))
    return expanded, cursor, incomplete, compact_literals


def _label_ordinal(node):
    """Comparable ordinal families; unknown enumerations stay unresolved."""
    label = node.label.strip("()")
    if node.tag in {"clause", "subclause"} and ROMAN_LABEL.fullmatch(label):
        values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
        total = largest = 0
        for letter in reversed(label.casefold()):
            value = values[letter]
            total += -value if value < largest else value
            largest = max(largest, value)
        return ("roman",), total
    if number := re.fullmatch(r"(.*?)(\d+)", label):
        return ("number", number[1]), int(number[2])
    if re.fullmatch(r"([a-z])\1*", label, re.I):
        return ("letter", label.isupper()), (len(label) - 1) * 26 + ord(
            label[0].lower()
        ) - ord("a")
    if suffix := re.fullmatch(r"(\d+(?:[.-]\d+)*)([A-Za-z])", label):
        return ("suffix", suffix[1], suffix[2].isupper()), ord(suffix[2].lower()) - ord(
            "a"
        )
    return None


def _text_nodes(text, sections):
    """Recognized text hierarchy, scoped to authoritative section boundaries.

    Never infer title/section ancestry from flattened XML when XML nodes exist.
    A section-only caller retains exact local offsets without promoting quoted
    section headings into siblings of the enclosing bill section.
    """
    result = []
    if sections:
        for identity, start, end, label, heading in sections:
            root = len(result)
            result.append(
                Node(start, end, "section", _label(label), heading, identity=identity)
            )
            try:
                parsed = parse_federal_structure("SEC. 0. SOURCE\n" + text[start:end])
            except ExpectedExtractionRejection:
                parsed = ()
            prefix = len("SEC. 0. SOURCE\n")
            parents = {}
            for item in parsed:
                if item.span.start_char < prefix or item.level not in LEVELS[1:]:
                    continue
                a, b = (
                    start + item.span.start_char - prefix,
                    min(end, start + item.span.end_char - prefix),
                )
                parent_item = parsed.parents.get(id(item))
                parent = parents.get(id(parent_item), root)
                parents[id(item)] = len(result)
                result.append(
                    Node(a, b, item.level, item.label, item.heading or "", parent)
                )
    else:
        try:
            parsed = parse_federal_structure(text)
        except ExpectedExtractionRejection:
            parsed = ()
        indexes = {}
        for item in parsed:
            parent = indexes.get(id(parsed.parents.get(id(item))))
            indexes[id(item)] = len(result)
            result.append(
                Node(
                    item.span.start_char,
                    item.span.end_char,
                    item.level,
                    _label(item.label),
                    item.heading or "",
                    parent,
                )
            )
    if not result:
        result = [Node(0, len(text), "section", identity="document")]
    return result


class DependencyIndex:
    table_scopes = {"tgroup", "table"}
    definition_levels = inherited_definition_levels = SCOPE_NAMES
    scope_candidate = SCOPE
    use_external_markup = True
    resolve_missing_scope = True

    def __init__(self, text, sections):
        self.text = text
        xml = getattr(sections, "provisions", ())
        self.nodes = (
            [
                Node(
                    p.start,
                    p.end,
                    p.tag,
                    _label(p.label),
                    p.heading,
                    p.parent,
                    getattr(p, "identity", ""),
                    p.quoted_depth,
                    getattr(p, "references", ()),
                    getattr(p, "table_label_level", None),
                    getattr(p, "external_references", ()),
                    getattr(p, "inherited_cell_ranges", ()),
                )
                for p in xml
            ]
            if xml
            else _text_nodes(text, sections)
        )
        self.children = defaultdict(list)
        self._ancestors, self._quotes = [], []
        for i, node in enumerate(self.nodes):
            self.children[node.parent].append(i)
            ancestors = (
                (node.parent, *self._ancestors[node.parent])
                if node.parent is not None
                else ()
            )
            self._ancestors.append(ancestors)
            self._quotes.append(
                i
                if node.tag in {"quoted-block", "quoted-text"}
                else self._quotes[node.parent] if node.parent is not None else None
            )
        self._required = {}
        self.by_identity = {
            n.identity: i for i, n in enumerate(self.nodes) if n.identity
        }
        self.direct = [self._direct(i) for i in range(len(self.nodes))]
        self.direct_text = [
            "\n".join(text[a:b] for a, b in spans) for spans in self.direct
        ]
        self.sections = defaultdict(list)
        for i, node in enumerate(self.nodes):
            if node.tag == "section":
                self.sections[self.quote_scope(i), node.label.casefold()].append(i)
        self.definitions = defaultdict(list)
        self.qualifications = defaultdict(list)
        self.incoming = defaultdict(set)
        self.links = defaultdict(set)
        self.introduction_links = defaultdict(set)
        self.table_authorizations = defaultdict(set)
        self.tables_under = defaultdict(list)
        for i, node in enumerate(self.nodes):
            if node.tag == "table":
                for ancestor in self.ancestors(i):
                    self.tables_under[ancestor].append(i)
        self.unresolved = defaultdict(set)
        self._index_dependencies()
        self.incoming_descendants = defaultdict(list)
        for target in self.incoming:
            for ancestor in self.ancestors(target):
                self.incoming_descendants[ancestor].append(target)

    def _direct(self, index):
        node = self.nodes[index]
        cursor, spans = node.start, []
        # Ingestion renders direct continuations before quoted blocks, even
        # when their inline quoted-text children appear later in XML order.
        # Subtract the union of immutable child intervals in text order; an
        # already emitted parent prefix must never also belong to a child.
        for start, end in sorted(
            (self.nodes[child].start, self.nodes[child].end)
            for child in self.children[index]
        ):
            if cursor < start:
                spans.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < node.end:
            spans.append((cursor, node.end))
        return spans

    def ancestors(self, index):
        return self._ancestors[index]

    def quote_scope(self, index):
        return self._quotes[index]

    def scope(self, index, level):
        quote = self.quote_scope(index)
        if level.casefold() == "act":
            return quote
        for i in (index, *self.ancestors(index)):
            if self.nodes[i].tag == level.casefold() and self.quote_scope(i) == quote:
                return i
        return quote

    def _definition_scope(self, index, raw):
        declaration = re.search(
            rf"\b(?:in|for purposes of|as used in)\s+this\s+({self.definition_levels})\b",
            raw,
            re.I,
        )
        if declaration:
            return self.scope(index, declaration[1])
        for ancestor in self.ancestors(index):
            introduction = self.direct_text[ancestor]
            declaration = re.search(
                rf"\b(?:in|for purposes of|as used in)\s+this\s+({self.inherited_definition_levels})\b",
                introduction,
                re.I,
            )
            if declaration:
                return self.scope(index, declaration[1])
            if self.nodes[ancestor].tag == "section":
                break
        # A definition subsection inherits its legal section. A standalone
        # definitions section inherits the nearest title/division (or bill).
        section = self.scope(index, "section")
        if (
            section is not None
            and "definition" not in self.nodes[section].heading.casefold()
        ):
            return section
        for i in self.ancestors(index):
            if self.nodes[i].tag in {"subtitle", "title", "division"}:
                return i
        return self.quote_scope(index)

    def _descendant(self, index, scope):
        return (
            (scope is None and self.quote_scope(index) is None)
            or index == scope
            or scope in self.ancestors(index)
        )

    def _path_target(self, index, labels, *, first_kind=None):
        current = [index]
        for depth, label in enumerate(labels):
            following = []
            for parent in current:
                for child in self.children[parent]:
                    if (
                        self.nodes[child].label == label
                        and self.quote_scope(child) == self.quote_scope(parent)
                        and (
                            depth
                            or first_kind is None
                            or self.nodes[child].tag == first_kind
                        )
                    ):
                        following.append(child)
            current = following
        return current

    def _external_amendment(self, index):
        if self.quote_scope(index) is not None:
            return False
        operation = external = False
        for i in (index, *self.ancestors(index)):
            raw = self.direct_text[i]
            operation = operation or bool(
                re.search(r"\b(?:amend\w*|striking|inserting|repeal\w*)\b", raw, re.I)
            )
            external = external or bool(
                re.search(
                    r"\b(?:United States Code|U\.S\.C\.|Public Law|title\s+\d+|such (?:section|subsection|Act))\b|\bof\s+(?!this\s+Act\b)[^.;]{1,100}\bAct\b",
                    raw,
                    re.I,
                )
            )
            if operation and external:
                return True
            if self.nodes[i].tag == "section":
                break
        return False

    def _scoped_group(self, index, match, raw):
        def exists(candidate, end):
            return self._reference_targets(
                index,
                candidate,
                raw,
                after=raw[end : end + 100],
                before=raw[: match.start()],
            )

        return _reference_group(match, raw, exists)

    def _reference_targets(self, index, match, raw, *, after=None, before=None):
        kind, label = match["kind"].casefold(), match["label"]
        suffix = re.findall(r"\([A-Za-z0-9]+\)", match["suffix"])
        after = raw[match.end() : match.end() + 100] if after is None else after
        before = raw[: match.start()] if before is None else before
        # An unparsed annotation can carry an external qualification. Do not
        # silently treat 'section 2 (as amended) of the Other Act' as local.
        if after.lstrip().startswith("("):
            return []
        local = LOCAL_SCOPE.match(after)
        if re.match(r"\s+of\s+", after, re.I) and not local:
            return []
        if (
            self._external_amendment(index)
            and not local
            and not re.search(
                r"\b(?:added|amended|redesignated|transferred|inserted)\s+by\s*$",
                before,
                re.I,
            )
        ):
            return []
        explicit_scope = None
        if local and local[1].casefold() != "act":
            level = local[1].casefold()
            explicit_scope = self.scope(index, level)
            if (
                explicit_scope is None
                or self.nodes[explicit_scope].tag != level
                or (level in LEVELS and LEVELS.index(level) >= LEVELS.index(kind))
            ):
                return []
        if kind == "section":
            candidates = self.sections.get(
                (self.quote_scope(index), label.casefold()), []
            )
            if explicit_scope is not None:
                candidates = [
                    target
                    for target in candidates
                    if self._descendant(target, explicit_scope)
                ]
            # Bare section numbers inside instructions amending another law
            # are not numbers in the current bill.
            if (
                not local
                and self.quote_scope(index) is None
                and re.search(r"\b(?:amend\w*|striking|inserting)\b", raw, re.I)
            ):
                return []
            return (
                self._path_target(candidates[0], suffix) if len(candidates) == 1 else []
            )
        labels = re.findall(r"\([A-Za-z0-9]+\)", label) + suffix
        if not labels:
            return []
        rank = LEVELS.index(kind)
        enclosing = (
            explicit_scope
            if local
            else next(
                (
                    i
                    for i in (index, *self.ancestors(index))
                    if self.nodes[i].tag in LEVELS[:rank]
                    and self.quote_scope(i) == self.quote_scope(index)
                ),
                None,
            )
        )
        return (
            self._path_target(enclosing, labels, first_kind=kind)
            if enclosing is not None
            else []
        )

    def _range_targets(self, first, last):
        """Expand an interval only within the endpoints' verified legal scope.

        The actual intervening provisions supply evidence (including inserted
        labels such as section 2A). Their ordinal sequence must also be complete:
        present (a) and (c) cannot prove the absence of a missing (b).
        """
        if len(first) != 1 or len(last) != 1:
            return [], False
        left, right = self.nodes[first[0]], self.nodes[last[0]]
        if left.tag != right.tag or self.quote_scope(first[0]) != self.quote_scope(
            last[0]
        ):
            return [], False
        if left.tag == "section":
            candidates = [
                target
                for (quote, _), targets in self.sections.items()
                if quote == self.quote_scope(first[0])
                for target in targets
            ]
        elif left.parent == right.parent:
            candidates = [
                target
                for target in self.children[left.parent]
                if self.nodes[target].tag == left.tag
                and self.quote_scope(target) == self.quote_scope(first[0])
            ]
        else:
            return [], False
        start, end = _label_ordinal(left), _label_ordinal(right)
        if (
            start is None
            or end is None
            or start[0] != end[0]
            or start[1] > end[1]
            or left.start > right.start
        ):
            return [], False
        targets = sorted(
            (
                target
                for target in candidates
                if left.start <= self.nodes[target].start <= right.start
            ),
            key=lambda target: self.nodes[target].start,
        )
        ordinals = [
            ordinal[1]
            for target in targets
            if (ordinal := _label_ordinal(self.nodes[target])) is not None
            and ordinal[0] == start[0]
        ]
        complete = len(ordinals) == end[1] - start[1] + 1 and all(
            value == start[1] + offset for offset, value in enumerate(ordinals)
        )
        return targets, complete

    def _retain_incoming_reference(self, origin, target):
        # A reference can impose eligibility, a use restriction or a condition
        # on its target without using any particular modal phrase. The parser
        # establishes a local relationship, not whether it is legally relevant;
        # retain it for interpretation (or bounded dependency review) instead of
        # treating a failed wording match as proof that it does not apply.
        if origin != target and self.quote_scope(origin) == self.quote_scope(target):
            self.incoming[target].add(origin)

    def _index_dependencies(self):
        for i, node in enumerate(self.nodes):
            if node.tag in NAVIGATION:
                continue
            raw = self.direct_text[i]
            normalized = " ".join(raw.split())
            for pattern in (DEFINITION, QUOTED_DEFINITION):
                for match in pattern.finditer(normalized):
                    term = _normalize(match["term"])
                    if term:
                        self.definitions[term].append(
                            (self._definition_scope(i, normalized), i)
                        )
            if self.scope_candidate.search(normalized):
                for match in SCOPE.finditer(normalized):
                    scope = self.scope(i, match[1])
                    level = match[1].casefold()
                    if (
                        self.resolve_missing_scope
                        and level != "act"
                        and scope == self.quote_scope(i)
                    ):
                        # A missing structural parent cannot impose a rule on
                        # every section of the bill (or of the quoted law).
                        self.unresolved[i].add(match[0])
                        continue
                    if level not in LEVELS:
                        if not QUALIFICATION.search(normalized):
                            continue
                        # Mere mentions of enactment, authorization or an
                        # amendment by "this Act" do not make a local rule a
                        # restriction on every other provision of the bill.
                        preceding = normalized[
                            max(0, match.start() - 140) : match.start()
                        ]
                        explicit = re.search(
                            r"\b(?:nothing|no provision)\s+in\s*$", preceding, re.I
                        ) or re.search(
                            r"\b(?:no|none of the)\s+(?:funds|amounts)\b[^.;:]{0,120}$",
                            preceding,
                            re.I,
                        )
                        if re.search(
                            r"\b(?:according to|provides that|states that|made available to carry out)\b",
                            normalized[: match.start()],
                            re.I,
                        ):
                            explicit = False
                        if not explicit or (scope is None and level != "act"):
                            continue
                    if scope != i:
                        self.qualifications[scope].append(i)
            for identity in node.references:
                if identity in self.by_identity:
                    target = self.by_identity[identity]
                    self.links[i].add(target)
                    self._retain_incoming_reference(i, target)
            if self.use_external_markup and node.external_references:
                # Keep immutable evidence; mask only external labels in the local
                # reference parser, preserving independently marked local links.
                fragments = []
                for left, right in self.direct[i]:
                    fragment = self.text[left:right]
                    for start, end, citation in node.external_references:
                        if left <= start < end <= right:
                            self.unresolved[i].add(citation)
                            fragment = (
                                fragment[: start - left]
                                + " " * (end - start)
                                + fragment[end - left :]
                            )
                    fragments.append(fragment)
                normalized = " ".join(" ".join(fragments).split())
            consumed = 0
            for match in REFERENCE.finditer(normalized):
                if match.start() < consumed:
                    continue
                if (
                    node.tag == "section"
                    and match.start() == 0
                    and match["kind"].casefold() == "section"
                    and match["label"].casefold() == node.label.casefold()
                ):
                    continue  # A rendered section heading is not a cross-reference.
                # Lists and ranges share their final qualification. Keep an
                # obligation for the entire expression if any member, scope,
                # or intervening ordinal cannot be resolved unambiguously.
                members, cursor, incomplete, compact_literals = self._scoped_group(
                    i, match, normalized
                )
                consumed = cursor
                after = normalized[cursor : cursor + 100]
                targets, previous = [], []
                for is_range, member in members:
                    resolved = self._reference_targets(
                        i,
                        member,
                        normalized,
                        after=after,
                        before=normalized[: match.start()],
                    )
                    if len(resolved) != 1:
                        resolved = []
                        incomplete = True
                    targets.extend(resolved)
                    if is_range:
                        expanded, complete = self._range_targets(previous, resolved)
                        targets.extend(expanded)
                        incomplete = incomplete or not complete
                    previous = resolved
                for literal in compact_literals:
                    resolved = self._reference_targets(
                        i,
                        literal,
                        normalized,
                        after=after,
                        before=normalized[: match.start()],
                    )
                    if resolved:
                        # 'Sections 2-4' may also identify an actual section
                        # labeled '2-4'. Preserve both available interpretations
                        # and require review instead of silently selecting one.
                        targets.extend(resolved)
                        incomplete = True
                if incomplete:
                    self.unresolved[i].add(normalized[match.start() : cursor])
                targets = list(dict.fromkeys(targets))
                preceding = normalized[max(0, match.start() - 160) : match.start()]
                amendment_identity = re.search(
                    r"\b(?:amendments?\s+(?:made|effected)|(?:law|provision)\s+amended|changes?\s+made)\s+by\s*$",
                    preceding,
                    re.I,
                )
                amendment_identity = amendment_identity or (
                    re.search(
                        r"\bas\s+(?:added|redesignated|transferred)\s+by\s*$",
                        preceding,
                        re.I,
                    )
                )
                identity_frame = re.search(
                    r"\b(?:shall (?:take effect|be executed|continue in effect)|remains? in effect|is amended as follows|by conforming|by striking any heading)\b",
                    normalized,
                    re.I,
                ) or any(
                    re.search(
                        r"^(?:savings(?: provision| clause)?|(?:further )?technical amendments|coordination with other amendments.*|conforming amendments)$",
                        self.nodes[a].heading,
                        re.I,
                    )
                    for a in (i, *self.ancestors(i))
                )
                amendment_identity = (
                    amendment_identity
                    and identity_frame
                    and not re.search(
                        r"\b(?:means|has the meaning|defined|subject to|requirements?|conditions?|eligibility|entitled|pursuant to)\b",
                        normalized,
                        re.I,
                    )
                )
                table_reference = re.search(
                    r"\bfunding\s+table\b[^.;]{0,100}$", preceding, re.I
                ) and re.search(
                    r"\b(?:authorized to be appropriated|hereby appropriated|authorization of appropriations)\b",
                    normalized,
                    re.I,
                )
                for target in targets:
                    # A precise provision inserted into another statute is
                    # available evidence, not an unavailable external citation.
                    # E.g. 'section 6100 of title 10, as added by section 1'
                    # resolves to quoted section 6100 inside bill section 1.
                    inserted = []
                    if re.search(r"\bas\s+added\s+by\s*$", preceding, re.I):
                        prior = list(REFERENCE.finditer(normalized[: match.start()]))
                        if prior and prior[-1]["kind"].casefold() == "section":
                            reference = prior[-1]
                            inserted = [
                                j
                                for (_, label), candidates in self.sections.items()
                                if label == reference["label"].casefold()
                                for j in candidates
                                if self.quote_scope(j) is not None
                                and target in self.ancestors(j)
                            ]
                            if len(inserted) == 1:
                                suffix = re.findall(
                                    r"\([A-Za-z0-9]+\)", reference["suffix"]
                                )
                                inserted = self._path_target(inserted[0], suffix)
                            else:
                                inserted = []
                            if inserted:
                                self.unresolved[i].discard(reference[0])
                    if inserted:
                        self.links[i].discard(target)
                        self.links[i].update(inserted)
                    elif amendment_identity:
                        self.links[i].discard(target)
                        self.introduction_links[i].add(target)
                    elif table_reference and self.tables_under[target]:
                        # The authorization owns the legal authority, while
                        # each separately owned table row carries its amount.
                        # Give rows that authority too; never interpret a table
                        # labeled 'authorized' as money actually appropriated.
                        self.links[i].discard(target)
                        self.introduction_links[i].add(target)
                        for table in self.tables_under[target]:
                            self.table_authorizations[table].add(i)
                    else:
                        self.links[i].add(target)
                for target in targets:
                    self._retain_incoming_reference(i, target)
        alternatives = sorted(self.definitions, key=len, reverse=True)
        for term in tuple(alternatives):
            if term.endswith("y") and len(term) > 1 and term[-2] not in "aeiou":
                plural = term[:-1] + "ies"
            elif term.endswith(("s", "x", "ch", "sh")):
                plural = term + "es"
            else:
                plural = term + "s"
            self.definitions[plural].extend(self.definitions[term])
        alternatives = sorted(self.definitions, key=len, reverse=True)
        self.definition_pattern = (
            re.compile(
                r"(?<!\w)(?:"
                + "|".join(re.escape(t) for t in alternatives)
                + r")(?!\w)",
                re.I,
            )
            if alternatives
            else None
        )
        self.definition_links = defaultdict(set)
        if self.definition_pattern:
            for i, raw in enumerate(self.direct_text):
                if self.nodes[i].tag in NAVIGATION:
                    continue
                for match in self.definition_pattern.finditer(_normalize(raw)):
                    for scope, defining in self.definitions[_normalize(match[0])]:
                        if self._descendant(i, scope):
                            self.definition_links[i].add(defining)
        table_parts = defaultdict(lambda: {"heads": [], "rows": []})
        for i, node in enumerate(self.nodes):
            table = next(
                (
                    p
                    for p in self.ancestors(i)
                    if self.nodes[p].tag in self.table_scopes
                ),
                None,
            )
            if table is None:
                continue
            if node.tag == "thead":
                table_parts[table]["heads"].append(i)
            elif node.tag == "row":
                table_parts[table]["rows"].append(i)
        for parts in table_parts.values():
            active = {}
            for row in parts["rows"]:
                self.links[row].update(parts["heads"])
                level = self.nodes[row].table_label_level
                if level is not None:
                    active = {
                        rank: heading
                        for rank, heading in active.items()
                        if rank < level
                    }
                    active[level] = row
                self.links[row].update(
                    heading for heading in active.values() if heading != row
                )

    def ownership_units(self):
        """Yield disjoint ranges; all whitespace and navigation retain ownership."""
        pieces = []

        def visit(index):
            node = self.nodes[index]
            size = len(self.text[node.start : node.end].encode())
            if node.tag in NAVIGATION or (
                node.tag not in CONTAINERS and size <= UNIT_BYTES
            ):
                pieces.append((node.start, node.end, index))
                return
            if self.children[index]:
                pieces.extend((a, b, index) for a, b in self.direct[index])
                for child in self.children[index]:
                    visit(child)
                return
            # Text-only source with independent sentences has no XML children.
            # Keep complete sentences, never discard the unsplit remainder.
            cursor = node.start
            for match in re.finditer(
                r"(?<=[.!?])\s+|\n+", self.text[node.start : node.end]
            ):
                end = node.start + match.end()
                if end > cursor:
                    pieces.append((cursor, end, index))
                    cursor = end
            if cursor < node.end:
                pieces.append((cursor, node.end, index))

        for root in self.children[None]:
            visit(root)
        cursor = 0
        result = []
        for a, b, index in sorted(pieces):
            if a < cursor:
                raise ValueError("overlapping_context_units")
            if cursor < a:
                result.append((cursor, a, None))
            result.append((a, b, index))
            cursor = b
        if cursor < len(self.text):
            result.append((cursor, len(self.text), None))
        return result

    def required(self, start, end, index):
        """Return the complete source ranges supporting one ownership unit."""
        if index is None:
            return ((start, end),), ()
        identity = (start, end, index)
        if identity in self._required:
            return self._required[identity]
        selected, expanded, pending = set(), set(), []
        unresolved = set()

        def add_range(a, b):
            if a < b and self.text[a:b].strip():
                selected.add((a, b))

        def include(node_index, *, whole=True):
            key = (node_index, whole)
            if key in expanded:
                return
            expanded.add(key)
            node = self.nodes[node_index]
            if node.tag in NAVIGATION:
                return
            if whole:
                add_range(node.start, node.end)
                pending.append(node_index)
                for child in self.children[node_index]:
                    inspect(child)
            else:
                for a, b in self.direct[node_index]:
                    add_range(a, b)
                pending.append(node_index)
            for ancestor in self.ancestors(node_index):
                if self.nodes[ancestor].tag not in NAVIGATION:
                    include(ancestor, whole=False)
            for scope in (node_index, *self.ancestors(node_index)):
                for qualifier in self.qualifications[scope]:
                    include(qualifier)

        def inspect(node_index):
            key = (node_index, "inspect")
            if key in expanded:
                return
            expanded.add(key)
            pending.append(node_index)
            for child in self.children[node_index]:
                if self.nodes[child].tag not in NAVIGATION:
                    inspect(child)

        node = self.nodes[index]
        add_range(start, end)
        if node.tag in NAVIGATION:
            # Navigation has no operative dependency on the thousands of
            # provision numbers it lists. Its own bytes are still reviewed.
            return (), ()
        if (start, end) == (node.start, node.end) and len(
            self.text[node.start : node.end].encode()
        ) <= UNIT_BYTES:
            include(index)
        else:
            # This is a parent's direct introduction/continuation or an
            # unstructured sentence, not ownership of every child provision.
            pending.append(index)
            for ancestor in self.ancestors(index):
                include(ancestor, whole=False)
        for a in (index, *self.ancestors(index), None):
            for qualifier in self.qualifications[a]:
                include(qualifier)
        # A referring restriction is evidence about the target. Its reference
        # back to a partially owned ancestor must not expand unrelated siblings.
        incoming_targets = defaultdict(set)
        examined = set()

        def include_restrictions(target):
            if target in examined:
                return
            examined.add(target)
            for origin in self.incoming[target]:
                incoming_targets[origin].add(target)
                if origin != index and origin not in self.ancestors(index):
                    include(origin)

        for target in (
            index,
            *self.ancestors(index),
            *[i for i in pending if self._descendant(i, index)],
        ):
            include_restrictions(target)
        while pending:
            current = pending.pop()
            for a, b in self.nodes[current].inherited_cell_ranges:
                add_range(a, b)
            unresolved.update(self.unresolved[current])
            for linked in (
                self.links[current] - incoming_targets[current]
            ) | self.definition_links[current]:
                include(linked)
                # Follow restrictions on provisions used by the current
                # provision. A merely incoming citation may describe a
                # separate program; its own incoming citations cannot make
                # that program's restrictions govern this one.
                for target in (
                    linked,
                    *self.ancestors(linked),
                    *self.incoming_descendants[linked],
                ):
                    include_restrictions(target)
            for linked in self.introduction_links[current]:
                include(linked, whole=False)
                for table in self.tables_under[linked]:
                    include(table, whole=False)
                    for child in self.children[table]:
                        if self.nodes[child].tag in {"thead", "tgroup"}:
                            include(child, whole=self.nodes[child].tag == "thead")
                            for header in self.children[child]:
                                if self.nodes[header].tag == "thead":
                                    include(header)
            if self.nodes[current].tag == "table":
                for authorizer in self.table_authorizations[current]:
                    include(authorizer)
        merged = []
        for a, b in sorted(selected):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        result = tuple(merged), tuple(sorted(unresolved))
        self._required[identity] = result
        return result
