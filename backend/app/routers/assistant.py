"""Chat with the AI assistant about the signed-in person's own college.

Coordinators get the scheduling assistant on their latest timetable: it can suggest a change (returned as `proposal`
for the page to preview), saved only through POST /api/timetables/{v}/revise. Heads of department and teachers get an
assistant on the published timetable that can propose a change to a class they may change (applied by the person
through POST /api/changes). Students (with their college code, no account) can only ask questions."""

from typing import Literal

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser, current_user, get_db
from ..db import Database
from ..security import token_hash
from ..services.assistant_tools import SchedulingTools, WeekTools
from .students import STUDENT_COOKIE, student_college

router = APIRouter(prefix="/api", tags=["assistant"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[Turn] = Field(default=[], max_length=40)


def chat_function(request: Request):
    chat = request.app.state.assistant_chat
    if chat is None:
        raise HTTPException(503, "The AI assistant isn't switched on for this server. It needs an Anthropic API key (ANTHROPIC_API_KEY).")
    return chat


def week_tools(college_id: str, college_name: str, db: Database, request: Request, role: str, **who) -> WeekTools:
    info = db.published(college_id)
    base = db.get_timetable(college_id, info["version"]) if info else None
    current = db.get_college_data(college_id)
    if current is None:
        raise HTTPException(404, "Your college's data couldn't be found.")
    version = base["version"] if base else None
    return WeekTools(college_name=college_name, base=base, current_data=current, role=role, tz=request.app.state.timezone,
                     week_changes=lambda week: db.week_changes(college_id, version, week), **who)


def answer(request: Request, chat, college_name: str, tools, body: ChatIn) -> dict:
    if not request.app.state.assistant_quota.take():
        raise HTTPException(429, "The AI assistant has answered all the questions it can today. It's back tomorrow.")
    try:
        return chat(college_name, tools, [t.model_dump() for t in body.history], body.message.strip())
    except anthropic.AuthenticationError:
        raise HTTPException(503, "The assistant's API key was refused. Check ANTHROPIC_API_KEY on the server.")
    except anthropic.PermissionDeniedError:
        raise HTTPException(503, "The assistant's API key isn't allowed to use this model.")
    except anthropic.RateLimitError:
        raise HTTPException(429, "The assistant is busy right now. Try again in a minute.")
    except anthropic.APIConnectionError:
        raise HTTPException(503, "Couldn't reach the assistant. Check the server's internet connection.")
    except anthropic.APIStatusError:
        raise HTTPException(502, "The assistant had a problem answering. Try again.")


@router.post("/assistant/chat")
def ask(body: ChatIn, request: Request, user: CurrentUser = Depends(current_user), db: Database = Depends(get_db)):
    chat = chat_function(request)
    if user.role == "coordinator":
        data = db.get_college_data(user.college_id)
        if data is None:
            raise HTTPException(404, "Your college's data couldn't be found.")
        tools = SchedulingTools(data, db.get_timetable(user.college_id))
    elif (user.role == "hod" and user.dept_id) or (user.role == "teacher" and user.teacher_id):
        tools = week_tools(user.college_id, user.college_name, db, request, user.role, teacher_id=user.teacher_id,
                           dept_id=user.dept_id, person=user.name)
        if not request.app.state.person_quota.take(f"user:{user.id}"):
            raise HTTPException(429, "You've asked all the questions you can today. The assistant is back tomorrow.")
    else:
        raise HTTPException(403, "The assistant isn't available for your account.")
    return answer(request, chat, user.college_name, tools, body)


@router.post("/student/assistant")
def ask_as_student(body: ChatIn, request: Request, college=Depends(student_college), db: Database = Depends(get_db)):
    """Students' questions about their college's published timetable (no changes)."""
    chat = chat_function(request)
    tools = week_tools(college["id"], college["name"], db, request, "student")
    if not request.app.state.student_quota.take(f"phone:{token_hash(request.cookies.get(STUDENT_COOKIE, ''))}"):
        raise HTTPException(429, "You've asked all the questions you can today on this phone. The assistant is back tomorrow.")
    return answer(request, chat, college["name"], tools, body)
