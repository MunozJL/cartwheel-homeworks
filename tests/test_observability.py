"""HW2 Part D: authentication tests for the session endpoints.

Offline by design: no Langfuse, no Docker, no model-provider key. These
exercise the identity checks in server/app.py -- the server, not the
conversation, decides who the caller is.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from server import app as server_app


@pytest.fixture(autouse=True)
def _clear_sessions():
    server_app._SESSIONS.clear()
    yield
    server_app._SESSIONS.clear()


def test_create_session_rejects_role_mismatch(world: dict) -> None:
    """User 1 is a shopper in the database; claiming 'merchant' is refused."""
    with pytest.raises(HTTPException) as exc:
        server_app.create_session(
            server_app.SessionCreate(user_id=1, role="merchant")
        )
    assert exc.value.status_code == 403
    assert not server_app._SESSIONS  # nothing was bound


def test_token_cannot_authorize_a_different_session(world: dict) -> None:
    """A token minted for one session must not authorize another."""
    session_a = server_app.create_session(
        server_app.SessionCreate(user_id=1, role="shopper")
    )
    session_b = server_app.create_session(
        server_app.SessionCreate(user_id=9002, role="merchant")
    )

    with pytest.raises(HTTPException) as exc:
        server_app._authorize(
            session_b["session_id"], f"Bearer {session_a['token']}"
        )
    assert exc.value.status_code == 403
