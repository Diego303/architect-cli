"""
Tool para aplicar parches en formato unified diff.

Implementa un parser puro-Python de unified diff y aplica los hunks
al archivo objetivo. Usa el comando `patch` del sistema como fallback
si el parser puro falla.
"""

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..execution.validators import (
    PathTraversalError,
    ValidationError,
    validate_file_exists,
    validate_path,
)
from .base import BaseTool, ToolResult
from .schemas import ApplyPatchArgs

# ─────────────────────────────────────────────────────────────────────────────
# Internals: parser y aplicador de unified diff
# ─────────────────────────────────────────────────────────────────────────────

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    """Error al parsear o aplicar un parche unified diff."""


@dataclass
class _Hunk:
    """Representa un hunk (@@ ... @@) de un unified diff."""

    orig_start: int  # Número de línea 1-based en el original donde empieza el hunk
    orig_count: int  # Número de líneas del original consumidas por el hunk
    new_start: int   # Número de línea 1-based en el resultado
    new_count: int   # Número de líneas en el resultado
    lines: list[str] = field(default_factory=list)  # Líneas del hunk (sin \n final de línea de diff)


def _parse_hunks(patch_text: str) -> list[_Hunk]:
    """Parsea un texto de unified diff y devuelve una lista de hunks.

    Ignora las cabeceras --- / +++ si están presentes.
    Acepta patches con o sin cabeceras de archivo.

    Args:
        patch_text: Contenido del parche en formato unified diff

    Returns:
        Lista de _Hunk en orden de aparición

    Raises:
        PatchError: Si el formato es inválido
    """
    hunks: list[_Hunk] = []
    current: _Hunk | None = None

    for line in patch_text.split("\n"):
        # Ignorar cabeceras de archivo (--- / +++)
        if line.startswith("--- ") or line.startswith("+++ "):
            continue

        m = _HUNK_HEADER.match(line)
        if m:
            if current is not None:
                hunks.append(current)
            orig_start = int(m.group(1))
            orig_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            current = _Hunk(orig_start, orig_count, new_start, new_count)
        elif current is not None:
            # Acumular líneas del hunk actual
            if line.startswith(("-", "+", " ")):
                current.lines.append(line)
            # Ignorar "\ No newline at end of file" y otras anotaciones

    if current is not None:
        hunks.append(current)

    return hunks


def _apply_hunks_to_lines(
    lines: list[str],
    hunks: list[_Hunk],
    path: str,
) -> list[str]:
    """Aplica una lista de hunks a una lista de líneas de archivo.

    Cada línea de `lines` debe terminar en '\\n' (excepto posiblemente la última).
    Las líneas del hunk son strings sin '\\n' al final (solo el prefijo +/-/ ).

    Args:
        lines: Contenido del archivo como lista de líneas (con endings)
        hunks: Hunks a aplicar en orden
        path: Path del archivo (solo para mensajes de error)

    Returns:
        Contenido modificado como lista de líneas

    Raises:
        PatchError: Si un hunk no coincide con el contenido actual
    """
    result = list(lines)
    offset = 0  # Delta acumulado de líneas añadidas/eliminadas

    for hunk in hunks:
        # Separar orig_content (lo que debe estar) y new_content (lo que irá)
        orig_content: list[str] = []
        new_content: list[str] = []

        for hunk_line in hunk.lines:
            if hunk_line.startswith("-"):
                orig_content.append(hunk_line[1:])
            elif hunk_line.startswith("+"):
                new_content.append(hunk_line[1:])
            else:
                # Línea de contexto (empieza con " " o es vacía)
                content = hunk_line[1:] if hunk_line.startswith(" ") else hunk_line
                orig_content.append(content)
                new_content.append(content)

        # Calcular posición de inserción en el resultado (con offset acumulado)
        if hunk.orig_count == 0:
            # Inserción pura: se inserta DESPUÉS de la línea orig_start
            insert_at = hunk.orig_start + offset
        else:
            # Reemplazo: comienza en orig_start (1-based → 0-based)
            insert_at = hunk.orig_start - 1 + offset

        # Validar que orig_content coincida con el contenido actual del archivo
        if hunk.orig_count > 0:
            actual_slice = result[insert_at : insert_at + hunk.orig_count]
            actual_stripped = [ln.rstrip("\n\r") for ln in actual_slice]
            expected_stripped = [ln.rstrip("\n\r") for ln in orig_content]

            if actual_stripped != expected_stripped:
                raise PatchError(
                    f"El hunk @@ -{hunk.orig_start},{hunk.orig_count} no coincide con el "
                    f"contenido actual de {path}. "
                    f"¿El parche corresponde a una versión diferente del archivo?"
                )

        # Construir las líneas nuevas con endings correctos
        # Si el contenido del parche no tiene \n, añadirlo (para que coincida con el formato del archivo)
        new_file_lines: list[str] = []
        for content in new_content:
            if content.endswith("\n"):
                new_file_lines.append(content)
            else:
                new_file_lines.append(content + "\n")

        # Aplicar el hunk
        result[insert_at : insert_at + hunk.orig_count] = new_file_lines
        offset += len(new_file_lines) - hunk.orig_count

    return result


