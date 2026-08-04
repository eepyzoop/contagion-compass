import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://contagion:contagion@localhost:5432/contagion_compass",
)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_engine():
    # pool_pre_ping: a long LLM turn can leave a pooled connection idle long
    # enough for RDS/network NAT to drop it; this pings and transparently
    # reconnects instead of raising on the next query.
    return create_engine(DATABASE_URL, pool_pre_ping=True)


def init_schema(engine=None):
    engine = engine or get_engine()
    schema_sql = SCHEMA_PATH.read_text()
    # Strip "--" line comments before splitting on ";" -- a comment containing
    # a literal semicolon (e.g. "-- ... now; state/province later") would
    # otherwise fragment a statement mid-way.
    schema_sql = re.sub(r"--[^\n]*", "", schema_sql)
    with engine.begin() as conn:
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
