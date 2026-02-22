# Crear un MCP Server de Architect

Guía para construir un servidor MCP (Model Context Protocol) que exponga `architect` como herramienta remota. Esto permite que otros agentes de IA — un asistente de IDE, un chatbot de Slack, u otro architect — deleguen la implementación de código a architect via JSON-RPC 2.0.

---

## Índice

- [Concepto](#concepto)
- [Arquitectura](#arquitectura)
- [Requisitos](#requisitos)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Implementación: tools.py](#implementación-toolspy)
- [Implementación: server.py](#implementación-serverpy)
- [Ejecución y pruebas](#ejecución-y-pruebas)
- [Conectar desde architect como cliente](#conectar-desde-architect-como-cliente)
- [Despliegue en contenedor](#despliegue-en-contenedor)
- [Buenas prácticas](#buenas-prácticas)

---

## Concepto

Architect se instala como paquete Python y se invoca via CLI. Un servidor MCP puede wrappear esas invocaciones con `subprocess` y exponerlas como tools JSON-RPC 2.0. Así, cualquier cliente MCP (incluido otro architect) puede pedir:

- "Implementa esta feature en `/workspace`"
- "Revisa el código y dame un informe"
- "Planifica cómo refactorizar este módulo"
- "Genera tests para esta función"

Cada petición se traduce internamente a un `architect run "..." --mode yolo --json` y el resultado se devuelve como respuesta MCP.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│  Cliente MCP (otro agente, IDE, chatbot)                │
│  → tools/call: architect_implement_code                 │
└──────────────────────────┬──────────────────────────────┘
                           │ JSON-RPC 2.0 / HTTP
                           ▼
┌─────────────────────────────────────────────────────────┐
│  MCP Server (server.py)                                 │
│                                                         │
│  Tools registradas:                                     │
│  ├── architect_implement_code   → build agent           │
│  ├── architect_review_code      → review agent          │
│  ├── architect_plan_task        → plan agent            │
│  ├── architect_generate_tests   → build agent (tests)   │
│  ├── architect_generate_docs    → build agent (docs)    │
│  └── architect_run_custom       → cualquier prompt      │
│                                                         │
│  Cada tool invoca:                                      │
│    subprocess.run(["architect", "run", ...])            │
└──────────────────────────┬──────────────────────────────┘
                           │ subprocess
                           ▼
┌─────────────────────────────────────────────────────────┐
│  architect CLI                                          │
│  --mode yolo --json --quiet --budget N                  │
│                                                         │
│  Lee/escribe archivos en el workspace                   │
│  Ejecuta tests/linters si --allow-commands              │
│  Retorna JSON a stdout                                  │
└─────────────────────────────────────────────────────────┘
```

---

## Requisitos

```bash
# Instalar architect
git clone -b main --single-branch https://github.com/Diego303/architect-cli.git
cd architect-cli && pip install -e .

# Instalar el SDK oficial de MCP para Python
pip install mcp

# Verificar
architect --version
python -c "import mcp; print('MCP SDK OK')"
```

La API key del LLM debe estar disponible como variable de entorno:

```bash
export LITELLM_API_KEY="sk-..."
```

---

## Estructura del proyecto

```
architect-mcp-server/
├── server.py          # Servidor MCP (punto de entrada)
├── tools.py           # Funciones que invocan architect via subprocess
├── config.yaml        # Configuración de architect (opcional)
├── requirements.txt   # Dependencias
└── Containerfile      # Para despliegue en contenedor
```

**requirements.txt:**

```
mcp>=1.0
```

---

## Implementación: tools.py

Este módulo encapsula todas las invocaciones a architect. Cada función ejecuta `architect run` como subprocess, parsea el JSON de salida y devuelve un resultado estructurado.

```python
"""
Tools que invocan architect CLI via subprocess.

Cada función ejecuta architect con --mode yolo --json --quiet
y retorna un dict con el resultado parseado. Todas las funciones
manejan errores de subprocess, timeouts y JSON inválido.
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Timeout por defecto para subprocess (5 minutos)
DEFAULT_TIMEOUT = 300

# Budget por defecto en USD por invocación
DEFAULT_BUDGET = 2.0


@dataclass(frozen=True)
class ArchitectResult:
    """Resultado parseado de una invocación a architect CLI."""

    success: bool
    status: str
    output: str
    steps: int
    exit_code: int
    cost_usd: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "success": self.success,
            "status": self.status,
            "output": self.output,
            "steps": self.steps,
            "exit_code": self.exit_code,
        }
        if self.cost_usd is not None:
            d["cost_usd"] = self.cost_usd
        if self.error is not None:
            d["error"] = self.error
        return d


def _run_architect(
    prompt: str,
    workspace: str,
    agent: str = "build",
    model: str | None = None,
    budget: float = DEFAULT_BUDGET,
    timeout: int = DEFAULT_TIMEOUT,
    allow_commands: bool = False,
    self_eval: str = "off",
    config_path: str | None = None,
    extra_args: list[str] | None = None,
) -> ArchitectResult:
    """Ejecuta architect CLI como subprocess y parsea el resultado.

    Args:
        prompt: Descripción de la tarea.
        workspace: Path absoluto al directorio de trabajo.
        agent: Agente a usar (build, plan, review, resume).
        model: Modelo LLM (None usa el default de config/env).
        budget: Límite de gasto en USD.
        timeout: Timeout del subprocess en segundos.
        allow_commands: Habilitar run_command tool.
        self_eval: Modo de auto-evaluación (off, basic, full).
        config_path: Path al archivo config.yaml.
        extra_args: Argumentos CLI adicionales.

    Returns:
        ArchitectResult con el resultado parseado.
    """
    # Validar workspace
    workspace_path = Path(workspace)
    if not workspace_path.is_dir():
        return ArchitectResult(
            success=False,
            status="failed",
            output="",
            steps=0,
            exit_code=-1,
            error=f"Workspace no existe o no es un directorio: {workspace}",
        )

    # Construir comando
    cmd = [
        "architect", "run", prompt,
        "--mode", "yolo",
        "--json",
        "--quiet",
        "-w", str(workspace_path.resolve()),
        "-a", agent,
        "--budget", str(budget),
        "--show-costs",
    ]

    if model:
        cmd.extend(["--model", model])

    if allow_commands:
        cmd.append("--allow-commands")

    if self_eval != "off":
        cmd.extend(["--self-eval", self_eval])

    if config_path:
        cmd.extend(["-c", config_path])

    if extra_args:
        cmd.extend(extra_args)

    logger.info(
        "Ejecutando architect: agent=%s workspace=%s budget=%.2f",
        agent, workspace, budget,
    )

    # Ejecutar subprocess
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(workspace_path),
        )
    except subprocess.TimeoutExpired:
        logger.error("Timeout ejecutando architect (%ds)", timeout)
        return ArchitectResult(
            success=False,
            status="failed",
            output="",
            steps=0,
            exit_code=-1,
            error=f"Timeout: architect no terminó en {timeout}s",
        )
    except FileNotFoundError:
        logger.error("architect CLI no encontrado en PATH")
        return ArchitectResult(
            success=False,
            status="failed",
            output="",
            steps=0,
            exit_code=-1,
            error="architect CLI no está instalado o no está en PATH",
        )
    except OSError as e:
        logger.error("Error ejecutando architect: %s", e)
        return ArchitectResult(
            success=False,
            status="failed",
            output="",
            steps=0,
            exit_code=-1,
            error=f"Error de sistema: {e}",
        )

    # Parsear JSON de stdout
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        # Si no es JSON válido, capturar stdout como texto plano
        logger.warning("architect no retornó JSON válido (exit code %d)", result.returncode)
        return ArchitectResult(
            success=result.returncode == 0,
            status="failed" if result.returncode != 0 else "success",
            output=result.stdout.strip() or result.stderr.strip(),
            steps=0,
            exit_code=result.returncode,
            error=result.stderr.strip() if result.returncode != 0 else None,
        )

    # Extraer campos del JSON
    status = data.get("status", "failed")
    cost_usd = None
    costs = data.get("costs")
    if isinstance(costs, dict):
        cost_usd = costs.get("total_cost_usd")

    return ArchitectResult(
        success=status == "success",
        status=status,
        output=data.get("output") or "",
        steps=data.get("steps", 0),
        exit_code=result.returncode,
        cost_usd=cost_usd,
        error=data.get("stop_reason") if status != "success" else None,
    )


# ─── Tools públicas ──────────────────────────────────────────────────────


def implement_code(
    prompt: str,
    workspace: str,
    model: str | None = None,
    budget: float = DEFAULT_BUDGET,
    allow_commands: bool = True,
    self_eval: str = "basic",
    config_path: str | None = None,
) -> ArchitectResult:
    """Implementa código según una descripción en lenguaje natural.

    Usa el agente build: lee el proyecto, planifica cambios, edita archivos,
    y opcionalmente ejecuta tests para verificar.

    Args:
        prompt: Qué implementar (ej: "añade validación de email a user.py").
        workspace: Directorio del proyecto.
        model: Modelo LLM a usar.
        budget: Límite de gasto en USD.
        allow_commands: Permitir ejecución de tests/linters.
        self_eval: Auto-evaluación (off, basic, full).
        config_path: Config YAML de architect.

    Returns:
        ArchitectResult con el resultado de la implementación.
    """
    return _run_architect(
        prompt=prompt,
        workspace=workspace,
        agent="build",
        model=model,
        budget=budget,
        allow_commands=allow_commands,
        self_eval=self_eval,
        config_path=config_path,
    )


def review_code(
    prompt: str,
    workspace: str,
    model: str | None = None,
    budget: float = 0.50,
    config_path: str | None = None,
) -> ArchitectResult:
    """Revisa código y genera un informe de calidad.

    Usa el agente review: solo lectura, busca bugs, vulnerabilidades,
    code smells y oportunidades de mejora.

    Args:
        prompt: Qué revisar (ej: "revisa src/auth/ buscando vulnerabilidades").
        workspace: Directorio del proyecto.
        model: Modelo LLM a usar.
        budget: Límite de gasto en USD.
        config_path: Config YAML de architect.

    Returns:
        ArchitectResult con el informe de review.
    """
    return _run_architect(
        prompt=prompt,
        workspace=workspace,
        agent="review",
        model=model,
        budget=budget,
        config_path=config_path,
    )


def plan_task(
    prompt: str,
    workspace: str,
    model: str | None = None,
    budget: float = 0.50,
    config_path: str | None = None,
) -> ArchitectResult:
    """Genera un plan de implementación sin modificar archivos.

    Usa el agente plan: lee el proyecto y produce un plan detallado
    con archivos a crear/modificar, cambios concretos y orden.

    Args:
        prompt: Qué planificar (ej: "¿cómo añadir autenticación JWT?").
        workspace: Directorio del proyecto.
        model: Modelo LLM a usar.
        budget: Límite de gasto en USD.
        config_path: Config YAML de architect.

    Returns:
        ArchitectResult con el plan de implementación.
    """
    return _run_architect(
        prompt=prompt,
        workspace=workspace,
        agent="plan",
        model=model,
        budget=budget,
        config_path=config_path,
    )


def generate_tests(
    prompt: str,
    workspace: str,
    model: str | None = None,
    budget: float = DEFAULT_BUDGET,
    config_path: str | None = None,
) -> ArchitectResult:
    """Genera tests unitarios para el código indicado.

    Usa el agente build con un prompt orientado a testing.
    Permite ejecución de comandos para que el agente pueda
    correr los tests que genera y verificar que pasan.

    Args:
        prompt: Qué testear (ej: "genera tests para src/services/payment.py").
        workspace: Directorio del proyecto.
        model: Modelo LLM a usar.
        budget: Límite de gasto en USD.
        config_path: Config YAML de architect.

    Returns:
        ArchitectResult con el resultado de la generación.
    """
    full_prompt = (
        f"{prompt}\n\n"
        "Genera tests unitarios completos con pytest. "
        "Cubre flujos normales, errores y edge cases. "
        "Ejecuta los tests al final para verificar que pasan."
    )
    return _run_architect(
        prompt=full_prompt,
        workspace=workspace,
        agent="build",
        model=model,
        budget=budget,
        allow_commands=True,
        self_eval="basic",
        config_path=config_path,
    )


def generate_docs(
    prompt: str,
    workspace: str,
    model: str | None = None,
    budget: float = 1.0,
    config_path: str | None = None,
) -> ArchitectResult:
    """Genera o actualiza documentación del proyecto.

    Usa el agente build con un prompt orientado a documentación.

    Args:
        prompt: Qué documentar (ej: "genera docs de la API REST en docs/api.md").
        workspace: Directorio del proyecto.
        model: Modelo LLM a usar.
        budget: Límite de gasto en USD.
        config_path: Config YAML de architect.

    Returns:
        ArchitectResult con el resultado de la generación.
    """
    full_prompt = (
        f"{prompt}\n\n"
        "Genera documentación clara en formato Markdown. "
        "Lee el código fuente para extraer la información real. "
        "No inventes datos que no estén en el código."
    )
    return _run_architect(
        prompt=full_prompt,
        workspace=workspace,
        agent="build",
        model=model,
        budget=budget,
        allow_commands=False,
        config_path=config_path,
    )


def run_custom(
    prompt: str,
    workspace: str,
    agent: str = "build",
    model: str | None = None,
    budget: float = DEFAULT_BUDGET,
    allow_commands: bool = False,
    self_eval: str = "off",
    config_path: str | None = None,
) -> ArchitectResult:
    """Ejecuta architect con un prompt y configuración arbitrarios.

    Tool genérica para cualquier tarea que no encaje en las tools
    específicas. Expone todos los parámetros de configuración.

    Args:
        prompt: Tarea a realizar.
        workspace: Directorio del proyecto.
        agent: Agente a usar (build, plan, review, resume).
        model: Modelo LLM a usar.
        budget: Límite de gasto en USD.
        allow_commands: Permitir ejecución de comandos.
        self_eval: Modo de auto-evaluación.
        config_path: Config YAML de architect.

    Returns:
        ArchitectResult con el resultado.
    """
    return _run_architect(
        prompt=prompt,
        workspace=workspace,
        agent=agent,
        model=model,
        budget=budget,
        allow_commands=allow_commands,
        self_eval=self_eval,
        config_path=config_path,
    )
```

---

## Implementación: server.py

El servidor usa el SDK oficial de MCP para Python. Registra cada tool con su schema JSON y maneja las peticiones JSON-RPC 2.0 automáticamente.

```python
"""
MCP Server que expone architect CLI como herramientas remotas.

Ejecutar:
    python server.py                     # Modo stdio (para clientes locales)
    python server.py --transport http    # Modo HTTP (para clientes remotos)
    python server.py --port 8080         # HTTP en puerto custom

Cada tool invoca architect via subprocess con --mode yolo --json.
"""

import argparse
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

import tools

# ── Logging ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("architect-mcp")

# ── Server MCP ────────────────────────────────────────────────────────────

server = Server("architect-mcp")


# ── Registro de tools ─────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Retorna la lista de tools disponibles con sus schemas."""
    return [
        Tool(
            name="architect_implement_code",
            description=(
                "Implementa código en un proyecto según una descripción "
                "en lenguaje natural. Lee el proyecto, planifica cambios, "
                "edita archivos y opcionalmente ejecuta tests para verificar."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Descripción de qué implementar",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Path absoluto al directorio del proyecto",
                    },
                    "model": {
                        "type": "string",
                        "description": "Modelo LLM (ej: gpt-4o, claude-sonnet-4-6). Opcional.",
                    },
                    "budget": {
                        "type": "number",
                        "description": "Límite de gasto en USD (default: 2.0)",
                        "default": 2.0,
                    },
                    "allow_commands": {
                        "type": "boolean",
                        "description": "Permitir ejecución de tests/linters (default: true)",
                        "default": True,
                    },
                    "self_eval": {
                        "type": "string",
                        "description": "Auto-evaluación: off, basic, full (default: basic)",
                        "enum": ["off", "basic", "full"],
                        "default": "basic",
                    },
                },
                "required": ["prompt", "workspace"],
            },
        ),
        Tool(
            name="architect_review_code",
            description=(
                "Revisa código y genera un informe de calidad: "
                "bugs, vulnerabilidades, code smells y oportunidades de mejora. "
                "Solo lectura, no modifica archivos."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Qué revisar (ej: 'revisa src/auth/ buscando vulnerabilidades')",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Path absoluto al directorio del proyecto",
                    },
                    "model": {
                        "type": "string",
                        "description": "Modelo LLM. Opcional.",
                    },
                    "budget": {
                        "type": "number",
                        "description": "Límite de gasto en USD (default: 0.50)",
                        "default": 0.50,
                    },
                },
                "required": ["prompt", "workspace"],
            },
        ),
        Tool(
            name="architect_plan_task",
            description=(
                "Analiza un proyecto y genera un plan de implementación "
                "detallado sin modificar archivos. Incluye archivos afectados, "
                "cambios concretos y orden de ejecución."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Qué planificar (ej: '¿cómo añadir autenticación JWT?')",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Path absoluto al directorio del proyecto",
                    },
                    "model": {
                        "type": "string",
                        "description": "Modelo LLM. Opcional.",
                    },
                    "budget": {
                        "type": "number",
                        "description": "Límite de gasto en USD (default: 0.50)",
                        "default": 0.50,
                    },
                },
                "required": ["prompt", "workspace"],
            },
        ),
        Tool(
            name="architect_generate_tests",
            description=(
                "Genera tests unitarios para código existente. "
                "Lee el código fuente, genera tests con pytest, "
                "y ejecuta los tests para verificar que pasan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Qué testear (ej: 'genera tests para src/services/payment.py')",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Path absoluto al directorio del proyecto",
                    },
                    "model": {
                        "type": "string",
                        "description": "Modelo LLM. Opcional.",
                    },
                    "budget": {
                        "type": "number",
                        "description": "Límite de gasto en USD (default: 2.0)",
                        "default": 2.0,
                    },
                },
                "required": ["prompt", "workspace"],
            },
        ),
        Tool(
            name="architect_generate_docs",
            description=(
                "Genera o actualiza documentación técnica del proyecto "
                "en formato Markdown. Lee el código fuente para extraer "
                "información real."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Qué documentar (ej: 'genera docs de la API REST')",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Path absoluto al directorio del proyecto",
                    },
                    "model": {
                        "type": "string",
                        "description": "Modelo LLM. Opcional.",
                    },
                    "budget": {
                        "type": "number",
                        "description": "Límite de gasto en USD (default: 1.0)",
                        "default": 1.0,
                    },
                },
                "required": ["prompt", "workspace"],
            },
        ),
        Tool(
            name="architect_run_custom",
            description=(
                "Ejecuta architect con un prompt y configuración arbitrarios. "
                "Tool genérica para tareas que no encajen en las tools específicas."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Tarea a realizar",
                    },
                    "workspace": {
                        "type": "string",
                        "description": "Path absoluto al directorio del proyecto",
                    },
                    "agent": {
                        "type": "string",
                        "description": "Agente: build, plan, review, resume (default: build)",
                        "enum": ["build", "plan", "review", "resume"],
                        "default": "build",
                    },
                    "model": {
                        "type": "string",
                        "description": "Modelo LLM. Opcional.",
                    },
                    "budget": {
                        "type": "number",
                        "description": "Límite de gasto en USD (default: 2.0)",
                        "default": 2.0,
                    },
                    "allow_commands": {
                        "type": "boolean",
                        "description": "Permitir ejecución de comandos (default: false)",
                        "default": False,
                    },
                    "self_eval": {
                        "type": "string",
                        "description": "Auto-evaluación: off, basic, full (default: off)",
                        "enum": ["off", "basic", "full"],
                        "default": "off",
                    },
                },
                "required": ["prompt", "workspace"],
            },
        ),
    ]


