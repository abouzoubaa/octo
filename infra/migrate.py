"""Run: `python infra/migrate.py` (or the `cci-migrate` console script)."""
from cci_core.bootstrap import init_db

if __name__ == "__main__":
    init_db()
