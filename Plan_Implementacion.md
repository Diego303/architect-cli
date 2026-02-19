# Plan de Implementación: CLI Agentica Headless

## Resumen Ejecutivo

Herramienta CLI headless que orquesta agentes de IA para ejecutar tareas sobre archivos locales y servicios MCP remotos, usando LiteLLM como capa única de acceso a LLMs. Diseñada para funcionar sin supervisión en CI, cron y pipelines.

**Nombre de trabajo**: `architect`

---

## Decisiones Técnicas Clave

### ¿Por qué NO LangChain/LangGraph?

Tras evaluar el stack, la recomendación es **no usar LangChain ni LangGraph** para este proyecto. Razones:

1. **LiteLLM ya resuelve la abstracción de proveedores LLM.** LangChain añadiría una segunda capa de abstracción sobre algo que ya está abstraído — complejidad sin valor.
2. **El agent loop es sencillo y determinista.** LangGraph brilla en grafos complejos con múltiples ramas condicionales. Nuestro loop es lineal: `LLM → parse → validate → execute → repeat`. Implementarlo a mano son ~150 líneas de código claro vs. una dependencia de miles de líneas con conceptos propios (nodes, edges, state, checkpoints).
3. **Control total sobre el Execution Engine.** El sistema de políticas de confirmación, validación de paths y dry-run necesita estar integrado en el loop sin capas intermedias que dificulten el debugging.
4. **Menos dependencias = menos puntos de fallo.** Para una herramienta headless que corre en CI, cada dependencia es un riesgo. LangChain trae un árbol de dependencias considerable.

**Excepción**: Si en el futuro se necesitan flujos multi-agente complejos (agentes que se llaman entre sí, grafos con ciclos), LangGraph sería una buena opción. El diseño modular permite integrarlo sin reescribir.

### Stack Tecnológico

| Componente | Elección | Justificación |
|-----------|----------|---------------|
| Python | 3.12+ | Pattern matching, typing moderno, `tomllib` nativo |
| CLI parsing | `click` | Maduro, composable, buen soporte para subcomandos y grupos |
| Config | `PyYAML` + `pydantic` v2 | YAML para legibilidad, Pydantic para validación y defaults |
| LLM | `litellm` | Requisito del proyecto — abstrae 100+ proveedores |
| HTTP (MCP) | `httpx` | Async-capable, streaming nativo, timeouts granulares |
| Logging | `structlog` | JSON estructurado nativo, pipeline configurable |
| Packaging | `pyproject.toml` + `hatchling` | Estándar moderno, sin `setup.py` |

### Decisiones de Diseño Importantes

1. **Sync-first, async donde sea necesario.** El agent loop principal es síncrono (predecible, debuggable). Solo las llamadas HTTP a MCP y LiteLLM usan async internamente, pero se exponen con wrappers síncronos al loop.

2. **Tool calling nativo de LiteLLM.** Se usa el formato estándar de function calling de OpenAI que LiteLLM traduce automáticamente para cada proveedor. No se parsean respuestas en texto libre.

3. **Pydantic como fuente de verdad para schemas.** Cada tool define su schema como modelo Pydantic. De ahí se genera automáticamente el JSON Schema para el LLM y la validación de argumentos.

4. **Inmutabilidad del estado del agente.** Cada paso del loop produce un nuevo `AgentState` en vez de mutar uno existente. Esto facilita logging, debugging y eventual persistencia.

---

## Estructura del Proyecto

```
architect/
├── pyproject.toml
├── README.md
├── config.example.yaml
├── src/
│   └── architect/
│       ├── __init__.py
│       ├── __main__.py              # Entry point: python -m architect
│       ├── cli.py                   # Click CLI definition
│       ├── config/
│       │   ├── __init__.py
│       │   ├── schema.py            # Pydantic models para config
│       │   └── loader.py            # YAML + env + CLI merge
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── registry.py          # Registro y selección de agentes
│       │   ├── base.py              # AgentConfig dataclass
│       │   └── prompts.py           # System prompts por defecto
│       ├── core/
│       │   ├── __init__.py
│       │   ├── loop.py              # Agent loop principal
│       │   ├── state.py             # AgentState, StepResult, etc
│       │   └── context.py           # Construcción de contexto/mensajes
│       ├── llm/
│       │   ├── __init__.py
│       │   └── adapter.py           # Wrapper sobre LiteLLM
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── registry.py          # ToolRegistry (local + MCP)
│       │   ├── base.py              # BaseTool ABC + schema
│       │   ├── filesystem.py        # read_file, write_file, etc
│       │   └── schemas.py           # Pydantic models para args
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── client.py            # HTTP client para MCP
│       │   ├── discovery.py         # Descubrimiento de tools
│       │   └── adapter.py           # MCP tool → BaseTool wrapper
│       ├── execution/
│       │   ├── __init__.py
│       │   ├── engine.py            # Execution Engine central
│       │   ├── policies.py          # Políticas de confirmación
│       │   └── validators.py        # Validación de paths y args
│       └── logging/
│           ├── __init__.py
│           └── setup.py             # Configuración de structlog
├── tests/                           # Estructura preparada (no implementar ahora)
│   ├── conftest.py
│   ├── test_config/
│   ├── test_tools/
│   ├── test_core/
│   └── test_execution/
└── scripts/
    └── dev-setup.sh
```