# ── Handlers de tools ─────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Despacha la invocación de una tool al handler correspondiente."""
    logger.info("Tool invocada: %s", name)

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return [TextContent(
            type="text",
            text=f"Tool desconocida: {name}",
        )]

    try:
        result = handler(arguments)
    except Exception as e:
        logger.exception("Error ejecutando tool %s", name)
        return [TextContent(
            type="text",
            text=f"Error interno ejecutando {name}: {e}",
        )]

    # Formatear respuesta
    if result.success:
        text = result.output
        if result.cost_usd is not None:
            text += f"\n\n[Coste: ${result.cost_usd:.4f} | Steps: {result.steps}]"
    else:
        text = f"Error ({result.status}): {result.error or 'desconocido'}"
        if result.output:
            text += f"\n\nOutput parcial:\n{result.output}"

    return [TextContent(type="text", text=text)]


# ── Mapeo de tools a handlers ─────────────────────────────────────────────

def _handle_implement(args: dict) -> tools.ArchitectResult:
    return tools.implement_code(
        prompt=args["prompt"],
        workspace=args["workspace"],
        model=args.get("model"),
        budget=args.get("budget", 2.0),
        allow_commands=args.get("allow_commands", True),
        self_eval=args.get("self_eval", "basic"),
    )


def _handle_review(args: dict) -> tools.ArchitectResult:
    return tools.review_code(
        prompt=args["prompt"],
        workspace=args["workspace"],
        model=args.get("model"),
        budget=args.get("budget", 0.50),
    )


