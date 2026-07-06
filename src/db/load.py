import pandas as pd
from sqlalchemy import text

from src.db.connection import get_engine, init_schema

UPSERT_SQL = text(
    """
    INSERT INTO raw_readings
        (disease, region, country_iso3, metric, period_start, period_end,
         resolution, value, source)
    VALUES
        (:disease, :region, :country_iso3, :metric, :period_start, :period_end,
         :resolution, :value, :source)
    ON CONFLICT (disease, region, metric, period_start, resolution, source)
    DO UPDATE SET value = EXCLUDED.value, period_end = EXCLUDED.period_end
    """
)


def load_readings(df: pd.DataFrame, engine=None) -> int:
    """Upserts a raw_readings-shaped DataFrame into Postgres. Returns row count loaded."""
    engine = engine or get_engine()
    init_schema(engine)

    records = df.to_dict(orient="records")
    with engine.begin() as conn:
        for record in records:
            conn.execute(UPSERT_SQL, record)

    return len(records)


if __name__ == "__main__":
    from src.ingest.download_opendengue import load_clean_national_dengue

    data = load_clean_national_dengue()
    n = load_readings(data)
    print(f"Loaded {n} readings into raw_readings")
