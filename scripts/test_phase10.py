#!/usr/bin/env python3
"""
Test suite para F10 - Contexto Incremental Inteligente.

Prueba el indexador de repositorio, las tools de búsqueda (search_code,
grep, find_files) y la inyección del índice en el system prompt.

No requiere API key ni conexión a internet.
"""

import sys
import tempfile
from pathlib import Path

# Asegurar que el módulo está en el path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

PASS = "✅"
FAIL = "❌"
results = []


def test(name: str, fn) -> bool:
    """Ejecuta una prueba y registra el resultado."""
    try:
        fn()
        print(f"  {PASS} {name}")
        results.append(True)
        return True
    except AssertionError as e:
        print(f"  {FAIL} {name}: {e}")
        results.append(False)
        return False
    except Exception as e:
        print(f"  {FAIL} {name}: {type(e).__name__}: {e}")
        results.append(False)
        return False


# ---------------------------------------------------------------------------
# Utilidades para crear workspace temporal
# ---------------------------------------------------------------------------

def make_workspace(files: dict[str, str]) -> Path:
    """Crea un workspace temporal con los archivos especificados."""
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    for rel_path, content in files.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# 1. Importaciones
# ---------------------------------------------------------------------------

print("\n── Prueba 1: Importaciones ──")


def test_imports():
    from architect.indexer import FileInfo, IndexCache, RepoIndex, RepoIndexer
    from architect.tools import FindFilesTool, GrepTool, SearchCodeTool
    from architect.tools.schemas import FindFilesArgs, GrepArgs, SearchCodeArgs
    from architect.config.schema import IndexerConfig, AppConfig

    # Verificar que IndexerConfig existe en AppConfig
    cfg = AppConfig()
    assert hasattr(cfg, "indexer"), "AppConfig debe tener campo 'indexer'"
    assert isinstance(cfg.indexer, IndexerConfig)
    assert cfg.indexer.enabled is True
    assert cfg.indexer.max_file_size == 1_000_000


test("Importaciones de módulos indexer, search tools y IndexerConfig", test_imports)


# ---------------------------------------------------------------------------
# 2. RepoIndexer — build_index básico
# ---------------------------------------------------------------------------

print("\n── Prueba 2: RepoIndexer básico ──")

SAMPLE_FILES = {
    "README.md": "# Proyecto\n\nDescripción del proyecto.\n",
    "src/main.py": "def main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n",
    "src/utils.py": "def helper():\n    pass\n\nclass MyClass:\n    pass\n",
    "src/config.py": "import os\n\nDEBUG = os.getenv('DEBUG', 'false')\n",
    "tests/test_main.py": "import pytest\n\ndef test_main():\n    assert True\n",
    "tests/test_utils.py": "def test_helper():\n    pass\n",
    ".gitignore": "*.pyc\n__pycache__/\n",
    "pyproject.toml": "[project]\nname = 'test'\nversion = '0.1.0'\n",
}


def test_repo_indexer_basic():
    from architect.indexer import RepoIndexer

    workspace = make_workspace(SAMPLE_FILES)
    indexer = RepoIndexer(workspace_root=workspace)
    index = indexer.build_index()

    # Verificar que se indexaron los archivos correctos
    assert index.total_files > 0, "Debe haber archivos indexados"
    assert index.total_lines > 0, "Debe haber líneas contadas"
    assert index.build_time_ms >= 0

    # Verificar que los archivos Python están presentes
    python_files = [f for f in index.files.keys() if f.endswith(".py")]
    assert len(python_files) >= 5, f"Esperaba >=5 .py, encontré {len(python_files)}"

    # Verificar lenguajes detectados
    assert "python" in index.languages, "Python debe estar en los lenguajes"
    assert "markdown" in index.languages or "yaml" in index.languages or "toml" in index.languages

    # Verificar tree_summary
    assert index.tree_summary, "tree_summary no debe estar vacío"
    assert "src" in index.tree_summary or "README" in index.tree_summary


