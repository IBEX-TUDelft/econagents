import asyncio
import json
from typing import Any, ClassVar, Optional

import pytest
from pydantic import BaseModel

from econagents.domain.reasoning import capture_reasoning, report_reasoning
from tests.conftest import MockRole


class Decision(BaseModel):
    reasoning: str
    choice: str


class LLMReturning(MockRole):
    """A role whose model returns ``response``."""

    response: ClassVar[Any] = None

    def __init__(self, response: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.llm = type(self.llm)()

        async def get_response(*args: Any, **kw: Any) -> Any:
            return response

        self.llm.get_response = get_response  # type: ignore[method-assign]


def test_report_outside_a_capture_is_ignored():
    report_reasoning("nobody listens")


def test_capture_collects_reports_in_order_and_strips_them():
    with capture_reasoning() as texts:
        report_reasoning("  first ")
        report_reasoning("second")
    assert texts == ["first", "second"]


@pytest.mark.parametrize("text", [None, "", "   ", 42])
def test_blank_or_non_text_reasoning_is_ignored(text):
    with capture_reasoning() as texts:
        report_reasoning(text)
    assert texts == []


def test_captures_nest():
    with capture_reasoning() as outer:
        report_reasoning("a")
        with capture_reasoning() as inner:
            report_reasoning("b")
    assert outer == ["a", "b"]
    assert inner == ["b"]


@pytest.mark.asyncio
async def test_a_task_started_inside_the_capture_reports_to_it():
    async def decide() -> None:
        await asyncio.sleep(0)
        report_reasoning("from a task")

    with capture_reasoning() as texts:
        await asyncio.wait_for(decide(), timeout=1)
    assert texts == ["from a task"]


@pytest.mark.asyncio
async def test_role_reports_the_reasoning_of_a_json_response(game_state, prompts_path, logger):
    role = LLMReturning(json.dumps({"reasoning": "It pays more.", "message": "x"}), logger=logger)
    with capture_reasoning() as texts:
        result = await role.handle_phase_with_llm(0, game_state, prompts_path)
    assert texts == ["It pays more."]
    assert result == {"reasoning": "It pays more.", "message": "x"}


@pytest.mark.asyncio
async def test_role_reports_the_reasoning_of_a_structured_response(game_state, prompts_path, logger):
    role = LLMReturning(Decision(reasoning="Trust them.", choice="COOPERATE"), logger=logger)
    with capture_reasoning() as texts:
        await role.handle_phase_with_llm(0, game_state, prompts_path)
    assert texts == ["Trust them."]


@pytest.mark.asyncio
async def test_role_reads_the_field_it_names(game_state, prompts_path, logger):
    class WhyRole(LLMReturning):
        reasoning_field: ClassVar[Optional[str]] = "why"

    role = WhyRole(json.dumps({"why": "Cheap.", "reasoning": "not this one"}), logger=logger)
    with capture_reasoning() as texts:
        await role.handle_phase_with_llm(0, game_state, prompts_path)
    assert texts == ["Cheap."]


@pytest.mark.asyncio
async def test_role_without_a_reasoning_field_reports_nothing(game_state, prompts_path, logger):
    class SilentRole(LLMReturning):
        reasoning_field: ClassVar[Optional[str]] = None

    role = SilentRole(json.dumps({"reasoning": "hidden"}), logger=logger)
    with capture_reasoning() as texts:
        await role.handle_phase_with_llm(0, game_state, prompts_path)
    assert texts == []


@pytest.mark.parametrize("response", ["not json", json.dumps([1, 2]), json.dumps({"reasoning": 3}), None])
def test_extract_reasoning_without_text_is_none(response, logger):
    assert LLMReturning(None, logger=logger).extract_reasoning(response) is None
