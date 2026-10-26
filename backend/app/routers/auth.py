import json
import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..auth import COOKIE_NAME, ROLES, CurrentUser, current_user, get_db, user_from_row
from ..db import SESSION_SECONDS, Database
from ..schema import CollegeData
from ..security import DUMMY_HASH, new_student_code, verify_password
from ..seed import DEMO_USERS
from ..services import demo
from ..services.links import email_link
from ..services.new_college import college_id_for, empty_college

router = APIRouter(prefix="/api/auth", tags=["sign-in"])

WRONG = "That email and password don't match. Try again."


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


def me_payload(user: CurrentUser) -> dict:
    return {"user": {"name": user.name, "email": user.email, "role": user.role, "role_label": ROLES.get(user.role, user.role),
                     "teacher": user.teacher_id, "dept": user.dept_id},
            "college": {"name": user.college_name}}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Database = Depends(get_db)):
    email = body.email.strip().lower()
    limiter = request.app.state.login_limiter
    if limiter.blocked(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait 15 minutes, then try again.")
    row = db.find_user_by_email(email)
    if not verify_password(body.password, row["password_hash"] if row else DUMMY_HASH) or row is None:
        limiter.failed(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, WRONG)
    limiter.succeeded(email)
    return start_session(row, request, response, db)


def start_session(row, request: Request, response: Response, db: Database) -> dict:
    token = db.create_session(row["id"])
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax",
                        secure=request.app.state.cookie_secure, path="/")
    return me_payload(user_from_row(db.user_for_token(token)))


# ---- demo accounts: only while demo sign-in is switched on (SAMAY_DEMO_LOGIN) --------------------------------
def demo_users(request: Request) -> list[dict]:
    if not request.app.state.demo_login:
        raise HTTPException(404, "Not found")
    return json.loads(DEMO_USERS.read_text(encoding="utf-8"))["users"]


@router.get("/demo-accounts")
def demo_accounts(request: Request, db: Database = Depends(get_db)):
    out, student_codes = [], {}
    for u in demo_users(request):
        row = db.find_user_by_email(u["email"])
        data = db.get_college_data(row["college_id"]) if row else None
        if data:
            out.append({"email": u["email"], "role": u["role"], "role_label": ROLES.get(u["role"], u["role"]), "name": u["name"],
                        "college": data["name"], "place": data.get("place", ""), "published": db.published(row["college_id"]) is not None})
            # The fixed public demo code (e.g. DEMO-2026), so visitors can try the student view; never a college's own code.
            fixed = demo.READY.get(row["college_id"])
            if fixed and db.student_code(row["college_id"]) == fixed:
                student_codes[data["name"]] = f"{fixed[:4]}-{fixed[4:]}"
    return {"accounts": out, "student_codes": student_codes}


class DemoIn(BaseModel):
    email: str


@router.post("/demo")
def demo_login(body: DemoIn, request: Request, response: Response, db: Database = Depends(get_db)):
    email = body.email.strip().lower()
    if email not in {u["email"].lower() for u in demo_users(request)}:
        raise HTTPException(404, "That isn't a demo account.")
    row = db.find_user_by_email(email)
    if row is None:
        raise HTTPException(404, "That isn't a demo account.")
    return start_session(row, request, response, db)


# ---- a new college signs up --------------------------------------------------------------------------------
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupIn(BaseModel):
    college_name: str = Field(min_length=2, max_length=120)
    place: str = Field("", max_length=80)
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(pattern=EMAIL, max_length=254)
    password: str = Field(min_length=8, max_length=200)


PRACTICE_DOMAIN = "practice.samay"  # accounts of practice colleges: no password, so only their own session gets in
PRACTICE_SECONDS = 24 * 3600


@router.post("/practice", status_code=status.HTTP_201_CREATED)
def practice(request: Request, response: Response, db: Database = Depends(get_db)):
    """Demo only: a new, empty college of your own, to try Samay from the very start (no sign-up). It is private
    like any college, and deleted after a day."""
    if not request.app.state.demo_login:
        raise HTTPException(404, "Not found")
    who, limiter = f"practice:{request.client.host if request.client else 'unknown'}", request.app.state.practice_limiter
    if limiter.blocked(who):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You've started several practice colleges. Wait 15 minutes, then try again.")
    limiter.failed(who)  # counts each one started
    db.delete_old_colleges("practice-", time.time() - PRACTICE_SECONDS)
    college_id = f"practice-{secrets.token_hex(4)}"
    data = CollegeData.model_validate(empty_college(college_id, "Your College (practice)", "")).model_dump(mode="json", exclude_none=True)
    db.add_college(college_id, data["name"], data)
    email = f"{college_id}@{PRACTICE_DOMAIN}"
    db.add_user(email, "You", "coordinator", college_id, None)
    return start_session(db.find_user_by_email(email), request, response, db)


class PracticeSwitchIn(BaseModel):
    role: Literal["coordinator", "hod", "teacher", "student"]