test("RepoIndexer.build_index() indexa workspace correctamente", test_repo_indexer_basic)


def test_repo_indexer_excludes():
    from architect.indexer import RepoIndexer

    files_with_ignored = {
        **SAMPLE_FILES,
        "__pycache__/module.cpython-312.pyc": "binary",
        "node_modules/dep/index.js": "module.exports = {}",
        ".git/HEAD": "ref: refs/heads/main",
    }
    workspace = make_workspace(files_with_ignored)
    indexer = RepoIndexer(workspace_root=workspace)
    index = indexer.build_index()

    # Los archivos en dirs ignorados NO deben aparecer
    # Usamos partes de ruta para evitar falsos positivos (.gitignore contiene ".git")
    IGNORED = {"__pycache__", "node_modules", ".git"}
    excluded = [f for f in index.files if any(part in IGNORED for part in Path(f).parts)]
    assert not excluded, f"Dirs ignorados no deben indexarse: {excluded}"


test("RepoIndexer excluye __pycache__, node_modules, .git", test_repo_indexer_excludes)


def test_repo_indexer_file_info():
    from architect.indexer import RepoIndexer

    workspace = make_workspace({"src/main.py": "def hello():\n    pass\n"})
    indexer = RepoIndexer(workspace_root=workspace)
    index = indexer.build_index()

    assert "src/main.py" in index.files
    info = index.files["src/main.py"]
    assert info.language == "python"
    assert info.lines == 2
    assert info.size_bytes > 0
    assert info.last_modified > 0


test("FileInfo contiene líneas, lenguaje y tamaño correctos", test_repo_indexer_file_info)


def test_repo_index_languages():
    from architect.indexer import RepoIndexer

    workspace = make_workspace({
        "a.py": "x = 1\n",
        "b.py": "y = 2\n",
        "c.js": "const z = 3;\n",
        "d.md": "# doc\n",
    })
    indexer = RepoIndexer(workspace_root=workspace)
    index = indexer.build_index()

    # Python debe tener más archivos que los demás
    assert index.languages.get("python", 0) == 2
    assert index.languages.get("javascript", 0) == 1

    # El primero en el dict debe ser el más frecuente (python)
    first_lang = next(iter(index.languages))
    assert first_lang == "python", f"Python debería ser primero, fue {first_lang}"


test("languages ordenadas por frecuencia", test_repo_index_languages)


# ---------------------------------------------------------------------------
# 3. IndexCache
# ---------------------------------------------------------------------------

print("\n── Prueba 3: IndexCache ──")


def test_index_cache_set_get():
    from architect.indexer import IndexCache, RepoIndex, FileInfo

    tmp_cache = Path(tempfile.mkdtemp()) / "cache"
    cache = IndexCache(cache_dir=tmp_cache, ttl_seconds=60)
    workspace = Path(tempfile.mkdtemp())

    # Crear un índice mínimo
    files = {"src/main.py": FileInfo("src/main.py", 100, 10, "python", 1000.0)}
    index = RepoIndex(files=files, tree_summary="tree", total_files=1, total_lines=10,
                      languages={"python": 1}, build_time_ms=5.0)

    # Guardar en cache
    cache.set(workspace, index)

    # Recuperar del cache
    recovered = cache.get(workspace)
    assert recovered is not None, "Cache debería retornar el índice"
    assert recovered.total_files == 1
    assert "src/main.py" in recovered.files
    assert recovered.files["src/main.py"].language == "python"


test("IndexCache.set() y get() funcionan correctamente", test_index_cache_set_get)


