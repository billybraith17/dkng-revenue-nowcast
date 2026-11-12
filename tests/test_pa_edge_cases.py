"""PA parser and discovery edge cases on synthetic inputs."""

import openpyxl
import pandas as pd
import pytest

from ggr.ingest.pa import FY_PARAM, fiscal_year_ids
from ggr.parse.pa import parse_workbook


def _make_workbook(tmp_path, sheets):
    """sheets: list of (title, rows). Rows are lists padded with None."""
    wb = openpyxl.Workbook()
    for i, (title, rows) in enumerate(sheets):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = title
        for row in rows:
            ws.append(row)
    path = tmp_path / "pa_synthetic.xlsx"
    wb.save(path)
    return path


HEADER = [None, None, "July 2022", None, "August 2022"]


def _block(licensee, online_values):
    """A licensee block with retail + online sections; online_values is
    {metric: (july, august)}."""
    rows = [[licensee], ["Retail Sports Wagering"], ["Handle*", None, 111.0, None, 222.0]]
    rows.append(["Online Sports Wagering"])
    for metric, (jul, aug) in online_values.items():
        rows.append([metric, None, jul, None, aug])
    return rows


def test_online_section_only_and_retail_ignored(tmp_path):
    rows = [["MONTHLY SPORTS WAGERING REPORT"], HEADER]
    rows += _block(
        "VALLEY FORGE CASINO",
        {
            "Handle*": (1000.0, 2000.0),
            "Revenue": (100.0, 200.0),
            "Promotional Credits": (10.0, 20.0),
            "Gross Revenue (Taxable)": (90.0, 180.0),
        },
    )
    rows += [["GRAND TOTAL"], ["Handle*", None, 99999.0, None, 99999.0]]
    path = _make_workbook(tmp_path, [("FY 2022-23", rows), ("Footnotes", [["FOOTNOTES:"]])])
    df = parse_workbook(path, "https://example.test")

    assert len(df) == 2  # two months, one licensee; grand total & retail ignored
    jul = df[df["period_end"] == "2022-07-31"].iloc[0]
    assert jul["operator_canonical"] == "fanduel"
    assert jul["handle"] == 1000.0
    assert jul["gross_revenue"] == 100.0
    assert jul["promo_credits"] == 10.0
    assert jul["adjusted_revenue"] == 90.0
    assert 111.0 not in df["handle"].values  # retail
    assert 99999.0 not in df["handle"].values  # grand total


def test_retail_only_licensee_emits_nothing(tmp_path):
    rows = [HEADER, ["WIND CREEK"], ["Retail Sports Wagering"], ["Handle*", None, 5.0, None, 6.0]]
    path = _make_workbook(tmp_path, [("FY 2022-23", rows)])
    assert parse_workbook(path, "https://example.test").empty


def test_conflicting_duplicate_block_raises(tmp_path):
    block = _block("VALLEY FORGE CASINO", {"Revenue": (100.0, 200.0)})
    rows = [HEADER] + block + _block("VALLEY FORGE CASINO", {"Revenue": (999.0, 200.0)})
    path = _make_workbook(tmp_path, [("FY 2022-23", rows)])
    with pytest.raises(ValueError, match="conflicting gross_revenue"):
        parse_workbook(path, "https://example.test")


def test_identical_duplicate_block_tolerated(tmp_path):
    block = _block("VALLEY FORGE CASINO", {"Revenue": (100.0, 200.0)})
    rows = [HEADER] + block + block
    path = _make_workbook(tmp_path, [("FY 2022-23", rows)])
    assert len(parse_workbook(path, "https://example.test")) == 2


def test_negative_revenue_kept(tmp_path):
    rows = [HEADER] + _block("VALLEY FORGE CASINO", {"Revenue": (-50.0, 60.0)})
    path = _make_workbook(tmp_path, [("FY 2022-23", rows)])
    df = parse_workbook(path, "https://example.test")
    assert df[df["period_end"] == "2022-07-31"]["gross_revenue"].iloc[0] == -50.0


def test_unknown_licensee_raises(tmp_path):
    rows = [HEADER] + _block("BRAND NEW CASINO", {"Revenue": (1.0, 2.0)})
    path = _make_workbook(tmp_path, [("FY 2022-23", rows)])
    with pytest.raises(ValueError, match="unknown operators.*BRAND NEW CASINO"):
        parse_workbook(path, "https://example.test")


def test_missing_month_header_raises(tmp_path):
    rows = [["no months here"]] + _block("VALLEY FORGE CASINO", {"Revenue": (1.0, 2.0)})
    path = _make_workbook(tmp_path, [("FY 2022-23", rows)])
    with pytest.raises(ValueError, match="no month header row"):
        parse_workbook(path, "https://example.test")


