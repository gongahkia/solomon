from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import requests

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text


@dataclass(frozen=True)
class InsiderTransaction:
    """Represents an insider transaction from SEC Form 4."""

    filing_date: date
    ticker: str
    insider_name: str
    insider_title: str
    transaction_type: str  # buy, sell, gift
    shares: float
    price_per_share: float | None
    total_value: float | None
    shares_owned_after: float | None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "filing_date": self.filing_date.isoformat(),
            "ticker": self.ticker,
            "insider_name": self.insider_name,
            "insider_title": self.insider_title,
            "transaction_type": self.transaction_type,
            "shares": self.shares,
            "price_per_share": self.price_per_share,
            "total_value": self.total_value,
            "shares_owned_after": self.shares_owned_after,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InsiderTransaction:
        """Create from dictionary."""
        return cls(
            filing_date=date.fromisoformat(data["filing_date"]),
            ticker=data["ticker"],
            insider_name=data["insider_name"],
            insider_title=data["insider_title"],
            transaction_type=data["transaction_type"],
            shares=data["shares"],
            price_per_share=data.get("price_per_share"),
            total_value=data.get("total_value"),
            shares_owned_after=data.get("shares_owned_after"),
        )


def parse_form4_xml(xml_content: str, ticker: str) -> list[InsiderTransaction]:
    """Parse SEC Form 4 XML content.

    Args:
        xml_content: Raw XML content from SEC EDGAR
        ticker: Stock ticker

    Returns:
        List of InsiderTransaction objects
    """
    transactions: list[InsiderTransaction] = []

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    # Get reporting owner info
    owner_name = ""
    owner_title = ""

    for owner in root.findall(".//reportingOwner"):
        name_elem = owner.find(".//rptOwnerName")
        if name_elem is not None and name_elem.text:
            owner_name = name_elem.text.strip()

        title_elem = owner.find(".//officerTitle")
        if title_elem is not None and title_elem.text:
            owner_title = title_elem.text.strip()

        # Also check relationship
        if not owner_title:
            rel = owner.find(".//reportingOwnerRelationship")
            if rel is not None:
                if rel.find(".//isDirector") is not None:
                    owner_title = "Director"
                elif rel.find(".//isOfficer") is not None:
                    owner_title = "Officer"
                elif rel.find(".//isTenPercentOwner") is not None:
                    owner_title = "10% Owner"

    # Get filing date
    filing_date_elem = root.find(".//periodOfReport")
    if filing_date_elem is None or not filing_date_elem.text:
        return []

    try:
        filing_date = datetime.strptime(filing_date_elem.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return []

    # Parse non-derivative transactions
    for trans in root.findall(".//nonDerivativeTransaction"):
        try:
            shares_elem = trans.find(".//transactionShares/value")
            shares = float(shares_elem.text) if shares_elem is not None and shares_elem.text else 0

            price_elem = trans.find(".//transactionPricePerShare/value")
            price = float(price_elem.text) if price_elem is not None and price_elem.text else None

            code_elem = trans.find(".//transactionAcquiredDisposedCode/value")
            trans_code = code_elem.text.strip() if code_elem is not None and code_elem.text else ""

            # A = acquired, D = disposed
            if trans_code == "A":
                trans_type = "buy"
            elif trans_code == "D":
                trans_type = "sell"
            else:
                trans_type = "other"

            total_value = shares * price if price else None

            owned_elem = trans.find(".//sharesOwnedFollowingTransaction/value")
            owned = float(owned_elem.text) if owned_elem is not None and owned_elem.text else None

            transactions.append(
                InsiderTransaction(
                    filing_date=filing_date,
                    ticker=ticker,
                    insider_name=owner_name,
                    insider_title=owner_title,
                    transaction_type=trans_type,
                    shares=shares,
                    price_per_share=price,
                    total_value=total_value,
                    shares_owned_after=owned,
                )
            )
        except (ValueError, TypeError):
            continue

    return transactions


def fetch_insider_transactions(ticker: str, days: int = 90) -> list[InsiderTransaction]:
    """Fetch insider transactions for a ticker from SEC EDGAR.

    Note: This is a simplified implementation. The full SEC EDGAR API
    requires more complex handling.

    Args:
        ticker: Stock ticker
        days: Number of days to look back

    Returns:
        List of InsiderTransaction objects
    """
    cache_dir = default_cache_dir()
    cache_key = f"insider:{ticker.upper()}:{days}"
    ttl_seconds = 6 * 3600  # 6 hours

    cached = load_cached_text(cache_dir, cache_key, ttl_seconds=ttl_seconds)
    if cached:
        try:
            data = json.loads(cached)
            return [InsiderTransaction.from_dict(t) for t in data]
        except Exception:
            pass

    # SEC EDGAR full-text search API
    base_url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": f'formType:"4" AND "{ticker.upper()}"',
        "dateRange": "custom",
        "startdt": (datetime.now().date().replace(day=1)).isoformat(),
        "enddt": datetime.now().date().isoformat(),
        "forms": "4",
    }

    transactions: list[InsiderTransaction] = []

    try:
        # Note: SEC EDGAR API may require specific headers
        headers = {
            "User-Agent": "stonks-cli/0.1.0 (educational purposes)",
            "Accept": "application/json",
        }

        resp = requests.get(base_url, params=params, headers=headers, timeout=30)

        if resp.status_code == 200:
            data = resp.json()
            # Parse results and fetch individual filings
            # This is simplified - full implementation would need more work
            hits = data.get("hits", {}).get("hits", [])

            for hit in hits[:20]:  # Limit to 20 filings
                source = hit.get("_source", {})
                filing_url = source.get("file_url")

                if filing_url:
                    try:
                        xml_resp = requests.get(filing_url, headers=headers, timeout=15)
                        if xml_resp.status_code == 200:
                            parsed = parse_form4_xml(xml_resp.text, ticker.upper())
                            transactions.extend(parsed)
                    except Exception:
                        continue

    except Exception:
        # Return empty list if API fails
        pass

    # Sort by date descending
    transactions.sort(key=lambda t: t.filing_date, reverse=True)

    # Cache results
    save_cached_text(cache_dir, cache_key, json.dumps([t.to_dict() for t in transactions]))

    return transactions


def calculate_insider_sentiment(transactions: list[InsiderTransaction], days: int = 30) -> dict[str, Any]:
    """Calculate insider sentiment from recent transactions.

    Args:
        transactions: List of InsiderTransaction objects
        days: Number of days to analyze

    Returns:
        Dictionary with sentiment metrics
    """
    cutoff = date.today()
    cutoff = cutoff.replace(day=max(1, cutoff.day - days))

    recent = [t for t in transactions if t.filing_date >= cutoff]

    buy_count = 0
    sell_count = 0
    net_shares = 0.0
    notable_buyers: list[str] = []
    notable_sellers: list[str] = []

    for t in recent:
        if t.transaction_type == "buy":
            buy_count += 1
            net_shares += t.shares
            if t.total_value and t.total_value > 100000:
                notable_buyers.append(t.insider_name)
        elif t.transaction_type == "sell":
            sell_count += 1
            net_shares -= t.shares
            if t.total_value and t.total_value > 100000:
                notable_sellers.append(t.insider_name)

    return {
        "net_shares": net_shares,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "notable_buyers": list(set(notable_buyers)),
        "notable_sellers": list(set(notable_sellers)),
    }
