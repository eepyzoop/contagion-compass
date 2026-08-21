"""
Checks src.ingest.who_don's pure helpers and fetch_recent_don's response
parsing, without hitting the real WHO API.

Usage:
    python -m tests.test_who_don
"""

import src.ingest.who_don as who_don


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_country_name_strips_city_suffix():
    assert who_don._country_name("BRAZIL-RIO_DE_JANEIRO") == "Brazil"
    assert who_don._country_name("MEXICO") == "Mexico"


def test_strip_html_removes_tags_and_unescapes_entities():
    raw = "<p>Cases rose &amp; spread <b>quickly</b>.</p>"
    assert who_don._strip_html(raw) == "Cases rose & spread  quickly ."


def test_fetch_recent_don_maps_fields(monkeypatch):
    payload = {
        "value": [
            {
                "Title": "Dengue - Brazil",
                "PublicationDate": "2024-03-13T21:37:50Z",
                "UrlName": "2002DON183",
                "Overview": "<p>Cases have risen.</p>",
                "Assessment": "<p>Risk is moderate.</p>",
            }
        ]
    }
    monkeypatch.setattr(who_don.requests, "get", lambda *a, **k: _FakeResponse(payload))
    articles = who_don.fetch_recent_don("dengue", "BRAZIL")
    assert len(articles) == 1
    assert articles[0]["title"] == "Dengue - Brazil"
    assert articles[0]["url"] == "https://www.who.int/emergencies/disease-outbreak-news/item/2002DON183"
    assert "risen" in articles[0]["overview"]


def test_fetch_recent_don_returns_empty_list_when_no_matches(monkeypatch):
    monkeypatch.setattr(who_don.requests, "get", lambda *a, **k: _FakeResponse({"value": []}))
    assert who_don.fetch_recent_don("dengue", "NOWHERE") == []


if __name__ == "__main__":
    class _Monkeypatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_country_name_strips_city_suffix()
    test_strip_html_removes_tags_and_unescapes_entities()
    test_fetch_recent_don_maps_fields(_Monkeypatch())
    test_fetch_recent_don_returns_empty_list_when_no_matches(_Monkeypatch())
    print("ok")