---

## Fases de Implementación

### FASE 0 — Scaffolding y Configuración (Día 1)

**Objetivo**: Proyecto instalable con `pip install -e .`, CLI que responde a `--help`, config cargando correctamente.

#### 0.1 — pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "architect"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "pyyaml>=6.0",
    "pydantic>=2.5",
    "litellm>=1.40",
    "httpx>=0.27",
    "structlog>=24.1",
]

[project.scripts]
architect = "architect.cli:main"
```

#### 0.2 — Schema de Configuración (Pydantic)

```python
# src/architect/config/schema.py
from pydantic import BaseModel, Field
from typing import Literal
from pathlib import Path

class LLMConfig(BaseModel):
    provider: str = "litellm"
    mode: Literal["proxy", "direct"] = "direct"
    model: str = "gpt-4.1"
    api_base: str | None = None
    api_key_env: str = "LITELLM_API_KEY"
    timeout: int = 60
    retries: int = 2
    stream: bool = True

class AgentConfig(BaseModel):
    system_prompt: str
    allowed_tools: list[str] = Field(default_factory=list)
    confirm_mode: Literal["confirm-all", "confirm-sensitive", "yolo"] = "confirm-sensitive"
    max_steps: int = 20

class LoggingConfig(BaseModel):
    level: Literal["debug", "info", "warn", "error"] = "info"
    file: Path | None = None
    verbose: int = 0

class WorkspaceConfig(BaseModel):
    root: Path = Path(".")
    allow_delete: bool = False

class MCPServerConfig(BaseModel):
    name: str
    url: str
    token_env: str | None = None
    token: str | None = None

class MCPConfig(BaseModel):
    servers: list[MCPServerConfig] = Field(default_factory=list)

class AppConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
```

#### 0.3 — Config Loader (deep merge)

```python
# src/architect/config/loader.py
# Orden de precedencia: defaults → YAML → env vars → CLI args
# Deep merge usando dict recursivo, sin perder claves
# Pydantic valida el resultado final
```

Lógica clave del deep merge:

```python
def deep_merge(base: dict, override: dict) -> dict:
    """Merge recursivo. Override gana en conflictos de hojas."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

#### 0.4 — CLI base (Click)

```python
# src/architect/cli.py
@click.group()
def main(): ...

@main.command()
@click.argument("prompt")
@click.option("-c", "--config", type=click.Path(exists=True))
@click.option("-a", "--agent", default=None)
@click.option("-m", "--mode", type=click.Choice(["confirm-all","confirm-sensitive","yolo"]))
@click.option("-w", "--workspace", type=click.Path())
@click.option("--dry-run", is_flag=True)
@click.option("--model")
@click.option("--api-base")
@click.option("--api-key")
@click.option("--no-stream", is_flag=True)
@click.option("--mcp-config")
@click.option("--disable-mcp", is_flag=True)
@click.option("-v", "--verbose", count=True)
@click.option("--log-level")
@click.option("--log-file", type=click.Path())
@click.option("--max-steps", type=int)
@click.option("--timeout", type=int)
@click.option("--json", "json_output", is_flag=True)
@click.option("--quiet", is_flag=True)
def run(prompt, **kwargs): ...
```

**Entregable F0**: `pip install -e .` funciona, `architect run --help` muestra ayuda, `architect run "test" -c config.yaml` carga config y la imprime en debug.

---

### FASE 1 — Tools y Execution Engine (Día 2-3)

**Objetivo**: Sistema de tools local funcional con validación, políticas de confirmación y dry-run.

#### 1.1 — Base Tool (ABC)

```python
# src/architect/tools/base.py
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any

class ToolResult(BaseModel):
    success: bool
    output: str
    error: str | None = None

class BaseTool(ABC):
    name: str
    description: str
    sensitive: bool = False
    args_model: type[BaseModel]  # Pydantic model para validar args

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult: ...

    def get_schema(self) -> dict:
        """Genera JSON Schema compatible con OpenAI function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            }
        }
