"""
Módulo LLM - Adapter para LiteLLM y gestión de llamadas a LLMs.

Exporta el LLMAdapter, modelos de respuesta y cache local.
"""

from .adapter import LLMAdapter, LLMResponse, StreamChunk, ToolCall
from .cache import LocalLLMCache

__all__ = [
    "LLMAdapter",
    "LLMResponse",
    "StreamChunk",
    "ToolCall",
    "LocalLLMCache",
]
