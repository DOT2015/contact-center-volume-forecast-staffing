import json
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def con():
    db = ROOT / "data" / "warehouse.duckdb"
    if not db.exists():
        pytest.skip("run `make all` first")
    c = duckdb.connect(str(db), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="session")
def truth():
    return json.loads((ROOT / "data" / "truth" / "planted_effects.json").read_text())


@pytest.fixture(scope="session")
def results():
    return json.loads((ROOT / "reports" / "results.json").read_text())


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]