def _handle_plan(args: dict) -> tools.ArchitectResult:
    return tools.plan_task(
        prompt=args["prompt"],
        workspace=args["workspace"],
        model=args.get("model"),
        budget=args.get("budget", 0.50),
    )


def _handle_generate_tests(args: dict) -> tools.ArchitectResult:
    return tools.generate_tests(
        prompt=args["prompt"],
        workspace=args["workspace"],
        model=args.get("model"),
        budget=args.get("budget", 2.0),
    )


def _handle_generate_docs(args: dict) -> tools.ArchitectResult:
    return tools.generate_docs(
        prompt=args["prompt"],
        workspace=args["workspace"],
        model=args.get("model"),
        budget=args.get("budget", 1.0),
    )


def _handle_run_custom(args: dict) -> tools.ArchitectResult:
    return tools.run_custom(
        prompt=args["prompt"],
        workspace=args["workspace"],
        agent=args.get("agent", "build"),
        model=args.get("model"),
        budget=args.get("budget", 2.0),
        allow_commands=args.get("allow_commands", False),
        self_eval=args.get("self_eval", "off"),
    )


TOOL_HANDLERS = {
    "architect_implement_code": _handle_implement,
    "architect_review_code": _handle_review,
    "architect_plan_task": _handle_plan,
    "architect_generate_tests": _handle_generate_tests,
    "architect_generate_docs": _handle_generate_docs,
    "architect_run_custom": _handle_run_custom,
}


