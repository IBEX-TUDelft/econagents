import json
from typing import Any, ClassVar, Optional

import pytest
from pydantic import BaseModel

from tests.conftest import MockRole

ENVELOPE = {"meta": {"type": "submit-choice"}, "payload": {"choice": "COOPERATE"}}


class Decision(BaseModel):
    reasoning: str
    choice: str


class EnvelopeRole(MockRole):
    """A role whose model returns ``response`` and whose parser returns ``parsed``."""

    def __init__(self, response: Any, parsed: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.llm = type(self.llm)()
        self.parsed = json.loads(json.dumps(ENVELOPE)) if parsed is None else parsed

        async def get_response(*args: Any, **kw: Any) -> Any:
            return response

        self.llm.get_response = get_response  # type: ignore[method-assign]

    def parse_phase_llm_response(self, response: Any, state: Any) -> Any:
        return self.parsed


@pytest.mark.asyncio
async def test_reasoning_of_a_json_response_goes_in_meta(game_state, prompts_path, logger):
    role = EnvelopeRole(json.dumps({"reasoning": " It pays more. ", "choice": "COOPERATE"}), logger=logger)
    result = await role.handle_phase_with_llm(0, game_state, prompts_path)

    assert result == {"meta": {"type": "submit-choice", "reasoning": "It pays more."}, "payload": ENVELOPE["payload"]}
    assert role.parsed == ENVELOPE


@pytest.mark.asyncio
async def test_reasoning_of_a_structured_response_goes_in_meta(game_state, prompts_path, logger):
    role = EnvelopeRole(Decision(reasoning="Trust them.", choice="COOPERATE"), logger=logger)
    result = await role.handle_phase_with_llm(0, game_state, prompts_path)

    assert result["meta"]["reasoning"] == "Trust them."


@pytest.mark.asyncio
async def test_role_reads_the_field_it_names(game_state, prompts_path, logger):
    class WhyRole(EnvelopeRole):
        reasoning_field: ClassVar[Optional[str]] = "why"

    role = WhyRole(json.dumps({"why": "Cheap.", "reasoning": "not this one"}), logger=logger)
    result = await role.handle_phase_with_llm(0, game_state, prompts_path)

    assert result["meta"]["reasoning"] == "Cheap."


@pytest.mark.asyncio
async def test_role_without_a_reasoning_field_adds_nothing(game_state, prompts_path, logger):
    class SilentRole(EnvelopeRole):
        reasoning_field: ClassVar[Optional[str]] = None

    role = SilentRole(json.dumps({"reasoning": "hidden"}), logger=logger)
    result = await role.handle_phase_with_llm(0, game_state, prompts_path)

    assert result == ENVELOPE


@pytest.mark.asyncio
async def test_action_without_meta_is_returned_unchanged(game_state, prompts_path, logger):
    flat = {"type": "choice", "choice": "DEFECT"}
    role = EnvelopeRole(json.dumps({"reasoning": "why"}), parsed=flat, logger=logger)
    result = await role.handle_phase_with_llm(0, game_state, prompts_path)

    assert result == {"type": "choice", "choice": "DEFECT"}


@pytest.mark.asyncio
async def test_default_parser_keeps_reasoning_as_a_decision_field(game_state, prompts_path, logger):
    role = MockRole(logger=logger)

    async def get_response(*args: Any, **kw: Any) -> Any:
        return json.dumps({"reasoning": "It pays more.", "message": "x"})

    role.llm = type(role.llm)()
    role.llm.get_response = get_response  # type: ignore[method-assign]
    result = await role.handle_phase_with_llm(0, game_state, prompts_path)

    assert result == {"reasoning": "It pays more.", "message": "x"}


@pytest.mark.parametrize(
    "response", ["not json", json.dumps([1, 2]), json.dumps({"reasoning": 3}), json.dumps({"reasoning": "  "}), None]
)
def test_extract_reasoning_without_text_is_none(response, logger):
    assert EnvelopeRole(None, logger=logger).extract_reasoning(response) is None
