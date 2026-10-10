"""``ChatOpenAI`` reports each provider response to ``capture_llm_calls``, including unparseable ones.

The Responses API is served by ``httpx.MockTransport`` behind the real OpenAI SDK; no network.
"""

import asyncio
from typing import Optional
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

from econagents.adapters.llm import LLMCallRecord, capture_llm_calls, report_llm_call
from econagents.adapters.llm.openai import ChatOpenAI


class _Decision(BaseModel):
    reasoning: str
    price: float


def _body(status: str, text: Optional[str], reason: Optional[str] = None) -> dict:
    output: list[dict] = [{"type": "reasoning", "id": "rs_1", "summary": []}]
    if text is not None:
        output.append(
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": status,
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.4-mini",
        "status": status,
        "incomplete_details": {"reason": reason} if reason else None,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 5},
        },
    }


def _fake_api(body: dict):
    real = openai.AsyncOpenAI

    def factory(*_args, **_kwargs):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        return real(
            api_key="sk-test",
            base_url="http://127.0.0.1:9/v1",
            http_client=httpx.AsyncClient(transport=transport),
            max_retries=0,
        )

    return patch("openai.AsyncOpenAI", side_effect=factory)


def _llm() -> ChatOpenAI:
    llm = ChatOpenAI()
    llm.observability = MagicMock()
    return llm


USAGE = {"input_tokens": 10, "output_tokens": 20, "reasoning_tokens": 5}


@pytest.mark.asyncio
async def test_completed_structured_response_is_recorded():
    text = '{"reasoning": "r", "price": 10}'
    with _fake_api(_body("completed", text)), capture_llm_calls() as calls:
        result = await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    assert result == _Decision(reasoning="r", price=10)
    assert calls == [LLMCallRecord("openai", "gpt-5.4-mini", "completed", USAGE, text, None)]


@pytest.mark.asyncio
async def test_unparseable_structured_response_is_recorded_and_the_error_reraised():
    text = '{"reasoning": "cut off'
    with _fake_api(_body("incomplete", text, "max_output_tokens")), capture_llm_calls() as calls:
        with pytest.raises(ValidationError):
            await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    [record] = calls
    assert (record.finish_reason, record.usage, record.raw_output) == ("max_output_tokens", USAGE, text)
    assert record.parse_error


@pytest.mark.asyncio
async def test_reasoning_only_response_is_recorded_without_output():
    with _fake_api(_body("incomplete", None, "max_output_tokens")), capture_llm_calls() as calls:
        result = await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    assert result is None
    assert [(c.finish_reason, c.raw_output, c.parse_error) for c in calls] == [("max_output_tokens", None, None)]


@pytest.mark.asyncio
async def test_plain_text_response_is_recorded():
    with _fake_api(_body("completed", "hello")), capture_llm_calls() as calls:
        result = await _llm().get_response([{"role": "user", "content": "x"}], {})

    assert result == "hello"
    assert [(c.finish_reason, c.raw_output) for c in calls] == [("completed", "hello")]


@pytest.mark.asyncio
async def test_calls_inside_wait_for_are_collected_and_nothing_leaks_outside():
    text = '{"reasoning": "r", "price": 1}'
    with _fake_api(_body("completed", text)):
        with capture_llm_calls() as calls:
            await asyncio.wait_for(
                _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision), 5
            )
        await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    assert len(calls) == 1


def test_report_without_capture_is_a_no_op():
    report_llm_call(LLMCallRecord("openai", None, None, None, None))
