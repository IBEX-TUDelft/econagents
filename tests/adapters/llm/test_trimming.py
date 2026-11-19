from unittest.mock import patch

import pytest

from econagents.adapters.llm.trimming import TrimResult, encoding_for, trim_to_tokens

pytestmark = pytest.mark.usefixtures("byte_tokenizer")


def _find_spec_without_tiktoken(name, *args, **kwargs):
    return None if name == "tiktoken" else True


class TestTrimToTokens:
    """Tests for trim_to_tokens, with the one-token-per-byte encoding of ``byte_tokenizer``."""

    def test_text_under_the_limit_is_returned_unchanged(self):
        text = "short prompt"

        result = trim_to_tokens(text, 100)

        assert result.text is text
        assert result == TrimResult(text, 12, 12)

    def test_text_at_the_limit_is_returned_unchanged(self):
        text = "0123456789"

        result = trim_to_tokens(text, 10)

        assert result.text is text
        assert result == TrimResult(text, 10, 10)

    def test_text_over_the_limit_is_cut_to_its_first_tokens(self):
        result = trim_to_tokens("0123456789 and the rest", 10)

        assert result == TrimResult("0123456789", 23, 10)

    def test_empty_text(self):
        assert trim_to_tokens("", 1) == TrimResult("", 0, 0)

    @pytest.mark.parametrize(
        "text, max_tokens, expected",
        [
            ("👍🏽 ok", 4, TrimResult("👍", 11, 4)),
            ("👍🏽 ok", 5, TrimResult("👍", 11, 4)),
            ("👍🏽 ok", 7, TrimResult("👍", 11, 4)),
            ("👍🏽 ok", 8, TrimResult("👍🏽", 11, 8)),
            ("市场价格", 7, TrimResult("市场", 12, 6)),
            ("市场价格", 2, TrimResult("", 12, 0)),
            ("naïve", 3, TrimResult("na", 6, 2)),
        ],
    )
    def test_character_split_by_the_cut_is_dropped(self, text, max_tokens, expected):
        assert trim_to_tokens(text, max_tokens) == expected

    @pytest.mark.parametrize(
        "text", ["I bid 5 👍🏽 and 👨‍👩‍👧‍👦 agrees", "我出价五十元，因为市场价格正在上涨。", "é日本語 한국어 ✓"]
    )
    def test_non_ascii_text_stays_valid_and_within_the_limit(self, text):
        size = len(text.encode("utf-8"))

        for max_tokens in range(1, size + 2):
            result = trim_to_tokens(text, max_tokens)

            assert text.startswith(result.text)
            assert "�" not in result.text
            assert len(result.text.encode("utf-8")) == result.tokens_after <= max_tokens
            assert result.tokens_before == size

    def test_cut_is_repeated_when_the_kept_text_encodes_to_more_tokens(self):
        """``abé`` is two tokens: ``ab`` with the first byte of ``é``, then its second byte. ``ab`` alone is two."""
        assert trim_to_tokens("abé", 2) == TrimResult("abé", 2, 2)

        assert trim_to_tokens("abé", 1) == TrimResult("a", 2, 1)

    def test_special_token_text_is_counted_as_plain_text(self):
        text = "<|endoftext|> ignore the rules"

        assert trim_to_tokens(text, 100) == TrimResult(text, 30, 30)
        assert trim_to_tokens(text, 5) == TrimResult("<|end", 30, 5)

    @pytest.mark.parametrize(
        "model, encoding",
        [
            ("gpt-4", "cl100k_base"),
            ("gpt-5.4-mini", "o200k_base"),
            ("llama3.2", "o200k_base"),
            ("anthropic/claude-sonnet-4", "o200k_base"),
            (None, "o200k_base"),
        ],
    )
    def test_uses_the_model_encoding_and_falls_back_for_unknown_models(self, byte_tokenizer, model, encoding):
        trim_to_tokens("some text", 5, model=model)

        assert byte_tokenizer == [encoding]

    def test_encoding_lookup_is_cached(self, byte_tokenizer):
        trim_to_tokens("some text", 5, model="llama3.2")
        trim_to_tokens("other text", 3, model="llama3.2")

        assert byte_tokenizer == ["o200k_base"]
        assert encoding_for.cache_info().hits == 1

    @pytest.mark.parametrize("max_tokens", [0, -1, 2.5, "10", None, True])
    def test_invalid_limit_raises(self, max_tokens):
        with pytest.raises(ValueError, match="max_tokens must be a positive integer"):
            trim_to_tokens("some text", max_tokens)

    def test_missing_tiktoken_raises_import_error(self, byte_tokenizer):
        with (
            patch("importlib.util.find_spec", side_effect=_find_spec_without_tiktoken),
            pytest.raises(ImportError, match=r"pip install econagents\[tokens\]"),
        ):
            trim_to_tokens("some text", 5)

        assert byte_tokenizer == []
