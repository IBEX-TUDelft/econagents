import json

import pytest

from econagents.adapters.protocol import IbexMessageCodec
from econagents.adapters.protocol.ibex import MAX_REASONING_LENGTH
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


def test_encode_action_puts_reasoning_in_meta_without_changing_the_action():
    codec = IbexMessageCodec()
    action = {"meta": {"type": "submit-choice"}, "payload": {"choice": "COOPERATE"}}
    encoded = codec.encode_action(action, reasoning="They cooperated last round.")

    assert json.loads(encoded) == {
        "meta": {"type": "submit-choice", "reasoning": "They cooperated last round."},
        "payload": {"choice": "COOPERATE"},
    }
    assert action == {"meta": {"type": "submit-choice"}, "payload": {"choice": "COOPERATE"}}


def test_encode_action_cuts_reasoning_to_the_server_limit():
    codec = IbexMessageCodec()
    encoded = codec.encode_action({"meta": {"type": "x"}, "payload": {}}, reasoning="y" * (MAX_REASONING_LENGTH + 10))

    assert json.loads(encoded)["meta"]["reasoning"] == "y" * MAX_REASONING_LENGTH


def test_encode_action_without_meta_ignores_reasoning():
    codec = IbexMessageCodec()
    encoded = codec.encode_action({"type": "choice", "choice": "DEFECT"}, reasoning="why")

    assert json.loads(encoded) == {"type": "choice", "choice": "DEFECT"}


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
