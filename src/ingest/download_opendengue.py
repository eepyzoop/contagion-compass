"""
Pulls dengue surveillance data from OpenDengue (https://opendengue.org), a
public, standardised global dengue case-count database (Clarke et al. 2024,
Scientific Data). No API is offered; the project publishes versioned CSV
extracts as zip files on GitHub.

We use the "National_extract" file (their "best national estimate": one
clean row per country per reporting period, already resolved to national
(Admin0) spatial resolution) rather than the much larger "Temporal_extract"
(which mixes national and subnational rows at whatever resolution each
source reported at). National_extract is what Phase 1 needs; subnational
(Admin1/state-level) data can be pulled from Temporal_extract later once the
national pipeline is working end-to-end.

Countries and date window were chosen by inspecting the raw data (see
project notes): Brazil and Mexico both report weekly, Admin0-level,
"Total" case counts with no significant gaps across 2014-2023 (Vietnam
was considered but dropped -- only ~half of its possible weekly reports
are present in that window). 2014-2023 is the widest common window that
is clean and gap-free across both countries.

The Philippines was considered too, but OpenDengue only has ~2 years of
national weekly "Total" data for it (2022-2023) -- not enough history to
ever satisfy the 3-year minimum baseline window in stats.py, so it's
excluded for now. Worth revisiting if OpenDengue backfills more history.
"""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

OPENDENGUE_VERSION = "V1.3"
NATIONAL_EXTRACT_URL = (
    "https://github.com/OpenDengue/master-repo/raw/main/data/releases/"
    f"{OPENDENGUE_VERSION}/National_extract_{OPENDENGUE_VERSION.replace('.', '_')}.zip"
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

# adm_0_name values as they appear in OpenDengue
COUNTRIES = ["BRAZIL", "MEXICO"]
WINDOW_START = "2014-01-01"
WINDOW_END = "2023-12-31"

DISEASE = "dengue"
METRIC = "reported_cases"
SOURCE = f"OpenDengue-{OPENDENGUE_VERSION}"


def download_national_extract(dest_dir: Path = DATA_DIR) -> Path:
    """Downloads and extracts the OpenDengue National_extract CSV, returns its path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    csv_name = f"National_extract_{OPENDENGUE_VERSION.replace('.', '_')}.csv"
    csv_path = dest_dir / csv_name

    if csv_path.exists():
        return csv_path

    resp = requests.get(NATIONAL_EXTRACT_URL, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(dest_dir)

    return csv_path


def load_clean_national_dengue(csv_path: Path = None) -> pd.DataFrame:
    """
    Loads the National_extract CSV and filters it down to the clean subset
    this project uses: our three countries, weekly resolution, "Total" case
    definition, within the chosen date window. Returns rows shaped to match
    the raw_readings table.
    """
    csv_path = csv_path or download_national_extract()
    df = pd.read_csv(csv_path, na_values=["NA"])

    df = df[
        df["adm_0_name"].isin(COUNTRIES)
        & (df["T_res"] == "Week")
        & (df["case_definition_standardised"] == "Total")
    ].copy()

    df["calendar_start_date"] = pd.to_datetime(df["calendar_start_date"])
    df["calendar_end_date"] = pd.to_datetime(df["calendar_end_date"])
    df = df[
        (df["calendar_start_date"] >= WINDOW_START)
        & (df["calendar_start_date"] <= WINDOW_END)
    ]

    out = pd.DataFrame(
        {
            "disease": DISEASE,
            "region": df["adm_0_name"],
            "country_iso3": df["ISO_A0"],
            "metric": METRIC,
            "period_start": df["calendar_start_date"].dt.date,
            "period_end": df["calendar_end_date"].dt.date,
            "resolution": "week",
            "value": df["dengue_total"].astype(float),
            "source": SOURCE,
        }
    )

    return out.sort_values(["region", "period_start"]).reset_index(drop=True)


if __name__ == "__main__":
    data = load_clean_national_dengue()
    out_path = DATA_DIR / "dengue_national_clean.csv"
    data.to_csv(out_path, index=False)
    print(f"Wrote {len(data)} rows to {out_path}")
    print(data.groupby("region")["period_start"].agg(["min", "max", "count"]))
