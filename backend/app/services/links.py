"""Invite and password-reset links: building them and emailing them (when email is set up)."""

from fastapi import Request

from .. import config

SUBJECTS = {"invite": "You're invited to {college}'s timetable on Samay", "reset": "Reset your Samay password"}
BODIES = {
    "invite": ("Hello {name},\n\n{by} added you to {college}'s timetable on Samay as {role}.\n"
               "Choose your password and sign in here (the link works once, for 7 days):\n\n{link}\n\n"
               "If you weren't expecting this, you can ignore this email."),
    "reset": ("Hello {name},\n\nSomeone asked to reset the password of your Samay account for {college}.\n"
              "Choose a new password here (the link works once, for 1 hour):\n\n{link}\n\n"
              "If it wasn't you, ignore this email: your password stays the same."),
}


def link_path(kind: str, token: str) -> str:
    """The page opens this and asks for a new password."""
    return f"/?{kind}={token}"


def full_link(request: Request, path: str) -> str:
    return (config.PUBLIC_URL or str(request.base_url).rstrip("/")) + path


def email_link(request: Request, kind: str, token: str, to: str, name: str, college: str, by: str = "", role: str = "") -> bool:
    """Email the link if email is set up; True only if it was sent."""
    send = request.app.state.send_email
    if send is None:
        return False
    link = full_link(request, link_path(kind, token))
    fields = {"name": name, "college": college, "by": by or "Your timetable coordinator", "role": role, "link": link}
    return bool(send(to, SUBJECTS[kind].format(**fields), BODIES[kind].format(**fields)))
