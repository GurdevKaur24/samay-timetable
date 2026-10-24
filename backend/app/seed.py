"""Load the seed colleges and their demo accounts into the database.

    python -m app.seed            # add anything missing
    python -m app.seed --reset    # delete the database file first, then seed
"""

import argparse
import json
from pathlib import Path

from solver.college import load_college, seed_college_ids

from .config import DB_PATH
from .db import Database
from .schema import CollegeData

DEMO_USERS = Path(__file__).resolve().parent.parent / "data" / "demo_users.json"


def seed(db: Database) -> list[str]:
    added = []
    with db.connect() as conn:
        existing = {r["id"] for r in conn.execute("SELECT id FROM colleges")}
    for college_id in seed_college_ids():
        if college_id in existing:
            continue
        data = CollegeData.model_validate(load_college(college_id)).model_dump(mode="json", exclude_none=True)
        db.add_college(college_id, data["name"], data)
        added.append(college_id)
    for u in json.loads(DEMO_USERS.read_text(encoding="utf-8"))["users"]:
        if db.find_user_by_email(u["email"]) is None and db.get_college_data(u["college"]) is not None:
            db.add_user(u["email"], u["name"], u["role"], u["college"], u["password"], u.get("teacher"), u.get("dept"))
    return added


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete the database first")
    args = parser.parse_args()
    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
    print("Added:", seed(Database(DB_PATH)) or "nothing new")
