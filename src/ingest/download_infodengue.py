"""
Pulls dengue surveillance data for a single Brazilian municipality from
InfoDengue (https://info.dengue.mat.br), a public nowcasting/surveillance
API for Brazil run by Fiocruz/UFMG researchers.

This replaces the originally-planned PAHO PLISA source for "current week"
data: PAHO's web portal (www.paho.org, opendata.paho.org) blocks automated
requests entirely (HTTP 403), its older www3.paho.org/data indicator
portal returns 502 Bad Gateway, and even CMU's Delphi Epidata project --
which scraped this same PAHO dengue portal -- marks its feed inactive
since 2020w31. InfoDengue is live, documented, and genuinely updates
weekly during dengue season.

Trade-off: InfoDengue is municipality-level only (no national/state
aggregate endpoint), so it can't be blended with OpenDengue's national
Brazil counts. Instead it stands on its own as a second, city-scoped
region: both its historical baseline AND its "current week" reading come
from InfoDengue itself, so nothing is mixed across sources.

We use `casos_est` (the nowcast-corrected estimate, adjusting for
reporting delay) rather than raw `casos`, since the whole point of a
"current week" reading is that it should reflect the platform's best
estimate of what's actually happening, not an artificially low count
because this week's reports haven't all arrived yet.
"""

import pandas as pd
import requests

API_URL = "https://info.dengue.mat.br/api/alertcity"

CITY_GEOCODE = 3304557  # Rio de Janeiro (IBGE municipality code)
CITY_NAME = "Rio de Janeiro"
REGION = "BRAZIL-RIO_DE_JANEIRO"
COUNTRY_ISO3 = "BRA"

# Other major cities the Phase 3 agent can cross-reference for spatial
# context ("is this just Rio, or showing up elsewhere too?"). Same
# alertcity endpoint, just a different geocode -- see context.md's
# "knock-on effects of switching to city-level data".
REGION_GEOCODES = {
    REGION: CITY_GEOCODE,
    "BRAZIL-SAO_PAULO": 3550308,
    "BRAZIL-BELO_HORIZONTE": 3106200,
    "BRAZIL-BRASILIA": 5300108,
}

DISEASE = "dengue"
METRIC = "estimated_cases"
SOURCE = "InfoDengue"

HISTORY_START_YEAR = 2010


def _fetch(geocode: int, ey_start: int, ey_end: int) -> pd.DataFrame:
    resp = requests.get(
        API_URL,
        params={
            "geocode": geocode,
            "disease": DISEASE,
            "format": "json",
            "ew_start": 1,
            "ew_end": 53,
            "ey_start": ey_start,
            "ey_end": ey_end,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return pd.DataFrame(resp.json())


def _to_raw_readings_shape(df: pd.DataFrame) -> pd.DataFrame:
    period_start = pd.to_datetime(df["data_iniSE"], unit="ms")
    out = pd.DataFrame(
        {
            "disease": DISEASE,
            "region": REGION,
            "country_iso3": COUNTRY_ISO3,
            "metric": METRIC,
            "period_start": period_start.dt.date,
            "period_end": (period_start + pd.Timedelta(days=6)).dt.date,
            "resolution": "week",
            "value": df["casos_est"].astype(float),
            "source": SOURCE,
        }
    )
    return out.sort_values("period_start").reset_index(drop=True)


def load_clean_infodengue_history(
    geocode: int = CITY_GEOCODE,
    start_year: int = HISTORY_START_YEAR,
    end_year: int = None,
) -> pd.DataFrame:
    """
    Full historical pull for baseline-building. Meant to be run
    occasionally (every ~6 months is plenty -- baselines don't need to
    change weekly), not on every agent run.
    """
    end_year = end_year or pd.Timestamp.today().year
    df = _fetch(geocode, start_year, end_year)
    return _to_raw_readings_shape(df)


def fetch_latest_week(geocode: int = CITY_GEOCODE) -> pd.DataFrame:
    """
    Pulls just the most recent epidemiological week available -- this is
    what the weekly check should call, not the full history pull.
    """
    today = pd.Timestamp.today()
    df = _fetch(geocode, today.year - 1, today.year)  # covers year boundary
    return _to_raw_readings_shape(df).tail(1).reset_index(drop=True)


def fetch_latest_week_raw(geocode: int) -> dict:
    """
    Live pull of the most recent InfoDengue week for a city, keeping fields
    the raw_readings pipeline discards (climate, Rt, InfoDengue's own alert
    level, confidence interval on the estimate). Used by the Phase 3 agent's
    cross-referencing tools directly -- not persisted to the DB, since these
    are read live at decision time rather than baselined.
    """
    today = pd.Timestamp.today()
    df = _fetch(geocode, today.year - 1, today.year)
    if df.empty:
        return {}
    row = df.sort_values("data_iniSE").iloc[-1]

    def _num(field):
        val = row.get(field)
        return float(val) if pd.notna(val) else None

    return {
        "period_start": str(pd.to_datetime(row["data_iniSE"], unit="ms").date()),
        "estimated_cases": _num("casos_est"),
        "estimated_cases_range": [_num("casos_est_min"), _num("casos_est_max")],
        "temp_avg_c": _num("tempmed"),
        "humidity_avg_pct": _num("umidmed"),
        "rt": _num("Rt"),
        "alert_level": int(row["nivel"]) if pd.notna(row.get("nivel")) else None,  # 1-4 scale, see docstring
    }


if __name__ == "__main__":
    history = load_clean_infodengue_history()
    print(f"Pulled {len(history)} weekly rows for {CITY_NAME} ({REGION})")
    print(history.tail())
