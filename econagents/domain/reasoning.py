"""Collect the reasoning behind a decision while it is being made."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_captured: ContextVar[tuple[list[str], ...]] = ContextVar("econagents_reasoning", default=())


@contextmanager
def capture_reasoning() -> Iterator[list[str]]:
    """Collect every text passed to ``report_reasoning`` inside the ``with`` block, in order.

    The list is shared with tasks started inside the block. Blocks nest: a text is added to every
    enclosing block.
    """
    texts: list[str] = []
    token = _captured.set((*_captured.get(), texts))
    try:
        yield texts
    finally:
        _captured.reset(token)


def report_reasoning(text: Optional[str]) -> None:
    """Record why the decision being made was taken; blank or ``None`` text is ignored.

    ``Role.handle_phase_with_llm`` calls it with the decision's reasoning field. A phase handler that
    decides without it can call it directly.
    """
    if not isinstance(text, str) or not text.strip():
        return
    for texts in _captured.get():
        texts.append(text.strip())