FILTER_HTML = """
<form><select name="{param}">
  <option value="All">- Any -</option>
  <option value="285">FY 2025/2026</option>
  <option value="252">FY 2024/2025</option>
  <option value="115">FY 2023/2024</option>
  <option value="50">FY 2022/2023</option>
  <option value="49">FY 2021/2022</option>
  <option value="110">FY 2020/2021</option>
  <option value="114">FY 2019/2020</option>
  <option value="116">FY 2018/2019</option>
  <option value="117">FY 2017/2018</option>
</select></form>
"""


def test_fiscal_year_ids_parsed_and_bounded():
    ids = fiscal_year_ids(FILTER_HTML.format(param=FY_PARAM))
    assert ids["FY2018-19"] == "116"
    assert ids["FY2025-26"] == "285"
    assert "FY2017-18" not in ids  # before online launch
    assert list(ids) == sorted(ids)


def test_fiscal_year_ids_missing_filter_raises():
    with pytest.raises(ValueError, match="filter.*not found"):
        fiscal_year_ids("<html><body>redesigned!</body></html>")


def test_fiscal_year_ids_too_few_years_raises():
    html = f'<select name="{FY_PARAM}"><option value="285">FY 2025/2026</option></select>'
    with pytest.raises(ValueError, match="expected ≥8"):
        fiscal_year_ids(html)


def test_build_refetches_only_the_two_newest_fiscal_years(monkeypatch):
    from ggr.ingest import pa as ingest_pa

    urls = {f"FY{y}-{str(y + 1)[2:]}": f"https://example.test/{y}.xlsx" for y in range(2018, 2027)}
    forced = {}

    def fake_fetch(url, subdir, force=False):
        forced[url] = force
        return url

    def fake_parse(path, url):
        year = int(url.rsplit("/", 1)[1][:4])
        return pd.DataFrame(
            {
                "period_end": [pd.Timestamp(year, 12, 31)],
                "operator_raw": ["X"],
                "operator_canonical": ["x"],
            }
        )

    # Deliberately unsorted: the choice must not depend on dictionary order.
    monkeypatch.setattr(ingest_pa, "discover", lambda: dict(reversed(urls.items())))
    monkeypatch.setattr(ingest_pa.cache, "fetch", fake_fetch)
    monkeypatch.setattr(ingest_pa, "parse_workbook", fake_parse)
    out = ingest_pa.build()
    assert len(out) == 9
    assert {u for u, f in forced.items() if f} == {
        "https://example.test/2025.xlsx",
        "https://example.test/2026.xlsx",
    }


@pytest.mark.parametrize("n_years, n_forced", [(1, 1), (2, 2), (3, 2)])
def test_build_refetch_count_with_few_fiscal_years(monkeypatch, n_years, n_forced):
    from ggr.ingest import pa as ingest_pa

    urls = {
        f"FY{y}-{str(y + 1)[2:]}": f"https://example.test/{y}.xlsx"
        for y in range(2018, 2018 + n_years)
    }
    forced = []

    def fake_fetch(url, subdir, force=False):
        forced.append(force)
        return url

    def fake_parse(path, url):
        year = int(url.rsplit("/", 1)[1][:4])
        return pd.DataFrame(
            {
                "period_end": [pd.Timestamp(year, 12, 31)],
                "operator_raw": ["X"],
                "operator_canonical": ["x"],
            }
        )

    monkeypatch.setattr(ingest_pa, "discover", lambda: urls)
    monkeypatch.setattr(ingest_pa.cache, "fetch", fake_fetch)
    monkeypatch.setattr(ingest_pa, "parse_workbook", fake_parse)
    ingest_pa.build()
    assert sum(forced) == n_forced
    assert forced[-n_forced:] == [True] * n_forced


def test_build_still_raises_on_overlapping_months(monkeypatch):
    from ggr.ingest import pa as ingest_pa

    urls = {"FY2024-25": "https://example.test/a.xlsx", "FY2025-26": "https://example.test/b.xlsx"}
    same_month = pd.DataFrame(
        {
            "period_end": [pd.Timestamp("2025-06-30")],
            "operator_raw": ["X"],
            "operator_canonical": ["x"],
        }
    )
    monkeypatch.setattr(ingest_pa, "discover", lambda: urls)
    monkeypatch.setattr(ingest_pa.cache, "fetch", lambda url, subdir, force=False: url)
    monkeypatch.setattr(ingest_pa, "parse_workbook", lambda path, url: same_month.copy())
    with pytest.raises(ValueError, match="overlapping months"):
        ingest_pa.build()