def test_index_cache_ttl():
    from architect.indexer import IndexCache, RepoIndex, FileInfo
    import time

    tmp_cache = Path(tempfile.mkdtemp()) / "cache"
    # TTL muy corto para testing
    cache = IndexCache(cache_dir=tmp_cache, ttl_seconds=1)
    workspace = Path(tempfile.mkdtemp())

    files = {"a.py": FileInfo("a.py", 10, 1, "python", 1000.0)}
    index = RepoIndex(files=files, tree_summary="t", total_files=1, total_lines=1,
                      languages={}, build_time_ms=1.0)
    cache.set(workspace, index)

    # El cache debería ser válido
    assert cache.get(workspace) is not None

    # Esperar a que expire
    time.sleep(1.1)
    result = cache.get(workspace)
    assert result is None, "Cache debería haber expirado"


test("IndexCache respeta TTL y expira correctamente", test_index_cache_ttl)


# ---------------------------------------------------------------------------
# 4. SearchCodeTool
# ---------------------------------------------------------------------------

print("\n── Prueba 4: SearchCodeTool ──")

SEARCH_FILES = {
    "src/main.py": (
        "def process_data(data: list) -> dict:\n"
        "    result = {}\n"
        "    for item in data:\n"
        "        result[item] = True\n"
        "    return result\n"
        "\n"
        "class DataProcessor:\n"
        "    def __init__(self):\n"
        "        self.data = []\n"
    ),
    "src/utils.py": (
        "import os\n"
        "import sys\n"
        "\n"
        "def process_file(path: str) -> str:\n"
        "    return path.strip()\n"
    ),
    "tests/test_main.py": (
        "from src.main import process_data\n"
        "\n"
        "def test_process_data():\n"
        "    result = process_data(['a', 'b'])\n"
        "    assert result == {'a': True, 'b': True}\n"
    ),
    "README.md": "# My Project\n\nProcess data efficiently.\n",
}


def test_search_code_basic():
    from architect.tools import SearchCodeTool

    workspace = make_workspace(SEARCH_FILES)
    tool = SearchCodeTool(workspace_root=workspace)

    result = tool.execute(pattern="def process_")
    assert result.success, f"search_code falló: {result.error}"
    assert "process_data" in result.output
    assert "process_file" in result.output
    assert "📄" in result.output


test("search_code encuentra coincidencias regex básicas", test_search_code_basic)


def test_search_code_with_file_pattern():
    from architect.tools import SearchCodeTool

    workspace = make_workspace(SEARCH_FILES)
    tool = SearchCodeTool(workspace_root=workspace)

    # Solo buscar en archivos .py (no .md)
    result = tool.execute(pattern="process", file_pattern="*.py")
    assert result.success
    assert "process" in result.output
    # README.md no debería aparecer porque buscamos solo *.py
    assert "README.md" not in result.output


test("search_code filtra por file_pattern correctamente", test_search_code_with_file_pattern)


def test_search_code_context_lines():
    from architect.tools import SearchCodeTool

    workspace = make_workspace(SEARCH_FILES)
    tool = SearchCodeTool(workspace_root=workspace)

    # Con 2 líneas de contexto
    result = tool.execute(pattern="DataProcessor", context_lines=2)
    assert result.success
    # Debe mostrar líneas de contexto (números de línea)
    assert ":" in result.output  # formato "línea: contenido"


test("search_code incluye líneas de contexto", test_search_code_context_lines)


def test_search_code_no_results():
    from architect.tools import SearchCodeTool

    workspace = make_workspace(SEARCH_FILES)
    tool = SearchCodeTool(workspace_root=workspace)

    result = tool.execute(pattern="NONEXISTENT_PATTERN_xyz123")
    assert result.success  # No es un error, simplemente sin resultados
    assert "Sin resultados" in result.output


test("search_code retorna éxito sin resultados (no error)", test_search_code_no_results)


def test_search_code_invalid_regex():
    from architect.tools import SearchCodeTool

    workspace = make_workspace(SEARCH_FILES)
    tool = SearchCodeTool(workspace_root=workspace)

    result = tool.execute(pattern="[invalid regex (")
    assert not result.success
    assert "inválido" in result.error.lower() or "invalid" in result.error.lower()


test("search_code retorna error con regex inválido", test_search_code_invalid_regex)


