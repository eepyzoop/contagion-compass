"""
WHO Disease Outbreak News (DON) -- WHO's official outbreak bulletin feed,
used by Phase 7's check_outbreak_news tool to corroborate or explain away a
statistical anomaly with real-world outbreak reporting.

Confirmed live 2026-08-21 via WHO's public OData JSON API. The older RSS
feed (www.who.int/feeds/entity/csr/don/en/rss.xml) is dead (404) -- same
"verify before building" lesson as the PAHO PLISA investigation in Phase 2a.
The API supports OData $filter/$orderby/$top; filtering server-side by
Title (WHO's titles are like "Dengue - Brazil") avoids pulling and
LLM-scanning the entire DON archive for every check.
"""

import html
import re

import requests

API_URL = "https://www.who.int/api/news/diseaseoutbreaknews"
ARTICLE_URL = "https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}"


def _country_name(region: str) -> str:
    """region is e.g. 'BRAZIL-RIO_DE_JANEIRO' or 'MEXICO' -- WHO DON titles
    use country names, not our region codes, so this strips down to the
    country component for filtering."""
    return region.split("-")[0].replace("_", " ").title()


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def fetch_recent_don(disease: str, region: str, limit: int = 3) -> list[dict]:
    """Most recent WHO DON articles whose title mentions both the disease
    and the region's country. Returns [] if none found -- not an error,
    just means WHO hasn't published a bulletin matching this disease/country."""
    country = _country_name(region)
    odata_filter = f"contains(Title,'{disease.title()}') and contains(Title,'{country}')"
    resp = requests.get(
        API_URL,
        params={"$top": limit, "$orderby": "PublicationDate desc", "$filter": odata_filter},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("value", [])
    return [
        {
            "title": item["Title"],
            "published": item["PublicationDate"],
            "url": ARTICLE_URL.format(url_name=item["UrlName"]),
            "overview": _strip_html(item.get("Overview")),
            "assessment": _strip_html(item.get("Assessment")),
        }
        for item in items
    ]


if __name__ == "__main__":
    articles = fetch_recent_don("dengue", "BRAZIL")
    print(f"Found {len(articles)} article(s)")
    for a in articles:
        print(f"  {a['published']} - {a['title']} - {a['url']}")
