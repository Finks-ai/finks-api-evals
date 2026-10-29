"""Render the public Finks API evals site (Finks-ai/finks-api-evals) from its summary.

    python render.py --data data/summary.json --out _site

`data/summary.json` is written by finks-search-eval's public_summary.py and is the only input. `check` refuses any
key or value outside SCHEMA, so the summary can only carry dates, numbers and the verdict words; every sentence on
the page is a constant here. `write` renders, then runs scan.py over what was written (a finding deletes the output).
"""

import argparse
import json
import re
import shutil
import sys
from html import escape
from pathlib import Path

from scan import FILES, Leak, scan

VERDICTS = {"pass": "pass", "fail": "fail", "accepted on review": "review", "grading deferred": "deferred"}  # verdict -> CSS class


class Refused(Exception):
    pass


def _day(v) -> bool:
    return isinstance(v, str) and re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])-[0-3]\d", v) is not None


def _score(v) -> bool:
    return v is None or (isinstance(v, float | int) and not isinstance(v, bool) and 0 <= v <= 1)


def _count(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 10_000


class Optional:
    """A key a dict may leave out; when present its value must pass `schema`."""

    def __init__(self, schema):
        self.schema = schema


SCHEMA = {
    "as_of": _day,
    "gates": [
        {
            "day": _day,
            "verdict": lambda v: v in VERDICTS,
            "search": {"dev": _score, "heldout": _score, "success": _score},
            "longtail": _score,
            "screener": lambda v: v is None or (
                isinstance(v, dict) and set(v) == {"passed", "total"} and all(map(_count, v.values()))
                and v["passed"] <= v["total"]
            ),
            "data": Optional({"exact": _score, "precision": _score}),  # only gates that ran the data block
        }
    ],
}


def check(v, schema=SCHEMA, path: str = "$") -> None:
    """Refuse `v` unless it has the schema's keys (Optional ones may be left out) and every leaf passes; never echoes
    the value."""
    if isinstance(schema, dict):
        required = {k for k, s in schema.items() if not isinstance(s, Optional)}
        if not isinstance(v, dict) or not required <= set(v) <= set(schema):
            raise Refused(f"{path}: keys differ from the schema")
        for k, s in schema.items():
            if k in v:
                check(v[k], s.schema if isinstance(s, Optional) else s, f"{path}.{k}")
    elif isinstance(schema, list):
        if not isinstance(v, list) or not v:
            raise Refused(f"{path}: expected a non-empty list")
        for i, x in enumerate(v):
            check(x, schema[0], f"{path}[{i}]")
    elif not schema(v):
        raise Refused(f"{path}: {type(v).__name__} value rejected by the schema")


CSS = """
:root{--pass:#007a5a;--fail:#c0392b;--review:#b25e00;--line:#e5e7eb;--muted:#6b7280}
*{box-sizing:border-box}
body{font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#111827;
background:#f9fafb;margin:0}
main{max-width:1000px;margin:0 auto;padding:24px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
a{color:#1d4ed8}
nav{margin-bottom:16px}
.muted{color:var(--muted)}
td:first-child{white-space:nowrap}
.small{font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-top:12px}
.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.big{font-size:28px;font-weight:700}
.pass{color:var(--pass)}
.fail{color:var(--fail)}
.review{color:var(--review)}
.deferred{color:var(--muted)}
table{border-collapse:collapse;width:100%;background:#fff}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left}
th{background:#f3f4f6}
dt{font-weight:600;margin-top:8px}
dd{margin:2px 0 0 0}
"""

ABOUT = (
    ("Search relevance, development", "How well the top 5 search results are ordered, scored by graded relevance "
     "(nDCG, top 5) from 0 to 1, on the development queries used for tuning."),
    ("Search relevance, held-out", "The same score on held-out queries nobody looks at or tunes on: the release "
     "gate. Only this average is published."),
    ("Found in top 5", "Share of find-the-item queries, over both query sets, whose known answer is among the "
     "top 5 results."),
    ("Small companies", "Share of the top 10 results that are about the company asked for, for the smallest "
     "listed companies by market value (the bottom three tenths). Only gates that ran it show a value."),
    ("Screener", "Structured stock screens checked against answers computed independently from the same data, "
     "plus requests that must be refused: screens passed of screens run."),
    ("Data panel, exact", "Share of held-out searches whose data panel (the facts shown beside the results, such as "
     "top holders or the next earnings date) shows exactly the kinds of data the question asks for, no more and no "
     "less. Only gates that ran it show a value."),
    ("Data panel, precision", "Share of the kinds of data shown in the data panel, over the held-out searches, that "
     "the question asked for."),
    ("Verdict", "pass: every gate check held. fail: the release was rolled back. accepted on review: a check "
     "flagged a drop that review found to be measurement noise, and the release was kept. grading deferred: the "
     "search scores wait for grading, show \"-\" until then, and the verdict is updated once graded."),
)


def num(v) -> str:
    return "-" if v is None else f"{v:.3f}"


def screens(v) -> str:
    return "-" if v is None else f"{v['passed']} of {v['total']}"


def data(g: dict, key: str):
    return (g.get("data") or {}).get(key)


def verdict(v: str) -> str:
    return f'<span class="{VERDICTS[v]}">{escape(v)}</span>'


def page(title: str, body: str, home: str) -> str:
    nav = f'<nav class="small"><a href="{home}">Finks API evals</a></nav>' if home else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body><main>{nav}{body}</main></body></html>\n"
    )


