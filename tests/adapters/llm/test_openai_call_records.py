"""``ChatOpenAI`` reports each provider response to ``capture_llm_calls``, including unparsable ones.

The Responses API is served by ``httpx.MockTransport`` behind the real OpenAI SDK; no network.
The record API is imported inside each test so that, against an econagents without it, the tests fail
instead of erroring at collection (IBEX-game_suite#7).
"""

import asyncio
import json
from typing import Optional
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest
from pydantic import BaseModel, ValidationError

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
    return _fake_http(lambda request: httpx.Response(200, json=body))


def _fake_http(handler):
    real = openai.AsyncOpenAI

    def factory(*_args, **_kwargs):
        transport = httpx.MockTransport(handler)
        return real(
            api_key="sk-test",
            base_url="http://127.0.0.1:9/v1",
            http_client=httpx.AsyncClient(transport=transport),
            max_retries=0,
        )

    return patch("openai.AsyncOpenAI", side_effect=factory)


def _api():
    from econagents.adapters import llm

    assert hasattr(llm, "capture_llm_calls"), "econagents.adapters.llm has no capture_llm_calls"
    return llm


def _llm() -> ChatOpenAI:
    llm = ChatOpenAI()
    llm.observability = MagicMock()
    return llm


USAGE = {"input_tokens": 10, "output_tokens": 20, "reasoning_tokens": 5}


@pytest.mark.asyncio
async def test_completed_structured_response_is_recorded():
    api = _api()
    text = '{"reasoning": "r", "price": 10}'
    with _fake_api(_body("completed", text)), _api().capture_llm_calls() as calls:
        result = await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    assert result == _Decision(reasoning="r", price=10)
    assert calls == [api.LLMCallRecord("openai", "gpt-5.4-mini", "completed", USAGE, text, None)]


@pytest.mark.asyncio
async def test_unparsable_structured_response_is_recorded_and_the_error_reraised():
    text = '{"reasoning": "cut off'
    with _fake_api(_body("incomplete", text, "max_output_tokens")), _api().capture_llm_calls() as calls:
        with pytest.raises(ValidationError):
            await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    [record] = calls
    assert (record.finish_reason, record.usage, record.raw_output) == ("max_output_tokens", USAGE, text)
    assert record.parse_error
    assert record.response_error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["application/json", "text/html"])
async def test_a_non_response_body_is_reported_as_a_response_error_and_the_original_error_reraised(content_type):
    """A proxy page served with status 200 is no model output: no parse_error, the decoding error re-raised."""
    page = b"<html>502 Bad Gateway</html>"
    llm = _llm()
    with _fake_http(lambda request: httpx.Response(200, content=page, headers={"content-type": content_type})):
        with _api().capture_llm_calls() as calls:
            with pytest.raises(Exception) as raised:
                await llm.get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    [record] = calls
    assert (record.parse_error, record.raw_output, record.finish_reason) == (None, None, None)
    assert record.response_error == str(raised.value)
    if content_type == "application/json":
        assert isinstance(raised.value, json.JSONDecodeError)
    llm.observability.track_llm_call.assert_called_once()


@pytest.mark.asyncio
async def test_a_json_body_that_is_no_model_response_is_a_response_error():
    with _fake_api({"error": {"message": "overloaded"}}), _api().capture_llm_calls() as calls:
        with pytest.raises(Exception):
            await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    assert [(c.parse_error, c.response_error is not None) for c in calls] == [(None, True)]


@pytest.mark.asyncio
async def test_reasoning_only_response_is_recorded_without_output():
    with _fake_api(_body("incomplete", None, "max_output_tokens")), _api().capture_llm_calls() as calls:
        result = await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    assert result is None
    assert [(c.finish_reason, c.raw_output, c.parse_error) for c in calls] == [("max_output_tokens", None, None)]


@pytest.mark.asyncio
async def test_plain_text_response_is_recorded():
    with _fake_api(_body("completed", "hello")), _api().capture_llm_calls() as calls:
        result = await _llm().get_response([{"role": "user", "content": "x"}], {})

    assert result == "hello"
    assert [(c.finish_reason, c.raw_output) for c in calls] == [("completed", "hello")]


@pytest.mark.asyncio
async def test_calls_inside_wait_for_are_collected_and_nothing_leaks_outside():
    text = '{"reasoning": "r", "price": 1}'
    with _fake_api(_body("completed", text)):
        with _api().capture_llm_calls() as calls:
            await asyncio.wait_for(
                _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision), 5
            )
        await _llm().get_response([{"role": "user", "content": "x"}], {}, response_schema=_Decision)

    assert len(calls) == 1


def test_report_without_capture_is_a_no_op():
    api = _api()
    api.report_llm_call(api.LLMCallRecord("openai", None, None, None, None))
