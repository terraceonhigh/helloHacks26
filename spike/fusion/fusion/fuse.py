"""Entity resolution + fusion over observations. Pure functions, no I/O.

    fuse(snapshots) -> (courses, tracks, warnings)
    status(track, now) -> "done" | "overdue" | "due_soon" | "upcoming" | "not_open" | "undated"

Implements SPEC.md "Fusion rules" 1-8. Nothing here knows any provider by
name except the platform words dropped from titles (rule 3).
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from fusion.model import (Conflict, CourseKey, CourseObservation, Observation, Provenance,
                          Snapshot, Track)

DUE_WINDOW = timedelta(hours=24)       # rule 3 "due" evidence
CONFLICT_TOLERANCE = timedelta(minutes=5)
DUE_SOON = timedelta(hours=48)


# --------------------------------------------------------------------------- courses (rule 1)

@dataclass
class FusedCourse:
    """One resolved course and every source's label for it."""
    key: CourseKey | str                     # str = unresolved (own course, warned)
    labels: list[dict] = field(default_factory=list)   # {source, source_id, label, title, url, section}
    sections: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_SUBJ_NUM = re.compile(r"(?<![A-Za-z])([A-Za-z]{2,5})[\s_\-]*(\d{3}[A-Za-z]?)(?![0-9])")
_TERM_SHORT = re.compile(r"(?<!\d)(\d{4})[\s_\-]*([WwSs])[\s_\-]*([12])(?![0-9])")
_TERM_LONG = re.compile(r"(?<!\d)(\d{4})\s+(Winter|Summer)(?:\s+Term)?\s+([12])(?![0-9])", re.I)
# section: 3 chars right after the course number, before the term ("-101-", "_101_", " 101 ", "-L1A-")
_SECTION = re.compile(r"(?<![A-Za-z])[A-Za-z]{2,5}[\s_\-]*\d{3}[A-Za-z]?[\s_\-]+([0-9]{3}|[A-Za-z][0-9][0-9A-Za-z])(?![0-9A-Za-z])")


def _term(text: str | None) -> str | None:
    if not text:
        return None
    m = _TERM_SHORT.search(text)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}{m.group(3)}"
    m = _TERM_LONG.search(text)
    if m:
        return f"{m.group(1)}{m.group(2)[0].upper()}{m.group(3)}"
    return None


def parse_course(label: str, title: str = "", term_hint: str | None = None) -> tuple[CourseKey | None, str | None]:
    """Canonical (CourseKey, section) from a course's label/title/term text, or (None, None).

    Handles CPSC121-101-2026W1, cpsc121_2026w1, CPSC_121_101_2026W1,
    "CPSC 121, 2026W1" and "CPSC 121: Models of Computation, 2026 Winter Term 1".
    The label wins over the title; the term may come from any of the three.
    """
    subj = num = section = None
    for text in (label, title):
        m = _SUBJ_NUM.search(text or "")
        if m:
            subj, num = m.group(1).upper(), m.group(2).upper()
            s = _SECTION.search(text)
            if s and not _TERM_SHORT.match(text[s.start(1):]):
                section = s.group(1).upper()
            break
    term = _term(label) or _term(title) or _term(term_hint)
    # ponytail: UBC-style term codes only (2026W1 / 2026 Winter Term 1). Other schools'
    # terms (Fall 2026, 2026FA, semester ids) need a per-school term table here.
    if not (subj and num and term):
        return None, None
    return CourseKey(subj, num, term), section


def _unresolved_key(c: CourseObservation) -> str:
    return f"{c.source}:{c.label or c.source_id}"


def resolve_courses(snapshots: list[Snapshot]) -> tuple[dict[tuple[str, str], CourseKey | str], list[FusedCourse], list[str]]:
    """Map (source, course_source_id) -> key, plus the fused course list and warnings."""
    mapping: dict[tuple[str, str], CourseKey | str] = {}
    fused: dict[CourseKey | str, FusedCourse] = {}
    warnings: list[str] = []
    for snap in snapshots:
        for c in snap.courses:
            key, section = parse_course(c.label, c.title, c.term_hint)
            fc_warn = None
            if key is None:
                key = _unresolved_key(c)
                fc_warn = (f"course {c.source}:{c.source_id} label {c.label!r} title {c.title!r} "
                           f"could not be parsed; kept as its own course")
                warnings.append(fc_warn)
            mapping[(c.source, c.source_id)] = key
            fc = fused.setdefault(key, FusedCourse(key))
            if fc_warn:
                fc.warnings.append(fc_warn)
            fc.labels.append({"source": c.source, "source_id": c.source_id, "label": c.label,
                              "title": c.title, "url": c.url, "section": section})
            if section and section not in fc.sections:
                fc.sections.append(section)
    for fc in fused.values():
        fc.labels.sort(key=lambda d: (d["source"], d["source_id"]))
        fc.sections.sort()
    courses = sorted(fused.values(), key=lambda fc: _course_sort(fc.key))
    return mapping, courses, warnings