# ── Punto de entrada ──────────────────────────────────────────────────────

async def main_stdio():
    """Ejecuta el servidor MCP en modo stdio."""
    logger.info("Iniciando architect MCP server (stdio)")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="Architect MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transporte: stdio (default) o http",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Puerto para transporte HTTP (default: 8080)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        import asyncio
        asyncio.run(main_stdio())

    elif args.transport == "http":
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Route
        import uvicorn

        sse = SseServerTransport("/messages")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1],
                    server.create_initialization_options(),
                )

        app = Starlette(routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
        ])

        logger.info("Iniciando architect MCP server HTTP en puerto %d", args.port)
        uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
```

---

## Ejecución y pruebas

### Modo stdio (desarrollo local)

```bash
# El servidor lee/escribe JSON-RPC por stdin/stdout
python server.py
```

Para probar manualmente, envía JSON-RPC por stdin:

```bash
# Listar tools
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python server.py

# Invocar una tool
echo '{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "architect_review_code",
    "arguments": {
      "prompt": "revisa el código buscando bugs",
      "workspace": "/home/user/mi-proyecto"
    }
  }
}' | python server.py
```

### Modo HTTP (para clientes remotos)

```bash
# Instalar dependencias HTTP
pip install uvicorn starlette

# Iniciar
python server.py --transport http --port 8080
```

Probar con curl:

```bash
# Listar tools
curl -X POST http://localhost:8080/messages \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

