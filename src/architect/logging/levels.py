"""
Nivel de logging HUMAN — Trazabilidad legible del agente.

v3-M5: Nivel custom entre INFO (20) y WARNING (30).
No indica severidad — indica trazabilidad de alto nivel para que el usuario
pueda seguir qué hace el agente sin ruido técnico.

Jerarquía:
    debug  (10) → HTTP payloads, args completos, timing
    info   (20) → Operaciones del sistema (config loaded, tool registered)
    human  (25) → ★ Qué hace el agente: LLM call, tool use, resultado
    warn   (30) → Problemas no fatales
    error  (40) → Errores
"""

import logging

# Nivel custom: entre INFO (20) y WARNING (30)
HUMAN = 25
logging.addLevelName(HUMAN, "HUMAN")
