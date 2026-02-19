"""
Módulo LLM - Adapter para LiteLLM y gestión de llamadas a LLMs.

Exporta el LLMAdapter y modelos de respuesta.
"""

from .adapter import LLMAdapter, LLMResponse, StreamChunk, ToolCall

__all__ = [
    "LLMAdapter",
    "LLMResponse",
    "StreamChunk",
    "ToolCall",
]
