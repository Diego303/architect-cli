"""
Modelos Pydantic para argumentos de tools.

Cada tool define su schema de argumentos como un modelo Pydantic,
lo que proporciona validación automática y generación de JSON Schema.
"""

from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    """Argumentos para read_file tool."""

    path: str = Field(
        description="Path relativo al workspace del archivo a leer",
        examples=["README.md", "src/main.py", "config/settings.yaml"],
    )

    model_config = {"extra": "forbid"}


class WriteFileArgs(BaseModel):
    """Argumentos para write_file tool."""

    path: str = Field(
        description="Path relativo al workspace del archivo a escribir",
        examples=["output.txt", "src/generated.py"],
    )
    content: str = Field(
        description="Contenido a escribir en el archivo",
    )
    mode: str = Field(
        default="overwrite",
        description="Modo de escritura: 'overwrite' (reemplaza) o 'append' (añade al final)",
        pattern="^(overwrite|append)$",
    )

    model_config = {"extra": "forbid"}


class DeleteFileArgs(BaseModel):
    """Argumentos para delete_file tool."""

    path: str = Field(
        description="Path relativo al workspace del archivo a eliminar",
        examples=["temp.txt", "old_config.yaml"],
    )

    model_config = {"extra": "forbid"}


class EditFileArgs(BaseModel):
    """Argumentos para edit_file tool (str_replace)."""

    path: str = Field(
        description="Path relativo al workspace del archivo a editar",
        examples=["src/main.py", "README.md"],
    )
    old_str: str = Field(
        description=(
            "Texto exacto a reemplazar. Debe aparecer exactamente una vez en el archivo. "
            "Incluye líneas de contexto vecinas para hacerlo inequívoco si es necesario."
        ),
    )
    new_str: str = Field(
        description=(
            "Texto de reemplazo. Puede ser cadena vacía para eliminar el bloque. "
            "Mantén la indentación correcta."
        ),
    )

    model_config = {"extra": "forbid"}


class ApplyPatchArgs(BaseModel):
    """Argumentos para apply_patch tool (unified diff)."""

    path: str = Field(
        description="Path relativo al workspace del archivo a parchear",
        examples=["src/main.py", "config.yaml"],
    )
    patch: str = Field(
        description=(
            "Parche en formato unified diff. Puede incluir una o varias secciones @@ -a,b +c,d @@. "
            "Las cabeceras --- / +++ son opcionales. "
            "Ejemplo: '@@ -3,4 +3,5 @@\\n contexto\\n-línea vieja\\n+línea nueva\\n contexto'"
        ),
    )

    model_config = {"extra": "forbid"}


class ListFilesArgs(BaseModel):
    """Argumentos para list_files tool."""

    path: str = Field(
        default=".",
        description="Path relativo al workspace del directorio a listar",
        examples=[".", "src", "tests/fixtures"],
    )
    pattern: str | None = Field(
        default=None,
        description="Patrón glob opcional para filtrar archivos (ej: '*.py', 'test_*.py')",
        examples=["*.py", "*.md", "test_*.py"],
    )
    recursive: bool = Field(
        default=False,
        description="Si True, lista archivos recursivamente en subdirectorios",
    )

    model_config = {"extra": "forbid"}
