from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text


@dataclass(frozen=True)
class NewsItem:
    """Represents a news article."""

    title: str
    url: str
    source: str
    published_date: datetime | None
    sentiment_score: float  # -1 to 1
    ticker_relevance: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "sentiment_score": self.sentiment_score,
            "ticker_relevance": self.ticker_relevance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NewsItem:
        """Create from dictionary."""
        pub_date = None
        if data.get("published_date"):
            try:
                pub_date = datetime.fromisoformat(data["published_date"])
            except Exception:
                pass

        return cls(
            title=data["title"],
            url=data["url"],
            source=data["source"],
            published_date=pub_date,
            sentiment_score=data.get("sentiment_score", 0.0),
            ticker_relevance=data.get("ticker_relevance", 1.0),
        )


# Sentiment keywords
POSITIVE_WORDS = {
    "surge", "jump", "beat", "profit", "growth", "upgrade", "soar", "rally",
    "gain", "rise", "up", "bullish", "strong", "record", "outperform",
    "exceed", "boost", "win", "success", "breakthrough",
}

NEGATIVE_WORDS = {
    "fall", "drop", "miss", "loss", "decline", "downgrade", "plunge", "crash",
    "sink", "down", "bearish", "weak", "cut", "underperform", "layoff",
    "warning", "concern", "risk", "fail", "trouble",
}


def score_headline_sentiment(title: str) -> float:
    """Calculate sentiment score for a headline.

    Args:
        title: Headline text

    Returns:
        Score from -1 to 1
    """
    if not title:
        return 0.0

    title_lower = title.lower()
    words = set(title_lower.split())

    score = 0.0
    for word in words:
        # Clean word of punctuation
        clean_word = "".join(c for c in word if c.isalpha())
        if clean_word in POSITIVE_WORDS:
            score += 0.1
        elif clean_word in NEGATIVE_WORDS:
            score -= 0.1

    # Clamp to [-1, 1]
    return max(-1.0, min(1.0, score))


def _parse_rss_date(date_str: str) -> datetime | None:
    """Parse various RSS date formats."""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except Exception:
            continue

    return None


def fetch_news_rss(ticker: str, sources: list[str] | None = None) -> list[NewsItem]:
    """Fetch news from RSS feeds.

    Args:
        ticker: Stock ticker
        sources: Optional list of sources to use

    Returns:
        List of NewsItem objects
    """
    cache_dir = default_cache_dir()
    cache_key = f"news:{ticker.upper()}"
    ttl_seconds = 30 * 60  # 30 minutes

    cached = load_cached_text(cache_dir, cache_key, ttl_seconds=ttl_seconds)
    if cached:
        try:
            data = json.loads(cached)
            return [NewsItem.from_dict(n) for n in data]
        except Exception:
            pass

    items: list[NewsItem] = []
    base_ticker = ticker.split(".")[0].upper()

    # Google News RSS
    try:
        google_url = f"https://news.google.com/rss/search?q={quote(base_ticker)}+stock&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(google_url, timeout=15, headers={"User-Agent": "stonks-cli/0.1.0"})
        if resp.status_code == 200:
            root = ET.fromstring(resp.text)
            for item in root.findall(".//item")[:20]:
                title_elem = item.find("title")
                link_elem = item.find("link")
                pub_elem = item.find("pubDate")

                if title_elem is not None and link_elem is not None:
                    title = title_elem.text or ""
                    link = link_elem.text or ""
                    pub_date = _parse_rss_date(pub_elem.text) if pub_elem is not None and pub_elem.text else None

                    items.append(
                        NewsItem(
                            title=title,
                            url=link,
                            source="Google News",
                            published_date=pub_date,
                            sentiment_score=score_headline_sentiment(title),
                        )
                    )
    except Exception:
        pass

    # Sort by date descending
    items.sort(key=lambda i: i.published_date or datetime.min, reverse=True)

    # Cache results
    save_cached_text(cache_dir, cache_key, json.dumps([n.to_dict() for n in items]))

    return items


def aggregate_news_sentiment(items: list[NewsItem], hours: int = 24) -> dict[str, Any]:
    """Aggregate sentiment from recent news.

    Args:
        items: List of NewsItem objects
        hours: Number of hours to look back

    Returns:
        Dictionary with sentiment metrics
    """
    cutoff = datetime.now() - timedelta(hours=hours)

    recent = [i for i in items if i.published_date and i.published_date >= cutoff]

    if not recent:
        recent = items[:10]  # Use latest 10 if no recent items

    if not recent:
        return {
            "avg_sentiment": 0.0,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
        }

    positive_count = sum(1 for i in recent if i.sentiment_score > 0.2)
    negative_count = sum(1 for i in recent if i.sentiment_score < -0.2)
    neutral_count = len(recent) - positive_count - negative_count

    avg_sentiment = sum(i.sentiment_score for i in recent) / len(recent)

    return {
        "avg_sentiment": avg_sentiment,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": neutral_count,
    }
