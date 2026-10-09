"""IBEX-game_suite#7: a truncated structured response must not vanish from logs and observability.

When ``max_output_tokens`` cuts structured output mid-JSON, ``client.responses.parse`` raises a
pydantic ``ValidationError`` (json_invalid, EOF) inside the SDK. ``ChatOpenAI.get_response`` then
never reaches ``observability.track_llm_call`` or ``_log_response``, so the finish reason
(``incomplete_details.reason``) and token usage of the failed call are lost, although the
``logger`` contract promises "each full provider response (including reasoning and usage)".

The Responses API is served by ``httpx.MockTransport`` behind the real OpenAI SDK; no network.
"""

import logging
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest
from pydantic import BaseModel

from econagents.adapters.llm.openai import ChatOpenAI

TRUNCATED = '{"reasoning": "The project median is below my signal so I will bid at 10'


class _Decision(BaseModel):
    reasoning: str
    price: float


def _body(text: str | None) -> dict:
    output: list[dict] = [{"type": "reasoning", "id": "rs_1", "summary": []}]
    if text is not None:
        output.append(
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "incomplete",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.4-mini",
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 4000,
            "total_tokens": 5200,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 3990},
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


async def _call(body: dict, logger: logging.Logger):
    llm = ChatOpenAI(response_kwargs={"max_output_tokens": 4000})
    llm.observability = MagicMock()
    with _fake_api(body):
        try:
            await llm.get_response(
                [{"role": "user", "content": "decide"}], tracing_extra={}, response_schema=_Decision, logger=logger
            )
        except Exception:  # noqa: BLE001
            pass
    return llm.observability


@pytest.mark.asyncio
async def test_truncated_structured_response_still_reaches_the_logger(caplog):
    name = "gs7.llm.truncated"
    with caplog.at_level(logging.DEBUG, logger=name):
        await _call(_body(TRUNCATED), logging.getLogger(name))
    logged = "\n".join(r.getMessage() for r in caplog.records if r.name == name)
    assert "max_output_tokens" in logged and "4000" in logged, (
        "the truncated response's finish reason and usage were never logged (SDK raised before _log_response); "
        f"logger got: {logged!r}"
    )


@pytest.mark.asyncio
async def test_truncated_structured_response_still_reaches_observability():
    observability = await _call(_body(TRUNCATED), logging.getLogger("gs7.llm.observed"))
    assert observability.track_llm_call.call_count == 1, (
        "observability.track_llm_call was skipped for the truncated call "
        f"(calls={observability.track_llm_call.call_count}): its usage is lost"
    )
