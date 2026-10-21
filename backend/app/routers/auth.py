import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..auth import COOKIE_NAME, CurrentUser, current_user, get_db
from ..db import SESSION_SECONDS, Database
from ..security import DUMMY_HASH, verify_password
from ..seed import DEMO_USERS

router = APIRouter(prefix="/api/auth", tags=["sign-in"])

WRONG = "That email and password don't match. Try again."


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


def me_payload(user: CurrentUser) -> dict:
    return {"user": {"name": user.name, "email": user.email, "role": user.role}, "college": {"name": user.college_name}}


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
    user = db.user_for_token(token)
    return me_payload(CurrentUser(user["id"], user["email"], user["name"], user["role"], user["college_id"], user["college_name"]))


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
            out.append({"email": u["email"], "role": u["role"], "college": data["name"], "place": data.get("place", "")})
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


@router.post("/logout")
def logout(request: Request, response: Response, db: Database = Depends(get_db)):
    if token := request.cookies.get(COOKIE_NAME):
        db.delete_session(token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"signed_out": True}


@router.get("/me")
def me(user: CurrentUser = Depends(current_user)):
    return me_payload(user)
