"""People who can sign in to the signed-in user's own college."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import ROLES, CurrentUser, coordinator_only, get_db
from ..db import Database
from .auth import EMAIL

router = APIRouter(prefix="/api/users", tags=["accounts"])


@router.get("")
def list_users(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    return {"users": [{"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"], "role_label": ROLES.get(u["role"], u["role"]),
                       "teacher": u["teacher_id"], "dept": u["dept_id"], "you": u["id"] == user.id}
                      for u in db.list_users(user.college_id)]}


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    role: Literal["coordinator", "hod", "teacher"] = "coordinator"
    teacher: str | None = None  # for a teacher account: which teacher in the college data
    dept: str | None = None     # for a head of department: which department


@router.post("", status_code=status.HTTP_201_CREATED)
def add_user(body: NewUser, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Add a coordinator or a teacher to the same college. They sign in with this temporary password."""
    email = body.email.strip().lower()
    if db.find_user_by_email(email):
        raise HTTPException(409, "Someone already uses that email.")
    teacher_id = dept_id = None
    data = db.get_college_data(user.college_id) or {}
    if body.role == "hod":
        if not any(d["id"] == body.dept for d in data.get("departments", [])):
            raise HTTPException(422, "Choose which department they head.")
        dept_id = body.dept
    if body.role == "teacher":
        teachers = data.get("teachers", [])
        if not any(t["id"] == body.teacher for t in teachers):
            raise HTTPException(422, "Choose which teacher this account is for.")
        if any(u["teacher_id"] == body.teacher for u in db.list_users(user.college_id)):
            raise HTTPException(409, "That teacher already has an account.")
        teacher_id = body.teacher
    new_id = db.add_user(email, body.name.strip(), body.role, user.college_id, body.password, teacher_id, dept_id)
    return {"id": new_id, "message": f"{body.name.strip()} can now sign in with {email}."}


@router.delete("/{user_id}")
def remove_user(user_id: int, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    if user_id == user.id:
        raise HTTPException(400, "You can't remove your own account.")
    if not db.delete_user(user.college_id, user_id):
        raise HTTPException(404, "That person wasn't found.")
    return {"removed": user_id}
