"""
Módulo indexer — Indexación del repositorio.

Proporciona un índice ligero del workspace para que el agente
conozca la estructura del proyecto sin necesidad de leer cada archivo.
"""

from .cache import IndexCache
from .tree import FileInfo, RepoIndex, RepoIndexer

__all__ = [
    "FileInfo",
    "RepoIndex",
    "RepoIndexer",
    "IndexCache",
]
