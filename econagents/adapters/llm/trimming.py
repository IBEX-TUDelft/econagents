"""Cut a text to a number of tokens."""

import importlib.util
from functools import lru_cache
from typing import TYPE_CHECKING, NamedTuple, Optional

if TYPE_CHECKING:
    import tiktoken

FALLBACK_ENCODING = "o200k_base"


class TrimResult(NamedTuple):
    """A text cut to a token limit, with its token count before and after the cut."""

    text: str
    tokens_before: int
    tokens_after: int


def check_token_limit(value: object, name: str = "max_tokens") -> None:
    """Raise ``ValueError`` unless ``value`` is a positive integer."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


@lru_cache(maxsize=None)
def encoding_for(model: Optional[str] = None) -> "tiktoken.Encoding":
    """Return tiktoken's encoding for ``model``, or ``o200k_base`` when tiktoken does not know the model.

    tiktoken downloads the file of an encoding the first time it is used and caches it on disk.

    Raises:
        ImportError: If tiktoken is not installed.
    """
    if not importlib.util.find_spec("tiktoken"):
        raise ImportError(
            "max_message_tokens needs tiktoken, which is not installed. Install it with: pip install econagents[tokens]"
        )
    import tiktoken

    try:
        name = tiktoken.encoding_name_for_model(model) if model else FALLBACK_ENCODING
    except KeyError:
        name = FALLBACK_ENCODING
    return tiktoken.get_encoding(name)


def trim_to_tokens(text: str, max_tokens: int, model: Optional[str] = None) -> TrimResult:
    """Cut ``text`` to its first ``max_tokens`` tokens.

    Tokens are counted with tiktoken's encoding for ``model``. tiktoken only knows OpenAI model names.
    For any other name (most Ollama and OpenRouter models) ``o200k_base`` is used, so the count is an
    estimate of what the model's own tokenizer gives.

    A text at or under the limit is returned unchanged. A cut never leaves part of a character: a
    character split by the cut is dropped, and the returned text encodes to at most ``max_tokens``
    tokens. Text that spells a special token (for example ``<|endoftext|>``) is counted as plain text.

    Raises:
        ValueError: If ``max_tokens`` is not a positive integer.
        ImportError: If tiktoken is not installed.
    """
    check_token_limit(max_tokens)
    encoding = encoding_for(model)
    tokens = encoding.encode_ordinary(text)
    tokens_before = len(tokens)
    # Dropping a split character can leave text that encodes to more tokens than were kept, so cut until it fits.
    while len(tokens) > max_tokens:
        text = encoding.decode(tokens[:max_tokens], errors="ignore")
        tokens = encoding.encode_ordinary(text)
    return TrimResult(text, tokens_before, len(tokens))
