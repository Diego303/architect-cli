"""
Skills ecosystem — carga de .architect.md, descubrimiento e instalación de skills (v4-A3).
Procedural memory — detección y persistencia de correcciones (v4-A4).
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