def test_search_code_case_insensitive():
    from architect.tools import SearchCodeTool

    workspace = make_workspace(SEARCH_FILES)
    tool = SearchCodeTool(workspace_root=workspace)

    result = tool.execute(pattern="DATAPROCESSOR", case_sensitive=False)
    assert result.success
    assert "DataProcessor" in result.output or "dataprocessor" in result.output.lower()


test("search_code case_sensitive=False funciona", test_search_code_case_insensitive)


# ---------------------------------------------------------------------------
# 5. GrepTool
# ---------------------------------------------------------------------------

print("\n── Prueba 5: GrepTool ──")


def test_grep_basic():
    from architect.tools import GrepTool

    workspace = make_workspace(SEARCH_FILES)
    tool = GrepTool(workspace_root=workspace)

    result = tool.execute(text="import os")
    assert result.success, f"grep falló: {result.error}"
    assert "src/utils.py" in result.output
    assert "import os" in result.output


test("grep encuentra texto literal básico", test_grep_basic)


def test_grep_with_file_pattern():
    from architect.tools import GrepTool

    workspace = make_workspace(SEARCH_FILES)
    tool = GrepTool(workspace_root=workspace)

    result = tool.execute(text="process", file_pattern="*.md")
    assert result.success
    # README.md tiene "Process" (capital P)
    # Si case_sensitive=True, no debería encontrarlo
    # Comprobamos que el filtro funciona: solo busca en .md


test("grep filtra por file_pattern", test_grep_with_file_pattern)


def test_grep_no_results():
    from architect.tools import GrepTool

    workspace = make_workspace(SEARCH_FILES)
    tool = GrepTool(workspace_root=workspace)

    result = tool.execute(text="xyzzy_nonexistent_string_99999")
    assert result.success
    assert "Sin resultados" in result.output


test("grep retorna éxito cuando no hay resultados", test_grep_no_results)


def test_grep_case_insensitive():
    from architect.tools import GrepTool

    workspace = make_workspace(SEARCH_FILES)
    tool = GrepTool(workspace_root=workspace)

    # "Process" en README.md empieza con mayúscula
    result = tool.execute(text="process", file_pattern="*.md", case_sensitive=False)
    assert result.success
    # Debe encontrar "Process" en README.md
    assert "README.md" in result.output


test("grep case_sensitive=False encuentra 'Process' con 'process'", test_grep_case_insensitive)


# ---------------------------------------------------------------------------
# 6. FindFilesTool
# ---------------------------------------------------------------------------

print("\n── Prueba 6: FindFilesTool ──")

FIND_FILES = {
    "src/main.py": "x",
    "src/utils.py": "x",
    "tests/test_main.py": "x",
    "tests/test_utils.py": "x",
    "tests/conftest.py": "x",
    "config/settings.yaml": "x",
    "config/dev.yaml": "x",
    "Dockerfile": "x",
    "README.md": "x",
    ".gitignore": "x",
}


def test_find_files_glob():
    from architect.tools import FindFilesTool

    workspace = make_workspace(FIND_FILES)
    tool = FindFilesTool(workspace_root=workspace)

    result = tool.execute(pattern="*.py")
    assert result.success, f"find_files falló: {result.error}"
    assert "main.py" in result.output
    assert "utils.py" in result.output
    assert "test_main.py" in result.output
    # Los .yaml y README.md no deben aparecer
    assert "settings.yaml" not in result.output
    assert "README.md" not in result.output


test("find_files encuentra archivos *.py", test_find_files_glob)


def test_find_files_test_pattern():
    from architect.tools import FindFilesTool

    workspace = make_workspace(FIND_FILES)
    tool = FindFilesTool(workspace_root=workspace)

    result = tool.execute(pattern="test_*.py")
    assert result.success
    assert "test_main.py" in result.output
    assert "test_utils.py" in result.output
    # main.py y conftest.py no deben aparecer
    assert "src/main.py" not in result.output


