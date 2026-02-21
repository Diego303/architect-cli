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


class SearchCodeArgs(BaseModel):
    """Argumentos para search_code tool."""

    pattern: str = Field(
        description=(
            "Patrón regex a buscar en el código. "
            "Ejemplos: 'def process_', 'class.*Tool', 'import (os|sys)'"
        ),
    )
    path: str = Field(
        default=".",
        description="Directorio o archivo donde buscar (relativo al workspace)",
    )
    file_pattern: str | None = Field(
        default=None,
        description="Filtro de archivos por nombre glob (ej: '*.py', '*.ts')",
        examples=["*.py", "*.js", "*.ts", "*.yaml"],
    )
    max_results: int = Field(
        default=20,
        description="Número máximo de resultados a retornar",
        ge=1,
        le=200,
    )
    context_lines: int = Field(
        default=2,
        description="Líneas de contexto antes y después de cada coincidencia",
        ge=0,
        le=10,
    )
    case_sensitive: bool = Field(
        default=True,
        description="Si False, la búsqueda ignora mayúsculas/minúsculas",
    )

    model_config = {"extra": "forbid"}


class GrepArgs(BaseModel):
    """Argumentos para grep tool."""

    text: str = Field(
        description=(
            "Texto literal a buscar (no regex). "
            "Más rápido que search_code para strings simples."
        ),
    )
    path: str = Field(
        default=".",
        description="Directorio o archivo donde buscar (relativo al workspace)",
    )
    file_pattern: str | None = Field(
        default=None,
        description="Filtro de archivos por nombre glob (ej: '*.py')",
        examples=["*.py", "*.js", "*.md"],
    )
    max_results: int = Field(
        default=30,
        description="Número máximo de resultados a retornar",
        ge=1,
        le=500,
    )
    case_sensitive: bool = Field(
        default=True,
        description="Si False, la búsqueda ignora mayúsculas/minúsculas",
    )

    model_config = {"extra": "forbid"}


class FindFilesArgs(BaseModel):
    """Argumentos para find_files tool."""

    pattern: str = Field(
        description=(
            "Patrón glob para nombres de archivo. "
            "Ejemplos: '*.test.py', 'Dockerfile*', 'config.yaml', '*.env'"
        ),
    )
    path: str = Field(
        default=".",
        description="Directorio donde buscar (relativo al workspace)",
    )

    model_config = {"extra": "forbid"}


class RunCommandArgs(BaseModel):
    """Argumentos para run_command tool (F13)."""

    command: str = Field(
        description=(
            "Comando a ejecutar en el shell. Puede incluir pipes y redirecciones. "
            "Ejemplos: 'pytest tests/', 'python -m mypy src/', 'git status', 'make build'"
        ),
    )
    cwd: str | None = Field(
        default=None,
        description=(
            "Directorio de trabajo relativo al workspace (opcional). "
            "Si no se especifica, se usa el workspace root."
        ),
        examples=["src", "tests", "frontend"],
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Timeout en segundos para el comando (1-600). Default: 30s.",
    )
    env: dict[str, str] | None = Field(
        default=None,
        description=(
            "Variables de entorno adicionales para el proceso (se fusionan con el entorno actual). "
            "Ejemplo: {'DEBUG': '1', 'PYTHONPATH': 'src'}"
        ),
    )

    model_config = {"extra": "forbid"}
