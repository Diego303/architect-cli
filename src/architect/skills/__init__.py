"""
Skills ecosystem -- loading .architect.md, skill discovery and installation (v4-A3).
Procedural memory -- correction detection and persistence (v4-A4).
"""

from .installer import SkillInstaller
from .loader import SkillInfo, SkillsLoader
from .memory import ProceduralMemory

__all__ = [
    "ProceduralMemory",
    "SkillInfo",
    "SkillInstaller",
    "SkillsLoader",
]
