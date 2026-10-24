import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

import render  # noqa: E402
import scan  # noqa: E402

EXPECTED = ROOT / "tests" / "expected"


def summary() -> dict:
    return json.loads((ROOT / "tests" / "summary.json").read_text())


def build(tmp_path: Path) -> Path:
    out = tmp_path / "site"
    render.write(render.site(summary()), out)
    return out


def test_renders_byte_identical(tmp_path):
    out = build(tmp_path)
    assert sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()) == sorted(scan.FILES)
    for rel in scan.FILES:
        assert (out / rel).read_bytes() == (EXPECTED / rel).read_bytes()


def test_published_summary_renders_and_scans(tmp_path):
    render.write(render.site(json.loads((ROOT / "data" / "summary.json").read_text())), tmp_path / "site")


@pytest.mark.parametrize(
    "planted",
    [
        "account 123456789012",
        "s3://bucket/key",
        "cost 12",
        "user@example.com",
        "see #456",
        "PR 266",
        "build 80b05605",
        "run 20261022T033929Z",
        "master_profiles",
        "api.example.com",
        "graded by Claude",
        "SELECT id FROM runs",
        "<script>alert(1)</script>",
        '<a href="https://example.com/">x</a>',
        '<p onclick="x">x</p>',
        "<!-- note -->",
        "s3:<span></span>//bucket",  # split across tags
        "\uff53\uff13://bucket",  # fullwidth
        "s3:\u200b//bucket",  # zero-width space
    ],
)
def test_scan_fails_on_planted_leak(tmp_path, planted):
    out = build(tmp_path)
    page = out / "gates/index.html"
    page.write_text(page.read_text().replace("</main>", f"<p>{planted}</p></main>"))
    with pytest.raises(scan.Leak) as e:
        scan.scan(out)
    assert planted not in str(e.value)


def test_scan_fails_on_css_and_extra_files(tmp_path):
    out = build(tmp_path)
    page = out / "index.html"
    text = page.read_text()
    page.write_text(text.replace("</style>", ".x{background:url(x)}</style>", 1))
    with pytest.raises(scan.Leak, match="CSS"):
        scan.scan(out)
    page.write_text(text)
    (out / "gates/data.json").write_text("{}")
    with pytest.raises(scan.Leak, match="unexpected file"):
        scan.scan(out)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(extra=1),
        lambda s: s["gates"][0].update(verdict="shipped by PR 266"),
        lambda s: s["gates"][0].update(day="22 Oct"),
        lambda s: s["gates"][0]["search"].update(dev="0.8"),
        lambda s: s["gates"][0]["search"].update(dev=1.5),
        lambda s: s["gates"][0]["search"].update(query="NVDA earnings"),
        lambda s: s["gates"][0].update(screener={"passed": 5, "total": 4}),
        lambda s: s["gates"][-1]["data"].update(exact=1.2),
        lambda s: s["gates"][-1]["data"].update(dataset="holders"),
        lambda s: s["gates"][-1].update(data={"exact": 0.5}),
        lambda s: s["gates"][0].update(data="holders"),
        lambda s: s.update(gates=[]),
    ],
)
def test_schema_refuses(tmp_path, mutate):
    s = summary()
    mutate(s)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(s))
    with pytest.raises(SystemExit, match="refused"):
        render.main(["--data", str(bad), "--out", str(tmp_path / "site")])
    assert not (tmp_path / "site").exists()


def test_data_is_optional_per_gate():
    s = summary()
    assert "data" not in s["gates"][0] and "data" in s["gates"][-1]
    render.check(s)
    gates = render.gates_page(s)
    assert "<td>0.817</td><td>0.976</td>" in gates and "Data panel, exact" in render.index_page(s)


def test_write_deletes_output_on_leak(tmp_path):
    files = render.site(summary())
    files["index.html"] = files["index.html"].replace("</main>", "<p>s3://x</p></main>")
    with pytest.raises(scan.Leak):
        render.write(files, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_write_refuses_to_replace_a_foreign_dir(tmp_path):
    (tmp_path / "notes.txt").write_text("keep me")
    with pytest.raises(SystemExit):
        render.write(render.site(summary()), tmp_path)
    assert (tmp_path / "notes.txt").exists()