### Test unitario del módulo tools

```python
# test_tools.py
"""Tests para tools.py — validan la invocación de architect via subprocess."""

import json
from unittest.mock import patch, MagicMock

import tools


def _mock_subprocess_success():
    """Simula una ejecución exitosa de architect."""
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = json.dumps({
        "status": "success",
        "stop_reason": "llm_done",
        "output": "Implementación completada. Se editó user.py.",
        "steps": 3,
        "tools_used": [
            {"name": "read_file", "success": True, "path": "user.py"},
            {"name": "edit_file", "success": True, "path": "user.py"},
        ],
        "duration_seconds": 8.5,
        "costs": {"total_cost_usd": 0.0042},
    })
    mock.stderr = ""
    return mock


def _mock_subprocess_failure():
    """Simula una ejecución fallida de architect."""
    mock = MagicMock()
    mock.returncode = 4
    mock.stdout = json.dumps({
        "status": "failed",
        "stop_reason": None,
        "output": None,
        "steps": 0,
    })
    mock.stderr = "Error de autenticación: API key inválida"
    return mock


@patch("subprocess.run")
def test_implement_code_success(mock_run):
    mock_run.return_value = _mock_subprocess_success()

    result = tools.implement_code(
        prompt="añade validación",
        workspace="/tmp/test-workspace",
    )

    assert result.success is True
    assert result.status == "success"
    assert "user.py" in result.output
    assert result.cost_usd == 0.0042
    assert result.exit_code == 0


@patch("subprocess.run")
def test_implement_code_auth_error(mock_run):
    mock_run.return_value = _mock_subprocess_failure()

    result = tools.implement_code(
        prompt="añade validación",
        workspace="/tmp/test-workspace",
    )

    assert result.success is False
    assert result.exit_code == 4


@patch("subprocess.run", side_effect=FileNotFoundError)
def test_implement_code_not_installed(mock_run):
    result = tools.implement_code(
        prompt="test",
        workspace="/tmp/test-workspace",
    )

    assert result.success is False
    assert "no está instalado" in result.error


def test_implement_code_invalid_workspace():
    result = tools.implement_code(
        prompt="test",
        workspace="/ruta/que/no/existe",
    )

    assert result.success is False
    assert "no existe" in result.error


@patch("subprocess.run", side_effect=tools.subprocess.TimeoutExpired(cmd="architect", timeout=300))
def test_implement_code_timeout(mock_run):
    result = tools.implement_code(
        prompt="test",
        workspace="/tmp/test-workspace",
    )

    assert result.success is False
    assert "Timeout" in result.error
```