@router.post("/practice/switch")
def practice_switch(body: PracticeSwitchIn, request: Request, response: Response, db: Database = Depends(get_db)):
    """In your own practice college only: look at it as its coordinator, a head of department, a teacher or a student."""
    from .students import STUDENT_COOKIE  # here: the students router imports this module's neighbours
    staff_token, student_token = request.cookies.get(COOKIE_NAME), request.cookies.get(STUDENT_COOKIE)
    row = db.user_for_token(staff_token) if staff_token else None
    college = db.college_for_student_token(student_token) if student_token and row is None else None
    college_id = row["college_id"] if row else college["id"] if college else None
    if not college_id or not college_id.startswith("practice-"):
        raise HTTPException(404, "Not found")
    data = db.get_college_data(college_id) or {}
    if body.role == "student":
        if db.published(college_id) is None:
            raise HTTPException(409, "Publish a timetable first (step 5): students only see a published timetable.")
        if db.student_code(college_id) is None:  # your own practice college: its student access turns on by itself
            db.set_student_code(college_id, new_student_code())
        token = db.create_student_session(college_id)
        response.set_cookie(STUDENT_COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="lax", secure=request.app.state.cookie_secure, path="/")
        if staff_token:
            db.delete_session(staff_token)
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"student": True, "college": {"name": data.get("name", "")}}
    dept = teacher = None
    if body.role == "hod":
        dept = next(iter(data.get("departments", [])), None)
        if dept is None:
            raise HTTPException(409, "Add a department first (College data → Departments), then look at it as its head.")
    if body.role == "teacher":
        info = db.published(college_id)
        published = db.get_timetable(college_id, info["version"]) if info else None
        teaching = {a["teacher"] for a in (published or {}).get("data", {}).get("assignments", [])}
        teachers = data.get("teachers", [])
        teacher = next((t for t in teachers if t["id"] in teaching), next(iter(teachers), None))
        if teacher is None:
            raise HTTPException(409, "Add a teacher first (College data → Teachers), then look at Samay as them.")
    suffix = "" if body.role == "coordinator" else "+" + body.role
    email = f"{college_id}{suffix}@{PRACTICE_DOMAIN}"
    user = db.find_user_by_email(email)
    stale = user is not None and ((dept and user["dept_id"] != dept["id"]) or (teacher and user["teacher_id"] != teacher["id"]))
    if stale:
        db.delete_user(college_id, user["id"])
    if user is None or stale:
        name = "You" if body.role == "coordinator" else f"Head of {dept['name']}" if dept else teacher["name"]
        db.add_user(email, name, body.role, college_id, None, teacher["id"] if teacher else None, dept["id"] if dept else None)
    if student_token:
        db.delete_student_session(student_token)
        response.delete_cookie(STUDENT_COOKIE, path="/")
    if staff_token:
        db.delete_session(staff_token)
    return start_session(db.find_user_by_email(email), request, response, db)


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, request: Request, response: Response, db: Database = Depends(get_db)):
    if not request.app.state.signup:
        raise HTTPException(404, "Not found")
    email = body.email.strip().lower()
    if db.find_user_by_email(email):
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    college_id = college_id_for(body.college_name)
    data = CollegeData.model_validate(empty_college(college_id, body.college_name.strip(), body.place.strip())).model_dump(mode="json", exclude_none=True)
    db.add_college(college_id, data["name"], data)
    db.add_user(email, body.name.strip(), "coordinator", college_id, body.password)
    return start_session(db.find_user_by_email(email), request, response, db)


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=8, max_length=200)


@router.post("/password")
def change_password(body: PasswordIn, request: Request, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    if not verify_password(body.current, db.password_hash(user.id) or DUMMY_HASH):
        raise HTTPException(400, "Your current password isn't right.")
    if body.new == body.current:
        raise HTTPException(400, "Choose a new password that's different from the current one.")
    db.set_password(user.id, body.new, keep_token=request.cookies.get(COOKIE_NAME))
    return {"changed": True, "message": "Password changed. You've been signed out everywhere else."}


# ---- forgot password, and invite / reset links ---------------------------------------------------------------
SENT = "If that email has a Samay account, we've sent it a link to choose a new password. The link works for 1 hour."
LINK_GONE = "This link has expired or was already used. Ask for a new one."


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


@router.post("/forgot")
def forgot_password(body: ForgotIn, request: Request, db: Database = Depends(get_db)):
    """Email a reset link. The answer is the same whether or not the email has an account."""
    email = body.email.strip().lower()
    limiter = request.app.state.forgot_limiter
    if limiter.blocked(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests for this email. Wait 15 minutes, then try again.")
    limiter.failed(email)  # every request counts
    row = db.find_user_by_email(email)
    if row is not None and request.app.state.send_email is not None:
        token = db.create_password_token(row["id"], "reset")
        college = db.user_for_token_college(row["college_id"])
        email_link(request, "reset", token, email, row["name"], college)
    return {"message": SENT, "email": request.app.state.send_email is not None}


class LinkIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


@router.post("/link")
def link_info(body: LinkIn, db: Database = Depends(get_db)):
    """What an invite or reset link is for, so the page can greet the person."""
    row = db.password_token(body.token)
    if row is None:
        raise HTTPException(404, LINK_GONE)
    return {"kind": row["kind"], "name": row["name"], "email": row["email"], "college": {"name": row["college_name"]}}


class SetPasswordIn(LinkIn):
    password: str = Field(min_length=8, max_length=200)


@router.post("/set-password")
def set_password_from_link(body: SetPasswordIn, request: Request, response: Response, db: Database = Depends(get_db)):
    """Choose a password from an invite or reset link (it works once), then sign in."""
    row = db.password_token(body.token)
    if row is None or db.use_password_token(body.token, body.password) is None:
        raise HTTPException(404, LINK_GONE)
    return start_session(db.find_user_by_email(row["email"]), request, response, db)


@router.post("/logout")
def logout(request: Request, response: Response, db: Database = Depends(get_db)):
    if token := request.cookies.get(COOKIE_NAME):
        db.delete_session(token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"signed_out": True}


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)):
    return me_payload(user)
