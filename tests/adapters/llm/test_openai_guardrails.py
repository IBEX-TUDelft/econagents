"""Request limits and moderation of ``ChatOpenAI`` (and the request limits of ``ChatOpenRouter``).

On by default: a request timeout of 120 seconds. Settings: the retry count, moderation of the input and
output on the same call (reported, never blocking) and a safety identifier.
"""

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from econagents.adapters.llm import capture_llm_calls
from econagents.adapters.llm.base import DEFAULT_TIMEOUT_S, sdk_client_options
from econagents.adapters.llm.openai import MODERATION_MODEL, ChatOpenAI, _moderation
from econagents.adapters.llm.openrouter import ChatOpenRouter

MESSAGES = [{"role": "user", "content": "Hello"}]


class _Schema(BaseModel):
    action: str


def moderation_result(flagged: bool, **scores: float) -> SimpleNamespace:
    return SimpleNamespace(
        type="moderation_result",
        flagged=flagged,
        categories={name: score >= 0.5 for name, score in scores.items()},
        category_scores=dict(scores),
        category_applied_input_types={name: ["text"] for name in scores},
        model="omni-moderation-2024-09-26",
    )


def response(moderation: Any = None) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp_1", model="gpt-5.4-mini", status="completed", incomplete_details=None, usage=None, output=[],
        output_text="ok", output_parsed=None, moderation=moderation,
    )  # fmt: skip


async def call(llm: ChatOpenAI, reply: Any, schema: type[BaseModel] | None = None) -> tuple[MagicMock, dict[str, Any]]:
    """Run one request against a mocked client; return the client class mock and the request's keyword arguments."""
    client = MagicMock()
    client.responses.create = AsyncMock(return_value=reply)
    raw = MagicMock()
    raw.parse.return_value = reply
    client.responses.with_raw_response.parse = AsyncMock(return_value=raw)
    llm.observability = MagicMock()
    with patch("openai.AsyncOpenAI", return_value=client) as client_class:
        await llm.get_response(MESSAGES, tracing_extra={}, response_schema=schema)
    request = client.responses.create if schema is None else client.responses.with_raw_response.parse
    return client_class, request.call_args.kwargs


class TestClientOptions:
    def test_none_leaves_the_packages_defaults(self):
        assert sdk_client_options(None, None) == {}

    def test_values_are_passed_on(self):
        assert sdk_client_options(30, 0) == {"timeout": 30.0, "max_retries": 0}
        assert sdk_client_options(2.5, 3) == {"timeout": 2.5, "max_retries": 3}

    @pytest.mark.parametrize("timeout", [0, -1, True, "30"])
    def test_a_timeout_must_be_a_positive_number(self, timeout):
        with pytest.raises(ValueError, match="timeout"):
            sdk_client_options(timeout, None)

    @pytest.mark.parametrize("max_retries", [-1, True, 1.5, "2"])
    def test_max_retries_must_be_a_non_negative_integer(self, max_retries):
        with pytest.raises(ValueError, match="max_retries"):
            sdk_client_options(None, max_retries)


class TestRequestLimits:
    @pytest.mark.asyncio
    async def test_a_request_times_out_after_120_seconds_by_default(self):
        client_class, request = await call(ChatOpenAI(), response())

        assert DEFAULT_TIMEOUT_S == 120.0
        client_class.assert_called_once_with(api_key=None, timeout=120.0)
        assert "timeout" not in request and "max_retries" not in request

    @pytest.mark.asyncio
    async def test_none_restores_the_packages_timeout(self):
        client_class, _ = await call(ChatOpenAI(timeout=None), response())

        client_class.assert_called_once_with(api_key=None)

    @pytest.mark.asyncio
    async def test_timeout_and_retries_are_set_on_the_client(self):
        client_class, _ = await call(ChatOpenAI(api_key="k", timeout=30, max_retries=0), response())

        client_class.assert_called_once_with(api_key="k", timeout=30.0, max_retries=0)

    def test_invalid_limits_fail_at_construction(self):
        with pytest.raises(ValueError, match="timeout"):
            ChatOpenAI(timeout=0)
        with pytest.raises(ValueError, match="max_retries"):
            ChatOpenAI(max_retries=-1)
        with patch("importlib.util.find_spec", return_value=True):
            with pytest.raises(ValueError, match="timeout"):
                ChatOpenRouter(timeout=-5)

    @pytest.mark.asyncio
    async def test_openrouter_gets_the_same_limits(self):
        reply = MagicMock()
        reply.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=None))]
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=reply)
        llm = ChatOpenRouter(api_key="k", max_retries=1)
        llm.observability = MagicMock()
        with patch("openai.AsyncOpenAI", return_value=client) as client_class:
            await llm.get_response(MESSAGES, tracing_extra={})

        assert client_class.call_args.kwargs["timeout"] == 120.0
        assert client_class.call_args.kwargs["max_retries"] == 1


