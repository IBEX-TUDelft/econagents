"""IBEX-game_suite#7: a failed WebSocket send must be visible to the caller.

``WebSocketTransport.send`` catches every exception, logs it and returns ``None``, and silently
drops the message when there is no connection. ``Agent.execute_phase_action`` therefore cannot tell
an economic action that left the process from one that was lost, and the loss is never recorded as
an infrastructure failure. Either raising or returning an explicit ``False`` would let the caller
know; returning ``None`` exactly as for a delivered message does not.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from econagents.adapters.transport import WebSocketTransport

POST_ORDER = '{"meta": {"type": "post-order", "component": {"type": "standard:dam", "name": "project"}}, "payload": {}}'


async def _send_outcome(transport: WebSocketTransport) -> str:
    try:
        result = await transport.send(POST_ORDER)
    except Exception as exc:  # noqa: BLE001
        return f"raised {type(exc).__name__}"
    return "returned False" if result is False else f"returned {result!r}"


@pytest.mark.asyncio
async def test_send_failure_is_surfaced_to_the_caller():
    transport = WebSocketTransport(url="ws://127.0.0.1:9")
    transport.ws = MagicMock(send=AsyncMock(side_effect=ConnectionResetError("socket closed")))

    outcome = await _send_outcome(transport)

    transport.ws.send.assert_awaited_once_with(POST_ORDER)
    assert outcome.startswith("raised") or outcome == "returned False", (
        f"ws.send raised ConnectionResetError but transport.send {outcome}: the lost action looks delivered"
    )


@pytest.mark.asyncio
async def test_send_without_connection_is_not_silently_dropped():
    transport = WebSocketTransport(url="ws://127.0.0.1:9")
    transport.ws = None

    outcome = await _send_outcome(transport)

    assert outcome.startswith("raised") or outcome == "returned False", (
        f"no connection, yet transport.send {outcome}: the message was dropped silently"
    )
