"""The signed-in user's own college. There is deliberately no way to name a college here: it always comes from the
session, so one college can never ask for another's data."""

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CurrentUser, current_user, get_db
from ..db import Database

router = APIRouter(prefix="/api/college", tags=["college"])

COUNTED = ["departments", "courses", "sections", "teachers", "subjects", "rooms", "assignments"]


def own_data(user: CurrentUser, db: Database) -> dict:
    data = db.get_college_data(user.college_id)
    if data is None:
        raise HTTPException(404, "Your college's data couldn't be found.")
    return data


@router.get("")
def college_summary(user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    data = own_data(user, db)
    return {
        "name": data["name"], "place": data.get("place", ""), "term": data.get("term", ""), "kind": data.get("kind", ""),
        "scheme": data["scheme"],
        "counts": {k: len(data.get(k, [])) for k in COUNTED},
        "version": db.get_data_version(user.college_id),
    }


@router.get("/data")
def college_data(user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    return {"version": db.get_data_version(user.college_id), "data": own_data(user, db)}
