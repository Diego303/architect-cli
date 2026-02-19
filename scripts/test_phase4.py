#!/usr/bin/env python3
"""
Script de prueba para verificar la Fase 4.

Demuestra el funcionamiento del sistema MCP:
- Cliente HTTP con JSON-RPC
- Descubrimiento de tools
- Adapter de tools MCP
- Integración con ToolRegistry

NOTA: Para probar con un servidor MCP real, necesitas:
1. Un servidor MCP corriendo (ej: en http://localhost:3000)
2. Configurarlo en config.yaml o como variable de entorno
"""

import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from architect.config.schema import MCPServerConfig
from architect.logging import configure_logging_basic
from architect.mcp import MCPClient, MCPDiscovery, MCPToolAdapter
from architect.tools import ToolRegistry


def test_mcp_client():
    """Prueba el cliente MCP (requiere servidor corriendo)."""
    print("=" * 70)
    print("PRUEBA 1: MCPClient (requiere servidor MCP)")
    print("=" * 70)
    print()

    # Configuración de ejemplo
    server_config = MCPServerConfig(
        name="test_server",
        url="http://localhost:3000",  # Cambiar según tu servidor
        token_env=None,
        token=None,
    )

    print(f"Intentando conectar a: {server_config.url}")
    print()

    try:
        client = MCPClient(server_config)

        # Intentar listar tools
        print("Listando tools disponibles...")
        tools = client.list_tools()

        print(f"✓ Tools encontradas: {len(tools)}")
        for tool in tools:
            print(f"  - {tool.get('name')}: {tool.get('description', 'Sin descripción')}")

        print()

        # Si hay tools, intentar ejecutar una
        if tools:
            first_tool = tools[0]
            tool_name = first_tool.get("name")

            print(f"Probando ejecución de: {tool_name}")
            print()

            try:
                # Ejecutar con argumentos vacíos (depende de la tool)
                result = client.call_tool(tool_name, {})
                print(f"✓ Resultado:")
                print(f"  {result}")
            except Exception as e:
                print(f"⚠️  Error ejecutando tool (puede requerir argumentos): {e}")

        client.close()

    except Exception as e:
        print(f"❌ Error conectando a servidor MCP: {e}")
        print()
        print("NOTA: Esta prueba requiere un servidor MCP corriendo.")
        print("Si no tienes uno, las siguientes pruebas funcionan sin servidor.")

    print()


def test_mcp_discovery():
    """Prueba el sistema de descubrimiento."""
    print("=" * 70)
    print("PRUEBA 2: MCPDiscovery")
    print("=" * 70)
    print()

    configure_logging_basic()

    # Configurar múltiples servidores (algunos pueden no existir)
    servers = [
        MCPServerConfig(
            name="local_server",
            url="http://localhost:3000",
        ),
        MCPServerConfig(
            name="another_server",
            url="http://localhost:3001",
        ),
    ]

    # Crear registry
    registry = ToolRegistry()

    print(f"Intentando descubrir tools de {len(servers)} servidor(es)...")
    print()

    # Descubrir y registrar
    discovery = MCPDiscovery()
    stats = discovery.discover_and_register(servers, registry)

    # Mostrar resultados
    print("Resultados del descubrimiento:")
    print(f"  Servidores totales: {stats['servers_total']}")
    print(f"  Servidores exitosos: {stats['servers_success']}")
    print(f"  Servidores fallidos: {stats['servers_failed']}")
    print(f"  Tools descubiertas: {stats['tools_discovered']}")
    print(f"  Tools registradas: {stats['tools_registered']}")

    if stats["errors"]:
        print()
        print("Errores:")
        for error in stats["errors"]:
            print(f"  - {error}")

    print()

    # Mostrar tools en registry
    all_tools = registry.list_all()
    print(f"✓ Total de tools en registry: {len(all_tools)}")
    for tool in all_tools:
        print(f"  - {tool.name} (sensitive={tool.sensitive})")

    print()