def _apply_patch_pure(file_content: str, patch_text: str, path: str) -> str:
    """Aplica un unified diff a un contenido de archivo usando Python puro.

    Args:
        file_content: Contenido actual del archivo
        patch_text: Parche en formato unified diff
        path: Path del archivo (para mensajes de error)

    Returns:
        Contenido modificado

    Raises:
        PatchError: Si el parche no puede aplicarse
    """
    if not patch_text.strip():
        raise PatchError("El parche está vacío.")

    hunks = _parse_hunks(patch_text)
    if not hunks:
        raise PatchError(
            "No se encontraron hunks válidos en el parche. "
            "El formato esperado es: @@ -a,b +c,d @@ (una o más secciones)."
        )

    lines = file_content.splitlines(keepends=True)
    result_lines = _apply_hunks_to_lines(lines, hunks, path)
    return "".join(result_lines)


def _apply_patch_system(file_path: Path, patch_text: str) -> str:
    """Aplica un parche usando el comando `patch` del sistema como fallback.

    Hace un --dry-run primero para validar, luego aplica.

    Args:
        file_path: Path al archivo a parchear
        patch_text: Parche en formato unified diff

    Returns:
        Contenido del archivo modificado

    Raises:
        PatchError: Si `patch` no está disponible o el parche falla
    """
    patch_exe = shutil.which("patch")
    if patch_exe is None:
        raise PatchError(
            "El comando `patch` no está disponible en el sistema. "
            "Instálalo con: apt install patch / brew install gpatch"
        )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(patch_text)
        patch_file = Path(tmp.name)

    try:
        # Dry-run primero para validar sin modificar el archivo
        dry = subprocess.run(
            [patch_exe, "--dry-run", "-f", "-i", str(patch_file), str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if dry.returncode != 0:
            raise PatchError(
                f"El parche no puede aplicarse (dry-run): {dry.stderr.strip() or dry.stdout.strip()}"
            )

        # Aplicar de verdad
        apply = subprocess.run(
            [patch_exe, "-f", "-i", str(patch_file), str(file_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if apply.returncode != 0:
            raise PatchError(
                f"Error al aplicar el parche: {apply.stderr.strip() or apply.stdout.strip()}"
            )

        return file_path.read_text(encoding="utf-8")

    finally:
        patch_file.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tool pública
# ─────────────────────────────────────────────────────────────────────────────


class ApplyPatchTool(BaseTool):
    """Aplica un parche en formato unified diff a un archivo del workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "apply_patch"
        self.description = (
            "Aplica un parche en formato unified diff a un archivo existente. "
            "Ideal para cambios que afectan múltiples secciones no contiguas (multi-hunk). "
            "Para un único bloque de cambio usa edit_file (más simple). "
            "Para archivos nuevos o reescritura total usa write_file."
        )
        self.sensitive = True
        self.args_model = ApplyPatchArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Aplica un parche unified diff al archivo.

        Args:
            path: Path relativo al workspace
            patch: Texto del parche en formato unified diff

        Returns:
            ToolResult indicando éxito con resumen o error descriptivo
        """
        try:
            args = self.validate_args(kwargs)
            file_path = validate_path(args.path, self.workspace_root)
            validate_file_exists(file_path)

            original = file_path.read_text(encoding="utf-8")

            # Intentar con el parser puro-Python primero
            try:
                modified = _apply_patch_pure(original, args.patch, args.path)
                method = "puro-Python"
            except PatchError as pure_err:
                # Fallback: intentar con el comando `patch` del sistema
                try:
                    modified = _apply_patch_system(file_path, args.patch)
                    method = "system patch"
                except PatchError as sys_err:
                    return ToolResult(
                        success=False,
                        output="",
                        error=(
                            f"No se pudo aplicar el parche a {args.path}.\n"
                            f"  Parser puro: {pure_err}\n"
                            f"  System patch: {sys_err}"
                        ),
                    )

            # Escribir el resultado (no-op si system patch ya lo hizo)
            file_path.write_text(modified, encoding="utf-8")

            # Resumen
            try:
                hunks = _parse_hunks(args.patch)
                lines_changed = sum(
                    sum(1 for ln in h.lines if ln.startswith(("+", "-")))
                    for h in hunks
                )
                summary = (
                    f"Parche aplicado a {args.path} ({method}). "
                    f"{len(hunks)} hunk(s), ~{lines_changed} líneas modificadas."
                )
            except Exception:
                summary = f"Parche aplicado a {args.path} ({method})."

            return ToolResult(success=True, output=summary)

        except PathTraversalError as e:
            return ToolResult(success=False, output="", error=f"Error de seguridad: {e}")
        except ValidationError as e:
            return ToolResult(success=False, output="", error=str(e))
        except UnicodeDecodeError:
            path_str = kwargs.get("path", "?")
            return ToolResult(
                success=False,
                output="",
                error=f"El archivo {path_str} no es un archivo de texto válido (UTF-8)",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado al aplicar parche en {kwargs.get('path', '?')}: {e}",
            )
