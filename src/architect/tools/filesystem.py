"""
Tools para operaciones sobre el filesystem local.

Incluye tools para leer, escribir, editar, eliminar y listar archivos,
todas con validación de paths y confinamiento al workspace.
"""

import difflib
import fnmatch
from pathlib import Path
from typing import Any

from ..execution.validators import (
    PathTraversalError,
    ValidationError,
    ensure_parent_directory,
    validate_directory_exists,
    validate_file_exists,
    validate_path,
)
from .base import BaseTool, ToolResult
from .schemas import DeleteFileArgs, EditFileArgs, ListFilesArgs, ReadFileArgs, WriteFileArgs


class ReadFileTool(BaseTool):
    """Lee el contenido de un archivo dentro del workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "read_file"
        self.description = (
            "Lee el contenido completo de un archivo. "
            "Usa este tool cuando necesites examinar código, "
            "configuración o cualquier archivo de texto."
        )
        self.sensitive = False
        self.args_model = ReadFileArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Lee un archivo del workspace.

        Args:
            path: Path relativo al workspace

        Returns:
            ToolResult con el contenido del archivo o error
        """
        try:
            # Validar argumentos
            args = self.validate_args(kwargs)

            # Validar y resolver path
            file_path = validate_path(args.path, self.workspace_root)

            # Verificar que el archivo exista
            validate_file_exists(file_path)

            # Leer contenido
            content = file_path.read_text(encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Contenido de {args.path}:\n\n{content}",
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error de seguridad: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                output="",
                error=f"El archivo {args.path} no es un archivo de texto válido (UTF-8)",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado al leer {args.path}: {e}",
            )


class WriteFileTool(BaseTool):
    """Escribe contenido en un archivo dentro del workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "write_file"
        self.description = (
            "Escribe o reemplaza completamente un archivo. "
            "Úsalo solo para archivos NUEVOS o cuando necesitas reescribir el archivo entero. "
            "Para modificaciones parciales usa edit_file (un bloque) o apply_patch (multi-hunk). "
            "Puede sobrescribir (mode='overwrite') o añadir al final (mode='append'). "
            "Crea directorios padres si no existen."
        )
        self.sensitive = True  # Operación sensible
        self.args_model = WriteFileArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Escribe contenido en un archivo.

        Args:
            path: Path relativo al workspace
            content: Contenido a escribir
            mode: 'overwrite' o 'append'

        Returns:
            ToolResult indicando éxito o error
        """
        try:
            # Validar argumentos
            args = self.validate_args(kwargs)

            # Validar y resolver path
            file_path = validate_path(args.path, self.workspace_root)

            # Asegurar que el directorio padre exista
            ensure_parent_directory(file_path)

            # Escribir según el modo
            if args.mode == "overwrite":
                file_path.write_text(args.content, encoding="utf-8")
                action = "sobrescrito"
            else:  # append
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(args.content)
                action = "añadido contenido a"

            return ToolResult(
                success=True,
                output=f"Archivo {args.path} {action} correctamente ({len(args.content)} caracteres)",
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error de seguridad: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado al escribir {args.path}: {e}",
            )


