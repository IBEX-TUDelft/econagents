"""Collect the provider-reported metadata of model calls made within a context."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from econagents.ports.llm import LLMCallRecord

_captured: ContextVar[tuple[list[LLMCallRecord], ...]] = ContextVar("econagents_llm_calls", default=())


@contextmanager
def capture_llm_calls() -> Iterator[list[LLMCallRecord]]:
    """Collect an ``LLMCallRecord`` for every provider response received inside the ``with`` block.

    The list is shared with tasks started inside the block, so a call wrapped in ``asyncio.wait_for``
    is collected too. Blocks nest: a record is added to every enclosing block. Adapters that do not
    report records leave the list empty.
    """
    calls: list[LLMCallRecord] = []
    token = _captured.set((*_captured.get(), calls))
    try:
        yield calls
    finally:
        _captured.reset(token)


def report_llm_call(record: LLMCallRecord) -> None:
    """Add ``record`` to every active ``capture_llm_calls`` block, if any."""
    for calls in _captured.get():
        calls.append(record)
