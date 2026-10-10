"""Reference validator for NIP-XX chart events (kind 1786, dialect vega-lite-nostr/1).

Command line:
    python3 tools/chartcheck.py FILE...
FILE holds one event (.json), a JSON array of events, or one event per line (.jsonl).
Lines shaped like {"name": ..., "event": {...}} are accepted too. Only kind 1786 events
are checked; other kinds are listed as skipped. A .json file holding a bare chart
document (an object with "data" and no "kind") is checked as event content, which is
handy before signing. Exit status is 1 if anything checked is invalid.

As a library:
    from chartcheck import validate_event, validate_content
Errors are returned as a list of strings; an empty list means valid.
Signatures are not checked here; verify them with your usual Nostr library.
"""
import json
import math
import pathlib
import re

from jsonschema import Draft7Validator
from jsonschema.exceptions import best_match

KIND = 1786
DIALECT = ("vega-lite-nostr", "1")
MAX_CONTENT_BYTES = 65536
CHANNEL_SORTS = {"x", "-x", "y", "-y", "color", "-color"}
# Full-date (midnight UTC) or date-time with an explicit offset; local times are ambiguous.
TEMPORAL = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})(?:\.\d{3})?(?:Z|[+-](\d{2}):(\d{2})))?$")
_MAX_DOUBLE = 1.7976931348623157e308

_SCHEMA_PATH = pathlib.Path(__file__).resolve().parent.parent / "vega-lite-nostr-1.schema.json"
SCHEMA = json.loads(_SCHEMA_PATH.read_text())
_VALIDATOR = Draft7Validator(SCHEMA)
# Same rules, one branch each: used only to word error messages precisely.
_BASE = {k: v for k, v in SCHEMA.items() if k != "oneOf"}
_BRANCH = {name: Draft7Validator({**_BASE, "allOf": [{"$ref": f"#/definitions/{name}"}]})
           for name in ("UnitSpec", "LayerSpec")}


class IJSONError(ValueError):
    pass