class EditFileTool(BaseTool):
    """Edita un archivo reemplazando un bloque de texto exacto (str_replace)."""

    def __init__(self, workspace_root: Path):
        self.name = "edit_file"
        self.description = (
            "Reemplaza un bloque exacto de texto en un archivo (str_replace). "
            "PREFERIR sobre write_file para modificaciones parciales en archivos existentes. "
            "old_str debe ser único en el archivo; incluye líneas de contexto vecinas si hay ambigüedad. "
            "Para cambios en múltiples secciones no contiguas, usa apply_patch. "
            "Para archivos nuevos o reescritura total, usa write_file."
        )
        self.sensitive = True
        self.args_model = EditFileArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Reemplaza un bloque exacto de texto en un archivo.

        Args:
            path: Path relativo al workspace
            old_str: Texto exacto a reemplazar (debe ser único en el archivo)
            new_str: Texto de reemplazo (puede ser vacío para eliminar el bloque)

        Returns:
            ToolResult con el diff generado o error descriptivo
        """
        try:
            args = self.validate_args(kwargs)

            if not args.old_str:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "old_str no puede estar vacío. "
                        "Para insertar al final usa write_file con mode='append', "
                        "o usa apply_patch con un hunk de inserción."
                    ),
                )

            file_path = validate_path(args.path, self.workspace_root)
            validate_file_exists(file_path)

            original = file_path.read_text(encoding="utf-8")

            # Contar ocurrencias exactas
            count = original.count(args.old_str)
            if count == 0:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"old_str no encontrado en {args.path}. "
                        "Verifica espacios, indentación y saltos de línea."
                    ),
                )
            if count > 1:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"old_str aparece {count} veces en {args.path}. "
                        "Añade más líneas de contexto para hacerlo único."
                    ),
                )

            # Reemplazar la única ocurrencia
            modified = original.replace(args.old_str, args.new_str, 1)
            file_path.write_text(modified, encoding="utf-8")

            # Generar diff para el output
            diff_lines = list(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    modified.splitlines(keepends=True),
                    fromfile=f"a/{args.path}",
                    tofile=f"b/{args.path}",
                    lineterm="",
                )
            )
            diff_str = "\n".join(diff_lines) if diff_lines else "(sin cambios visibles)"

            return ToolResult(
                success=True,
                output=f"Archivo {args.path} editado correctamente.\n\nDiff:\n{diff_str}",
            )

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
                error=f"Error inesperado al editar {kwargs.get('path', '?')}: {e}",
            )


class DeleteFileTool(BaseTool):
    """Elimina un archivo dentro del workspace."""

    def __init__(self, workspace_root: Path, allow_delete: bool):
        self.name = "delete_file"
        self.description = (
            "Elimina un archivo del workspace. "
            "Requiere que allow_delete=true en la configuración."
        )
        self.sensitive = True  # Operación MUY sensible
        self.args_model = DeleteFileArgs
        self.workspace_root = workspace_root
        self.allow_delete = allow_delete

    def execute(self, **kwargs: Any) -> ToolResult:
        """Elimina un archivo del workspace.

        Args:
            path: Path relativo al workspace

        Returns:
            ToolResult indicando éxito o error
        """
        try:
            # Verificar que delete esté permitido
            if not self.allow_delete:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "Las operaciones de borrado están deshabilitadas. "
                        "Configura workspace.allow_delete=true para permitirlas."
                    ),
                )

            # Validar argumentos
            args = self.validate_args(kwargs)

            # Validar y resolver path
            file_path = validate_path(args.path, self.workspace_root)

            # Verificar que el archivo exista
            validate_file_exists(file_path)

            # Eliminar archivo
            file_path.unlink()

            return ToolResult(
                success=True,
                output=f"Archivo {args.path} eliminado correctamente",
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error de seguridad: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado al eliminar {args.path}: {e}",
            )


class ListFilesTool(BaseTool):
    """Lista archivos y directorios dentro del workspace."""

    def __init__(self, workspace_root: Path):
        self.name = "list_files"
        self.description = (
            "Lista archivos y directorios en un path. "
            "Soporta patrones glob (*.py) y listado recursivo. "
            "Útil para explorar la estructura del proyecto."
        )
        self.sensitive = False
        self.args_model = ListFilesArgs
        self.workspace_root = workspace_root

    def execute(self, **kwargs: Any) -> ToolResult:
        """Lista archivos en un directorio.

        Args:
            path: Path relativo al workspace (default: ".")
            pattern: Patrón glob opcional (ej: "*.py")
            recursive: Si True, lista recursivamente

        Returns:
            ToolResult con la lista de archivos o error
        """
        try:
            # Validar argumentos
            args = self.validate_args(kwargs)

            # Validar y resolver path
            dir_path = validate_path(args.path, self.workspace_root)

            # Verificar que sea un directorio
            validate_directory_exists(dir_path)

            # Listar archivos
            if args.recursive:
                # Listar recursivamente
                if args.pattern:
                    files = list(dir_path.rglob(args.pattern))
                else:
                    files = list(dir_path.rglob("*"))
            else:
                # Listar solo este nivel
                files = list(dir_path.iterdir())
                # Aplicar patrón si está especificado
                if args.pattern:
                    files = [f for f in files if fnmatch.fnmatch(f.name, args.pattern)]

            # Ordenar y formatear
            files.sort()

            # Generar output formateado
            output_lines = [f"Contenido de {args.path}:"]
            output_lines.append("")

            if not files:
                output_lines.append("(directorio vacío)")
            else:
                for file_path in files:
                    # Path relativo al workspace para output
                    try:
                        rel_path = file_path.relative_to(self.workspace_root)
                    except ValueError:
                        rel_path = file_path

                    # Indicador de tipo
                    if file_path.is_dir():
                        indicator = "📁"
                        type_str = "DIR"
                    else:
                        indicator = "📄"
                        type_str = "FILE"

                    output_lines.append(f"{indicator} {type_str:4s} {rel_path}")

            output_lines.append("")
            output_lines.append(f"Total: {len(files)} items")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
            )

        except PathTraversalError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error de seguridad: {e}",
            )
        except ValidationError as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error inesperado al listar {args.path}: {e}",
            )
