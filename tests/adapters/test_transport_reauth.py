"""Reproduction for IBEX-game_suite#8: the transport must re-join after an unexpected close."""

import asyncio
import json

import pytest
import websockets

from econagents.adapters.transport import JoinPayloadAuth, WebSocketTransport

RECOVERY = "rec-abc"
JOIN = {"meta": {"type": "join"}, "payload": {"recovery": RECOVERY}}


class FakeIbexServer:
    """Mimics IBEX WebSocketService: `join` authenticates the socket; anything sent on an
    unauthenticated socket is dropped; `get-snapshot` on an authenticated socket gets a snapshot."""

    def __init__(self, phase: str = "market"):
        self.phase = phase
        self.conns: list[dict] = []
        self.server = None
        self.port = 0

    async def handler(self, ws):
        conn = {"ws": ws, "authed": False, "received": [], "dropped": []}
        self.conns.append(conn)
        try:
            async for raw in ws:
                msg = json.loads(raw)
                conn["received"].append(msg)
                mtype = msg.get("meta", {}).get("type")
                if mtype == "join" and msg.get("payload", {}).get("recovery") == RECOVERY:
                    conn["authed"] = True
                    await ws.send(json.dumps({"meta": {"type": "player-joined"}, "payload": {"playerNumber": 2}}))
                    await ws.send(json.dumps({"meta": {"type": "phase-transition"}, "payload": {"phase": self.phase}}))
                elif not conn["authed"]:
                    conn["dropped"].append(msg)
                elif mtype == "get-snapshot":
                    await ws.send(json.dumps({"meta": {"type": "snapshot"}, "payload": {"currentPhase": self.phase}}))
        except websockets.ConnectionClosed:
            pass

    async def start(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    def drop_current(self):
        """Fault injection: abort the newest connection's TCP transport (client sees close code 1006)."""
        self.conns[-1]["ws"].transport.abort()

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


async def wait_for(pred, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not pred():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.02)
    return True


@pytest.mark.asyncio
async def test_transport_reauthenticates_after_unexpected_close():
    srv = FakeIbexServer()
    await srv.start()

    async def on_msg(_message):
        return None

    transport = WebSocketTransport(
        url=f"ws://127.0.0.1:{srv.port}",
        auth_mechanism=JoinPayloadAuth(),
        auth_mechanism_kwargs={"recovery": RECOVERY},
        on_message_callback=on_msg,
    )
    task = asyncio.create_task(transport.start_listening())
    try:
        assert await wait_for(lambda: srv.conns and srv.conns[0]["authed"])
        srv.drop_current()
        assert await wait_for(lambda: len(srv.conns) >= 2), "client did not reconnect"
        await transport.send(json.dumps({"meta": {"type": "get-snapshot"}, "payload": {}}))
        await asyncio.sleep(0.2)
        second = srv.conns[1]
        assert second["received"], "reconnected socket sent nothing"
        assert second["received"][0] == JOIN, f"first frame after reconnect was {second['received'][0]}, not join"
        assert second["authed"], f"no join on reconnect; server dropped: {second['dropped']}"
    finally:
        await transport.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await srv.stop()
