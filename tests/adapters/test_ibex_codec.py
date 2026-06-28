import json

import pytest

from econagents.adapters.protocol import IbexMessageCodec
from econagents.domain import Action
from econagents.ports.codec import MessageDecodeError


def test_decode_ibex_envelope():
    codec = IbexMessageCodec()
    event = codec.decode_event(json.dumps({"meta": {"type": "phase-started"}, "payload": {"phase": "decision"}}))

    assert event.type == "phase-started"
    assert event.data == {"phase": "decision"}


def test_decode_invalid_json_raises_message_decode_error():
    codec = IbexMessageCodec()

    with pytest.raises(MessageDecodeError):
        codec.decode_event("not json")


def test_encode_dict_action_preserves_payload_shape():
    codec = IbexMessageCodec()
    encoded = codec.encode_action({"meta": {"type": "submit-choice"}, "payload": {"choice": "COOPERATE"}})

    assert json.loads(encoded) == {"meta": {"type": "submit-choice"}, "payload": {"choice": "COOPERATE"}}


def test_encode_domain_action():
    codec = IbexMessageCodec()
    encoded = codec.encode_action(Action(type="choice", payload={"choice": "DEFECT"}))

    assert json.loads(encoded) == {"type": "choice", "choice": "DEFECT"}


def test_encode_join_and_ready():
    codec = IbexMessageCodec()

    assert json.loads(codec.encode_join({"recovery": "abc"})) == {
        "meta": {"type": "join"},
        "payload": {"recovery": "abc"},
    }
    assert json.loads(codec.encode_ready()) == {
        "meta": {"type": "ready", "component": {"type": "standard:ready"}},
        "payload": {},
    }