```

#### 1.2 — Tools del Filesystem

Cuatro tools con esta lógica:

| Tool | Sensible | Validaciones |
|------|----------|-------------|
| `read_file` | No | Path dentro de workspace, archivo existe |
| `write_file` | Sí | Path dentro de workspace, directorio padre existe o se crea |
| `delete_file` | Sí | Path dentro de workspace, `allow_delete=true` en config |
| `list_files` | No | Path dentro de workspace |

**Validación de paths** (crítica para seguridad):

```python
# src/architect/execution/validators.py
def validate_path(path: str, workspace_root: Path) -> Path:
    """
    Resuelve el path y verifica que esté dentro del workspace.
    Previene path traversal (../../etc/passwd).
    """
    resolved = (workspace_root / path).resolve()
    workspace_resolved = workspace_root.resolve()
    if not str(resolved).startswith(str(workspace_resolved)):
        raise PathTraversalError(f"Path {path} escapa del workspace")
    return resolved
```

#### 1.3 — Tool Registry

```python
# src/architect/tools/registry.py
class ToolRegistry:
    _tools: dict[str, BaseTool]

    def register(self, tool: BaseTool) -> None: ...
    def get(self, name: str) -> BaseTool: ...
    def list_all(self) -> list[BaseTool]: ...
    def get_schemas(self, allowed: list[str] | None = None) -> list[dict]: ...
    def filter_by_names(self, names: list[str]) -> list[BaseTool]: ...
```

#### 1.4 — Execution Engine

El componente más importante del sistema:

```python
# src/architect/execution/engine.py
class ExecutionEngine:
    def __init__(self, registry: ToolRegistry, config: AppConfig, confirm_mode: str):
        self.registry = registry
        self.config = config
        self.confirm_mode = confirm_mode
        self.dry_run = False

    def execute_tool_call(self, tool_name: str, args: dict) -> ToolResult:
        """
        Pipeline completo:
        1. Buscar tool en registry
        2. Validar argumentos (Pydantic)
        3. Validar paths si aplica
        4. Aplicar política de confirmación
        5. Ejecutar (o simular en dry-run)
        6. Loggear resultado
        7. Retornar resultado (nunca excepción al agent loop)
        """
```

#### 1.5 — Políticas de Confirmación

```python
# src/architect/execution/policies.py
import sys

class ConfirmationPolicy:
    def __init__(self, mode: str):
        self.mode = mode

    def should_confirm(self, tool: BaseTool) -> bool:
        match self.mode:
            case "yolo":
                return False
            case "confirm-all":
                return True
            case "confirm-sensitive":
                return tool.sensitive

    def request_confirmation(self, tool_name: str, args: dict) -> bool:
        if not sys.stdin.isatty():
            raise NoTTYError(
                f"Se requiere confirmación para '{tool_name}' "
                f"pero no hay TTY disponible. "
                f"Usa --mode yolo o --dry-run."
            )
        # Prompt al usuario
        response = input(f"¿Ejecutar {tool_name}({args})? [y/N]: ")
        return response.lower() in ("y", "yes", "sí", "si")
```

**Entregable F1**: `architect run "lee el archivo README.md" --dry-run` muestra qué haría sin ejecutar. Las tools funcionan aisladas con validación completa.

---

### FASE 2 — LLM Adapter + Agent Loop (Día 3-5)

**Objetivo**: Loop de agente completo que envía mensajes al LLM, recibe tool calls, las ejecuta, y devuelve resultados.

#### 2.1 — LLM Adapter

```python
# src/architect/llm/adapter.py
import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

class LLMAdapter:
    def __init__(self, config: LLMConfig):
        self.config = config
        self._configure_litellm()

    def _configure_litellm(self):
        if self.config.api_base:
            litellm.api_base = self.config.api_base
        # Configurar key desde env var
        api_key = os.environ.get(self.config.api_key_env)
        if api_key:
            litellm.api_key = api_key

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True
    )
    def completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> LLMResponse:
        """
        Llamada al LLM. Normaliza la respuesta a un formato interno.
        Retries automáticos con backoff exponencial.
        """
        response = litellm.completion(
            model=self.config.model,
            messages=messages,
            tools=tools if tools else None,
            stream=stream,
            timeout=self.config.timeout,
        )
        return self._normalize_response(response)
```

**Formato interno normalizado** (independiente del proveedor):

```python
# src/architect/llm/adapter.py
class LLMResponse(BaseModel):
    content: str | None = None          # Texto de respuesta
    tool_calls: list[ToolCall] = []     # Tool calls solicitadas
    finish_reason: str = "stop"         # stop | tool_calls | length
    usage: dict | None = None           # Tokens usados

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict
```

#### 2.2 — Agent State (inmutable)

```python
# src/architect/core/state.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class StepResult:
    step_number: int
    llm_response: LLMResponse
    tool_calls_made: list[ToolCallResult]
    timestamp: float

