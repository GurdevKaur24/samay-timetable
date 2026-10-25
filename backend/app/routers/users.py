"""People who can sign in to the signed-in user's own college."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..auth import ROLES, CurrentUser, coordinator_only, get_db
from ..db import Database
from ..services.links import email_link, link_path
from .auth import EMAIL

router = APIRouter(prefix="/api/users", tags=["accounts"])


@router.get("")
def list_users(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    return {"users": [{"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"], "role_label": ROLES.get(u["role"], u["role"]),
                       "teacher": u["teacher_id"], "dept": u["dept_id"], "invited": bool(u["invited"]), "you": u["id"] == user.id}
                      for u in db.list_users(user.college_id)]}


class NewUser(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str | None = Field(None, min_length=8, max_length=200)  # leave out to send an invite link instead
    role: Literal["coordinator", "hod", "teacher"] = "coordinator"
    teacher: str | None = None  # for a teacher account: which teacher in the college data
    dept: str | None = None     # for a head of department: which department


def send(request: Request, db: Database, user: CurrentUser, person_id: int, kind: str, role: str = "") -> dict:
    """A new invite or reset link for one person of this college: emailed if possible, and always returned."""
    person = db.user_in_college(user.college_id, person_id)
    token = db.create_password_token(person_id, kind)
    emailed = email_link(request, kind, token, person["email"], person["name"], user.college_name, by=user.name, role=role)
    where = f"We emailed it to {person['email']}." if emailed else f"Send it to {person['name']} yourself (by email or message)."
    what = "invite link" if kind == "invite" else "link to choose a new password"
    return {"id": person_id, "link": link_path(kind, token), "emailed": emailed,
            "message": f"New {what} for {person['name']}. {where} It works once" + (", for 7 days." if kind == "invite" else ", for 1 hour.")}


@router.post("", status_code=status.HTTP_201_CREATED)
def add_user(body: NewUser, request: Request, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Add a coordinator, head of department or teacher to the same college: they get an invite link to choose their
    own password (or sign in with a temporary password, if one is given)."""
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
    if body.password:
        return {"id": new_id, "message": f"{body.name.strip()} can now sign in with {email}."}
    return send(request, db, user, new_id, "invite", ROLES[body.role])


@router.post("/{user_id}/invite")
def invite_again(user_id: int, request: Request, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """A fresh invite link for someone who hasn't joined yet (the old link stops working)."""
    person = db.user_in_college(user.college_id, user_id)
    if person is None:
        raise HTTPException(404, "That person wasn't found.")
    if not person["invited"]:
        raise HTTPException(409, f"{person['name']} has already set a password. Send a reset link instead.")
    return send(request, db, user, user_id, "invite")


@router.post("/{user_id}/reset-link")
def reset_link(user_id: int, request: Request, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """A link for someone of this college to choose a new password (e.g. they forgot it and email isn't set up)."""
    if db.user_in_college(user.college_id, user_id) is None:
        raise HTTPException(404, "That person wasn't found.")
    return send(request, db, user, user_id, "reset")


@router.delete("/{user_id}")
def remove_user(user_id: int, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    if user_id == user.id:
        raise HTTPException(400, "You can't remove your own account.")
    if not db.delete_user(user.college_id, user_id):
        raise HTTPException(404, "That person wasn't found.")
    return {"removed": user_id}
