"""Students: no accounts. The coordinator shares one college code (or its link / QR code); a phone that enters it sees
that college's published timetable, read-only. A wrong code says only "not found", so codes can't be used to learn
which colleges use Samay, and repeated wrong codes are blocked."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..auth import CurrentUser, coordinator_only, get_db
from ..db import STUDENT_SESSION_SECONDS, Database
from ..security import new_student_code, normalize_code
from ..services.published import published_timetable

router = APIRouter(tags=["students"])

STUDENT_COOKIE = "samay_student"
NOT_FOUND = "That code wasn't found. Check it with your college."


def shown(code: str | None) -> str | None:
    return f"{code[:4]}-{code[4:]}" if code else None


# ---- the coordinator manages the code ------------------------------------------------------------------------
@router.get("/api/student-access")
def student_access(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    code = db.student_code(user.college_id)
    return {"enabled": code is not None, "code": shown(code), "published": db.published(user.college_id) is not None}


@router.post("/api/student-access")
def new_code(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    """Turn student access on with a new code. Any old code and the phones that used it stop working."""
    code = new_student_code()
    db.set_student_code(user.college_id, code)
    return {"enabled": True, "code": shown(code), "message": "New student code ready. Share it, or print the QR code."}


@router.delete("/api/student-access")
def turn_off(user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    db.set_student_code(user.college_id, None)
    return {"enabled": False, "code": None, "message": "Student access is off. The old code no longer works."}


# ---- students -------------------------------------------------------------------------------------------------
class OpenIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


@router.post("/api/student/open")
def open_college(body: OpenIn, request: Request, response: Response, db: Database = Depends(get_db)):
    who = f"student:{request.client.host if request.client else 'unknown'}"
    limiter = request.app.state.student_limiter
    if limiter.blocked(who):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many tries. Wait 15 minutes, then try again.")
    college = db.college_for_student_code(normalize_code(body.code))
    if college is None:
        limiter.failed(who)
        raise HTTPException(404, NOT_FOUND)
    token = db.create_student_session(college["id"])
    response.set_cookie(STUDENT_COOKIE, token, max_age=STUDENT_SESSION_SECONDS, httponly=True, samesite="lax",
                        secure=request.app.state.cookie_secure, path="/")
    return {"college": {"name": college["name"]}}


def student_college(request: Request, db: Database = Depends(get_db)):
    token = request.cookies.get(STUDENT_COOKIE)
    college = db.college_for_student_token(token) if token else None
    if college is None:
        raise HTTPException(401, "Enter your college's student code to see the timetable.")
    return college


@router.get("/api/student/timetable")
def timetable(college=Depends(student_college), db: Database = Depends(get_db)):
    """The college's published timetable (no drafts, no teachers' free times)."""
    return {"college": {"name": college["name"]}, "published": published_timetable(college["id"], db)}


@router.post("/api/student/leave")
def leave(request: Request, response: Response, db: Database = Depends(get_db)):
    if token := request.cookies.get(STUDENT_COOKIE):
        db.delete_student_session(token)
    response.delete_cookie(STUDENT_COOKIE, path="/")
    return {"left": True}