def _pairs_no_dupes(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise IJSONError(f"duplicate member name {k!r}")
        obj[k] = v
    return obj


def _reject_constant(name):
    raise IJSONError(f"non-finite number {name}")


def _has_surrogate(s):
    return any("\ud800" <= ch <= "\udfff" for ch in s)


def _check_ijson_values(node, path="$"):
    if isinstance(node, float) and not math.isfinite(node):
        raise IJSONError(f"non-finite number at {path}")
    if isinstance(node, int) and not isinstance(node, bool) and abs(node) > _MAX_DOUBLE:
        raise IJSONError(f"integer outside the IEEE 754 double range at {path}")
    if isinstance(node, str) and _has_surrogate(node):
        raise IJSONError(f"unpaired surrogate at {path}")
    if isinstance(node, dict):
        for k, v in node.items():
            if _has_surrogate(k):
                raise IJSONError(f"unpaired surrogate in member name at {path}")
            _check_ijson_values(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_ijson_values(v, f"{path}[{i}]")


def parse_ijson(text):
    """Parse per RFC 7493 (I-JSON): no duplicate names, no NaN/Infinity,
    finite numbers, no unpaired surrogates."""
    obj = json.loads(text, object_pairs_hook=_pairs_no_dupes, parse_constant=_reject_constant)
    _check_ijson_values(obj)
    return obj


def _days_in_month(y, m):
    if m == 2:
        return 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
    return 30 if m in (4, 6, 9, 11) else 31


def valid_temporal(v):
    """YYYY-MM-DD, or YYYY-MM-DDTHH:MM:SS[.sss] with Z or +-HH:MM; calendar-valid,
    hours 00-23, seconds 00-59 (no leap seconds), offsets up to 23:59."""
    if not isinstance(v, str):
        return False
    m = TEMPORAL.match(v)
    if not m:
        return False
    y, mo, d, hh, mi, ss, oh, om = (int(g) if g is not None else None for g in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= _days_in_month(y, mo)):
        return False
    if hh is not None and not (hh <= 23 and mi <= 59 and ss <= 59):
        return False
    if oh is not None and not (oh <= 23 and om <= 59):
        return False
    return True


def _walk_units(spec):
    """Yield (unit_like_object) for the top-level spec and each layer item."""
    yield spec
    for item in spec.get("layer", []) or []:
        yield item


def _iter_conditions(encoding):
    for chan in (encoding or {}).values():
        if isinstance(chan, dict) and "condition" in chan:
            yield chan["condition"]


def _iter_field_refs(spec):
    for unit in _walk_units(spec):
        for chan in (unit.get("encoding") or {}).values():
            defs = chan if isinstance(chan, list) else [chan]
            for d in defs:
                if isinstance(d, dict):
                    if "field" in d:
                        yield d["field"]
                    cond = d.get("condition")
                    if isinstance(cond, dict) and "field" in cond:
                        yield cond["field"]
        for p in unit.get("params", []) or []:
            for f in p.get("select", {}).get("fields", []) or []:
                yield f


def semantic_errors(spec):
    errs = []
    names = []
    for unit in _walk_units(spec):
        for p in unit.get("params", []) or []:
            names.append(p["name"])
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        errs.append(f"param names not unique: {dupes}")
    declared = set(names)
    for unit in _walk_units(spec):
        for cond in _iter_conditions(unit.get("encoding")):
            if cond.get("param") not in declared:
                errs.append(f"condition references undeclared param {cond.get('param')!r}")
    # A sort that names an encoding channel must name another channel of the same
    # (merged) unit that carries a field definition; otherwise Vega-Lite's compiler throws.
    merged_units = ([{**(spec.get("encoding") or {}), **(item.get("encoding") or {})} for item in spec["layer"]]
                    if "layer" in spec else [spec.get("encoding") or {}])
    for enc in merged_units:
        for ch, d in enc.items():
            if isinstance(d, dict) and isinstance(d.get("sort"), str) and d["sort"] in CHANNEL_SORTS:
                target = d["sort"].lstrip("-")
                tdef = enc.get(target)
                if target == ch or not (isinstance(tdef, dict) and "field" in tdef):
                    errs.append(f"{ch}.sort={d['sort']!r} must name another channel encoded with a field")
        # xOffset/yOffset need a discrete band-scaled x/y in the same (merged) unit.
        for off, pos in (("xOffset", "x"), ("yOffset", "y")):
            if off in enc:
                p = enc.get(pos)
                if not (isinstance(p, dict) and p.get("type") in ("nominal", "ordinal")
                        and (p.get("scale") or {}).get("type", "band") == "band"):
                    errs.append(f"{off} requires {pos} to be a nominal/ordinal field on a band scale")
    temporal = set()
    for enc in merged_units:
        for pos, sec in (("x", "x2"), ("y", "y2")):
            d = enc.get(pos)
            if isinstance(d, dict) and d.get("type") == "temporal":
                temporal.add(d["field"])
                if isinstance(enc.get(sec), dict):   # x2/y2 share the temporal scale of x/y
                    temporal.add(enc[sec]["field"])
    for f in sorted(temporal):
        for i, row in enumerate(spec["data"]["values"]):
            v = row.get(f)
            if v is not None and not valid_temporal(v):
                errs.append(f"temporal field {f!r} row {i}: {v!r} is not a valid date or offset date-time")
                break
    present = set()
    for row in spec["data"]["values"]:
        present.update(row.keys())
    for f in sorted(set(_iter_field_refs(spec))):
        if f not in present:
            errs.append(f"field {f!r} is referenced but absent from every data row")
    return errs


def validate_content(content):
    """Validate the .content string of a chart event. Returns (spec_or_None, errors)."""
    if not isinstance(content, str):
        return None, ["content is not a string"]
    try:
        size = len(content.encode("utf-8"))
    except UnicodeEncodeError:
        return None, ["content is not valid Unicode (unpaired surrogate)"]
    if size > MAX_CONTENT_BYTES:
        return None, [f"content exceeds {MAX_CONTENT_BYTES} bytes"]
    try:
        spec = parse_ijson(content)
    except (IJSONError, ValueError) as e:
        return None, [f"not I-JSON: {e}"]
    schema_errors = list(_VALIDATOR.iter_errors(spec))
    if schema_errors:
        # Report the most specific failure (best_match descends into oneOf/anyOf branches).
        branch = _BRANCH["LayerSpec" if isinstance(spec, dict) and "layer" in spec else "UnitSpec"]
        e = best_match(branch.iter_errors(spec)) or best_match(schema_errors)
        where = "/".join(map(str, e.absolute_path)) or "$"
        return None, [f"schema: {where}: {e.message[:200]}"]
    errs = semantic_errors(spec)
    return (spec if not errs else None), errs


def validate_tags(tags):
    errs = []
    if not isinstance(tags, list) or not all(isinstance(t, list) and t and all(isinstance(x, str) for x in t) for t in tags):
        return ["tags must be a list of non-empty lists of strings"]
    dialects = [t for t in tags if t[0] == "dialect"]
    if len(dialects) != 1:
        errs.append(f"expected exactly one dialect tag, found {len(dialects)}")
    else:
        name, version = (dialects[0] + ["", ""])[1:3]
        if name != DIALECT[0]:
            errs.append(f"unsupported dialect {name!r}")
        elif not (version.isdigit() and version == str(int(version)) and int(version) >= 1):
            errs.append(f"dialect version {version!r} is not a positive integer")
        # A higher declared version is still rendered if the document validates against version 1
        # (NIP-XX, Dialect versioning); validate_content applies the version 1 rules.
    alts = [t for t in tags if t[0] == "alt"]
    if len(alts) != 1 or len(alts[0]) < 2 or not alts[0][1].strip():
        errs.append("expected exactly one non-empty alt tag")
    summaries = [t for t in tags if t[0] == "summary"]
    if len(summaries) > 1:
        errs.append("at most one summary tag")
    for t in alts + summaries:
        if len(t) > 1 and _has_surrogate(t[1]):
            errs.append(f"{t[0]} tag value is not valid Unicode text")
    return errs


def validate_event(event):
    errs = []
    if not isinstance(event, dict):
        return ["event is not an object"]
    if event.get("kind") != KIND:
        errs.append(f"kind is {event.get('kind')}, expected {KIND}")
    errs += validate_tags(event.get("tags", []))
    _, cerrs = validate_content(event.get("content"))
    return errs + cerrs


def _load_events(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if path.endswith(".jsonl"):
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(stripped)
        items = data if isinstance(data, list) else [data]
    for i, item in enumerate(items):
        if isinstance(item, dict) and "event" in item and isinstance(item["event"], dict):
            yield item.get("name") or f"#{i}", item["event"]
        else:
            yield f"#{i}", item


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    bad = 0
    for path in argv:
        if path.endswith(".json"):
            raw = pathlib.Path(path).read_text(encoding="utf-8")
            try:
                obj = json.loads(raw)
            except ValueError:
                obj = None
            if isinstance(obj, dict) and "kind" not in obj and "data" in obj:
                _, errs = validate_content(raw)
                bad += bool(errs)
                print(("INVALID  " if errs else "valid    ") + f"{path} (chart content)")
                for e in errs:
                    print(f"         - {e[:200]}")
                continue
        for name, ev in _load_events(path):
            label = f"{path} {name}"
            if not isinstance(ev, dict) or ev.get("kind") != KIND:
                print(f"skip     {label} (kind {ev.get('kind') if isinstance(ev, dict) else '?'})")
                continue
            errs = validate_event(ev)
            if errs:
                bad += 1
                print(f"INVALID  {label}")
                for e in errs:
                    print(f"         - {e[:200]}")
            else:
                print(f"valid    {label} ({ev.get('id', '')[:16]}...)")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
