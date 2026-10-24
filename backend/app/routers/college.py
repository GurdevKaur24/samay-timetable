"""The signed-in user's own college. There is deliberately no way to name a college here: it always comes from the
session, so one college can never ask for another's data."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from ..auth import CurrentUser, coordinator_only, get_db
from ..db import Database
from ..schema import CollegeData

router = APIRouter(prefix="/api/college", tags=["college"])

COUNTED = ["departments", "courses", "sections", "teachers", "subjects", "rooms", "assignments"]


def own_data(user: CurrentUser, db: Database) -> dict:
    data = db.get_college_data(user.college_id)
    if data is None:
        raise HTTPException(404, "Your college's data couldn't be found.")
    return data


@router.get("")
def college_summary(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    data = own_data(user, db)
    return {
        "name": data["name"], "place": data.get("place", ""), "term": data.get("term", ""), "kind": data.get("kind", ""),
        "scheme": data["scheme"],
        "counts": {k: len(data.get(k, [])) for k in COUNTED},
        "version": db.get_data_version(user.college_id),
    }


@router.get("/data")
def college_data(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    return {"version": db.get_data_version(user.college_id), "data": own_data(user, db)}


class SaveData(BaseModel):
    version: int  # the version the page started from, so two people can't overwrite each other
    data: dict


def plain_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        where = " → ".join(str(p) for p in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        out.append(msg if err["type"] == "value_error" else f"{where}: {msg}")
    return out


@router.put("/data")
def save_college_data(body: SaveData, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Replace the signed-in user's college data after checking all of it. The college id always comes from the session."""
    conflict = "Someone else changed your college's data after you opened it. Reload to see the latest, then try again."
    if body.version != db.get_data_version(user.college_id):
        raise HTTPException(409, conflict)
    try:
        checked = CollegeData.model_validate({**body.data, "id": user.college_id})
    except ValidationError as e:
        raise HTTPException(422, {"message": "Your changes weren't saved.", "problems": plain_errors(e)})
    version = db.save_college_data(user.college_id, checked.model_dump(mode="json", exclude_none=True), expected_version=body.version)
    if version is None:  # someone saved between our check and our write
        raise HTTPException(409, conflict)
    return {"version": version}
