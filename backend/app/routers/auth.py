import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..auth import COOKIE_NAME, ROLES, CurrentUser, current_user, get_db, user_from_row
from ..db import SESSION_SECONDS, Database
from ..schema import CollegeData
from ..security import DUMMY_HASH, verify_password
from ..seed import DEMO_USERS
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
    out = []
    for u in demo_users(request):
        row = db.find_user_by_email(u["email"])
        data = db.get_college_data(row["college_id"]) if row else None
        if data:
            out.append({"email": u["email"], "role": u["role"], "role_label": ROLES.get(u["role"], u["role"]), "name": u["name"],
                        "college": data["name"], "place": data.get("place", "")})
    return {"accounts": out}


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