def test_mcp_adapter():
    """Prueba el adapter de tools MCP."""
    print("=" * 70)
    print("PRUEBA 3: MCPToolAdapter")
    print("=" * 70)
    print()

    # Definición de tool MCP de ejemplo
    tool_definition = {
        "name": "example_tool",
        "description": "Una tool de ejemplo",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Mensaje a procesar"},
                "count": {"type": "integer", "description": "Número de repeticiones"},
            },
            "required": ["message"],
        },
    }

    # Crear un cliente mock (no se usará para ejecutar)
    server_config = MCPServerConfig(name="mock", url="http://mock")
    client = MCPClient(server_config)

    # Crear adapter
    adapter = MCPToolAdapter(
        client=client,
        tool_definition=tool_definition,
        server_name="mock",
    )

    print(f"✓ Adapter creado: {adapter}")
    print(f"  Nombre completo: {adapter.name}")
    print(f"  Nombre original: {adapter._original_name}")
    print(f"  Descripción: {adapter.description}")
    print(f"  Sensible: {adapter.sensitive}")
    print()

    # Verificar modelo de argumentos
    print("Modelo de argumentos generado:")
    schema = adapter.args_model.model_json_schema()
    print(f"  Propiedades: {list(schema.get('properties', {}).keys())}")
    print(f"  Requeridos: {schema.get('required', [])}")
    print()

    # Verificar schema para LLM
    llm_schema = adapter.get_schema()
    print("Schema para LLM (OpenAI format):")
    print(f"  Type: {llm_schema['type']}")
    print(f"  Function name: {llm_schema['function']['name']}")
    print()

    print("NOTA: La ejecución real requiere un servidor MCP funcionando.")
    print()

    client.close()


def test_server_info():
    """Prueba la obtención de info de servidor sin registrar."""
    print("=" * 70)
    print("PRUEBA 4: Información de Servidor")
    print("=" * 70)
    print()

    configure_logging_basic()

    server_config = MCPServerConfig(
        name="test_server",
        url="http://localhost:3000",
    )

    discovery = MCPDiscovery()
    info = discovery.discover_server_info(server_config)

    print(f"Información del servidor '{info['name']}':")
    print(f"  URL: {info['url']}")
    print(f"  Conectado: {info['connected']}")
    print(f"  Tools: {info['tools_count']}")

    if info["connected"]:
        print(f"  Lista de tools:")
        for tool_name in info["tools"]:
            print(f"    - {tool_name}")
    else:
        print(f"  Error: {info['error']}")

    print()


def main():
    """Ejecuta todas las pruebas."""
    print()
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 18 + "PRUEBAS DE FASE 4 - MCP Connector" + " " * 17 + "║")
    print("╚" + "═" * 68 + "╝")
    print()

    # Prueba 1: Cliente MCP (requiere servidor)
    try:
        test_mcp_client()
    except KeyboardInterrupt:
        print("\n⚠️  Prueba interrumpida")

    print("─" * 70)
    print()

    # Prueba 2: Discovery
    try:
        test_mcp_discovery()
    except KeyboardInterrupt:
        print("\n⚠️  Prueba interrumpida")

    print("─" * 70)
    print()

    # Prueba 3: Adapter
    try:
        test_mcp_adapter()
    except KeyboardInterrupt:
        print("\n⚠️  Prueba interrumpida")

    print("─" * 70)
    print()

    # Prueba 4: Server info
    try:
        test_server_info()
    except KeyboardInterrupt:
        print("\n⚠️  Prueba interrumpida")

    print("=" * 70)
    print("✓ PRUEBAS COMPLETADAS")
    print("=" * 70)
    print()
    print("NOTA: Para probar con un servidor MCP real:")
    print("1. Configura un servidor MCP en http://localhost:3000")
    print("2. O actualiza las URLs en este script")
    print("3. O añade servidores MCP en config.yaml:")
    print()
    print("   mcp:")
    print("     servers:")
    print("       - name: my_server")
    print("         url: http://localhost:3000")
    print()


if __name__ == "__main__":
    main()
