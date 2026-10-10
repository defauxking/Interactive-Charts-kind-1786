"""Accept/reject cases for the reference validator, built from the NIP's two example charts.

Run from the repository root:  python3 tests/run_cases.py
Each case is a valid example with one change. "accept" cases must validate; "reject" cases
must fail. Many reject cases reproduce a known problem (noted in the case name).
"""
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ex_dir, tools_dir = ROOT / "examples", ROOT / "tools"
sys.path.insert(0, str(tools_dir))
import chartcheck  # noqa: E402

bar = json.loads(pathlib.Path(ex_dir, "bar.json").read_text())
line = json.loads(pathlib.Path(ex_dir, "line.json").read_text())

cases = []  # (name, content_string, expect_valid)


def mut(base, fn, name, expect_valid=False):
    s = copy.deepcopy(base)
    fn(s)
    cases.append((name, json.dumps(s), expect_valid))


def raw(name, text, expect_valid=False):
    cases.append((name, text, expect_valid))


# ---- must be accepted
mut(bar, lambda s: None, "bar example")
cases[-1] = (cases[-1][0], cases[-1][1], True)
mut(line, lambda s: None, "line example", True)
mut(bar, lambda s: s.update(mark={"type": "bar", "tooltip": {"content": "data"}}), "mark tooltip content=data (times differ by renderer)")
mut(line, lambda s: s["layer"][0].update(params=[{"name": "zoom", "select": {"type": "interval", "encodings": ["x"]}, "bind": "scales"}]),
    "interval param bound to scales (zoom/pan)", True)
mut(line, lambda s: (s["layer"][0].update(params=[{"name": "pick", "select": {"type": "point", "fields": ["relay"]}, "bind": "legend"}]),
                     s["layer"][0].update(encoding={"opacity": {"condition": {"param": "pick", "value": 1}, "value": 0.2}})),
    "legend-bound highlight", True)
mut(bar, lambda s: s["encoding"].update(color={"condition": {"param": "sel", "field": "day", "type": "nominal"}, "value": "#cccccc"},
                                        ) or s.update(params=[{"name": "sel", "select": {"type": "point", "on": "click"}}]),
    "conditional field color with click selection", True)
mut(bar, lambda s: s["encoding"]["y"]["axis"].update(format="$,.2f"), "number format $,.2f", True)
mut(bar, lambda s: s["encoding"]["x"].update(sort="-y"), "sort by another field channel", True)
mut(bar, lambda s: s["encoding"]["x"].update(sort="color"), "sort by absent channel (crashes VL compiler)")
mut(bar, lambda s: (s["data"]["values"][0].update(g="a"), s["encoding"].update(xOffset={"field": "g", "type": "nominal"})),
    "grouped bars via xOffset", True)
mut(bar, lambda s: (s["data"]["values"][0].update(g="a"), s["encoding"].update(xOffset={"field": "g", "type": "nominal"}),
                    s["encoding"]["x"].update(scale={"type": "point"})), "xOffset with point-scaled x (crashes VL compiler)")
mut(line, lambda s: (s["layer"][0].update(params=[{"name": "pick", "select": {"type": "point", "fields": ["relay"], "clear": "dblclick"}, "bind": "legend"}])),
    "legend binding with explicit clear (crashes VL compiler)")
mut(bar, lambda s: (s.update(mark={"type": "bar", "cornerRadius": 3}),
                    s.update(params=[{"name": "hov", "select": {"type": "point", "on": "pointerover", "nearest": True}}])),
    "nearest on a bar mark (crashes VL compiler with cornerRadius)")

# ---- strings that Vega-Lite copies into generated expression code (review findings)
mut(bar, lambda s: s["encoding"]["x"].update(title='Day "UTC"'), "double quote in a title")
mut(bar, lambda s: s["encoding"]["x"].update(title="Bob's day"), "single quote in a title")
mut(bar, lambda s: s["encoding"]["x"].update(title="a\\b"), "backslash in a title")
mut(bar, lambda s: s["encoding"]["x"].update(title="a\u2028b"), "U+2028 in a title")
mut(bar, lambda s: s.update(title="Zaps \u2014 week 40 \u2019s"), "typographic dash and apostrophe in a title", True)
mut(line, lambda s: s["encoding"]["x"]["axis"].update(format="%H') + warn('x') + ('"), "quote in a time format (runs code in Vega-Lite 5)")
mut(bar, lambda s: s["encoding"]["y"]["axis"].update(format="'<9d"), "quote as number-format fill")
mut(bar, lambda s: s["encoding"]["x"].update(sort=["Mon\u2028", "Tue"]), "U+2028 in a sort value")
mut(bar, lambda s: s["encoding"]["x"].update(sort=["Mon'", "Tue"]), "quote in a sort value")
mut(bar, lambda s: s["encoding"]["x"].update(scale={"domain": ["Mon'", "Tue"]}), "quote in a domain value (not copied into code)", True)
mut(line, lambda s: s["layer"][0].update(params=[{"name": "p", "select": {"type": "point"}}, {"name": "p_tuple", "select": {"type": "point"}}]),
    "params p and p_tuple (duplicate Vega signal)")