@dataclass(frozen=True)
class ToolCallResult:
    tool_name: str
    args: dict
    result: ToolResult
    was_confirmed: bool
    was_dry_run: bool

@dataclass
class AgentState:
    messages: list[dict] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    status: Literal["running", "success", "partial", "failed"] = "running"
    final_output: str | None = None

    @property
    def current_step(self) -> int:
        return len(self.steps)
```

#### 2.3 — Context Builder

```python
# src/architect/core/context.py
class ContextBuilder:
    """Construye la lista de mensajes para el LLM."""

    def build_initial(self, agent_config: AgentConfig, prompt: str) -> list[dict]:
        return [
            {"role": "system", "content": agent_config.system_prompt},
            {"role": "user", "content": prompt},
        ]

    def append_tool_results(
        self, messages: list[dict], tool_calls: list, results: list[ToolCallResult]
    ) -> list[dict]:
        """Añade assistant message con tool_calls + tool results."""
        # Formato estándar de OpenAI para tool results
        ...
```

#### 2.4 — Core Agent Loop

Este es el corazón del sistema:

```python
# src/architect/core/loop.py
class AgentLoop:
    def __init__(
        self,
        llm: LLMAdapter,
        engine: ExecutionEngine,
        agent_config: AgentConfig,
        context_builder: ContextBuilder,
        logger: structlog.BoundLogger,
    ):
        self.llm = llm
        self.engine = engine
        self.agent_config = agent_config
        self.ctx = context_builder
        self.log = logger

    def run(self, prompt: str) -> AgentState:
        state = AgentState()
        state.messages = self.ctx.build_initial(self.agent_config, prompt)
        tools_schema = self.engine.registry.get_schemas(
            self.agent_config.allowed_tools or None
        )

        for step in range(self.agent_config.max_steps):
            self.log.info("agent.step", step=step)

            # 1. Llamar al LLM
            try:
                response = self.llm.completion(
                    messages=state.messages,
                    tools=tools_schema if tools_schema else None,
                )
            except Exception as e:
                self.log.error("llm.error", error=str(e), step=step)
                state.status = "failed"
                state.final_output = f"Error LLM: {e}"
                break

            # 2. Si el LLM responde con texto final → terminar
            if response.finish_reason == "stop" and not response.tool_calls:
                state.final_output = response.content
                state.status = "success"
                self.log.info("agent.complete", step=step)
                break

            # 3. Si hay tool calls → ejecutarlas
            tool_results = []
            for tc in response.tool_calls:
                self.log.info("tool.call", tool=tc.name, args=tc.arguments)
                result = self.engine.execute_tool_call(tc.name, tc.arguments)
                tool_results.append(ToolCallResult(
                    tool_name=tc.name,
                    args=tc.arguments,
                    result=result,
                    was_confirmed=True,
                    was_dry_run=self.engine.dry_run,
                ))
                self.log.info("tool.result", tool=tc.name, success=result.success)

            # 4. Actualizar mensajes con resultados
            state.messages = self.ctx.append_tool_results(
                state.messages, response.tool_calls, tool_results
            )

            # 5. Registrar step
            state.steps.append(StepResult(
                step_number=step,
                llm_response=response,
                tool_calls_made=tool_results,
                timestamp=time.time(),
            ))
        else:
            # Se agotaron los pasos
            state.status = "partial"
            state.final_output = "Se alcanzó el límite de pasos."
            self.log.warn("agent.max_steps_reached")

        return state
```

**Manejo de errores en tools dentro del loop**: cuando una tool falla, **no se rompe el loop**. El error se devuelve al LLM como resultado de la tool para que pueda razonar sobre él:

```python
# Dentro del execute_tool_call del engine:
try:
    result = tool.execute(**validated_args)
except Exception as e:
    result = ToolResult(success=False, output="", error=str(e))
# Siempre retorna ToolResult, nunca propaga excepciones
```

**Entregable F2**: `architect run "crea un archivo hello.txt con 'hola mundo'" -a build --mode yolo` crea el archivo. El loop completo funciona: LLM → tool call → ejecución → resultado → LLM → respuesta final.

---

### FASE 3 — Sistema de Agentes (Día 5-6)

**Objetivo**: Agentes configurables desde YAML, modo mixto plan+build por defecto, agentes custom.

#### 3.1 — Agentes por Defecto

```python
# src/architect/agents/prompts.py
PLAN_PROMPT = """Eres un agente de planificación. Tu trabajo es:
1. Analizar la tarea del usuario
2. Descomponerla en pasos concretos y accionables
3. Identificar qué archivos necesitas leer o modificar
4. Devolver un plan estructurado

NUNCA ejecutes acciones directamente. Solo planifica.
Responde con un plan numerado y claro."""