---

## Conectar desde architect como cliente

Un architect puede usar este servidor MCP como tool remota. Así un agente orquestador delega implementación a otro architect.

```yaml
# config-orquestador.yaml
llm:
  model: claude-sonnet-4-6

mcp:
  servers:
    - name: architect
      url: http://localhost:8080
      # token_env: ARCHITECT_MCP_TOKEN  # Si añades autenticación
```

```bash
# El agente orquestador puede pedir:
architect run \
  "Lee el ticket PROJ-42 y usa architect_implement_code \
   para implementar lo que pide en /workspace/myapp" \
  -c config-orquestador.yaml \
  --mode yolo
```

Internamente, architect descubre las tools del servidor MCP al inicio y las registra con prefijo `mcp_architect_`:

- `mcp_architect_architect_implement_code`
- `mcp_architect_architect_review_code`
- `mcp_architect_architect_plan_task`
- etc.

El LLM las ve como tools normales y puede invocarlas cuando lo considere apropiado.

---

## Despliegue en contenedor

```dockerfile
# Containerfile.mcp-server
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Instalar architect
RUN git clone -b main --single-branch \
      https://github.com/Diego303/architect-cli.git /opt/architect-cli && \
    cd /opt/architect-cli && pip install --no-cache-dir -e .

# Instalar dependencias del MCP server
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Instalar dependencias HTTP (para transporte SSE)
RUN pip install --no-cache-dir uvicorn starlette

# Copiar código del servidor
COPY server.py tools.py /app/

WORKDIR /app

ENV ARCHITECT_WORKSPACE=/workspace
ENV HOME=/tmp

EXPOSE 8080

ENTRYPOINT ["python", "server.py"]
CMD ["--transport", "http", "--port", "8080"]
```