mut(line, lambda s: s["layer"][0].update(mark={"type": "line", "strokeDash": [0.001, 0.001]}), "microscopic dash pattern")
mut(line, lambda s: s["layer"][0].update(mark={"type": "line", "strokeDash": [0, 0]}), "zero dash pattern")
mut(line, lambda s: s["encoding"]["x"].update(stack="zero"), "stack on a temporal field")
mut(bar, lambda s: s["encoding"].update(tooltip=[{"field": "sats", "type": "quantitative", "title": None}]), "tooltip title null", True)
mut(bar, lambda s: (s.update(params=[{"name": "sel", "select": {"type": "point"}}]),
                    s["encoding"].update(color={"condition": {"param": "sel", "field": "sats", "type": "quantitative", "scale": {"type": "ordinal"}}, "value": "#ccc"})),
    "conditional color: ordinal scale on quantitative field")
mut(bar, lambda s: s["encoding"].update(color={"field": "day", "type": "nominal", "sort": "-y"}), "channel sort on a color field")
mut(line, lambda s: s["data"]["values"][0].update(t="2026-02-30T00:00:00Z"), "impossible date 30 Feb")
mut(line, lambda s: s["data"]["values"][0].update(t="2026-10-09T24:00:00Z"), "hour 24")
mut(line, lambda s: s["data"]["values"][0].update(t="2026-10-09T23:59:60Z"), "leap second")
raw("401-digit integer", json.dumps(bar).replace("21000", "9" * 401))
raw("raw unpaired surrogate character", json.dumps(bar, ensure_ascii=False).replace("Mon", chr(0xD800)))

mut(bar, lambda s: (s["data"]["values"][0].update(sats_end=999), s["encoding"].update(tooltip=[{"field": "sats_end", "type": "quantitative"}])),
    "underscore field name (collides with derived stack fields)")
for w in ["in", "new", "this", "null", "typeof"]:
    mut(line, lambda s, w=w: s["layer"][0].update(params=[{"name": w, "select": {"type": "interval"}, "bind": "scales"}]), f"param named {w}")

# ---- network / external references
mut(bar, lambda s: s.update(data={"url": "https://example.com/data.json"}), "data.url")
mut(bar, lambda s: s["data"].update(url="https://example.com/data.json"), "data.values plus data.url")
mut(bar, lambda s: s["data"].update(format={"type": "json"}), "data.format")
mut(bar, lambda s: s.update(mark="image"), "image mark")
mut(bar, lambda s: s["encoding"].update(url={"field": "day", "type": "nominal"}), "url channel")
mut(bar, lambda s: s["encoding"].update(href={"field": "day", "type": "nominal"}), "href channel")
mut(bar, lambda s: s.update(mark={"type": "bar", "href": "https://example.com"}), "mark.href")
mut(bar, lambda s: s.update({"$schema": "https://vega.github.io/schema/vega-lite/v5.json"}), "$schema URL")
mut(bar, lambda s: s.update(mark={"type": "bar", "color": "url(https://example.com/p.svg#g)"}), "color url() paint server")
mut(bar, lambda s: s.update(config={"font": "x"}), "config block")
mut(bar, lambda s: s.update(usermeta={"embedOptions": {"actions": True}}), "usermeta/embedOptions")

# ---- code / expression surfaces
mut(bar, lambda s: s.update(transform=[{"calculate": "datum.sats * 2", "as": "x2"}]), "transform calculate expression")
mut(bar, lambda s: s.update(transform=[{"filter": {"field": "sats", "gt": 0}}]), "transform filter (any transform)")
mut(bar, lambda s: s.update(mark={"type": "bar", "color": {"expr": "'#f00'"}}), "ExprRef in mark color")
mut(bar, lambda s: s["encoding"]["y"]["axis"].update(labelExpr="datum.label"), "axis labelExpr")
mut(line, lambda s: s["layer"][1]["params"][0]["select"].update(on="pointerover[event.shiftKey]"), "event-stream filter in on")
mut(line, lambda s: s["layer"][1]["params"][0]["select"].update(toggle="event.shiftKey"), "toggle expression string")
mut(line, lambda s: s["layer"][0].update(params=[{"name": "zoom", "select": {"type": "interval", "zoom": "wheel![event.shiftKey]"}, "bind": "scales"}]),
    "interval zoom event stream")
