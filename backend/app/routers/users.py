"""People who can sign in to the signed-in user's own college."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user, get_db
from ..db import Database
from .auth import EMAIL

router = APIRouter(prefix="/api/users", tags=["accounts"])


@router.get("")
def list_users(user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    return {"users": [{"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"], "you": u["id"] == user.id}
                      for u in db.list_users(user.college_id)]}


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str = Field(min_length=8, max_length=200)


@router.post("", status_code=status.HTTP_201_CREATED)
def add_user(body: NewUser, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    """Add another timetable coordinator to the same college. They sign in with this temporary password."""
    email = body.email.strip().lower()
    if db.find_user_by_email(email):
        raise HTTPException(409, "Someone already uses that email.")
    new_id = db.add_user(email, body.name.strip(), "coordinator", user.college_id, body.password)
    return {"id": new_id, "message": f"{body.name.strip()} can now sign in with {email}."}


@router.delete("/{user_id}")
def remove_user(user_id: int, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    if user_id == user.id:
        raise HTTPException(400, "You can't remove your own account.")
    if not db.delete_user(user.college_id, user_id):
        raise HTTPException(404, "That person wasn't found.")
    return {"removed": user_id}