def _course_sort(key: CourseKey | str):
    return (1, key, "", "") if isinstance(key, str) else (0, key.subject, key.number, key.term)


def course_name(key: CourseKey | str) -> str:
    return key if isinstance(key, str) else str(key)


# --------------------------------------------------------------------------- evidence (rule 3)

# ponytail: denylist of query params known not to identify an item (tracking, session, view
# mode). Upgrade path: a per-host allowlist of identifying params learned from the adapters.
_NOISE_PARAMS = {"action", "user", "key", "effectiveuser", "session_key", "sesskey", "lang",
                 "forceview", "redirect", "embed", "display", "fbclid", "gclid", "ref", "source",
                 "module_item_id", "wrap", "time"}
_LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}


_URL_SAFE = "/:@!$&'()*+,;=-._~"


def _canon_pct(text: str) -> str:
    """One spelling per character: 'Quiz%201' and 'Quiz 1' compare equal."""
    return quote(unquote(text), safe=_URL_SAFE)


def normalize_url(url: str | None) -> str | None:
    """Scheme-less, host-lowercased, default-port-less, trailing-slash-less URL with only
    item-identifying query params (sorted) and canonical percent-encoding.

    Total: a URL that can't be parsed (bad port, broken IPv6 host) gives None, never raises,
    so one typo in one source's body can't take down the fuse for every source."""
    if not url:
        return None
    try:
        p = urlsplit(url.strip())
        port = p.port
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    # ponytail: every loopback alias is the same host (a local oracle is reachable as both
    # localhost and 127.0.0.1). Real deployments have one canonical host; drop this then.
    if host in _LOOPBACK:
        host = "localhost"
    if port and not ((p.scheme == "http" and port == 80) or (p.scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    # ponytail: unquoting also turns an encoded "%2F" into a real "/" (a different path to a
    # strict server). Upgrade: split on %2F first if a provider ever uses it in item paths.
    path = _canon_pct(re.sub(r"/+", "/", p.path)).rstrip("/")
    q = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
               if k.lower() not in _NOISE_PARAMS and not k.lower().startswith("utm_"))
    # fragments are kept: some items are only identified by one (Moodle "...#event_6")
    frag = _canon_pct(p.fragment)
    return f"{host}{path}" + (f"?{urlencode(q)}" if q else "") + (f"#{frag}" if frag else "")


_PLATFORM_WORDS = {"webwork", "prairielearn", "moodle", "canvas"}
_FILLER = {"due", "the", "a", "an", "online", "deadline", "submission", "submit", "on", "at", "by"}
_ABBREV = {"hw": ["homework"], "hwk": ["homework"], "ps": ["problem", "set"],
           "pset": ["problem", "set"], "mp": ["machine", "problem"], "asn": ["assignment"],
           "asgn": ["assignment"], "assn": ["assignment"]}


# An identifier number: dotted parts ("4.1") and an optional one-letter suffix ("2a"), the
# suffix only when no other letter follows ("10am" is "10" + "am"). Else a letter run.
_TOKEN = re.compile(r"\d+(?:\.\d+)*(?:[a-z](?![a-z]))?|[a-z]+")
_NUM_TOKEN = re.compile(r"([\d.]+)([a-z]?)")


def _is_num(t: str) -> bool:
    return t[:1].isdigit()


def title_tokens(title: str) -> list[str]:
    """Normalised title tokens: lowercase, split into identifier numbers ("2", "4.1", "2a") and
    words, platform words and filler dropped, abbreviations expanded, leading zeros stripped
    from each number part. A lone letter right after a number is that number's suffix
    ("HW 2 a" == "HW 2a"), never the filler article."""
    raw = _TOKEN.findall((title or "").lower())
    out: list[str] = []
    prev_num = False
    for t in raw:
        if _is_num(t):
            digits, suffix = _NUM_TOKEN.fullmatch(t).groups()
            out.append(".".join(str(int(x)) for x in digits.split(".")) + suffix)
            prev_num = True
            continue
        if prev_num and len(t) == 1 and not out[-1][-1].isalpha():
            out[-1] += t
        elif t in _PLATFORM_WORDS or t in _FILLER:
            pass
        else:
            out.extend(_ABBREV.get(t, [t]))
        prev_num = False
    return out


def _numbers(tokens: list[str]) -> list[str]:
    """Identifier numbers in title order: order matters ("Lab 1 Part 2" is not "Lab 2 Part 1")."""
    return [t for t in tokens if _is_num(t)]


def title_match(a: str, b: str) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    if _numbers(ta) != _numbers(tb):      # "Quiz 2" never matches "Quiz 3", nor 2/3 vs 3/2
        return False
    return Counter(ta) == Counter(tb)


def _targets(o: Observation) -> set[str]:
    return {u for u in (normalize_url(o.url), normalize_url(o.submit_url)) if u}


def _links(o: Observation) -> set[str]:
    return {u for u in (normalize_url(x) for x in o.links_out) if u}


def shallow_targets(snapshots: list[Snapshot], items: list[Observation]) -> frozenset[tuple[str, str]]:
    """(source, normalised url) pairs that are NOT one item's deep link: a url/submit_url that
    two or more observations of the same source share (e.g. a list page standing in for
    items that have no link yet), or a source's course page. A link to one of these says
    "go to that course/list", not "this is that item", so it is never link evidence."""
    count: Counter = Counter()
    for o in items:
        for t in _targets(o):
            count[(o.source, t)] += 1
    out = {k for k, n in count.items() if n > 1}
    for snap in snapshots:
        for c in snap.courses:
            u = normalize_url(c.url)
            if u:
                out.add((c.source, u))
    return frozenset(out)


_NO_SHALLOW: frozenset = frozenset()


def _deep_targets(b: Observation, shallow: frozenset) -> set[str]:
    return {t for t in _targets(b) if (b.source, t) not in shallow}


def links_to(a: Observation, b: Observation, shallow: frozenset = _NO_SHALLOW) -> bool:
    """A's body links to B's own page or submit page (a deep link, not a shared list page)."""
    return bool(_links(a) & _deep_targets(b, shallow))


def _minutes_apart(x: datetime, y: datetime) -> float:
    # instants, not wall clocks: Python ignores tzinfo when both sides share one tzinfo
    # object (a cached ZoneInfo), which is wrong across a DST change
    return abs(x.timestamp() - y.timestamp()) / 60


def evidence(a: Observation, b: Observation, shallow: frozenset = _NO_SHALLOW) -> dict | None:
    """The evidence record between two observations if it is enough to merge, else None."""
    link = links_to(a, b, shallow) or links_to(b, a, shallow)
    title = title_match(a.title, b.title)
    delta = None
    if a.due is not None and b.due is not None:
        delta = round(_minutes_apart(a.due, b.due))
    due_ok = delta is not None and delta <= DUE_WINDOW.total_seconds() / 60
    undated = a.due is None or b.due is None
    if link:
        kind = "link"
    elif title and due_ok:
        kind = "title+due"
    elif title and undated:
        kind = "title+undated"
    else:
        return None
    signals = [s for s, on in (("link", link), ("title", title), ("due", due_ok)) if on]
    direction = []
    if links_to(a, b, shallow):
        direction.append([[a.source, a.source_id], [b.source, b.source_id]])
    if links_to(b, a, shallow):
        direction.append([[b.source, b.source_id], [a.source, a.source_id]])
    return {"a": (a.source, a.source_id), "b": (b.source, b.source_id), "kind": kind,
            "signals": signals, "links": direction, "due_delta_min": delta}


_STRENGTH = {"link": 0, "title+due": 1, "title+undated": 2}


# --------------------------------------------------------------------------- fusion (rules 2, 4, 5, 8)

_KIND_RANK = {"exam": 6, "quiz": 5, "homework": 4, "lab": 4, "project": 4, "assignment": 3,
              "reading": 2, "event": 1, "announcement": 0}
_NOT_SUBMITTABLE = {"event", "announcement", "reading"}


def _oid(o: Observation) -> tuple[str, str]:
    return (o.source, o.source_id)


def track_id(members: list[Observation]) -> str:
    ids = sorted({_oid(o) for o in members})
    return hashlib.sha1("\n".join(f"{s}\x1f{i}" for s, i in ids).encode()).hexdigest()[:12]


def submit_authority(members: list[Observation], shallow: frozenset = _NO_SHALLOW) -> Observation:
    """Rule 5: the observation linked TO by the others; else the only one with a submit_url;
    else the earliest due. Among linked-to members a sink (links to no other member) wins:
    in a chain Canvas -> Moodle pointer -> PrairieLearn the work is submitted at the end."""
    ms = sorted(members, key=_oid)
    inbound = {_oid(m): sum(1 for o in ms if o is not m and links_to(o, m, shallow)) for m in ms}
    sink = {_oid(m): not any(links_to(m, o, shallow) for o in ms if o is not m) for m in ms}
    linked = [m for m in ms if inbound[_oid(m)]]
    if linked:
        return sorted(linked, key=lambda m: (not sink[_oid(m)], -inbound[_oid(m)], *_earliest(m)))[0]
    with_submit = [m for m in ms if m.submit_url]
    if len(with_submit) == 1:
        return with_submit[0]
    # earliest due; ties go to something you can submit (not a calendar event), then by id
    return sorted(ms, key=_earliest)[0]


def _earliest(m: Observation):
    return (m.due is None, m.due.timestamp() if m.due else 0, m.kind in _NOT_SUBMITTABLE, _oid(m))


def _prov(o: Observation, value) -> Provenance:
    return Provenance(value=value, source=o.source, source_id=o.source_id)


def build_track(course, members: list[Observation], edges: list[dict], warnings: list[str],
                shallow: frozenset = _NO_SHALLOW) -> Track:
    members = sorted(members, key=_oid)
    auth = submit_authority(members, shallow)

    due_from = auth if auth.due is not None else next(
        # authority gives no due (e.g. a pointer with a forgotten date): earliest dated member
        (m for m in sorted(members, key=_earliest) if m.due is not None), None)
    due = _prov(due_from, due_from.due) if due_from else None
    conflicts = []
    if due is not None:
        for m in members:
            if m is not due_from and m.due is not None and _minutes_apart(m.due, due.value) > CONFLICT_TOLERANCE.total_seconds() / 60:
                conflicts.append(Conflict("due", m.source, m.source_id, m.due, due.value))

    kind_src = sorted(members, key=lambda m: (-_KIND_RANK.get(m.kind, 3 if m.kind else -1),
                                              m is not auth, _oid(m)))[0]
    opens_src = auth if auth.opens is not None else next((m for m in members if m.opens is not None), None)
    weight_src = auth if auth.weight is not None else next((m for m in members if m.weight is not None), None)
    links: dict[str, str] = {}
    for m in members:
        links.setdefault(m.source, m.url)
    return Track(
        id=track_id(members), course=course,
        title=_prov(auth, auth.title), kind=_prov(kind_src, kind_src.kind),
        due=due,
        opens=_prov(opens_src, opens_src.opens) if opens_src else None,
        done=_prov(auth, auth.done) if auth.done is not None else None,
        weight=_prov(weight_src, weight_src.weight) if weight_src else None,
        action_url=auth.submit_url or auth.url,
        links=links, members=members, evidence=edges, conflicts=conflicts, warnings=warnings)


def _check_aware(o: Observation):
    for name in ("due", "opens"):
        v = getattr(o, name)
        if v is not None and (v.tzinfo is None or v.tzinfo.utcoffset(v) is None):
            raise ValueError(f"naive datetime {name}={v!r} in {o.source}:{o.source_id}")


def fuse(snapshots: list[Snapshot]) -> tuple[list[FusedCourse], list[Track], list[str]]:
    """Resolve courses, find which observations describe the same work, fuse them into tracks.

    Deterministic: input order never changes the output (everything is sorted by
    (source, source_id) first).
    """
    mapping, courses, warnings = resolve_courses(snapshots)

    # dedupe identities: a source listing the same item twice is one node. Two DIFFERENT
    # readings under one identity (two snapshots sharing a source name, e.g. two Moodle
    # schools) are warned about, and the survivor is chosen by content, never input order.
    seen: dict[tuple[str, str], dict[str, Observation]] = {}
    for snap in snapshots:
        for o in snap.items:
            _check_aware(o)
            seen.setdefault(_oid(o), {}).setdefault(_canonical(o), o)
    obs: dict[tuple[str, str], Observation] = {}
    for oid in sorted(seen):
        variants = seen[oid]
        keep = min(variants)
        obs[oid] = variants[keep]
        if len(variants) > 1:
            titles = sorted(v.title for v in variants.values())
            warnings.append(f"item {oid[0]}:{oid[1]} appears {len(variants)} times with different "
                            f"content (titles {titles}); kept {variants[keep].title!r} and dropped the "
                            f"rest. Two sources sharing one source name?")

    for oid in sorted(obs):
        o = obs[oid]
        for fname, vals in (("url", [o.url]), ("submit_url", [o.submit_url]), ("links_out", o.links_out)):
            for v in vals:
                if v and normalize_url(v) is None:
                    warnings.append(f"item {o.source}:{o.source_id}: unparseable URL in {fname} "
                                    f"ignored for link evidence: {v[:200]!r}")
    shallow = shallow_targets(snapshots, list(obs.values()))

    # blocking: group by resolved course (rule 2)
    blocks: dict[object, list[Observation]] = {}
    for oid in sorted(obs):
        o = obs[oid]
        key = mapping.get((o.source, o.course_source_id))
        if key is None:
            key = f"{o.source}:{o.course_source_id}"
            w = f"item {o.source}:{o.source_id} points at unknown course {o.course_source_id!r}; kept apart"
            warnings.append(w)
        blocks.setdefault(key, []).append(o)

    tracks: list[Track] = []
    for key in sorted(blocks, key=_course_sort):
        tracks.extend(_fuse_block(key, blocks[key], warnings, shallow))
    return courses, tracks, warnings


def _canonical(o: Observation) -> str:
    return json.dumps(asdict(o), default=str, sort_keys=True)


def _fuse_block(course, items: list[Observation], warnings: list[str],
                shallow: frozenset = _NO_SHALLOW) -> list[Track]:
    edges = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.source == b.source:      # rule 2: same source never merges (distinct ids here)
                continue
            for x, y in ((a, b), (b, a)):
                ignored = sorted(_links(x) & (_targets(y) - _deep_targets(y, shallow)))
                if ignored:
                    warnings.append(f"link {x.source}:{x.source_id} -> {y.source}:{y.source_id} not used "
                                    f"as evidence: {ignored[0]} is a shared list/course page of "
                                    f"{y.source}, not that item's own deep link")
            e = evidence(a, b, shallow)
            if e:
                edges.append(e)

    # rule 4: union-find over evidence
    parent = {_oid(o): _oid(o) for o in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        ra, rb = find(e["a"]), find(e["b"])
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    comps: dict[tuple, list[Observation]] = {}
    for o in items:
        comps.setdefault(find(_oid(o)), []).append(o)

    tracks = []
    for root in sorted(comps):
        members = comps[root]
        mids = {_oid(m) for m in members}
        comp_edges = [e for e in edges if e["a"] in mids]
        by_source = Counter(m.source for m in members)
        if all(n == 1 for n in by_source.values()):
            tracks.append(build_track(course, members, comp_edges, [], shallow))
            continue
        tracks.extend(_split(course, members, comp_edges, warnings, shallow))
    return tracks


def _split(course, members: list[Observation], edges: list[dict], warnings: list[str],
           shallow: frozenset = _NO_SHALLOW) -> list[Track]:
    """Sanity pass: a transitive chain put two same-source observations together. Rebuild the
    component strongest-evidence-first, refusing any union that would join two groups sharing
    a source, and warn about each refused edge."""
    group = {_oid(m): frozenset([_oid(m)]) for m in members}
    refused = []
    for e in sorted(edges, key=lambda e: (_STRENGTH[e["kind"]], e["due_delta_min"] if e["due_delta_min"] is not None else 10**9, e["a"], e["b"])):
        ga, gb = group[e["a"]], group[e["b"]]
        if ga is gb or ga == gb:
            continue
        if {s for s, _ in ga} & {s for s, _ in gb}:
            refused.append(e)
            continue
        merged = ga | gb
        for oid in merged:
            group[oid] = merged
    groups = sorted(set(group.values()), key=lambda g: sorted(g))
    msg = ("split a transitive merge that would put two observations from the same source in one "
           "track: " + "; ".join(f"{a[0]}:{a[1]} x {b[0]}:{b[1]} ({e['kind']}) refused"
                                  for e in refused for a, b in [(e["a"], e["b"])]))
    warnings.append(msg)
    by_id = {_oid(m): m for m in members}
    out = []
    for g in groups:
        g_edges = [e for e in edges if e["a"] in g and e["b"] in g and e not in refused]
        out.append(build_track(course, [by_id[i] for i in g], g_edges, [msg], shallow))
    return out


# --------------------------------------------------------------------------- status + order (rules 6, 7)

def status(track: Track, now: datetime) -> str:
    """Computed at read time, never stored."""
    if now.tzinfo is None:
        raise ValueError("now must be tz-aware")
    if track.done is not None and track.done.value is True:
        return "done"
    t = now.timestamp()                   # instants: see _minutes_apart
    if track.opens is not None and track.opens.value.timestamp() > t:
        return "not_open"
    if track.due is None:
        return "undated"
    due = track.due.value.timestamp()
    if due < t:
        return "overdue"
    if due - t <= DUE_SOON.total_seconds():
        return "due_soon"
    return "upcoming"


def order(tracks: list[Track], now: datetime, include_done: bool = False) -> list[Track]:
    """Overdue first, then due ascending, undated last. Done hidden unless include_done."""
    def key(t: Track):
        st = status(t, now)
        return (st != "overdue", t.due is None, t.due.value.timestamp() if t.due else 0,
                _course_sort(t.course), t.title.value, t.id)
    return sorted((t for t in tracks if include_done or status(t, now) != "done"), key=key)


# --------------------------------------------------------------------------- JSON

def _j(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, (CourseKey,)):
        return str(v)
    if isinstance(v, tuple):
        return [_j(x) for x in v]
    return v


def prov_json(p: Provenance | None):
    return None if p is None else {"value": _j(p.value), "source": p.source, "source_id": p.source_id}


def observation_json(o: Observation, course=None) -> dict:
    d = {k: _j(getattr(o, k)) for k in o.__dataclass_fields__}
    if course is not None:
        d["course"] = course_name(course)
    return d


def track_json(t: Track, now: datetime, full: bool = False) -> dict:
    d = {"id": t.id, "course": course_name(t.course), "title": t.title.value, "kind": t.kind.value,
         "status": status(t, now), "due": _j(t.due.value) if t.due else None,
         "opens": _j(t.opens.value) if t.opens else None,
         "done": t.done.value if t.done else None, "weight": t.weight.value if t.weight else None,
         "action_url": t.action_url, "links": dict(sorted(t.links.items())),
         "sources": sorted({m.source for m in t.members}),
         "evidence_kinds": sorted({e["kind"] for e in t.evidence}),
         "conflicts": len(t.conflicts), "warnings": len(t.warnings)}
    if full:
        d.update({
            "provenance": {f: prov_json(getattr(t, f)) for f in ("title", "kind", "due", "opens", "done", "weight")},
            "members": [observation_json(m) for m in t.members],
            "evidence": [{**e, "a": list(e["a"]), "b": list(e["b"])} for e in t.evidence],
            "conflicts": [{"field": c.field, "source": c.source, "source_id": c.source_id,
                           "value": _j(c.value), "chosen": _j(c.chosen),
                           "delta_min": round((c.value.timestamp() - c.chosen.timestamp()) / 60)
                           if isinstance(c.value, datetime) and isinstance(c.chosen, datetime) else None}
                          for c in t.conflicts],
            "warnings": list(t.warnings),
        })
    return d


def course_json(fc: FusedCourse) -> dict:
    k = fc.key
    return {"key": course_name(k), "resolved": not isinstance(k, str),
            "subject": None if isinstance(k, str) else k.subject,
            "number": None if isinstance(k, str) else k.number,
            "term": None if isinstance(k, str) else k.term,
            "name": k if isinstance(k, str) else f"{k.subject} {k.number}",
            "sections": list(fc.sections), "labels": list(fc.labels), "warnings": list(fc.warnings)}


def course_matches(key: CourseKey | str, query: str) -> bool:
    """?course= accepts "CPSC 121", "CPSC121", "CPSC 121 / 2026W1" or an unresolved label."""
    q = re.sub(r"[\s_/-]+", "", query).upper()
    if isinstance(key, str):
        return re.sub(r"[\s_/-]+", "", key).upper() == q
    return q in {f"{key.subject}{key.number}", f"{key.subject}{key.number}{key.term}"}