mut(line, lambda s: s["layer"][1]["encoding"]["opacity"].update(condition={"test": "datum.ms > 200", "value": 1}), "condition test predicate string")
mut(line, lambda s: s["layer"][1]["params"].append({"name": "slider", "value": 1, "bind": {"input": "range"}}), "input-bound variable param")
mut(bar, lambda s: s.update(mark={"type": "point", "shape": "M0,-1L1,1L-1,1Z"}), "SVG path as shape")
mut(bar, lambda s: s["encoding"]["y"]["axis"].update(format="0100000000d"), "d3-format width DoS")
mut(bar, lambda s: s["encoding"]["y"].update(formatType="customFn"), "formatType")

# ---- determinism / UTC
mut(line, lambda s: s["encoding"]["x"].pop("scale"), "temporal without utc scale")
mut(line, lambda s: s["encoding"]["x"].update(scale={"type": "time"}), "temporal with local time scale")
mut(line, lambda s: s["encoding"].update(tooltip=[{"field": "t", "type": "temporal"}]), "temporal tooltip field")
mut(line, lambda s: s["data"]["values"][0].update(t="2026-10-09T00:00:00"), "temporal value without offset (local time)")
mut(line, lambda s: s["data"]["values"][0].update(t=1760000000), "temporal value as epoch number")
mut(line, lambda s: s["data"]["values"][0].update(t="2026-10-09"), "temporal value as full-date", True)
mut(line, lambda s: (s["data"]["values"][0].update(t2="2026-10-09T05:00:00"), s["layer"].append({"mark": "rule", "encoding": {"x2": {"field": "t2"}}})),
    "local-time value via x2 of a temporal x")
mut(line, lambda s: s["data"]["values"][0].update(t="2026-10-09T02:00:00+02:00"), "temporal value with offset", True)
mut(line, lambda s: s["encoding"].update(time={"field": "t", "type": "temporal"}), "animation time channel")

# ---- prototype / field-name abuse
mut(bar, lambda s: s["data"]["values"][0].update({"__proto__": 1}), "__proto__ data key")
mut(bar, lambda s: s["data"]["values"][0].update({"constructor": 1}), "constructor data key")
mut(bar, lambda s: s["encoding"]["y"].update(field="toString"), "toString field")
mut(bar, lambda s: s["encoding"]["y"].update(field="a.b"), "nested field path")
mut(bar, lambda s: s["encoding"]["y"].update(field="sats\"]+x+[\""), "quote injection in field name")
mut(line, lambda s: s["layer"][1]["params"][0].update(name="width"), "param named width")

# ---- structure / limits
mut(bar, lambda s: s["data"]["values"][0].update(nested={"a": 1}), "nested object in row")
mut(bar, lambda s: s["data"]["values"][0].update(day="x" * 257), "string over 256 chars")
mut(bar, lambda s: s["data"].update(values=[{"day": "d", "sats": i} for i in range(5001)]), "5001 rows")
tiny = {"data": {"values": [{"a": i % 10} for i in range(5000)]}, "mark": "point",
        "encoding": {"x": {"field": "a", "type": "quantitative"}}}
raw("5000 one-field rows (limit)", json.dumps(tiny, separators=(",", ":")), True)
tiny["data"]["values"].append({"a": 1})
raw("5001 one-field rows", json.dumps(tiny, separators=(",", ":")))
mut(bar, lambda s: s.update(facet={"field": "day", "type": "nominal"}), "facet composition")
mut(bar, lambda s: s["encoding"]["y"].update(field="missing"), "field absent from data")
mut(line, lambda s: s["layer"][1]["encoding"]["opacity"]["condition"].update(param="nope"), "undeclared param")
mut(line, lambda s: s["layer"][0].update(params=[{"name": "hover", "select": {"type": "point"}}]), "duplicate param name")
mut(bar, lambda s: s.update(title={"text": "t", "href": "https://example.com"}), "title extra prop")
raw("duplicate member name", json.dumps(bar)[:-1] + ', "mark": "line"}')
raw("1e400 overflow", json.dumps(bar).replace("21000", "1e400"))
raw("NaN literal", json.dumps(bar).replace("21000", "NaN"))
raw("unpaired surrogate", json.dumps(bar).replace('"Mon"', '"\\ud800"'))
big = copy.deepcopy(bar)
big["data"]["values"] = [{"day": "d" * 200, "sats": i} for i in range(400)]
raw("content over 65536 bytes", json.dumps(big))

passed = 0
for name, text, expect_valid in cases:
    spec, errs = chartcheck.validate_content(text)
    ok = (not errs) == expect_valid
    passed += ok
    first = errs[0] if errs else ""
    print(f"{'PASS' if ok else 'FAIL'}  [{'accept' if expect_valid else 'reject'}] {name}" + (f"  -- {first[:110]}" if first else ""))
print(f"\n{passed}/{len(cases)} validation cases behave as expected")
sys.exit(0 if passed == len(cases) else 1)