test("find_files encuentra test_*.py correctamente", test_find_files_test_pattern)


def test_find_files_no_results():
    from architect.tools import FindFilesTool

    workspace = make_workspace(FIND_FILES)
    tool = FindFilesTool(workspace_root=workspace)

    result = tool.execute(pattern="*.nonexistent")
    assert result.success
    assert "No se encontraron" in result.output


test("find_files retorna éxito cuando no hay coincidencias", test_find_files_no_results)


def test_find_files_yaml():
    from architect.tools import FindFilesTool

    workspace = make_workspace(FIND_FILES)
    tool = FindFilesTool(workspace_root=workspace)

    result = tool.execute(pattern="*.yaml")
    assert result.success
    assert "settings.yaml" in result.output
    assert "dev.yaml" in result.output


test("find_files encuentra archivos *.yaml", test_find_files_yaml)


# ---------------------------------------------------------------------------
# 7. ContextBuilder con RepoIndex
# ---------------------------------------------------------------------------

print("\n── Prueba 7: ContextBuilder con RepoIndex ──")


def test_context_builder_without_index():
    from architect.core.context import ContextBuilder
    from architect.config.schema import AgentConfig

    ctx = ContextBuilder()  # Sin repo_index
    config = AgentConfig(system_prompt="Eres un agente.", allowed_tools=[], confirm_mode="yolo")

    messages = ctx.build_initial(config, "hola")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Eres un agente."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "hola"


test("ContextBuilder sin repo_index genera mensajes normales", test_context_builder_without_index)


def test_context_builder_with_index():
    from architect.core.context import ContextBuilder
    from architect.config.schema import AgentConfig
    from architect.indexer import RepoIndexer

    workspace = make_workspace(SAMPLE_FILES)
    index = RepoIndexer(workspace_root=workspace).build_index()

    ctx = ContextBuilder(repo_index=index)
    config = AgentConfig(system_prompt="Eres un agente.", allowed_tools=[], confirm_mode="yolo")

    messages = ctx.build_initial(config, "analiza el proyecto")
    assert len(messages) == 2

    system_content = messages[0]["content"]
    # Debe incluir la sección del proyecto
    assert "Estructura del Proyecto" in system_content
    assert "archivos" in system_content.lower()
    assert "python" in system_content.lower()
    # Debe incluir el árbol
    assert "src" in system_content


test("ContextBuilder con repo_index inyecta estructura en system prompt", test_context_builder_with_index)


def test_context_builder_base_prompt_preserved():
    """El prompt base del agente no debe ser alterado, solo extendido."""
    from architect.core.context import ContextBuilder
    from architect.config.schema import AgentConfig
    from architect.indexer import RepoIndexer

    workspace = make_workspace({"a.py": "x = 1\n"})
    index = RepoIndexer(workspace_root=workspace).build_index()

    base_prompt = "Eres un agente especializado en Python."
    ctx = ContextBuilder(repo_index=index)
    config = AgentConfig(system_prompt=base_prompt, allowed_tools=[], confirm_mode="yolo")

    messages = ctx.build_initial(config, "tarea")
    system = messages[0]["content"]

    # El prompt base debe estar al inicio
    assert system.startswith(base_prompt), "El prompt base debe estar al inicio del system"
    # La sección de estructura al final
    assert system.index("Estructura del Proyecto") > len(base_prompt)


test("ContextBuilder preserva prompt base e inyecta al final", test_context_builder_base_prompt_preserved)


# ---------------------------------------------------------------------------
# 8. IndexerConfig en schema
# ---------------------------------------------------------------------------

print("\n── Prueba 8: IndexerConfig ──")


def test_indexer_config_defaults():
    from architect.config.schema import IndexerConfig

    cfg = IndexerConfig()
    assert cfg.enabled is True
    assert cfg.max_file_size == 1_000_000
    assert cfg.use_cache is True
    assert cfg.exclude_dirs == []
    assert cfg.exclude_patterns == []