def index_page(s: dict) -> str:
    g = s["gates"][-1]
    cards = (
        ("Verdict", verdict(g["verdict"])),
        ("Search relevance, development", num(g["search"]["dev"])),
        ("Search relevance, held-out", num(g["search"]["heldout"])),
        ("Found in top 5", num(g["search"]["success"])),
        ("Small companies", num(g["longtail"])),
        ("Screener", screens(g["screener"])),
        ("Data panel, exact", num(data(g, "exact"))),
    )
    body = (
        "<header><h1>Finks API search quality</h1>"
        f'<div class="muted">latest release gate {g["day"]} · {len(s["gates"])} gates published</div></header>'
        "<p>Every Finks API release is checked by a fixed set of evals before it ships: search relevance, "
        "small-company search, the data panel and the stock screener. This site publishes their aggregate scores "
        "only.</p>"
        '<div class="grid">'
        + "".join(f'<div class="card"><div class="muted">{k}</div><div class="big">{v}</div></div>' for k, v in cards)
        + '</div><p><a href="gates/">Every release gate</a></p>'
    )
    return page("Finks API search quality", body, "")


def gates_page(s: dict) -> str:
    rows = "".join(
        f"<tr><td>{g['day']}</td><td>{verdict(g['verdict'])}</td><td>{num(g['search']['dev'])}</td>"
        f"<td>{num(g['search']['heldout'])}</td><td>{num(g['search']['success'])}</td><td>{num(g['longtail'])}</td>"
        f"<td>{screens(g['screener'])}</td><td>{num(data(g, 'exact'))}</td><td>{num(data(g, 'precision'))}</td></tr>"
        for g in reversed(s["gates"])
    )
    body = (
        "<header><h1>Release gates</h1>"
        f'<div class="muted">as of {s["as_of"]} · newest first · scores from 0 to 1</div></header>'
        "<table><tr><th>Day</th><th>Verdict</th><th>Search relevance, development</th>"
        "<th>Search relevance, held-out</th><th>Found in top 5</th><th>Small companies</th><th>Screener</th>"
        "<th>Data panel, exact</th><th>Data panel, precision</th></tr>"
        f"{rows}</table>"
        "<p class=\"small muted\">Each search score is the mean of the release's two runs after it went live, "
        "re-scored against today's grades, so older rows can move slightly as grades are added. A dash means the "
        "eval was not part of that gate.</p>"
        "<h2>What each column measures</h2><dl>"
        + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in ABOUT)
        + "</dl>"
    )
    return page(f"Finks API release gates {s['as_of']}", body, "../")


def site(s: dict) -> dict[str, str]:
    check(s)
    return {"index.html": index_page(s), "gates/index.html": gates_page(s)}


def write(files: dict[str, str], out: Path) -> None:
    if out.exists():
        if any(not p.is_dir() and str(p.relative_to(out)) not in FILES for p in out.rglob("*")):
            sys.exit(f"{out} holds files other than the site: refusing to replace it")
        shutil.rmtree(out)
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(text)
    try:
        scan(out)
    except Leak:
        shutil.rmtree(out)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="render")
    ap.add_argument("--data", type=Path, required=True, help="the summary JSON to render")
    ap.add_argument("--out", type=Path, required=True, help="directory to write the site into")
    a = ap.parse_args(argv)
    try:
        write(site(json.loads(a.data.read_text())), a.out)
    except (Refused, Leak) as e:
        sys.exit(f"refused: {e}")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
