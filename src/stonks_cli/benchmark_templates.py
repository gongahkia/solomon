from __future__ import annotations

from dataclasses import dataclass

from stonks_cli.config import BenchmarkComponent, BenchmarkSettings
from stonks_cli.types import Currency

_RETRIEVED_AT = "2026-07-23T00:00:00+00:00"


@dataclass(frozen=True)
class BenchmarkTemplate:
    identifier: str
    name: str
    components: tuple[BenchmarkComponent, ...]
    coverage: str
    return_methodology: str
    cost_availability: str
    diversification: str
    pros: tuple[str, ...]
    cons: tuple[str, ...]
    source_provenance: tuple[str, ...]
    retrieved_at: str = _RETRIEVED_AT

    @property
    def settings(self) -> BenchmarkSettings:
        return BenchmarkSettings(self.components)


_TEMPLATES = (
    BenchmarkTemplate(
        "us-sg-core",
        "US/Singapore core",
        BenchmarkSettings().components,
        "US large-cap equities plus Singapore large-cap equities.",
        "Total-return index levels when sourced; USD is converted to the reporting currency using sourced FX.",
        "Index levels may require a licensed data source; linked index products can have separate fees and availability.",
        "Two-country equity blend; US concentration remains material.",
        ("Keeps the existing 75/25 default.", "Includes explicit Singapore exposure."),
        ("Not globally diversified.", "Equity losses remain possible."),
        ("S&P Dow Jones Indices", "FTSE Russell"),
    ),
    BenchmarkTemplate(
        "global-equity",
        "Global equity",
        (
            BenchmarkComponent(
                "GLOBAL:ACWI",
                "MSCI ACWI Index",
                Currency.USD,
                "1",
                "https://www.msci.com/indexes/index/892400/msci-acwi-index",
            ),
        ),
        "Large- and mid-cap equities across developed and emerging markets.",
        "MSCI net total return index series when available; USD reporting basis before profile FX conversion.",
        "Index data can be licensed; linked ETFs have issuer fees and exchange/region availability constraints.",
        "Broad country and issuer coverage, but market-cap weighting can concentrate exposure.",
        ("Broader geography than the core template.", "Single sourced global reference series."),
        ("Currency and equity-market risk remain.", "Not a capital-preservation reference."),
        ("MSCI",),
    ),
    BenchmarkTemplate(
        "global-reit",
        "Global listed real estate",
        (
            BenchmarkComponent(
                "GLOBAL:EPRA_NAREIT_DEVELOPED",
                "FTSE EPRA Nareit Developed Index",
                Currency.USD,
                "1",
                "https://research.ftserussell.com/Analytics/FactSheets/temp/aad58f07-6527-411d-a871-99f09b77afa4.pdf",
            ),
        ),
        "Developed-market listed real estate companies and REITs.",
        "USD total-return index series when available.",
        "Index data can be licensed; listed real-estate fund costs and availability vary by issuer and market.",
        "Global real-estate sector exposure; less diversified than a broad-equity index.",
        ("Makes property-sector exposure explicit.", "Uses an index-provider total-return methodology."),
        ("Sector concentration can be high.", "Interest-rate sensitivity remains material."),
        ("FTSE Russell", "EPRA", "Nareit"),
    ),
    BenchmarkTemplate(
        "us-dividend",
        "US dividend growth",
        (
            BenchmarkComponent(
                "US:VIG",
                "Vanguard Dividend Appreciation ETF",
                Currency.USD,
                "1",
                "https://investor.vanguard.com/investment-products/etfs/profile/vig",
            ),
        ),
        "US companies selected through the S&P U.S. Dividend Growers methodology, represented by an ETF reference.",
        "ETF total return, including distributions, when sourced.",
        "Vanguard lists a 0.04% expense ratio; availability and tax treatment vary by account, venue, and region.",
        "US dividend-growth equity exposure; not a broad global or bond reference.",
        ("Makes dividend-growth methodology explicit.", "Issuer publishes fund facts and expenses."),
        ("No dividend or return outcome is guaranteed.", "US equity and sector concentration remain."),
        ("Vanguard",),
    ),
    BenchmarkTemplate(
        "us-bond-core",
        "US aggregate bonds",
        (
            BenchmarkComponent(
                "US:AGG",
                "iShares Core U.S. Aggregate Bond ETF",
                Currency.USD,
                "1",
                "https://www.ishares.com/us/products/239458/ishares-core-us-aggregate-bond-etf",
            ),
        ),
        "US investment-grade aggregate-bond exposure, represented by an ETF reference.",
        "ETF total return, including distributions, when sourced.",
        "iShares lists a 0.03% expense ratio; availability, duration risk, and tax treatment vary by user and venue.",
        "Many investment-grade bond holdings; interest-rate and credit exposure remain.",
        ("Provides a lower-equity-risk comparison.", "Issuer publishes holdings, fee, and benchmark details."),
        ("Not cash and not capital guaranteed.", "USD and interest-rate risk remain."),
        ("iShares", "BlackRock"),
    ),
)


def list_templates() -> tuple[BenchmarkTemplate, ...]:
    return _TEMPLATES


def get_template(identifier: str) -> BenchmarkTemplate:
    normalized = identifier.strip().lower()
    for template in _TEMPLATES:
        if template.identifier == normalized:
            return template
    raise ValueError("benchmark template is not available")