BUILD_PROMPT = """Eres un agente de construcción. Tu trabajo es ejecutar tareas
sobre archivos usando las herramientas disponibles.

Reglas:
- Lee archivos antes de modificarlos para entender el contexto
- Haz cambios incrementales y explica cada paso
- Si algo falla, intenta una alternativa antes de rendirte
- Al terminar, resume qué hiciste y qué archivos cambiaste"""

RESUME_PROMPT = """Eres un agente de análisis y resumen. Tu trabajo es:
1. Leer los archivos o información indicados
2. Producir un resumen claro y estructurado
3. No modificar ningún archivo

Sé conciso pero completo."""

REVIEW_PROMPT = """Eres un agente de revisión de código. Tu trabajo es:
1. Leer los archivos indicados
2. Identificar problemas, mejoras posibles y buenas prácticas
3. No modificar ningún archivo
4. Dar feedback constructivo y accionable"""
```

#### 3.2 — Agentes por Defecto (Registro)

```python
# src/architect/agents/registry.py
DEFAULT_AGENTS = {
    "plan": AgentConfig(
        system_prompt=PLAN_PROMPT,
        allowed_tools=["read_file", "list_files"],
        confirm_mode="confirm-all",
        max_steps=5,
    ),
    "build": AgentConfig(
        system_prompt=BUILD_PROMPT,
        allowed_tools=["read_file", "write_file", "delete_file", "list_files"],
        confirm_mode="confirm-sensitive",
        max_steps=20,
    ),
    "resume": AgentConfig(
        system_prompt=RESUME_PROMPT,
        allowed_tools=["read_file", "list_files"],
        confirm_mode="yolo",
        max_steps=10,
    ),
    "review": AgentConfig(
        system_prompt=REVIEW_PROMPT,
        allowed_tools=["read_file", "list_files"],
        confirm_mode="yolo",
        max_steps=15,
    ),
}
```

#### 3.3 — Modo Mixto por Defecto (plan → build)

Cuando no se especifica agente, el sistema ejecuta un flujo de dos fases:

```python
# src/architect/core/loop.py
class MixedModeRunner:
    """Ejecuta plan primero, luego build con el plan como contexto."""

    def run(self, prompt: str) -> AgentState:
        # Fase 1: Plan
        plan_loop = AgentLoop(llm, engine, plan_config, ...)
        plan_state = plan_loop.run(prompt)

        if plan_state.status == "failed":
            return plan_state

        # Fase 2: Build con plan como contexto
        enriched_prompt = (
            f"El usuario pidió: {prompt}\n\n"
            f"Plan generado:\n{plan_state.final_output}\n\n"
            f"Ejecuta este plan paso a paso."
        )
        build_loop = AgentLoop(llm, engine, build_config, ...)
        return build_loop.run(enriched_prompt)
```

#### 3.4 — Agentes Custom desde YAML

Los agentes definidos en el YAML se mezclan con los defaults:

```python
# En el config loader:
def resolve_agents(yaml_agents: dict, defaults: dict) -> dict:
    merged = {**defaults}
    for name, config in yaml_agents.items():
        if name in merged:
            # Override parcial: solo los campos que el usuario definió
            merged[name] = merged[name].model_copy(update=config)
        else:
            # Nuevo agente custom
            merged[name] = AgentConfig(**config)
    return merged
```

Esto permite definir agentes personalizados en YAML:

```yaml
agents:
  deploy:
    system_prompt: "Eres un agente de deployment..."
    allowed_tools: [read_file, write_file]
    confirm_mode: confirm-all
    max_steps: 10
```

**Entregable F3**: `architect run "analiza este proyecto" -a review` funciona. `architect run "refactoriza main.py"` sin `-a` ejecuta plan+build. Agentes custom desde YAML funcionan.

---

### FASE 4 — MCP Connector (Día 6-8)

**Objetivo**: Conectar a servidores MCP remotos, descubrir tools dinámicamente, y hacerlas indistinguibles de las locales.

#### 4.1 — Cliente HTTP para MCP

```python
# src/architect/mcp/client.py
import httpx

class MCPClient:
    def __init__(self, server_config: MCPServerConfig):
        self.config = server_config
        self.base_url = server_config.url
        self.token = self._resolve_token()
        self.http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
            timeout=30.0,
        )

    def _resolve_token(self) -> str | None:
        if self.config.token:
            return self.config.token
        if self.config.token_env:
            return os.environ.get(self.config.token_env)
        return None

    def list_tools(self) -> list[dict]:
        """GET /tools → lista de tools MCP disponibles."""
        response = self.http.post("/", json={
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        })
        return response.json()["result"]["tools"]

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """POST / → ejecuta una tool MCP."""
        response = self.http.post("/", json={
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": 2,
        })
        return response.json()["result"]