class TestRequestParameters:
    @pytest.mark.asyncio
    async def test_nothing_is_added_by_default(self):
        _, request = await call(ChatOpenAI(), response())

        assert "moderation" not in request and "safety_identifier" not in request

    @pytest.mark.asyncio
    async def test_moderation_true_names_the_default_model(self):
        _, request = await call(ChatOpenAI(moderation=True), response())

        assert request["moderation"] == {"model": MODERATION_MODEL} == {"model": "omni-moderation-latest"}

    @pytest.mark.asyncio
    async def test_moderation_takes_a_model_name(self):
        _, request = await call(ChatOpenAI(moderation="omni-moderation-2024-09-26"), response())

        assert request["moderation"] == {"model": "omni-moderation-2024-09-26"}

    @pytest.mark.asyncio
    async def test_a_structured_request_carries_them_too(self):
        llm = ChatOpenAI(moderation=True, safety_identifier="3f1c9a")
        _, request = await call(llm, response(), schema=_Schema)

        assert request["moderation"] == {"model": MODERATION_MODEL}
        assert request["safety_identifier"] == "3f1c9a"
        assert request["text_format"] is _Schema

    @pytest.mark.asyncio
    async def test_response_kwargs_win_over_the_settings(self):
        policy = {"model": "omni-moderation-latest", "policy": {"input": {"mode": "score"}}}
        llm = ChatOpenAI(moderation=True, response_kwargs={"moderation": policy, "store": False})
        _, request = await call(llm, response())

        assert request["moderation"] == policy
        assert request["store"] is False

    @pytest.mark.parametrize("moderation", ["", 1, None, {"model": "x"}])
    def test_an_invalid_moderation_setting_fails_at_construction(self, moderation):
        with pytest.raises(ValueError, match="moderation"):
            ChatOpenAI(moderation=moderation)

    @pytest.mark.parametrize("identifier", ["", 7])
    def test_an_invalid_safety_identifier_fails_at_construction(self, identifier):
        with pytest.raises(ValueError, match="safety_identifier"):
            ChatOpenAI(safety_identifier=identifier)

    def test_an_openai_package_without_the_parameters_fails_at_construction(self):
        old_package = frozenset({"model", "input", "max_output_tokens"})
        with patch("econagents.adapters.llm.openai._responses_parameters", return_value=old_package):
            with pytest.raises(ImportError, match="moderation and safety_identifier need a newer openai"):
                ChatOpenAI(moderation=True, safety_identifier="3f1c9a")
            ChatOpenAI()

    def test_the_installed_openai_package_has_the_parameters(self):
        ChatOpenAI(moderation=True, safety_identifier="3f1c9a")


class TestModerationRecord:
    def test_a_response_without_moderation_has_none(self):
        assert _moderation(response()) is None
        assert _moderation(MagicMock()) is None
        assert _moderation(None) is None

    def test_results_are_reported_as_plain_data(self):
        moderation = SimpleNamespace(
            input=moderation_result(True, harassment=0.91, violence=0.02),
            output=moderation_result(False, harassment=0.01, violence=0.0),
        )

        assert _moderation(response(moderation)) == {
            "input": {
                "flagged": True,
                "categories": ["harassment"],
                "category_scores": {"harassment": 0.91, "violence": 0.02},
                "model": "omni-moderation-2024-09-26",
            },
            "output": {
                "flagged": False,
                "categories": [],
                "category_scores": {"harassment": 0.01, "violence": 0.0},
                "model": "omni-moderation-2024-09-26",
            },
        }

    def test_a_moderation_failure_is_reported_as_an_error(self):
        moderation = SimpleNamespace(
            input=SimpleNamespace(type="error", code="moderation_unavailable", message="try again"),
            output=None,
        )

        assert _moderation(response(moderation)) == {
            "input": {"error": "moderation_unavailable", "message": "try again"}
        }

    def test_a_response_held_as_a_dict_is_read_too(self):
        body = {
            "moderation": {
                "input": {
                    "type": "moderation_result",
                    "flagged": False,
                    "categories": {"hate": False},
                    "category_scores": {"hate": 0.1},
                    "model": "m",
                }
            }
        }

        assert _moderation(body) == {
            "input": {"flagged": False, "categories": [], "category_scores": {"hate": 0.1}, "model": "m"}
        }

    @pytest.mark.asyncio
    async def test_the_call_record_carries_the_moderation_and_flagged_content_is_logged(self, caplog):
        moderation = SimpleNamespace(
            input=moderation_result(True, harassment=0.91, hate=0.7), output=moderation_result(False, harassment=0.0)
        )
        with capture_llm_calls() as calls, caplog.at_level(logging.WARNING):
            await call(ChatOpenAI(moderation=True), response(moderation))

        [record] = calls
        assert record.moderation["input"]["flagged"] is True
        assert record.moderation["output"]["flagged"] is False
        assert record.raw_output == "ok", "moderation never blocks or changes the response"
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == ["Moderation flagged the input of a gpt-5.4-mini call: harassment, hate"]

    @pytest.mark.asyncio
    async def test_unflagged_content_logs_nothing(self, caplog):
        moderation = SimpleNamespace(
            input=moderation_result(False, hate=0.0), output=moderation_result(False, hate=0.0)
        )
        with capture_llm_calls() as calls, caplog.at_level(logging.WARNING):
            await call(ChatOpenAI(moderation=True), response(moderation))

        assert calls[0].moderation is not None
        assert not caplog.records

    @pytest.mark.asyncio
    async def test_without_moderation_the_record_has_none(self):
        with capture_llm_calls() as calls:
            await call(ChatOpenAI(), response())

        assert calls[0].moderation is None
