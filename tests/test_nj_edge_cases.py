"""NJ discovery and regex edge cases on synthetic inputs."""

import pytest

from ggr.ingest.nj import monthly_pdf_urls
from ggr.parse.nj import ONLINE_VALUE, RETURN_MONTH


def _listing(months):
    links = "".join(
        f'<a href="https://www.nj.gov/oag/ge/docs/Financials/SWRTaxReturns/{y}/{name}{y}.pdf">x</a>'
        for y, name in months
    )
    return f"<html><body>{links}</body></html>"


FULL_2018 = [(2018, m) for m in ("June", "July", "August", "September", "October", "November", "December")]


class TestDiscovery:
    def test_parses_and_sorts_months(self):
        urls = monthly_pdf_urls(_listing(FULL_2018))
        assert list(urls) == [(2018, m) for m in range(6, 13)]

    def test_amendment_files_excluded(self, capsys):
        html = _listing(FULL_2018).replace(
            "</body>",
            '<a href="https://x/SWRTaxReturns/2018/107Amendments_2018.pdf">a</a></body>',
        )
        urls = monthly_pdf_urls(html)
        assert len(urls) == 7
        assert "107Amendments_2018.pdf" in capsys.readouterr().out

    def test_hole_in_months_raises(self):
        months = [m for m in FULL_2018 if m != (2018, "September")]
        with pytest.raises(ValueError, match=r"holes.*2018, 9"):
            monthly_pdf_urls(_listing(months))

    def test_renamed_file_is_a_hole_not_a_note(self):
        html = _listing(FULL_2018).replace("September2018.pdf", "September2018_revised.pdf")
        with pytest.raises(ValueError, match="holes"):
            monthly_pdf_urls(html)

    def test_missing_launch_month_raises(self):
        with pytest.raises(ValueError, match="no launch month"):
            monthly_pdf_urls(_listing([(2019, "January")]))


class TestReturnMonthRegex:
    @pytest.mark.parametrize(
        ("text", "month", "year"),
        [
            ("FOR THE MONTH OF JUNE 2024", "JUNE", "2024"),
            ("FOR THE MONTH OF JUNE, 2018", "JUNE", "2018"),
            ("FOR THE MONTH ENDED JANUARY, 2020", "JANUARY", "2020"),
            ("FOR THE PERIOD OF JANUARY 26-31, 2019", "JANUARY", "2019"),
            ("FOR THE MONTH OF OF FEBRUARY 2026", "FEBRUARY", "2026"),
            ("FOR THE MONTH OF DECEMBER", "DECEMBER", None),
        ],
    )
    def test_all_observed_wordings(self, text, month, year):
        m = RETURN_MONTH.search(text)
        assert m is not None
        assert m.group(1) == month
        assert m.group(2) == year


class TestOnlineValueRegex:
    @pytest.mark.parametrize(
        "line",
        [
            "16 Monthly Online Sports Wagering Gross Revenue 1 ,915,362",  # 2019-2025
            "8 Current Month Internet Sports Wagering Gross Revenue $ -",  # 2018
            "15 Monthly Internet Sports Wagering Gross Revenue $ 2 6,752",  # combined era
            "16 Monthly Online Sportsbook Gross Revenue 11,321,521",  # 2026
            "15 Monthly Retail Sports Wagering Gross Revenue $ 7 93,682",  # mislabeled (Ocean)
        ],
    )
    def test_value_lines_match(self, line):
        assert ONLINE_VALUE.match(line)

    @pytest.mark.parametrize(
        "line",
        [
            "14 Year-to-Date Online Sports Wagering Gross Revenue $ 4 ,192,270",
            "15 Less: Last Month's Year-to-Date Online Sports Wagering Gross Revenue 2 ,276,908",
            "18 Monthly Taxable Online Sports Wagering Gross Revenue 1 ,915,362",
            "17 Monthly Adjustments -",
            "3 Monthly Sportsbook Lounge Gross Revenue 14,854",  # retail, 2026 layout
        ],
    )
    def test_non_value_lines_do_not_match(self, line):
        assert not ONLINE_VALUE.match(line)