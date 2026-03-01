"""
Indexer module — Repository indexing.

Provides a lightweight workspace index so the agent can know the
project structure without having to read each file.
"""

from .cache import IndexCache
from .tree import FileInfo, RepoIndex, RepoIndexer

__all__ = [
    "FileInfo",
    "RepoIndex",
    "RepoIndexer",
    "IndexCache",
]
