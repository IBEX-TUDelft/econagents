from econagents.adapters.llm.base import BaseLLM
from econagents.adapters.llm.call_records import capture_llm_calls, report_llm_call
from econagents.adapters.llm.observability import ObservabilityProvider, get_observability_provider
from econagents.adapters.llm.openai import ChatOpenAI
from econagents.adapters.llm.openrouter import ChatOpenRouter
from econagents.ports.llm import LLMCallRecord, LLMProvider

try:
    from econagents.adapters.llm.ollama import ChatOllama
except ImportError:
    pass

__all__: list[str] = [
    "BaseLLM",
    "ChatOpenAI",
    "ChatOpenRouter",
    "LLMCallRecord",
    "LLMProvider",
    "ObservabilityProvider",
    "capture_llm_calls",
    "get_observability_provider",
    "report_llm_call",
]
