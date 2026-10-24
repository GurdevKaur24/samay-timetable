"""Chat with the AI scheduling assistant about the signed-in coordinator's own college. It can suggest a change
(returned as `proposal` for the page to preview); saving still goes through POST /api/timetables/{v}/revise."""

from typing import Literal

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import CurrentUser, coordinator_only, get_db
from ..db import Database
from ..services.assistant_tools import SchedulingTools

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[Turn] = Field(default=[], max_length=40)


@router.post("/chat")
def ask(body: ChatIn, request: Request, user: CurrentUser = Depends(coordinator_only), db: Database = Depends(get_db)):
    chat = request.app.state.assistant_chat
    if chat is None:
        raise HTTPException(503, "The AI assistant isn't switched on for this server. It needs an Anthropic API key (ANTHROPIC_API_KEY).")
    data = db.get_college_data(user.college_id)
    if data is None:
        raise HTTPException(404, "Your college's data couldn't be found.")
    tools = SchedulingTools(data, db.get_timetable(user.college_id))
    try:
        return chat(user.college_name, tools, [t.model_dump() for t in body.history], body.message.strip())
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
