# Guía Técnica de Architect CLI (CLAUDE.md)

Esta guía proporciona la información técnica necesaria para que agentes de IA operen eficientemente en el proyecto `architect-cli`.

## Comandos de Desarrollo

### Instalación y Setup
```bash
# Instalación en modo editable con dependencias de desarrollo
pip install -e .[dev]
```

### Ejecución de la CLI
```bash
# Ejecución directa (vía entrypoint)
architect run "tu prompt aqui"

# Ejecución como módulo
python -m architect run "tu prompt aqui"
```

### Tests y Calidad
```bash
# Ejecutar todos los tests con cobertura
pytest

# Comprobar tipado estático
mypy src

# Formateo y linting
black .
ruff check .
```

## Guías de Estilo y Arquitectura

### Estándares de Código
- **Versión**: Python 3.12+ (aprovechar pattern matching y tipos modernos).
- **Tipado**: Uso estricto de `typing` y validación con **Pydantic v2**.
- **Formato**: Seguir estándares de `black` (100 caracteres de ancho).
- **Logging**: Usar `structlog` para logs estructurados (JSON en producción).

### Principios de Diseño
1.  **Inmutabilidad**: El estado del agente (`AgentState`) debe ser tratado como inmutable entre pasos. Cada paso genera un nuevo estado o resultado.
2.  **Seguridad**: Todas las herramientas de sistema de archivos deben validar que el path esté dentro del `workspace_root` (prevención de Path Traversal).
3.  **Abstracción LLM**: Usar exclusivamente `LiteLLM` para interactuar con modelos. No añadir capas extra innecesarias.
4.  **Tools**: Cada herramienta debe heredar de `BaseTool` y definir su schema mediante un modelo Pydantic (`args_model`).

## Estructura del Proyecto

- `src/architect/core/`: Lógica central del loop del agente y gestión de estado.
- `src/architect/tools/`: Implementación de herramientas locales (fs, etc.).
- `src/architect/llm/`: Adaptadores para LiteLLM.
- `src/architect/mcp/`: Cliente y conectores para servidores MCP remotos.
- `src/architect/execution/`: Motor de ejecución con políticas de confirmación y seguridad.
- `src/architect/config/`: Schemas de configuración y carga de YAML/ENV.

## Flujo del Agente
El loop es determinista y lineal: `LLM → Parse → Validate → Execute → Repeat`.
No se permiten excepciones que rompan el loop; los errores de ejecución se devuelven al LLM como el resultado de la herramienta para que pueda razonar y corregir.
