"""Player identity an agent is bound to, and the machine-readable identity records written to its log."""

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

# Version of the identity header, identity-bound and model-call records written to agent logs.
TRACE_SCHEMA_VERSION = 1

SNAPSHOT_EVENT = "snapshot"
PLAYER_JOINED_EVENT = "player-joined"

IdentitySource = Literal["snapshot", "player-joined", "recovery"]


@dataclass(frozen=True)
class PlayerIdentity:
    """The seat the server bound an agent's connection to, and how the agent learned it.

    ``source`` is ``"snapshot"`` (the snapshot's own ``playerNumber``/``role``), ``"player-joined"`` (the
    first ``player-joined`` received after a join on a connection) or ``"recovery"`` (the roster entry
    carrying the agent's recovery token). ``connection`` is the transport's connection epoch when the
    transport reports one.
    """

    player_number: int
    role: Optional[str]
    source: IdentitySource
    connection: Optional[int] = None

    def as_record(self) -> dict[str, Any]:
        return {"record": "identity-bound", "trace_schema_version": TRACE_SCHEMA_VERSION, **asdict(self)}


class IdentityMismatchError(RuntimeError):
    """The server bound the agent to a different seat than the one it was configured for."""


def json_record(record: dict[str, Any]) -> str:
    """One-line JSON for a log record; values JSON cannot hold are written as strings."""
    return json.dumps(record, default=str, separators=(",", ":"))