```bash
# Build
docker build -t architect-mcp-server -f Containerfile.mcp-server .

# Run
docker run -d \
  -p 8080:8080 \
  -e LITELLM_API_KEY="${LITELLM_API_KEY}" \
  -v /ruta/a/proyectos:/workspace \
  architect-mcp-server
```

---

## Buenas prácticas

### Seguridad

- **No exponer el servidor a internet sin autenticación.** El servidor ejecuta código arbitrario via architect. Añade un middleware de autenticación (Bearer token, mTLS) si lo expones fuera de localhost.
- **Usar `--budget` siempre.** Sin budget, una petición maliciosa puede consumir tokens indefinidamente.
- **Validar workspace.** El módulo `tools.py` valida que el workspace exista antes de invocar architect. Considera añadir una whitelist de workspaces permitidos.
- **No pasar `--api-key` por argumentos.** Usa variables de entorno (`LITELLM_API_KEY`). Los argumentos del proceso son visibles en `ps aux`.

### Robustez

- **Timeout de subprocess.** Todas las invocaciones tienen timeout (default 300s). Sin timeout, un architect colgado bloquea el servidor indefinidamente.
- **Manejo de errores exhaustivo.** El `_run_architect()` captura: `TimeoutExpired`, `FileNotFoundError`, `OSError`, y `JSONDecodeError`. Nunca propaga excepciones al cliente MCP.
- **Resultado siempre estructurado.** `ArchitectResult` garantiza que siempre hay `success`, `status` y `exit_code`, incluso en errores de sistema.
- **Logging a stderr.** El servidor loguea todas las invocaciones y errores. Los logs no se mezclan con la comunicación JSON-RPC.

### Rendimiento

- **Un subprocess por petición.** Cada tool call lanza un proceso architect independiente. Para concurrencia alta, considera un pool de workers o un servidor async con `asyncio.create_subprocess_exec`.
- **Prompt caching.** Si el servidor recibe peticiones repetidas sobre el mismo proyecto, activa `prompt_caching: true` en la config de architect para reducir costes y latencia.
- **Modelos ligeros para reviews.** Usa `gpt-4o-mini` para `review_code` y `plan_task` (solo lectura, no necesitan capacidad de edición avanzada). Reserva `gpt-4o` o `claude-sonnet-4-6` para `implement_code`.

### Extensibilidad

- **Añadir nuevas tools** es añadir una función en `tools.py`, registrar el `Tool` en `list_tools()`, y crear un handler en `TOOL_HANDLERS`. El patrón es siempre el mismo.
- **Config YAML custom.** Cada tool puede recibir `config_path` para usar una configuración de architect diferente. Útil para separar configs de review (modelo barato) vs implementación (modelo potente).
- **Agentes custom.** Puedes definir agentes custom en el config YAML de architect (documenter, tester, security) y exponerlos como tools MCP con `run_custom(agent="documenter")`.