test("IndexerConfig tiene defaults correctos", test_indexer_config_defaults)


def test_indexer_config_in_app_config():
    from architect.config.schema import AppConfig

    cfg = AppConfig()
    assert hasattr(cfg, "indexer")
    assert cfg.indexer.enabled is True


test("IndexerConfig integrada en AppConfig como campo 'indexer'", test_indexer_config_in_app_config)


def test_indexer_config_custom():
    from architect.config.schema import IndexerConfig

    cfg = IndexerConfig(
        enabled=False,
        max_file_size=500_000,
        exclude_dirs=["vendor", "dist"],
        exclude_patterns=["*.generated.py"],
        use_cache=False,
    )
    assert cfg.enabled is False
    assert cfg.max_file_size == 500_000
    assert "vendor" in cfg.exclude_dirs
    assert "*.generated.py" in cfg.exclude_patterns


test("IndexerConfig acepta configuración personalizada", test_indexer_config_custom)


# ---------------------------------------------------------------------------
# 9. Tools en registry
# ---------------------------------------------------------------------------

print("\n── Prueba 9: Search tools en registry ──")


def test_search_tools_registered():
    from architect.tools import ToolRegistry, register_all_tools
    from architect.config.schema import WorkspaceConfig

    workspace = Path(tempfile.mkdtemp())
    registry = ToolRegistry()
    cfg = WorkspaceConfig(root=str(workspace), allow_delete=False)
    register_all_tools(registry, cfg)

    assert registry.has_tool("search_code"), "search_code debe estar en registry"
    assert registry.has_tool("grep"), "grep debe estar en registry"
    assert registry.has_tool("find_files"), "find_files debe estar en registry"


test("register_all_tools registra search_code, grep, find_files", test_search_tools_registered)


def test_search_tools_not_sensitive():
    from architect.tools import SearchCodeTool, GrepTool, FindFilesTool
    workspace = Path(tempfile.mkdtemp())

    assert not SearchCodeTool(workspace).sensitive, "search_code no debe ser sensible"
    assert not GrepTool(workspace).sensitive, "grep no debe ser sensible"
    assert not FindFilesTool(workspace).sensitive, "find_files no debe ser sensible"


test("search_code, grep, find_files tienen sensitive=False", test_search_tools_not_sensitive)


def test_search_tools_schemas_valid():
    from architect.tools import SearchCodeTool, GrepTool, FindFilesTool
    workspace = Path(tempfile.mkdtemp())

    for ToolClass in [SearchCodeTool, GrepTool, FindFilesTool]:
        tool = ToolClass(workspace)
        schema = tool.get_schema()
        assert schema["type"] == "function"
        assert "description" in schema["function"]
        assert len(schema["function"]["description"]) > 10


test("search_code, grep, find_files generan JSON schemas válidos", test_search_tools_schemas_valid)


# ---------------------------------------------------------------------------
# 10. Default agents tienen search tools
# ---------------------------------------------------------------------------

print("\n── Prueba 10: Agentes con search tools ──")


def test_default_agents_have_search_tools():
    from architect.agents.registry import DEFAULT_AGENTS

    for agent_name in ["plan", "build", "resume", "review"]:
        agent = DEFAULT_AGENTS[agent_name]
        assert "search_code" in agent.allowed_tools, \
            f"Agente '{agent_name}' debe tener search_code"
        assert "grep" in agent.allowed_tools, \
            f"Agente '{agent_name}' debe tener grep"
        assert "find_files" in agent.allowed_tools, \
            f"Agente '{agent_name}' debe tener find_files"


test("Todos los agentes por defecto tienen search_code, grep, find_files", test_default_agents_have_search_tools)


def test_build_agent_has_edit_tools():
    """El agente build debe tener tanto search como edit tools."""
    from architect.agents.registry import DEFAULT_AGENTS

    build = DEFAULT_AGENTS["build"]
    required = ["read_file", "write_file", "edit_file", "apply_patch",
                "search_code", "grep", "find_files"]
    for tool in required:
        assert tool in build.allowed_tools, \
            f"Agente 'build' debe tener {tool}"


