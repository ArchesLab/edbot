# Chainlit prototype UI. Only calls edbot.service: no agent logic, filtering, or study logic here,
# so swapping this file for the FastAPI + React frontend later doesn't touch the agent.
#
# Run from the repo root (Chainlit reads .env and .chainlit/config.toml from the current directory):
#   uv run chainlit run src/edbot/ui/chainlit_app.py --host 0.0.0.0 --port 8000
import hmac
import os
import chainlit as cl

from edbot import service
from edbot.edbot_agent import setup_logging

def _test_accounts() -> dict[str, str]:
    """Parse EDBOT_TEST_ACCOUNTS from .env ("alice:pw1,bob:pw2") into {username: password}."""
    accounts = {}
    for entry in os.environ.get("EDBOT_TEST_ACCOUNTS", "").split(","):
        username, sep, password = entry.strip().partition(":")
        if sep and username and password:
            accounts[username] = password
    return accounts

def _student_id() -> str:
    """The logged-in tester's username doubles as their student ID (one conversation each)."""
    return cl.user_session.get("user").identifier

@cl.on_app_startup
async def startup():
    setup_logging(1) # INFO: subagent calls and timings in the server console
    # Build the agent now, so the first student doesn't wait for the SEBook sync
    await service.get_agent()

@cl.on_app_shutdown
async def shutdown():
    await service.close()

@cl.password_auth_callback
def login(username: str, password: str) -> cl.User | None:
    """Test login only, replaced by SSO in Phase 3. Returning None rejects the login."""
    expected = _test_accounts().get(username)
    # compare_digest takes the same time whether or not the passwords match, so timing can't leak them
    if expected is not None and hmac.compare_digest(password.encode(), expected.encode()):
        return cl.User(identifier=username)
    return None

@cl.on_chat_start
async def start():
    """Show the student's saved conversation, so every visit continues the same chat."""
    for message in await service.get_history(_student_id()):
        await cl.Message(
            content=message.content,
            type="user_message" if message.role == "student" else "assistant_message",
        ).send()

@cl.on_message
async def on_message(message: cl.Message):
    status = cl.Message(content="") # temporary progress note, removed once the reply starts
    status_shown = True
    reply = cl.Message(content="")
    await status.send()

    async for event in service.chat_turn(_student_id(), message.content):
        if event.type in ("text", "error") and status_shown:
            await status.remove()
            status_shown = False

        if event.type == "status" and status_shown:
            status.content = f"_{event.text}_" # italic
            await status.update()
        elif event.type == "text":
            await reply.stream_token(event.text) # sends the reply on the first token, then appends
        elif event.type == "error":
            reply.content = event.message
        # "done" needs no handling: the loop ends right after it

    if status_shown: # the turn ended without any reply text
        await status.remove()
    await reply.send()