```

#### 4.2 — Descubrimiento y Registro

```python
# src/architect/mcp/discovery.py
class MCPDiscovery:
    def discover_and_register(
        self, servers: list[MCPServerConfig], registry: ToolRegistry
    ) -> None:
        for server_config in servers:
            client = MCPClient(server_config)
            try:
                remote_tools = client.list_tools()
                for tool_def in remote_tools:
                    wrapped = MCPToolAdapter(
                        client=client,
                        tool_definition=tool_def,
                        server_name=server_config.name,
                    )
                    registry.register(wrapped)
            except Exception as e:
                log.warn("mcp.discovery_failed",
                         server=server_config.name, error=str(e))
                # No rompe — el agente funciona sin estas tools
```

#### 4.3 — MCP Tool → BaseTool Adapter

```python
# src/architect/mcp/adapter.py
class MCPToolAdapter(BaseTool):
    """Adapta una tool MCP remota al interfaz BaseTool local."""

    def __init__(self, client: MCPClient, tool_definition: dict, server_name: str):
        self.client = client
        self.name = f"mcp_{server_name}_{tool_definition['name']}"
        self.description = tool_definition.get("description", "")
        self.sensitive = True  # MCP tools son sensibles por defecto
        self._raw_schema = tool_definition.get("inputSchema", {})
        # Generar Pydantic model dinámico desde JSON Schema
        self.args_model = self._build_args_model()

    def execute(self, **kwargs) -> ToolResult:
        try:
            result = self.client.call_tool(
                self._original_name, kwargs
            )
            return ToolResult(
                success=True,
                output=str(result.get("content", "")),
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
```

**Punto clave**: Para el agente y el LLM, una tool MCP es **exactamente igual** que una tool local. Mismo schema, mismo formato de resultado, mismas políticas de confirmación.

**Entregable F4**: Con un servidor MCP en la config, `architect run "usa la tool X" --mode yolo` descubre y ejecuta tools remotas. Si el servidor no está disponible, el agente funciona sin esas tools.

---

### FASE 5 — Logging Completo (Día 8-9)

**Objetivo**: Logging estructurado JSON para archivos, logs humanos para stdout, niveles de verbose controlados.

#### 5.1 — Configuración de structlog

```python
# src/architect/logging/setup.py
import structlog
import logging
import sys

def configure_logging(config: LoggingConfig, json_output: bool, quiet: bool):
    """
    Dos pipelines independientes:
    1. Archivo → JSON estructurado (siempre, si se configura)
    2. Stdout → Humano legible (controlado por verbose/quiet)
    """
    processors_shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Pipeline para archivo (JSON)
    if config.file:
        file_handler = logging.FileHandler(config.file)
        file_handler.setLevel(logging.DEBUG)  # Siempre todo al archivo
        # ... configurar JSON renderer

    # Pipeline para stdout (humano)
    if not quiet:
        console_handler = logging.StreamHandler(sys.stderr)  # stderr para no romper pipes
        level = _verbose_to_level(config.verbose)
        console_handler.setLevel(level)
        # ... configurar ConsoleRenderer

def _verbose_to_level(verbose: int) -> int:
    """
    -v   → INFO (steps del agente, tool calls)
    -vv  → DEBUG (args, respuestas LLM)
    -vvv → TRACE (todo, incluyendo HTTP)
    sin -v → WARNING (solo problemas)
    """
    return {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}.get(
        verbose, logging.DEBUG
    )
```

#### 5.2 — Formato de Logs JSON

```json
{
  "timestamp": "2025-01-15T10:30:45.123Z",
  "level": "info",
  "event": "tool.call",
  "agent": "build",
  "step": 3,
  "tool": "write_file",
  "args": {"path": "src/main.py", "content": "..."},
  "duration_ms": 45
}
```

#### 5.3 — Logs de stdout por nivel

| Verbose | Muestra |
|---------|---------|
| (ninguno) | Solo errores y resultado final |
| `-v` | Steps del agente, tool calls (nombre) |
| `-vv` | Args de tools, respuestas resumidas del LLM |
| `-vvv` | Todo: HTTP, payloads completos, timing |

**Regla**: Los logs van a **stderr**. Solo el resultado final (o `--json`) va a **stdout**. Así nunca se rompen pipes:

```bash
architect run "resume este proyecto" --quiet | jq .
architect run "planifica migración" -v 2>agent.log
```

**Entregable F5**: `architect run "..." -vvv --log-file run.json` produce logs legibles en terminal y JSON estructurado en archivo.

---

### FASE 6 — Streaming + Output Final (Día 9-10)

**Objetivo**: Streaming del LLM visible en terminal, salida JSON estructurada, códigos de salida correctos.

#### 6.1 — Streaming

```python
# En el LLM adapter, cuando stream=True:
def completion_stream(self, messages, tools=None):
    """Yield chunks y al final retorna LLMResponse completa."""
    collected_content = []
    collected_tool_calls = []

    for chunk in litellm.completion(
        model=self.config.model,
        messages=messages,
        tools=tools,
        stream=True,
    ):
        delta = chunk.choices[0].delta
        if delta.content:
            collected_content.append(delta.content)
            yield StreamChunk(type="content", data=delta.content)
        if delta.tool_calls:
            # Acumular tool calls parciales
            ...

    # Retornar respuesta completa al final
    return self._assemble_response(collected_content, collected_tool_calls)
```

**Importante**: El streaming se muestra en stderr (para no romper pipes). Si `--quiet` o `--json`, no se muestra streaming.

#### 6.2 — Salida Estructurada

```python
# Formato de salida con --json
{
    "status": "success",          # success | partial | failed
    "output": "He creado...",     # Texto final del agente
    "steps": 5,                   # Pasos ejecutados
    "tools_used": [               # Resumen de tools
        {"name": "read_file", "path": "main.py", "success": true},
        {"name": "write_file", "path": "main.py", "success": true}
    ],
    "duration_seconds": 12.5,
    "model": "gpt-4.1"
}
```

#### 6.3 — Códigos de Salida

| Código | Significado |
|--------|-------------|
| 0 | Éxito (`SUCCESS`) |
| 1 | Fallo del agente (`FAILED`) |
| 2 | Parcial (`PARTIAL` — hizo algo pero no todo) |
| 3 | Error de configuración |
| 4 | Error de autenticación LLM |
| 5 | Timeout |
| 130 | Interrumpido por usuario (SIGINT) |

**Entregable F6**: Streaming visible en terminal, `--json` produce salida parseable, `echo $?` retorna códigos correctos.

---

### FASE 7 — Robustez y Tolerancia a Fallos (Día 10-11)

**Objetivo**: El sistema no se cae ante errores. Se recupera, informa, y termina limpiamente.

#### 7.1 — Retries en LLM

Ya implementado en F2 con `tenacity`. Adicional:

```python
# Manejar rate limits específicamente
@retry(
    retry=retry_if_exception_type((litellm.RateLimitError, litellm.ServiceUnavailableError)),
    stop=stop_after_attempt(config.retries + 1),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    before_sleep=lambda retry_state: log.warn(
        "llm.retry",
        attempt=retry_state.attempt_number,
        wait=retry_state.next_action.sleep,
    ),
)
```

#### 7.2 — Timeout por Step

```python
import signal

class StepTimeout:
    def __init__(self, seconds: int):
        self.seconds = seconds

    def __enter__(self):
        if self.seconds > 0:
            signal.signal(signal.SIGALRM, self._handler)
            signal.alarm(self.seconds)
        return self

    def __exit__(self, *args):
        signal.alarm(0)

    def _handler(self, signum, frame):
        raise StepTimeoutError(f"Step excedió {self.seconds}s")
```

#### 7.3 — Errores de Tool → Feedback al Agente

```python
# En el agent loop, si una tool falla:
tool_result = ToolResult(
    success=False,
    output="",
    error="Error: el archivo no existe. ¿Quizás el path es incorrecto?"
)
# Esto se envía al LLM como resultado de la tool
# El LLM puede razonar sobre el error e intentar otra cosa
```

#### 7.4 — Graceful Shutdown

```python
import signal

class GracefulShutdown:
    def __init__(self):
        self._interrupted = False
        signal.signal(signal.SIGINT, self._handler)
        signal.signal(signal.SIGTERM, self._handler)

    def _handler(self, signum, frame):
        if self._interrupted:
            sys.exit(130)  # Segundo SIGINT → salir inmediatamente
        self._interrupted = True
        log.warn("shutdown.requested", signal=signum)

    @property
    def should_stop(self) -> bool:
        return self._interrupted
```

El agent loop consulta `should_stop` antes de cada step.

**Entregable F7**: El sistema se recupera de errores de LLM (retries), errores de tools (feedback al agente), timeouts (termina limpiamente), y SIGINT (graceful shutdown).

---

### FASE 8 — Integración Final y Pulido (Día 11-12)

**Objetivo**: Todo conectado, probado manualmente, documentación básica.

#### 8.1 — Flujo completo en `cli.py`

```python
@main.command()
def run(prompt, **kwargs):
    # 1. Cargar config (YAML + overrides)
    config = load_config(kwargs)

    # 2. Configurar logging
    configure_logging(config.logging, kwargs["json_output"], kwargs["quiet"])

    # 3. Configurar LLM
    llm = LLMAdapter(config.llm)

    # 4. Configurar tools
    registry = ToolRegistry()
    register_filesystem_tools(registry, config.workspace)

    # 5. Descubrir MCP tools
    if not kwargs["disable_mcp"]:
        MCPDiscovery().discover_and_register(config.mcp.servers, registry)

    # 6. Configurar Execution Engine
    agent_config = resolve_agent(kwargs["agent"], config.agents)
    engine = ExecutionEngine(registry, config, agent_config.confirm_mode)
    engine.dry_run = kwargs["dry_run"]

    # 7. Ejecutar agent loop
    shutdown = GracefulShutdown()
    loop = AgentLoop(llm, engine, agent_config, ContextBuilder(), log)
    loop.shutdown_signal = shutdown

    state = loop.run(prompt)

    # 8. Output
    if kwargs["json_output"]:
        print(json.dumps(state.to_output_dict()))
    elif not kwargs["quiet"]:
        print(state.final_output or "Sin resultado.")

    # 9. Exit code
    sys.exit({"success": 0, "partial": 2, "failed": 1}.get(state.status, 1))
```

#### 8.2 — config.example.yaml completo

Incluir un ejemplo comentado con todas las opciones disponibles.

#### 8.3 — README.md

Documentación mínima pero útil con: instalación, quickstart, configuración, ejemplos.

---

## Cronograma Resumido

| Fase | Días | Entregable |
|------|------|-----------|
| F0 — Scaffolding | 1 | Proyecto instalable, CLI con `--help` |
| F1 — Tools + Engine | 2 | Tools locales + validación + dry-run |
| F2 — LLM + Loop | 2 | Agent loop completo funcional |
| F3 — Agentes | 1 | Agentes configurables, modo mixto |
| F4 — MCP | 2 | Conexión y descubrimiento MCP |
| F5 — Logging | 1 | Logs estructurados + stdout |
| F6 — Streaming + Output | 1 | Streaming + JSON + exit codes |
| F7 — Robustez | 1 | Retries + timeouts + graceful shutdown |
| F8 — Integración | 1 | Todo conectado + docs |
| **Total** | **~12 días** | **MVP funcional completo** |

---

## Dependencias entre Fases

```
F0 (scaffolding)
 ├── F1 (tools + engine)
 │    └── F2 (LLM + loop)   ← requiere F0 + F1
 │         ├── F3 (agentes)  ← requiere F2
 │         ├── F6 (streaming) ← requiere F2
 │         └── F7 (robustez)  ← requiere F2
 ├── F4 (MCP)               ← requiere F1 (registry)
 └── F5 (logging)            ← requiere F0 (puede hacerse en paralelo)

F8 (integración)             ← requiere todo lo anterior
```

---

## Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|-----------|
| LiteLLM no soporta tool calling con algún proveedor | Alto | Fallback a parsing de texto (modo degradado) |
| Servidores MCP no estándar | Medio | Validación defensiva, logs claros, never crash |
| Streaming rompe pipes | Alto | Streaming siempre a stderr, stdout solo para output final |
| Path traversal en tools | Crítico | Validación estricta con `resolve()` + prefix check |
| LLM genera tool calls inválidas | Medio | Validación Pydantic antes de ejecutar, error devuelto al LLM |
| Rate limits del LLM | Medio | Retries con backoff exponencial |
| Agente entra en loop infinito | Alto | `max_steps` hard limit + timeout global |

---

## Extensiones Futuras (post-MVP)

1. **Persistencia de estado**: Guardar y reanudar ejecuciones parciales.
2. **Multi-agente**: Un agente delegando a otros.
3. **Plugin system**: Tools cargadas desde paquetes Python externos.
4. **Web UI opcional**: Dashboard para ver logs en tiempo real (sin romper headless).
5. **Testing framework**: Tests unitarios y de integración para agents y tools.
6. **Prompt caching**: Cache de respuestas del LLM para desarrollo.
7. **Métricas**: Tokens usados, costes estimados, duración por step.

---

## Principios que Guían la Implementación

1. **Cada componente tiene una única responsabilidad.** Si una clase hace dos cosas, dividirla.
2. **Las excepciones nunca cruzan fronteras de componente sin transformarse.** Cada capa captura y traduce.
3. **El LLM nunca ejecuta directamente.** Siempre pasa por validación + políticas.
4. **Los logs son ciudadanos de primera clase.** Si algo pasa y no se loggeó, no pasó.
5. **La configuración fluye hacia abajo, nunca hacia arriba.** Los componentes reciben config, no la buscan.
6. **Fallar parcialmente es mejor que fallar completamente.** `PARTIAL` > `FAILED`.
7. **El código más simple que funciona es el mejor código.** Sin abstracciones prematuras.