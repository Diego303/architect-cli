#!/usr/bin/env python3
"""
Script de prueba para Fase 9 - Diff Inteligente y apply_patch.

Prueba las nuevas herramientas de edición:
1. EditFileTool (str_replace) — caso feliz
2. EditFileTool — old_str no encontrado
3. EditFileTool — old_str ambiguo (>1 ocurrencias)
4. EditFileTool — old_str vacío
5. ApplyPatchTool — parche válido (single-hunk)
6. ApplyPatchTool — parche multi-hunk
7. ApplyPatchTool — parche de inserción pura (orig_count=0)
8. ApplyPatchTool — contexto incorrecto (debe fallar con error claro)
9. Jerarquía en descriptions de tools
10. Exportaciones del módulo tools

No requieren API key.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

EXPECTED_VERSION = "0.9.0"


def _separator(title: str) -> None:
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    sys.exit(1)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_file(tmp_dir: Path, name: str, content: str) -> Path:
    p = tmp_dir / name
    p.write_text(content, encoding="utf-8")
    return p


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_imports() -> None:
    _separator("Test 1 — Importaciones del módulo tools")
    from architect.tools import (
        ApplyPatchArgs,
        ApplyPatchTool,
        EditFileArgs,
        EditFileTool,
        PatchError,
    )
    _ok("EditFileTool importado")
    _ok("ApplyPatchTool importado")
    _ok("PatchError importado")
    _ok("EditFileArgs importado")
    _ok("ApplyPatchArgs importado")


def test_version_consistency() -> None:
    _separator("Test 2 — Consistencia de versión 0.9.0")
    import architect
    if architect.__version__ != EXPECTED_VERSION:
        _fail(f"__version__ = {architect.__version__!r}, esperado {EXPECTED_VERSION!r}")
    _ok(f"architect.__version__ == {EXPECTED_VERSION!r}")

    import tomllib
    toml_path = Path(__file__).parent.parent / "pyproject.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    toml_ver = data["project"]["version"]
    if toml_ver != EXPECTED_VERSION:
        _fail(f"pyproject.toml version = {toml_ver!r}, esperado {EXPECTED_VERSION!r}")
    _ok(f"pyproject.toml version == {EXPECTED_VERSION!r}")


def test_edit_file_success() -> None:
    _separator("Test 3 — EditFileTool caso feliz (str_replace)")
    from architect.tools import EditFileTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = _make_file(root, "hello.py", "def hello():\n    return 'world'\n")

        tool = EditFileTool(root)
        result = tool.execute(
            path="hello.py",
            old_str="    return 'world'",
            new_str="    return 'Python'",
        )

        if not result.success:
            _fail(f"Debería tener éxito: {result.error}")

        content = f.read_text()
        if "return 'Python'" not in content:
            _fail(f"Contenido inesperado: {content!r}")
        if "return 'world'" in content:
            _fail("old_str todavía presente en el archivo")

        if "Diff:" not in result.output:
            _fail("El output debería incluir el diff")

        _ok("Reemplazo aplicado correctamente")
        _ok("Diff incluido en el output")


def test_edit_file_not_found() -> None:
    _separator("Test 4 — EditFileTool old_str no encontrado")
    from architect.tools import EditFileTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_file(root, "f.py", "x = 1\ny = 2\n")

        tool = EditFileTool(root)
        result = tool.execute(path="f.py", old_str="z = 99", new_str="z = 100")

        if result.success:
            _fail("Debería fallar cuando old_str no existe")
        if "no encontrado" not in (result.error or ""):
            _fail(f"Error esperado 'no encontrado', obtenido: {result.error!r}")
        _ok(f"Error correcto: {result.error!r}")


def test_edit_file_ambiguous() -> None:
    _separator("Test 5 — EditFileTool old_str ambiguo")
    from architect.tools import EditFileTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_file(root, "f.py", "x = 1\nx = 1\n")

        tool = EditFileTool(root)
        result = tool.execute(path="f.py", old_str="x = 1", new_str="x = 2")

        if result.success:
            _fail("Debería fallar cuando old_str aparece múltiples veces")
        if "2 veces" not in (result.error or "") and "veces" not in (result.error or ""):
            _fail(f"Error esperado con conteo, obtenido: {result.error!r}")
        _ok(f"Error correcto: {result.error!r}")


def test_edit_file_empty_old_str() -> None:
    _separator("Test 6 — EditFileTool old_str vacío")
    from architect.tools import EditFileTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_file(root, "f.py", "x = 1\n")

        tool = EditFileTool(root)
        result = tool.execute(path="f.py", old_str="", new_str="algo")

        if result.success:
            _fail("Debería fallar cuando old_str es vacío")
        _ok(f"Error correcto para old_str vacío: {result.error!r}")


def test_apply_patch_single_hunk() -> None:
    _separator("Test 7 — ApplyPatchTool parche single-hunk")
    from architect.tools import ApplyPatchTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = _make_file(root, "code.py", "line1\nline2\nline3\nline4\n")

        # Reemplaza line2 por line2_modified
        patch = "@@ -1,4 +1,4 @@\n line1\n-line2\n+line2_modified\n line3\n line4\n"

        tool = ApplyPatchTool(root)
        result = tool.execute(path="code.py", patch=patch)

        if not result.success:
            _fail(f"Debería tener éxito: {result.error}")

        content = f.read_text()
        if "line2_modified" not in content:
            _fail(f"Contenido inesperado: {content!r}")
        if "line2\n" in content:
            _fail("La línea original todavía está presente")

        _ok("Parche single-hunk aplicado correctamente")
        _ok(f"Output: {result.output!r}")


def test_apply_patch_multi_hunk() -> None:
    _separator("Test 8 — ApplyPatchTool parche multi-hunk")
    from architect.tools import ApplyPatchTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        content = "\n".join(f"line{i}" for i in range(1, 11)) + "\n"
        f = _make_file(root, "multi.py", content)

        # Modifica line2 y line8
        patch = (
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_NEW\n"
            " line3\n"
            "@@ -7,4 +7,4 @@\n"
            " line7\n"
            "-line8\n"
            "+line8_NEW\n"
            " line9\n"
            " line10\n"
        )

        tool = ApplyPatchTool(root)
        result = tool.execute(path="multi.py", patch=patch)

        if not result.success:
            _fail(f"Debería tener éxito: {result.error}")

        new_content = f.read_text()
        if "line2_NEW" not in new_content:
            _fail("line2_NEW no está en el resultado")
        if "line8_NEW" not in new_content:
            _fail("line8_NEW no está en el resultado")

        _ok("Parche multi-hunk (2 hunks) aplicado correctamente")


def test_apply_patch_insertion() -> None:
    _separator("Test 9 — ApplyPatchTool inserción pura (orig_count=0)")
    from architect.tools import ApplyPatchTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = _make_file(root, "ins.py", "line1\nline2\nline3\n")

        # Insertar después de line1 (orig_start=1, orig_count=0)
        patch = "@@ -1,0 +2,1 @@\n+inserted_line\n"

        tool = ApplyPatchTool(root)
        result = tool.execute(path="ins.py", patch=patch)

        if not result.success:
            _fail(f"Debería tener éxito: {result.error}")

        new_content = f.read_text()
        if "inserted_line" not in new_content:
            _fail(f"Línea insertada no encontrada: {new_content!r}")

        _ok("Inserción pura aplicada correctamente")
        _ok(f"Contenido: {new_content!r}")


def test_apply_patch_bad_context() -> None:
    _separator("Test 10 — ApplyPatchTool contexto incorrecto")
    from architect.tools import ApplyPatchTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_file(root, "bad.py", "alpha\nbeta\ngamma\n")

        # Parche que espera "foo" pero el archivo tiene "alpha"
        patch = "@@ -1,3 +1,3 @@\n foo\n-bar\n+baz\n gamma\n"

        tool = ApplyPatchTool(root)
        result = tool.execute(path="bad.py", patch=patch)

        if result.success:
            _fail("Debería fallar cuando el contexto no coincide")
        _ok(f"Error correcto: {result.error!r}")


def test_tool_descriptions_hierarchy() -> None:
    _separator("Test 11 — Jerarquía en descriptions de tools")
    from architect.tools import ApplyPatchTool, EditFileTool, WriteFileTool

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        edit = EditFileTool(root)
        patch = ApplyPatchTool(root)
        write = WriteFileTool(root)

        if "PREFERIR" not in edit.description and "preferir" not in edit.description.lower():
            _fail(f"EditFileTool description no menciona preferencia: {edit.description!r}")
        _ok("EditFileTool description menciona jerarquía de preferencia")

        if "write_file" not in patch.description:
            _fail("ApplyPatchTool description debería mencionar write_file como alternativa")
        _ok("ApplyPatchTool description menciona write_file")

        if "edit_file" not in write.description:
            _fail("WriteFileTool description debería mencionar edit_file como alternativa")
        _ok("WriteFileTool description menciona edit_file")


def test_new_tools_in_registry() -> None:
    _separator("Test 12 — Nuevas tools registradas en ToolRegistry")
    from architect.config.schema import WorkspaceConfig
    from architect.tools import ToolRegistry, register_filesystem_tools

    with tempfile.TemporaryDirectory() as tmp:
        ws = WorkspaceConfig(root=tmp)
        registry = ToolRegistry()
        register_filesystem_tools(registry, ws)

        tool_names = list(registry._tools.keys())

        for expected in ("edit_file", "apply_patch"):
            if expected not in tool_names:
                _fail(f"Tool {expected!r} no está en el registry. Disponibles: {tool_names}")
            _ok(f"Tool {expected!r} registrada")

        _ok(f"Todas las tools disponibles: {tool_names}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Fase 9 — Diff Inteligente y apply_patch")
    print("=" * 60)

    test_imports()
    test_version_consistency()
    test_edit_file_success()
    test_edit_file_not_found()
    test_edit_file_ambiguous()
    test_edit_file_empty_old_str()
    test_apply_patch_single_hunk()
    test_apply_patch_multi_hunk()
    test_apply_patch_insertion()
    test_apply_patch_bad_context()
    test_tool_descriptions_hierarchy()
    test_new_tools_in_registry()

    print(f"\n{'═' * 60}")
    print("  ✅ Todos los tests de Fase 9 pasaron correctamente")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