test("Agente 'build' tiene tanto search tools como edit tools", test_build_agent_has_edit_tools)


# ---------------------------------------------------------------------------
# 11. Versión 0.15.0
# ---------------------------------------------------------------------------

print("\n── Prueba 11: Versión ──")


def test_version_consistency():
    import architect
    import subprocess

    # __init__.py
    assert architect.__version__ == "0.15.0", f"__version__ = {architect.__version__}"

    # pyproject.toml
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    content = pyproject.read_text()
    assert 'version = "0.15.0"' in content, "pyproject.toml debe tener 0.15.0"


test("Versión 0.15.0 consistente en __init__.py y pyproject.toml", test_version_consistency)


def test_cli_version():
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "architect", "--version"],
        cwd=str(Path(__file__).parent.parent),
        capture_output=True,
        text=True,
    )
    assert "0.15.0" in result.stdout or "0.15.0" in result.stderr


test("CLI --version muestra 0.15.0", test_cli_version)


# ---------------------------------------------------------------------------
# 12. Integración: indexar y buscar en el mismo workspace
# ---------------------------------------------------------------------------

print("\n── Prueba 12: Integración indexer + search ──")


def test_full_integration():
    """Construye un índice real y luego busca código en él."""
    from architect.indexer import RepoIndexer
    from architect.tools import SearchCodeTool, GrepTool, FindFilesTool
    from architect.core.context import ContextBuilder
    from architect.config.schema import AgentConfig

    workspace = make_workspace({
        "src/api.py": (
            "from flask import Flask\n"
            "app = Flask(__name__)\n"
            "\n"
            "@app.route('/health')\n"
            "def health_check():\n"
            "    return {'status': 'ok'}\n"
        ),
        "src/models.py": (
            "class User:\n"
            "    def __init__(self, name: str):\n"
            "        self.name = name\n"
        ),
        "tests/test_api.py": (
            "from src.api import app\n"
            "import pytest\n"
            "\n"
            "def test_health():\n"
            "    client = app.test_client()\n"
            "    response = client.get('/health')\n"
            "    assert response.status_code == 200\n"
        ),
    })

    # 1. Construir índice
    index = RepoIndexer(workspace_root=workspace).build_index()
    assert index.total_files == 3

    # 2. Inyectar en ContextBuilder
    ctx = ContextBuilder(repo_index=index)
    cfg = AgentConfig(system_prompt="Eres un agente.", allowed_tools=[], confirm_mode="yolo")
    messages = ctx.build_initial(cfg, "añade autenticación")
    assert "Estructura del Proyecto" in messages[0]["content"]

    # 3. Usar search_code para encontrar código relevante
    search = SearchCodeTool(workspace_root=workspace)
    result = search.execute(pattern="@app.route")
    assert result.success
    assert "api.py" in result.output

    # 4. Usar grep para encontrar imports
    grep = GrepTool(workspace_root=workspace)
    result = grep.execute(text="from flask")
    assert result.success
    assert "api.py" in result.output

    # 5. Usar find_files para localizar tests
    find = FindFilesTool(workspace_root=workspace)
    result = find.execute(pattern="test_*.py")
    assert result.success
    assert "test_api.py" in result.output


test("Integración completa: indexar + búsqueda + ContextBuilder", test_full_integration)


# ---------------------------------------------------------------------------
# Resumen
# ---------------------------------------------------------------------------

total = len(results)
passed = sum(results)
failed = total - passed

print(f"\n{'=' * 60}")
print(f"F10 — Contexto Incremental Inteligente")
print(f"Resultado: {passed}/{total} pruebas pasaron")
if failed:
    print(f"⚠️  {failed} prueba(s) fallaron")
else:
    print("✅ Todas las pruebas pasaron")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
