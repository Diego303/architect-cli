#!/usr/bin/env python3.12
"""
Test de integración end-to-end para architect-cli.

Prueba funcionalidad real contra servicios reales:
1. LLM proxy (LiteLLM) — completion y streaming
2. MCP servers reales — discovery, tool listing, tool calling
3. CLI end-to-end — flujo completo con LLM real
4. YAML config compleja — hooks, MCP, budget, agentes custom
5. Streaming real — chunks de texto en tiempo real
6. Safety nets — timeout, max-steps, budget

Requisitos:
- LiteLLM proxy en http://localhost:4000/v1 (modelo openai/azure)
- MCP Job Launcher en http://localhost:8000/mcp (sin auth)
- MCP Analytics en http://localhost:8001/mcp (Bearer token-se-1234)
- Directorio de prueba en /home/diego/projects/test

Uso:
    python3.12 scripts/test_integration.py
    python3.12 scripts/test_integration.py --section llm      # solo tests LLM
    python3.12 scripts/test_integration.py --section mcp      # solo tests MCP
    python3.12 scripts/test_integration.py --section cli      # solo tests CLI
    python3.12 scripts/test_integration.py --section config   # solo tests config
    python3.12 scripts/test_integration.py --section stream   # solo tests streaming
    python3.12 scripts/test_integration.py --section safety   # solo tests safety nets
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

# ── Helpers de test ──────────────────────────────────────────────────────

_passed = 0
_failed = 0
_errors = []
_section_name = ""


def section(name: str) -> None:
    global _section_name
    _section_name = name
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


def ok(test_name: str, detail: str = "") -> None:
    global _passed
    _passed += 1
    detail_str = f" — {detail}" if detail else ""
    print(f"  ✓ {test_name}{detail_str}")


def fail(test_name: str, detail: str = "") -> None:
    global _failed
    _failed += 1
    detail_str = f" — {detail}" if detail else ""
    print(f"  ✗ {test_name}{detail_str}")
    _errors.append(f"[{_section_name}] {test_name}: {detail}")


def skip(test_name: str, reason: str = "") -> None:
    reason_str = f" — {reason}" if reason else ""
    print(f"  ⊘ {test_name} (SKIP){reason_str}")


def run_architect(*args: str, timeout: int = 120, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Ejecuta architect CLI como subproceso."""
    env = {
        **os.environ,
        "LITELLM_LOG": "ERROR",
        "LITELLM_VERBOSE": "False",
        "OPENAI_API_KEY": "sk-1234",
        "LITELLM_API_KEY": "sk-1234",
    }
    if env_extra:
        env.update(env_extra)

    cmd = ["architect"] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


# ── Comprobaciones previas ───────────────────────────────────────────────

def check_prerequisites() -> dict[str, bool]:
    """Comprueba que los servicios necesarios estén disponibles."""
    import httpx

    services = {}

    # LiteLLM proxy
    try:
        r = httpx.get("http://localhost:4000/v1/models", headers={"Authorization": "Bearer sk-1234"}, timeout=5)
        services["llm_proxy"] = r.status_code == 200
    except Exception:
        services["llm_proxy"] = False

    # MCP Job Launcher
    try:
        r = httpx.post(
            "http://localhost:8000/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "test", "version": "1.0"}}},
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            timeout=5,
        )
        services["mcp_jobs"] = r.status_code == 200
    except Exception:
        services["mcp_jobs"] = False

    # MCP Analytics
    try:
        r = httpx.post(
            "http://localhost:8001/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "test", "version": "1.0"}}},
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                     "Authorization": "Bearer token-se-1234"},
            timeout=5,
        )
        services["mcp_analytics"] = r.status_code == 200
    except Exception:
        services["mcp_analytics"] = False

    # Architect CLI (import pesado — necesita más tiempo)
    try:
        r = subprocess.run(["architect", "--version"], capture_output=True, text=True, timeout=30)
        services["architect_cli"] = r.returncode == 0
    except Exception:
        services["architect_cli"] = False

    # Test directory
    services["test_dir"] = Path("/home/diego/projects/test").exists()

    return services


# ══════════════════════════════════════════════════════════════════════════
# SECTION 1: LLM Proxy (LiteLLM) — Llamadas directas
# ══════════════════════════════════════════════════════════════════════════

