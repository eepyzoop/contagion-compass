"""
Checks fetch_latest_week_raw's field extraction (picks the latest week,
maps InfoDengue's raw column names, handles missing/NaN values) without
hitting the real API.

Usage:
    python -m tests.test_infodengue_climate
"""

import pandas as pd

import src.ingest.download_infodengue as di


def _fake_fetch(rows):
    def fetch(geocode, ey_start, ey_end):
        return pd.DataFrame(rows)

    return fetch


def test_picks_latest_week_and_maps_fields(monkeypatch):
    rows = [
        {
            "data_iniSE": pd.Timestamp("2026-06-14").value // 10**6,
            "casos_est": 200.0, "casos_est_min": 180.0, "casos_est_max": 220.0,
            "tempmed": 28.0, "umidmed": 70.0, "Rt": 1.1, "nivel": 2,
        },
        {
            "data_iniSE": pd.Timestamp("2026-06-21").value // 10**6,
            "casos_est": 294.5, "casos_est_min": 260.0, "casos_est_max": 330.0,
            "tempmed": 27.5, "umidmed": 72.0, "Rt": 1.4, "nivel": 3,
        },
    ]
    monkeypatch.setattr(di, "_fetch", _fake_fetch(rows))
    result = di.fetch_latest_week_raw(3304557)
    assert result["period_start"] == "2026-06-21"
    assert result["estimated_cases"] == 294.5
    assert result["estimated_cases_range"] == [260.0, 330.0]
    assert result["temp_avg_c"] == 27.5
    assert result["alert_level"] == 3


def test_handles_missing_fields():
    rows = [
        {
            "data_iniSE": pd.Timestamp("2026-06-21").value // 10**6,
            "casos_est": 100.0, "casos_est_min": None, "casos_est_max": None,
            "tempmed": None, "umidmed": None, "Rt": None, "nivel": None,
        }
    ]
    di._fetch = _fake_fetch(rows)
    result = di.fetch_latest_week_raw(3304557)
    assert result["temp_avg_c"] is None
    assert result["alert_level"] is None


def test_empty_response_returns_empty_dict():
    di._fetch = lambda geocode, ey_start, ey_end: pd.DataFrame()
    assert di.fetch_latest_week_raw(3304557) == {}


if __name__ == "__main__":
    class _Monkeypatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_picks_latest_week_and_maps_fields(_Monkeypatch())
    test_handles_missing_fields()
    test_empty_response_returns_empty_dict()
    print("ok")