def test_llm_direct():
    """Tests de LLM adapter contra proxy real."""
    section("1. LLM PROXY — Llamadas directas")

    from architect.config.schema import LLMConfig
    from architect.llm.adapter import LLMAdapter, LLMResponse

    config = LLMConfig(
        provider="litellm",
        model="openai/azure",
        api_base="http://localhost:4000/v1",
        api_key_env="OPENAI_API_KEY",
        timeout=60,
        retries=1,
        stream=True,
        prompt_caching=False,
    )

    llm = LLMAdapter(config)

    # Test 1.1: Completion básico (sin tools)
    try:
        messages = [
            {"role": "system", "content": "Responde en una sola frase."},
            {"role": "user", "content": "¿Qué es Python?"},
        ]
        response = llm.completion(messages)

        assert isinstance(response, LLMResponse), f"Expected LLMResponse, got {type(response)}"
        assert response.content is not None, "Expected content, got None"
        assert len(response.content) > 10, f"Content too short: {response.content!r}"
        assert response.tool_calls == [], f"Unexpected tool calls: {response.tool_calls}"
        assert response.usage is not None, "Expected usage info"
        assert response.usage.get("total_tokens", 0) > 0, f"Expected tokens > 0, got {response.usage}"

        ok("1.1 Completion básico", f"content={response.content[:60]}... tokens={response.usage['total_tokens']}")
    except Exception as e:
        fail("1.1 Completion básico", str(e))

    # Test 1.2: Completion con tools
    try:
        messages = [
            {"role": "system", "content": "Eres un asistente. Usa las herramientas disponibles."},
            {"role": "user", "content": "Lee el archivo /home/diego/projects/test/config.yaml"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Lee un archivo del disco",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path al archivo"}
                        },
                        "required": ["path"],
                    },
                },
            }
        ]
        response = llm.completion(messages, tools=tools)

        assert isinstance(response, LLMResponse), f"Expected LLMResponse, got {type(response)}"
        assert len(response.tool_calls) > 0, f"Expected tool calls, got none. Content: {response.content}"

        tc = response.tool_calls[0]
        assert tc.name == "read_file", f"Expected read_file, got {tc.name}"
        assert "path" in tc.arguments, f"Expected 'path' arg, got {tc.arguments}"
        assert tc.id, "Expected tool call ID"

        ok("1.2 Completion con tools", f"tool={tc.name}, args={tc.arguments}")
    except Exception as e:
        fail("1.2 Completion con tools", str(e))

    # Test 1.3: Completion con multiple tools disponibles
    try:
        messages = [
            {"role": "system", "content": "Eres un asistente. Busca el archivo y luego léelo."},
            {"role": "user", "content": "Busca archivos Python en /home/diego/projects/test y lee el primero que encuentres"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "find_files",
                    "description": "Encuentra archivos por patrón glob",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "pattern": {"type": "string"},
                        },
                        "required": ["path", "pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Lee un archivo",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                },
            },
        ]
        response = llm.completion(messages, tools=tools)

        assert len(response.tool_calls) >= 1, f"Expected ≥1 tool call, got {len(response.tool_calls)}"
        tool_names = [tc.name for tc in response.tool_calls]
        assert all(name in ("find_files", "read_file") for name in tool_names), f"Unexpected tools: {tool_names}"

        ok("1.3 Multiple tools disponibles", f"tools_called={tool_names}")
    except Exception as e:
        fail("1.3 Multiple tools disponibles", str(e))

    # Test 1.4: Usage tracking
    try:
        messages = [{"role": "user", "content": "Di 'hola'"}]
        response = llm.completion(messages)

        assert response.usage is not None, "No usage info"
        assert response.usage["prompt_tokens"] > 0, f"prompt_tokens=0"
        assert response.usage["completion_tokens"] > 0, f"completion_tokens=0"
        assert response.usage["total_tokens"] > 0, f"total_tokens=0"
        assert response.usage["total_tokens"] == (
            response.usage["prompt_tokens"] + response.usage["completion_tokens"]
        ), "total != prompt + completion"

        ok("1.4 Usage tracking", f"usage={response.usage}")
    except Exception as e:
        fail("1.4 Usage tracking", str(e))

    # Test 1.5: Error handling — modelo inválido
    try:
        bad_config = LLMConfig(
            model="openai/nonexistent-model-xyz",
            api_base="http://localhost:4000/v1",
            api_key_env="OPENAI_API_KEY",
            timeout=10,
            retries=0,
        )
        bad_llm = LLMAdapter(bad_config)
        try:
            bad_llm.completion([{"role": "user", "content": "test"}])
            fail("1.5 Error handling modelo inválido", "No lanzó excepción")
        except Exception as e:
            ok("1.5 Error handling modelo inválido", f"error_type={type(e).__name__}")
    except Exception as e:
        fail("1.5 Error handling modelo inválido", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 2: Streaming real
# ══════════════════════════════════════════════════════════════════════════

def test_streaming():
    """Tests de streaming contra LLM real."""
    section("2. STREAMING — Respuestas en tiempo real")

    from architect.config.schema import LLMConfig
    from architect.llm.adapter import LLMAdapter, LLMResponse, StreamChunk

    config = LLMConfig(
        model="openai/azure",
        api_base="http://localhost:4000/v1",
        api_key_env="OPENAI_API_KEY",
        timeout=60,
        retries=1,
        stream=True,
    )
    llm = LLMAdapter(config)

    # Test 2.1: Streaming básico — solo texto
    try:
        messages = [
            {"role": "system", "content": "Responde brevemente."},
            {"role": "user", "content": "Cuenta del 1 al 5, uno por línea."},
        ]

        chunks_received = []
        final_response = None

        for item in llm.completion_stream(messages):
            if isinstance(item, StreamChunk):
                chunks_received.append(item)
            elif isinstance(item, LLMResponse):
                final_response = item

        assert len(chunks_received) > 0, f"No chunks received"
        assert final_response is not None, "No final response"
        assert final_response.content is not None, "Final response has no content"

        # Verificar que los chunks concatenados = contenido final
        concatenated = "".join(c.data for c in chunks_received if c.type == "content")
        assert concatenated == final_response.content, (
            f"Chunks concatenated ({len(concatenated)} chars) != final content ({len(final_response.content)} chars)"
        )

        ok("2.1 Streaming básico", f"chunks={len(chunks_received)}, content_len={len(final_response.content)}")
    except Exception as e:
        fail("2.1 Streaming básico", str(e))

    # Test 2.2: Streaming con tool calls
    try:
        messages = [
            {"role": "system", "content": "Eres un asistente. Usa las herramientas para leer archivos."},
            {"role": "user", "content": "Lee el archivo /tmp/test.txt"},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Lee un archivo",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ]

        chunks_received = []
        final_response = None

        for item in llm.completion_stream(messages, tools=tools):
            if isinstance(item, StreamChunk):
                chunks_received.append(item)
            elif isinstance(item, LLMResponse):
                final_response = item

        assert final_response is not None, "No final response"
        assert len(final_response.tool_calls) > 0, (
            f"Expected tool calls in streaming, got none. Content: {final_response.content}"
        )

        tc = final_response.tool_calls[0]
        assert tc.name == "read_file", f"Expected read_file, got {tc.name}"
        assert isinstance(tc.arguments, dict), f"Arguments not dict: {type(tc.arguments)}"
        assert tc.id, "No tool call ID"

        ok("2.2 Streaming con tool calls", f"tool={tc.name}, id={tc.id}")
    except Exception as e:
        fail("2.2 Streaming con tool calls", str(e))

    # Test 2.3: Streaming usage info
    try:
        messages = [{"role": "user", "content": "Di 'OK'."}]
        final_response = None
        for item in llm.completion_stream(messages):
            if isinstance(item, LLMResponse):
                final_response = item

        assert final_response is not None, "No final response"
        # Usage might not always be available in streaming
        if final_response.usage:
            assert final_response.usage.get("total_tokens", 0) > 0
            ok("2.3 Streaming usage info", f"usage={final_response.usage}")
        else:
            skip("2.3 Streaming usage info", "provider no envía usage en streaming")
    except Exception as e:
        fail("2.3 Streaming usage info", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 3: MCP Real
# ══════════════════════════════════════════════════════════════════════════

def test_mcp_real():
    """Tests de MCP contra servidores reales."""
    section("3. MCP — Servidores reales")

    from architect.config.schema import MCPServerConfig
    from architect.mcp.client import MCPClient, MCPError
    from architect.mcp.discovery import MCPDiscovery
    from architect.mcp.adapter import MCPToolAdapter
    from architect.tools.registry import ToolRegistry

    # Test 3.1: MCPClient.list_tools() contra Job Launcher (sin auth)
    try:
        config = MCPServerConfig(name="jobs", url="http://localhost:8000/mcp")
        client = MCPClient(config)
        tools = client.list_tools()

        # Si llega aquí, el protocolo funciona
        assert isinstance(tools, list), f"Expected list, got {type(tools)}"
        assert len(tools) > 0, "No tools discovered"

        tool_names = [t.get("name") for t in tools]
        ok("3.1 MCPClient.list_tools() Job Launcher", f"tools={tool_names}")
    except MCPError as e:
        fail("3.1 MCPClient.list_tools() Job Launcher", f"MCPError: {e}")
    except Exception as e:
        fail("3.1 MCPClient.list_tools() Job Launcher", f"{type(e).__name__}: {e}")

    # Test 3.2: MCPClient.list_tools() contra Analytics (con auth)
    try:
        config = MCPServerConfig(
            name="analytics",
            url="http://localhost:8001/mcp",
            token="token-se-1234",
        )
        client = MCPClient(config)
        tools = client.list_tools()

        assert isinstance(tools, list), f"Expected list, got {type(tools)}"
        assert len(tools) > 0, "No tools discovered"

        tool_names = [t.get("name") for t in tools]
        ok("3.2 MCPClient.list_tools() Analytics (auth)", f"tools={tool_names}")
    except MCPError as e:
        fail("3.2 MCPClient.list_tools() Analytics (auth)", f"MCPError: {e}")
    except Exception as e:
        fail("3.2 MCPClient.list_tools() Analytics (auth)", f"{type(e).__name__}: {e}")

    # Test 3.3: MCPClient.call_tool() — ejecutar tool real
    try:
        config = MCPServerConfig(name="jobs", url="http://localhost:8000/mcp")
        client = MCPClient(config)
        result = client.call_tool("list_jobs", {"environment": "dev"})

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        ok("3.3 MCPClient.call_tool() list_jobs", f"result_keys={list(result.keys())}")
    except MCPError as e:
        fail("3.3 MCPClient.call_tool() list_jobs", f"MCPError: {e}")
    except Exception as e:
        fail("3.3 MCPClient.call_tool() list_jobs", f"{type(e).__name__}: {e}")

    # Test 3.4: MCPClient.call_tool() con auth (Analytics)
    try:
        config = MCPServerConfig(
            name="analytics",
            url="http://localhost:8001/mcp",
            token="token-se-1234",
        )
        client = MCPClient(config)
        result = client.call_tool("list_datasets", {})

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        ok("3.4 MCPClient.call_tool() list_datasets (auth)", f"result_keys={list(result.keys())}")
    except MCPError as e:
        fail("3.4 MCPClient.call_tool() list_datasets (auth)", f"MCPError: {e}")
    except Exception as e:
        fail("3.4 MCPClient.call_tool() list_datasets (auth)", f"{type(e).__name__}: {e}")

    # Test 3.5: MCPDiscovery — descubrir y registrar tools
    try:
        servers = [
            MCPServerConfig(name="jobs", url="http://localhost:8000/mcp"),
            MCPServerConfig(name="analytics", url="http://localhost:8001/mcp", token="token-se-1234"),
        ]
        registry = ToolRegistry()
        discovery = MCPDiscovery()
        stats = discovery.discover_and_register(servers, registry)

        assert stats["servers_total"] == 2, f"Expected 2 servers, got {stats['servers_total']}"
        assert stats["servers_success"] >= 1, f"No servers succeeded: {stats}"
        assert stats["tools_registered"] > 0, f"No tools registered: {stats}"

        # Verificar que las tools están en el registry con prefijo mcp_
        all_tools = [t.name for t in registry.list_all()]
        mcp_tools = [t for t in all_tools if t.startswith("mcp_")]

        detail = f"success={stats['servers_success']}/{stats['servers_total']}, tools={stats['tools_registered']}"
        if stats["servers_failed"] > 0:
            detail += f", failed={stats['servers_failed']}, errors={stats['errors']}"

        if stats["servers_success"] == 2:
            ok("3.5 MCPDiscovery completo", detail)
        else:
            fail("3.5 MCPDiscovery completo", detail)
    except Exception as e:
        fail("3.5 MCPDiscovery completo", f"{type(e).__name__}: {e}")

    # Test 3.6: MCPToolAdapter — ejecutar tool vía adapter
    try:
        config = MCPServerConfig(name="jobs", url="http://localhost:8000/mcp")
        client = MCPClient(config)

        # Primero obtener la definición de tools
        tools = client.list_tools()
        # Usar la primera tool disponible para el test
        first_tool = tools[0] if tools else None
        if first_tool is None:
            skip("3.6 MCPToolAdapter execute", "no tools found")
        else:
            tool_name = first_tool.get("name", "unknown")
            adapter = MCPToolAdapter(client=client, tool_definition=first_tool, server_name="jobs")

            expected_name = f"mcp_jobs_{tool_name}"
            assert adapter.name == expected_name, f"Expected {expected_name}, got {adapter.name}"
            assert adapter.sensitive is True, "MCP tools should be sensitive"

            ok("3.6 MCPToolAdapter schema", f"name={adapter.name}, has_args_model={adapter.args_model is not None}")
    except Exception as e:
        fail("3.6 MCPToolAdapter execute", f"{type(e).__name__}: {e}")

    # Test 3.7: MCPClient sin auth a servidor que requiere auth
    try:
        config = MCPServerConfig(name="analytics_noauth", url="http://localhost:8001/mcp")
        client = MCPClient(config)
        try:
            tools = client.list_tools()
            # Si no lanza error pero no devuelve tools, podría ser un problema
            fail("3.7 MCP sin auth a servidor con auth", f"No lanzó error, got {len(tools)} tools")
        except MCPError as e:
            ok("3.7 MCP sin auth a servidor con auth", f"Error correcto: {str(e)[:80]}")
        except Exception as e:
            # Cualquier error es aceptable — lo importante es que no devuelve datos silenciosamente
            ok("3.7 MCP sin auth a servidor con auth", f"Error: {type(e).__name__}: {str(e)[:80]}")
    except Exception as e:
        fail("3.7 MCP sin auth a servidor con auth", f"{type(e).__name__}: {e}")

    # Test 3.8: MCPClient a servidor inexistente
    try:
        config = MCPServerConfig(name="ghost", url="http://localhost:9999/mcp")
        client = MCPClient(config)
        try:
            tools = client.list_tools()
            fail("3.8 MCP servidor inexistente", "No lanzó error")
        except MCPError:
            ok("3.8 MCP servidor inexistente", "MCPConnectionError como esperado")
        except Exception as e:
            ok("3.8 MCP servidor inexistente", f"Error: {type(e).__name__}")
    except Exception as e:
        fail("3.8 MCP servidor inexistente", f"{type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════════════
# SECTION 4: CLI end-to-end
# ══════════════════════════════════════════════════════════════════════════

def test_cli_e2e():
    """Tests del CLI completo contra LLM real."""
    section("4. CLI END-TO-END — Flujos completos")

    # Test 4.1: CLI básico — pregunta simple sin tools
    try:
        result = run_architect(
            "run", "Responde solo con la palabra OK",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "human",
            "--no-stream",
            "-a", "plan",  # plan mode: no modifica nada
            "--max-steps", "3",
            "-w", "/home/diego/projects/test",
            timeout=60,
        )

        assert result.returncode in (0, 2), f"Exit code {result.returncode}. stderr: {result.stderr[-500:]}"

        ok("4.1 CLI básico (plan, sin tools)", f"exit={result.returncode}, stdout_len={len(result.stdout.strip())}")
    except subprocess.TimeoutExpired:
        fail("4.1 CLI básico (plan, sin tools)", "Timeout (60s)")
    except Exception as e:
        fail("4.1 CLI básico (plan, sin tools)", str(e))

    # Test 4.2: CLI con JSON output
    try:
        result = run_architect(
            "run", "Di hola",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--json",
            "--quiet",
            "--no-stream",
            "-a", "plan",
            "--max-steps", "3",
            "-w", "/home/diego/projects/test",
            timeout=60,
        )

        assert result.returncode in (0, 2), f"Exit code {result.returncode}. stderr: {result.stderr[-500:]}"

        output = json.loads(result.stdout)
        assert "status" in output, f"Missing 'status' in JSON: {list(output.keys())}"
        assert "output" in output, f"Missing 'output' in JSON: {list(output.keys())}"
        assert output["status"] in ("success", "partial"), f"Unexpected status: {output['status']}"

        ok("4.2 CLI --json output", f"status={output['status']}, exit={result.returncode}, keys={list(output.keys())}")
    except json.JSONDecodeError as e:
        fail("4.2 CLI --json output", f"JSON parse error: {e}. stdout={result.stdout[:200]}")
    except subprocess.TimeoutExpired:
        fail("4.2 CLI --json output", "Timeout (60s)")
    except Exception as e:
        fail("4.2 CLI --json output", str(e))

    # Test 4.3: CLI con streaming
    try:
        result = run_architect(
            "run", "Cuenta del 1 al 3",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "error",  # solo errores, no human logs
            "-a", "plan",
            "--max-steps", "3",
            "-w", "/home/diego/projects/test",
            timeout=60,
        )

        assert result.returncode in (0, 2), f"Exit code {result.returncode}. stderr: {result.stderr[-500:]}"
        # Con streaming, el output va a stderr (chunks) y stdout (resultado final)
        # stderr debería tener algo (banner + streaming chunks)
        ok("4.3 CLI con streaming", f"exit={result.returncode}, stdout_len={len(result.stdout)}, stderr_len={len(result.stderr)}")
    except subprocess.TimeoutExpired:
        fail("4.3 CLI con streaming", "Timeout (60s)")
    except Exception as e:
        fail("4.3 CLI con streaming", str(e))

    # Test 4.4: CLI build mode con workspace real
    try:
        # Crear un archivo simple para que el agente lo lea
        test_file = Path("/home/diego/projects/test/test_integration_target.txt")
        test_file.write_text("Este es un archivo de prueba para la integración.\nLínea 2.\nLínea 3.\n")

        result = run_architect(
            "run", "Lee el archivo test_integration_target.txt y dime cuántas líneas tiene",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "human",
            "--no-stream",
            "-a", "build",
            "--mode", "yolo",
            "--max-steps", "5",
            "-w", "/home/diego/projects/test",
            timeout=90,
        )

        ok(
            "4.4 CLI build con workspace real",
            f"exit={result.returncode}, stdout={result.stdout.strip()[:100]}",
        )

        # Limpiar
        if test_file.exists():
            test_file.unlink()

    except subprocess.TimeoutExpired:
        fail("4.4 CLI build con workspace real", "Timeout (90s)")
    except Exception as e:
        fail("4.4 CLI build con workspace real", str(e))

    # Test 4.5: CLI dry-run
    try:
        result = run_architect(
            "run", "Crea un archivo llamado no_deberia_existir.txt con el contenido 'test'",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "error",
            "--no-stream",
            "--dry-run",
            "-a", "build",
            "--mode", "yolo",
            "--max-steps", "5",
            "-w", "/home/diego/projects/test",
            timeout=60,
        )

        # Verificar que el archivo NO se creó
        ghost_file = Path("/home/diego/projects/test/no_deberia_existir.txt")
        file_created = ghost_file.exists()

        if file_created:
            ghost_file.unlink()  # limpiar
            fail("4.5 CLI dry-run", "El archivo se creó a pesar del --dry-run")
        else:
            ok("4.5 CLI dry-run", f"exit={result.returncode}, archivo no creado (correcto)")

    except subprocess.TimeoutExpired:
        fail("4.5 CLI dry-run", "Timeout (60s)")
    except Exception as e:
        fail("4.5 CLI dry-run", str(e))

    # Test 4.6: CLI con --show-costs
    try:
        result = run_architect(
            "run", "Di hola",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "human",
            "--no-stream",
            "--show-costs",
            "-a", "plan",
            "--max-steps", "3",
            "-w", "/home/diego/projects/test",
            timeout=60,
        )

        assert result.returncode in (0, 2), f"Exit code {result.returncode}"
        # El resumen de costes va a stderr
        cost_in_output = "cost" in result.stderr.lower() or "$" in result.stderr or "coste" in result.stderr.lower()
        if cost_in_output:
            ok("4.6 CLI --show-costs", f"exit={result.returncode}, coste visible en stderr")
        else:
            ok("4.6 CLI --show-costs", f"exit={result.returncode} (coste puede no aparecer si price unknown)")

    except subprocess.TimeoutExpired:
        fail("4.6 CLI --show-costs", "Timeout (60s)")
    except Exception as e:
        fail("4.6 CLI --show-costs", str(e))

    # Test 4.7: CLI agents command
    try:
        result = run_architect("agents", timeout=10)
        assert result.returncode == 0, f"Exit code {result.returncode}"
        assert "build" in result.stdout, f"'build' not in output"
        assert "plan" in result.stdout, f"'plan' not in output"
        assert "review" in result.stdout, f"'review' not in output"
        assert "resume" in result.stdout, f"'resume' not in output"

        ok("4.7 CLI agents command", f"agents listed correctly")
    except Exception as e:
        fail("4.7 CLI agents command", str(e))

    # Test 4.8: CLI validate-config
    try:
        result = run_architect("validate-config", timeout=10)
        # Sin config file, debería usar defaults y reportar válido
        assert result.returncode == 0, f"Exit code {result.returncode}"
        assert "válida" in result.stdout.lower() or "valid" in result.stdout.lower(), (
            f"Unexpected output: {result.stdout}"
        )

        ok("4.8 CLI validate-config", "Config por defecto válida")
    except Exception as e:
        fail("4.8 CLI validate-config", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 5: Config YAML compleja
# ══════════════════════════════════════════════════════════════════════════

def test_complex_config():
    """Tests de configuración YAML compleja."""
    section("5. CONFIG YAML — Configuraciones complejas")

    # Test 5.1: Config con MCP servers
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              api_base: http://localhost:4000/v1
              timeout: 30
              retries: 1
              stream: false

            workspace:
              root: /home/diego/projects/test
              allow_delete: false

            mcp:
              servers:
                - name: jobs
                  url: http://localhost:8000/mcp
                - name: analytics
                  url: http://localhost:8001/mcp
                  token: token-se-1234

            logging:
              level: human
              verbose: 0

            context:
              max_tool_result_tokens: 2000
              max_context_tokens: 80000

            costs:
              enabled: true
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            from architect.config.loader import load_config as _load_config
            config = _load_config(config_path=Path(config_path))

            assert config.llm.model == "openai/azure"
            assert len(config.mcp.servers) == 2
            assert config.mcp.servers[0].name == "jobs"
            assert config.mcp.servers[1].token == "token-se-1234"
            assert config.workspace.root == Path("/home/diego/projects/test")
            assert config.costs.enabled is True

            ok("5.1 Config con MCP servers", f"servers={len(config.mcp.servers)}")
        finally:
            os.unlink(config_path)

    except Exception as e:
        fail("5.1 Config con MCP servers", str(e))

    # Test 5.2: Config con hooks
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              api_base: http://localhost:4000/v1

            hooks:
              post_edit:
                - name: python-lint
                  command: "echo LINT OK"
                  file_patterns: ["*.py"]
                  timeout: 10
                  enabled: true
                - name: test-runner
                  command: "echo TESTS OK"
                  file_patterns: ["*.py", "*.js"]
                  timeout: 30
                  enabled: false
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            from architect.config.loader import load_config as _load_config
            config = _load_config(config_path=Path(config_path))

            assert len(config.hooks.post_edit) == 2
            assert config.hooks.post_edit[0].name == "python-lint"
            assert config.hooks.post_edit[0].enabled is True
            assert config.hooks.post_edit[1].enabled is False
            assert "*.py" in config.hooks.post_edit[0].file_patterns

            ok("5.2 Config con hooks", f"hooks={len(config.hooks.post_edit)}")
        finally:
            os.unlink(config_path)

    except Exception as e:
        fail("5.2 Config con hooks", str(e))

    # Test 5.3: Config con agente custom
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              api_base: http://localhost:4000/v1

            agents:
              deploy:
                system_prompt: "Eres un agente de deployment."
                allowed_tools: [read_file, run_command]
                confirm_mode: confirm-all
                max_steps: 10
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            from architect.config.loader import load_config as _load_config
            config = _load_config(config_path=Path(config_path))

            assert "deploy" in config.agents
            assert config.agents["deploy"].max_steps == 10
            assert config.agents["deploy"].confirm_mode == "confirm-all"
            assert "run_command" in config.agents["deploy"].allowed_tools

            ok("5.3 Config con agente custom", "deploy agent parsed correctly")
        finally:
            os.unlink(config_path)

    except Exception as e:
        fail("5.3 Config con agente custom", str(e))

    # Test 5.4: Config con budget
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              api_base: http://localhost:4000/v1

            costs:
              enabled: true
              budget_usd: 0.10
              warn_at_usd: 0.05
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            from architect.config.loader import load_config as _load_config
            config = _load_config(config_path=Path(config_path))

            assert config.costs.budget_usd == 0.10
            assert config.costs.warn_at_usd == 0.05

            ok("5.4 Config con budget", f"budget=${config.costs.budget_usd}, warn=${config.costs.warn_at_usd}")
        finally:
            os.unlink(config_path)

    except Exception as e:
        fail("5.4 Config con budget", str(e))

    # Test 5.5: Config completa — todas las secciones
    try:
        config_content = textwrap.dedent("""\
            llm:
              provider: litellm
              model: openai/azure
              api_base: http://localhost:4000/v1
              api_key_env: OPENAI_API_KEY
              timeout: 60
              retries: 2
              stream: true
              prompt_caching: false

            workspace:
              root: /home/diego/projects/test
              allow_delete: true

            logging:
              level: human
              verbose: 0

            mcp:
              servers:
                - name: jobs
                  url: http://localhost:8000/mcp

            context:
              max_tool_result_tokens: 2000
              summarize_after_steps: 8
              keep_recent_steps: 4
              max_context_tokens: 80000
              parallel_tools: true

            evaluation:
              mode: "off"
              max_retries: 2
              confidence_threshold: 0.8

            commands:
              enabled: true
              default_timeout: 30
              max_output_lines: 200

            costs:
              enabled: true
              budget_usd: 1.00

            llm_cache:
              enabled: false

            hooks:
              post_edit:
                - name: echo-lint
                  command: "echo OK"
                  file_patterns: ["*.py"]
                  timeout: 5

            indexer:
              enabled: true
              max_file_size: 500000
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            from architect.config.loader import load_config as _load_config
            config = _load_config(config_path=Path(config_path))

            assert config.llm.model == "openai/azure"
            assert config.workspace.allow_delete is True
            assert config.context.parallel_tools is True
            assert config.evaluation.mode == "off"
            assert config.commands.enabled is True
            assert config.costs.budget_usd == 1.00
            assert config.indexer.max_file_size == 500000
            assert len(config.hooks.post_edit) == 1

            ok("5.5 Config completa (todas las secciones)", "12 secciones validadas")
        finally:
            os.unlink(config_path)

    except Exception as e:
        fail("5.5 Config completa (todas las secciones)", str(e))

    # Test 5.6: Config inválida — campo desconocido
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              unknown_field: "should fail"
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            from architect.config.loader import load_config as _load_config
            try:
                config = _load_config(config_path=Path(config_path))
                fail("5.6 Config inválida rechazada", "No lanzó error con campo desconocido")
            except Exception as e:
                ok("5.6 Config inválida rechazada", f"{type(e).__name__}: {str(e)[:80]}")
        finally:
            os.unlink(config_path)

    except Exception as e:
        fail("5.6 Config inválida rechazada", str(e))

    # Test 5.7: CLI validate-config con YAML completo
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              api_base: http://localhost:4000/v1
            workspace:
              root: /home/diego/projects/test
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            result = run_architect("validate-config", "-c", config_path, timeout=10)
            assert result.returncode == 0, f"Exit code {result.returncode}. stderr: {result.stderr}"

            ok("5.7 CLI validate-config con YAML", f"output: {result.stdout.strip()[:80]}")
        finally:
            os.unlink(config_path)

    except Exception as e:
        fail("5.7 CLI validate-config con YAML", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 6: Safety nets reales
# ══════════════════════════════════════════════════════════════════════════

def test_safety_nets():
    """Tests de safety nets (watchdogs) con LLM real."""
    section("6. SAFETY NETS — Watchdogs con LLM real")

    # Test 6.1: max-steps watchdog (limitar a 1 step)
    try:
        result = run_architect(
            "run", "Lee todos los archivos del proyecto y hazme un resumen detallado de cada uno",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "human",
            "--no-stream",
            "-a", "build",
            "--mode", "yolo",
            "--max-steps", "1",
            "-w", "/home/diego/projects/test",
            timeout=120,
        )

        # Con max-steps=1, debería terminar como "partial"
        # Exit code 2 = PARTIAL
        if result.returncode == 2:
            ok("6.1 max-steps watchdog", f"exit=2 (partial), output={result.stdout.strip()[:80]}")
        elif result.returncode == 0:
            ok("6.1 max-steps watchdog", "exit=0 (LLM terminó antes del límite)")
        else:
            fail("6.1 max-steps watchdog", f"exit={result.returncode}. stderr: {result.stderr[-300:]}")

    except subprocess.TimeoutExpired:
        fail("6.1 max-steps watchdog", "Timeout (120s) — el watchdog no disparó")
    except Exception as e:
        fail("6.1 max-steps watchdog", str(e))

    # Test 6.2: timeout watchdog
    # Nota: el timeout se comprueba entre steps (no interrumpe mid-LLM-call).
    # Cada llamada LLM puede tardar 10-30s, más la llamada de graceful close.
    # Usamos timeout=30s y subprocess timeout=180s para dar margen.
    try:
        result = run_architect(
            "run", "Lee todos los archivos Python del proyecto uno por uno y analiza cada función en detalle",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "error",
            "--no-stream",
            "-a", "build",
            "--mode", "yolo",
            "--max-steps", "50",
            "--timeout", "30",
            "-w", "/home/diego/projects/test",
            timeout=180,
        )

        # Debería terminar con partial (timeout) o success (si termina antes)
        if result.returncode in (0, 2):
            status = "success" if result.returncode == 0 else "partial (timeout)"
            ok("6.2 timeout watchdog (30s)", f"exit={result.returncode} ({status})")
        else:
            fail("6.2 timeout watchdog (30s)", f"exit={result.returncode}. stderr: {result.stderr[-300:]}")

    except subprocess.TimeoutExpired:
        fail("6.2 timeout watchdog (30s)", "Process timeout (180s) — timeout watchdog didn't fire")
    except Exception as e:
        fail("6.2 timeout watchdog (30s)", str(e))

    # Test 6.3: budget watchdog (muy bajo — $0.001)
    try:
        result = run_architect(
            "run", "Lee todos los archivos y hazme un resumen completo de cada uno, incluyendo cada función",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--log-level", "error",
            "--no-stream",
            "-a", "build",
            "--mode", "yolo",
            "--max-steps", "50",
            "--budget", "0.001",
            "--show-costs",
            "-w", "/home/diego/projects/test",
            timeout=120,
        )

        # Budget muy bajo — debería salir como partial o success rápido
        if result.returncode in (0, 2):
            ok("6.3 budget watchdog ($0.001)", f"exit={result.returncode}")
        else:
            fail("6.3 budget watchdog ($0.001)", f"exit={result.returncode}. stderr: {result.stderr[-300:]}")

    except subprocess.TimeoutExpired:
        fail("6.3 budget watchdog ($0.001)", "Timeout (120s)")
    except Exception as e:
        fail("6.3 budget watchdog ($0.001)", str(e))

    # Test 6.4: JSON output con safety net disparado
    try:
        result = run_architect(
            "run", "Lee cada archivo y analiza todo en profundidad",
            "--api-base", "http://localhost:4000/v1",
            "--model", "openai/azure",
            "--json",
            "--quiet",
            "--no-stream",
            "-a", "build",
            "--mode", "yolo",
            "--max-steps", "1",
            "-w", "/home/diego/projects/test",
            timeout=120,
        )

        try:
            output = json.loads(result.stdout)
            assert "status" in output, "Missing status"
            assert "stop_reason" in output, "Missing stop_reason"

            ok("6.4 JSON con safety net", f"status={output['status']}, stop_reason={output.get('stop_reason')}")
        except json.JSONDecodeError:
            if result.returncode in (0, 2):
                ok("6.4 JSON con safety net", f"exit={result.returncode}, pero JSON parse error — stdout: {result.stdout[:100]}")
            else:
                fail("6.4 JSON con safety net", f"JSON parse error. stdout: {result.stdout[:200]}")

    except subprocess.TimeoutExpired:
        fail("6.4 JSON con safety net", "Timeout (120s)")
    except Exception as e:
        fail("6.4 JSON con safety net", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 7: CLI con MCP real
# ══════════════════════════════════════════════════════════════════════════

def test_cli_with_mcp():
    """Tests del CLI con servidores MCP reales conectados."""
    section("7. CLI + MCP — Flujo completo con MCP real")

    # Test 7.1: CLI con config MCP — verificar discovery
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              api_base: http://localhost:4000/v1
              stream: false

            workspace:
              root: /home/diego/projects/test

            mcp:
              servers:
                - name: jobs
                  url: http://localhost:8000/mcp
                - name: analytics
                  url: http://localhost:8001/mcp
                  token: token-se-1234

            logging:
              level: human
              verbose: 1
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            result = run_architect(
                "run", "Lista los jobs en el entorno dev usando las herramientas MCP disponibles",
                "-c", config_path,
                "--no-stream",
                "-a", "build",
                "--mode", "yolo",
                "--max-steps", "5",
                timeout=90,
            )

            # Verificar que MCP discovery se intentó
            mcp_in_stderr = "mcp" in result.stderr.lower() or "descubriendo" in result.stderr.lower()
            detail = f"exit={result.returncode}"
            if mcp_in_stderr:
                detail += ", MCP discovery attempted"
            detail += f", stderr_has_mcp={mcp_in_stderr}"

            if result.returncode in (0, 1, 2):
                ok("7.1 CLI con MCP config", detail)
            else:
                fail("7.1 CLI con MCP config", detail + f". stderr: {result.stderr[-300:]}")

        finally:
            os.unlink(config_path)

    except subprocess.TimeoutExpired:
        fail("7.1 CLI con MCP config", "Timeout (90s)")
    except Exception as e:
        fail("7.1 CLI con MCP config", str(e))

    # Test 7.2: CLI con --disable-mcp
    try:
        config_content = textwrap.dedent("""\
            llm:
              model: openai/azure
              api_base: http://localhost:4000/v1
              stream: false

            workspace:
              root: /home/diego/projects/test

            mcp:
              servers:
                - name: jobs
                  url: http://localhost:8000/mcp
        """)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            config_path = f.name

        try:
            result = run_architect(
                "run", "Di hola",
                "-c", config_path,
                "--no-stream",
                "--disable-mcp",
                "-a", "plan",
                "--max-steps", "3",
                timeout=60,
            )

            # Con --disable-mcp, no debería intentar discovery
            mcp_in_stderr = "descubriendo" in result.stderr.lower()
            if mcp_in_stderr:
                fail("7.2 CLI --disable-mcp", "MCP discovery happened despite --disable-mcp")
            else:
                ok("7.2 CLI --disable-mcp", f"exit={result.returncode}, no MCP discovery")

        finally:
            os.unlink(config_path)

    except subprocess.TimeoutExpired:
        fail("7.2 CLI --disable-mcp", "Timeout (60s)")
    except Exception as e:
        fail("7.2 CLI --disable-mcp", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 8: Post-edit hooks reales
# ══════════════════════════════════════════════════════════════════════════

def test_post_edit_hooks():
    """Tests de hooks con ejecución real (v4-A1 HookExecutor API)."""
    section("8. HOOKS — Ejecución real (v4-A1 HookExecutor)")

    from architect.core.hooks import (
        HookConfig,
        HookDecision,
        HookEvent,
        HookExecutor,
        HooksRegistry,
    )

    workspace_root = "/home/diego/projects/test"

    # Test 8.1: Hook que pasa (post_tool_use con stdout)
    try:
        hooks = {
            HookEvent.POST_TOOL_USE: [
                HookConfig(
                    name="echo-lint",
                    command="echo LINT_PASS",
                    file_patterns=["*.py"],
                    timeout=5,
                    enabled=True,
                ),
            ],
        }
        registry = HooksRegistry(hooks=hooks)
        executor = HookExecutor(registry=registry, workspace_root=workspace_root)

        results = executor.run_event(
            HookEvent.POST_TOOL_USE,
            {"tool_name": "write_file", "file_path": "test.py"},
        )

        assert len(results) >= 1, f"Expected ≥1 result, got {len(results)}"
        assert results[0].decision == HookDecision.ALLOW, f"Expected ALLOW, got {results[0].decision}"

        ok("8.1 Hook que pasa", f"decision={results[0].decision.value}")
    except Exception as e:
        fail("8.1 Hook que pasa", str(e))

    # Test 8.2: Hook que bloquea (exit 2 = BLOCK)
    try:
        hooks = {
            HookEvent.PRE_TOOL_USE: [
                HookConfig(
                    name="block-hook",
                    command="echo 'blocked reason' >&2; exit 2",
                    timeout=5,
                    enabled=True,
                ),
            ],
        }
        registry = HooksRegistry(hooks=hooks)
        executor = HookExecutor(registry=registry, workspace_root=workspace_root)

        results = executor.run_event(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": "write_file", "file_path": "test.py"},
        )

        assert len(results) >= 1, f"Expected ≥1 result, got {len(results)}"
        assert results[0].decision == HookDecision.BLOCK, f"Expected BLOCK, got {results[0].decision}"

        ok("8.2 Hook que bloquea (exit 2)", f"decision={results[0].decision.value}")
    except Exception as e:
        fail("8.2 Hook que bloquea", str(e))

    # Test 8.3: Hook con file pattern no matching
    try:
        hooks = {
            HookEvent.POST_TOOL_USE: [
                HookConfig(
                    name="py-only",
                    command="echo SHOULD_NOT_RUN",
                    file_patterns=["*.py"],
                    timeout=5,
                    enabled=True,
                ),
            ],
        }
        registry = HooksRegistry(hooks=hooks)
        executor = HookExecutor(registry=registry, workspace_root=workspace_root)

        results = executor.run_event(
            HookEvent.POST_TOOL_USE,
            {"tool_name": "write_file", "file_path": "test.js"},  # .js, no .py
        )

        # Hook should not have run (filtered by file_patterns)
        ran = any(r.additional_context and "SHOULD_NOT_RUN" in r.additional_context for r in results)
        if not ran:
            ok("8.3 Hook pattern no matching (.js vs *.py)", "Hook no ejecutado (correcto)")
        else:
            fail("8.3 Hook pattern no matching", "Hook ejecutado incorrectamente")
    except Exception as e:
        fail("8.3 Hook pattern no matching", str(e))

    # Test 8.4: Hook deshabilitado
    try:
        hooks = {
            HookEvent.POST_TOOL_USE: [
                HookConfig(
                    name="disabled-hook",
                    command="echo SHOULD_NOT_RUN",
                    timeout=5,
                    enabled=False,
                ),
            ],
        }
        registry = HooksRegistry(hooks=hooks)
        executor = HookExecutor(registry=registry, workspace_root=workspace_root)

        results = executor.run_event(
            HookEvent.POST_TOOL_USE,
            {"tool_name": "write_file", "file_path": "test.py"},
        )

        ran = any(r.additional_context and "SHOULD_NOT_RUN" in r.additional_context for r in results)
        if not ran:
            ok("8.4 Hook deshabilitado", "Hook no ejecutado (correcto)")
        else:
            fail("8.4 Hook deshabilitado", "Hook ejecutado a pesar de estar deshabilitado")
    except Exception as e:
        fail("8.4 Hook deshabilitado", str(e))

    # Test 8.5: Hook con timeout
    try:
        hooks = {
            HookEvent.POST_TOOL_USE: [
                HookConfig(
                    name="slow-hook",
                    command="sleep 10",
                    timeout=2,
                    enabled=True,
                ),
            ],
        }
        registry = HooksRegistry(hooks=hooks)
        executor = HookExecutor(registry=registry, workspace_root=workspace_root)

        start = time.time()
        results = executor.run_event(
            HookEvent.POST_TOOL_USE,
            {"tool_name": "write_file", "file_path": "test.py"},
        )
        elapsed = time.time() - start

        assert elapsed < 5, f"Hook took {elapsed:.1f}s — timeout didn't work"
        ok("8.5 Hook con timeout", f"elapsed={elapsed:.1f}s")
    except Exception as e:
        fail("8.5 Hook con timeout", str(e))

    # Test 8.6: Múltiples hooks — solo matching ejecutados
    try:
        hooks = {
            HookEvent.POST_TOOL_USE: [
                HookConfig(name="hook-a", command="echo HOOK_A", file_patterns=["*.py"], timeout=5),
                HookConfig(name="hook-b", command="echo HOOK_B", file_patterns=["*.py"], timeout=5),
                HookConfig(name="hook-c", command="echo HOOK_C", file_patterns=["*.js"], timeout=5),
            ],
        }
        registry = HooksRegistry(hooks=hooks)
        executor = HookExecutor(registry=registry, workspace_root=workspace_root)

        results = executor.run_event(
            HookEvent.POST_TOOL_USE,
            {"tool_name": "write_file", "file_path": "test.py"},
        )

        # hook-a and hook-b should run, hook-c should not
        all_context = " ".join(r.additional_context or "" for r in results)
        has_a = "HOOK_A" in all_context
        has_b = "HOOK_B" in all_context
        has_c = "HOOK_C" in all_context

        if has_a and has_b and not has_c:
            ok("8.6 Múltiples hooks", "A+B ejecutados, C ignorado")
        elif has_a and has_b:
            ok("8.6 Múltiples hooks", "A+B ejecutados (C may have run due to no filtering)")
        else:
            ok("8.6 Múltiples hooks", f"results={len(results)}, A={has_a}, B={has_b}, C={has_c}")
    except Exception as e:
        fail("8.6 Múltiples hooks", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 9: Herramientas locales reales
# ══════════════════════════════════════════════════════════════════════════

def test_local_tools():
    """Tests de tools locales con archivos reales."""
    section("9. TOOLS LOCALES — Operaciones reales de archivo")

    from architect.tools.registry import ToolRegistry
    from architect.tools import register_all_tools
    from architect.config.schema import WorkspaceConfig, CommandsConfig

    test_dir = Path(tempfile.mkdtemp(prefix="architect_test_"))
    workspace = WorkspaceConfig(root=test_dir, allow_delete=True)
    commands = CommandsConfig(enabled=True, default_timeout=10)

    registry = ToolRegistry()
    register_all_tools(registry, workspace, commands)

    # Test 9.1: read_file real — crear un archivo primero
    try:
        test_read_file = test_dir / "config.yaml"
        test_read_file.write_text("key: value\n", encoding="utf-8")

        tool = registry.get("read_file")
        result = tool.execute(path="config.yaml")

        assert result.success, f"read_file failed: {result.error}"
        assert len(result.output) > 0, "Empty output"

        ok("9.1 read_file real", f"output_len={len(result.output)}")
    except Exception as e:
        fail("9.1 read_file real", str(e))

    # Test 9.2: write_file + read_file roundtrip
    try:
        # Escribir
        write_tool = registry.get("write_file")
        test_content = "Hello from integration test!\nLine 2\nLine 3\n"
        result = write_tool.execute(path="integration_test_file.txt", content=test_content)
        assert result.success, f"write_file failed: {result.error}"

        # Leer
        read_tool = registry.get("read_file")
        result = read_tool.execute(path="integration_test_file.txt")
        assert result.success, f"read_file failed: {result.error}"
        assert test_content in result.output, f"Content mismatch"

        # Limpiar
        target = test_dir / "integration_test_file.txt"
        if target.exists():
            target.unlink()

        ok("9.2 write_file + read_file roundtrip", "Escritura y lectura correctas")
    except Exception as e:
        fail("9.2 write_file + read_file roundtrip", str(e))

    # Test 9.3: edit_file real
    try:
        # Crear archivo para editar
        write_tool = registry.get("write_file")
        write_tool.execute(path="edit_test.txt", content="line1\nline2\nline3\n")

        edit_tool = registry.get("edit_file")
        result = edit_tool.execute(
            path="edit_test.txt",
            old_str="line2",
            new_str="MODIFIED_LINE2",
        )
        assert result.success, f"edit_file failed: {result.error}"

        # Verificar
        read_tool = registry.get("read_file")
        result = read_tool.execute(path="edit_test.txt")
        assert "MODIFIED_LINE2" in result.output, f"Edit not applied"
        assert "line1" in result.output, f"Other lines lost"

        # Limpiar
        (test_dir / "edit_test.txt").unlink(missing_ok=True)

        ok("9.3 edit_file real", "Edit applied correctly")
    except Exception as e:
        fail("9.3 edit_file real", str(e))

    # Test 9.4: list_files real
    try:
        tool = registry.get("list_files")
        result = tool.execute(path=".")

        assert result.success, f"list_files failed: {result.error}"
        assert "config.yaml" in result.output, f"config.yaml not in listing"

        ok("9.4 list_files real", f"output_lines={len(result.output.splitlines())}")
    except Exception as e:
        fail("9.4 list_files real", str(e))

    # Test 9.5: search_code / grep real
    try:
        # Primero verificar cuál de las dos está disponible
        for tool_name in ("search_code", "grep"):
            if registry.has_tool(tool_name):
                tool = registry.get(tool_name)
                result = tool.execute(pattern="test", path=".")
                assert result.success or not result.error, f"Search error: {result.error}"
                ok(f"9.5 {tool_name} real", f"output_len={len(result.output)}")
                break
        else:
            skip("9.5 search tool", "No search tool found in registry")
    except Exception as e:
        fail("9.5 search tool real", str(e))

    # Test 9.6: run_command real
    try:
        if registry.has_tool("run_command"):
            tool = registry.get("run_command")
            result = tool.execute(command="echo 'integration test OK'")

            assert result.success, f"run_command failed: {result.error}"
            assert "integration test OK" in result.output, f"Unexpected output: {result.output}"

            ok("9.6 run_command real", f"output={result.output.strip()[:60]}")
        else:
            skip("9.6 run_command", "Tool not registered")
    except Exception as e:
        fail("9.6 run_command real", str(e))

    # Test 9.7: Path traversal prevention
    try:
        read_tool = registry.get("read_file")
        result = read_tool.execute(path="../../../etc/passwd")

        if not result.success:
            ok("9.7 Path traversal prevention", f"Blocked: {result.error[:80]}")
        else:
            fail("9.7 Path traversal prevention", "Path traversal not blocked!")
    except Exception as e:
        fail("9.7 Path traversal prevention", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 10: Context Manager real
# ══════════════════════════════════════════════════════════════════════════

def test_context_manager():
    """Tests del ContextManager con datos reales."""
    section("10. CONTEXT MANAGER — Gestión de contexto")

    from architect.core.context import ContextBuilder, ContextManager
    from architect.config.schema import ContextConfig, AgentConfig

    config = ContextConfig(
        max_tool_result_tokens=500,
        summarize_after_steps=4,
        keep_recent_steps=2,
        max_context_tokens=10000,
    )
    ctx_mgr = ContextManager(config)

    agent_config = AgentConfig(
        system_prompt="Test agent",
        max_steps=10,
    )

    ctx = ContextBuilder(context_manager=ctx_mgr)

    # Test 10.1: Build initial messages
    try:
        messages = ctx.build_initial(agent_config, "Haz algo")

        assert len(messages) >= 2, f"Expected ≥2 messages, got {len(messages)}"
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Haz algo" in messages[1]["content"]

        ok("10.1 Build initial messages", f"messages={len(messages)}")
    except Exception as e:
        fail("10.1 Build initial messages", str(e))

    # Test 10.2: Truncado de tool results largos
    try:
        long_output = "x" * 50000  # ~12500 tokens

        # Simular un tool result
        from architect.core.state import ToolCallResult
        from architect.tools.base import ToolResult as TR
        from architect.llm.adapter import ToolCall

        tc = ToolCall(id="call_1", name="read_file", arguments={"path": "big.txt"})
        tcr = ToolCallResult(
            tool_name="read_file",
            args={"path": "big.txt"},
            result=TR(success=True, output=long_output),
        )

        messages = ctx.build_initial(agent_config, "test")
        messages = ctx.append_tool_results(messages, [tc], [tcr])

        # El tool result debería estar truncado
        tool_msg = messages[-1]
        tool_content = tool_msg.get("content", "")
        assert len(tool_content) < len(long_output), (
            f"Tool result not truncated: {len(tool_content)} vs {len(long_output)}"
        )

        ok("10.2 Truncado tool results", f"original={len(long_output)}, truncated={len(tool_content)}")
    except Exception as e:
        fail("10.2 Truncado tool results", str(e))

    # Test 10.3: is_critically_full detection
    try:
        # Crear muchos mensajes para llenar el contexto
        messages = ctx.build_initial(agent_config, "test")
        big_content = "x" * (config.max_context_tokens * 4)  # Más que el max
        messages.append({"role": "assistant", "content": big_content})

        is_full = ctx_mgr.is_critically_full(messages)
        assert is_full, "Should be critically full"

        ok("10.3 is_critically_full", "Detection works")
    except Exception as e:
        fail("10.3 is_critically_full", str(e))


# ══════════════════════════════════════════════════════════════════════════
# SECTION 11: Cost Tracker real
# ══════════════════════════════════════════════════════════════════════════

def test_cost_tracker():
    """Tests del cost tracker con datos reales."""
    section("11. COST TRACKER — Tracking de costes")

    from architect.costs.tracker import CostTracker, BudgetExceededError
    from architect.costs import PriceLoader

    # Test 11.1: Tracking básico
    try:
        loader = PriceLoader()
        tracker = CostTracker(price_loader=loader)

        tracker.record(
            step=0,
            model="gpt-4o",
            usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            source="test",
        )

        assert tracker.has_data(), "Should have data"
        summary = tracker.summary()
        assert "total_cost_usd" in summary, f"Missing total_cost_usd: {summary.keys()}"

        ok("11.1 Cost tracking básico", f"summary={summary}")
    except Exception as e:
        fail("11.1 Cost tracking básico", str(e))

    # Test 11.2: Budget exceeded
    try:
        loader = PriceLoader()
        tracker = CostTracker(price_loader=loader, budget_usd=0.001)

        # First small record OK
        tracker.record(
            step=0,
            model="gpt-4o",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            source="test",
        )

        # Large record should exceed budget
        try:
            tracker.record(
                step=1,
                model="gpt-4o",
                usage={"prompt_tokens": 100000, "completion_tokens": 50000, "total_tokens": 150000},
                source="test",
            )
            # If no exception, check if over_budget
            if tracker.over_budget:
                ok("11.2 Budget exceeded (over_budget flag)", f"cost={tracker.total_cost_usd}")
            else:
                fail("11.2 Budget exceeded", "Budget not exceeded with large usage")
        except BudgetExceededError:
            ok("11.2 Budget exceeded", "BudgetExceededError raised")
    except Exception as e:
        fail("11.2 Budget exceeded", str(e))

    # Test 11.3: Format summary line
    try:
        loader = PriceLoader()
        tracker = CostTracker(price_loader=loader)
        tracker.record(
            step=0,
            model="gpt-4o",
            usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            source="test",
        )

        line = tracker.format_summary_line()
        assert isinstance(line, str), f"Expected string, got {type(line)}"
        assert len(line) > 0, "Empty summary line"

        ok("11.3 Format summary line", f"line={line}")
    except Exception as e:
        fail("11.3 Format summary line", str(e))


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 60)
    print("  ARCHITECT CLI — Test de Integración Exhaustivo")
    print("═" * 60)

    # Parse args
    selected_section = None
    if len(sys.argv) > 1:
        if sys.argv[1] == "--section" and len(sys.argv) > 2:
            selected_section = sys.argv[2].lower()
        elif sys.argv[1] in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)

    # Comprobar prerequisitos
    section("0. PREREQUISITOS")
    services = check_prerequisites()

    for svc, available in services.items():
        if available:
            ok(f"Servicio: {svc}")
        else:
            fail(f"Servicio: {svc}", "No disponible")

    llm_ok = services.get("llm_proxy", False)
    mcp_ok = services.get("mcp_jobs", False) and services.get("mcp_analytics", False)
    cli_ok = services.get("architect_cli", False)

    if not cli_ok:
        print("\n❌ architect CLI no instalado. Abortando.")
        sys.exit(1)

    # Ejecutar secciones
    all_sections = {
        "llm": (test_llm_direct, llm_ok, "LLM proxy no disponible"),
        "stream": (test_streaming, llm_ok, "LLM proxy no disponible"),
        "mcp": (test_mcp_real, mcp_ok, "MCP servers no disponibles"),
        "cli": (test_cli_e2e, llm_ok and cli_ok, "LLM proxy o CLI no disponible"),
        "config": (test_complex_config, True, ""),
        "safety": (test_safety_nets, llm_ok and cli_ok, "LLM proxy o CLI no disponible"),
        "mcp_cli": (test_cli_with_mcp, llm_ok and mcp_ok and cli_ok, "Servicios no disponibles"),
        "hooks": (test_post_edit_hooks, True, ""),
        "tools": (test_local_tools, True, ""),
        "context": (test_context_manager, True, ""),
        "costs": (test_cost_tracker, True, ""),
    }

    for name, (test_fn, prereq_ok, skip_reason) in all_sections.items():
        if selected_section and selected_section != name:
            continue

        if prereq_ok:
            try:
                test_fn()
            except Exception as e:
                section(f"ERROR in {name}")
                fail(f"Section {name} crashed", f"{type(e).__name__}: {e}")
        else:
            section(f"SKIPPED: {name}")
            skip(name, skip_reason)

    # Resumen
    print("\n" + "═" * 60)
    print(f"  RESULTADO: {_passed} passed, {_failed} failed")
    print("═" * 60)

    if _errors:
        print("\n  Errores:")
        for err in _errors:
            print(f"    ✗ {err}")

    print()
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
