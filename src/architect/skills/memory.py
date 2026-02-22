"""
Procedural Memory — Detección y persistencia de correcciones entre sesiones (v4-A4).

Detecta cuando el usuario corrige al agente, persiste las correcciones en
.architect/memory.md y las inyecta automáticamente en el system prompt
de sesiones futuras.
"""

import re
from datetime import datetime
from pathlib import Path

import structlog

logger = structlog.get_logger()

CORRECTION_PATTERNS: list[tuple[str, str]] = [
    (r"no[,.]?\s+(usa|utiliza|haz|pon|cambia|es)\b", "direct_correction"),
    (r"(eso no|eso está mal|no es correcto|está mal)", "negation"),
    (r"(en realidad|realmente|de hecho)\b", "clarification"),
    (r"(debería ser|el correcto es|el comando es)\b", "should_be"),
    (r"(no funciona así|así no)\b", "wrong_approach"),
    (r"(siempre|nunca)\s+(usa|hagas|pongas)\b", "absolute_rule"),
]


class ProceduralMemory:
    """Memoria de correcciones y patrones que persiste entre sesiones."""

    MEMORY_FILE = ".architect/memory.md"

    def __init__(self, workspace_root: str):
        self.root = Path(workspace_root)
        self.memory_path = self.root / self.MEMORY_FILE
        self._entries: list[dict[str, str]] = []
        self._load()

    def _load(self) -> None:
        """Carga entradas existentes del archivo."""
        if not self.memory_path.exists():
            return
        content = self.memory_path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"^- \[(\d{4}-\d{2}-\d{2})\]\s*(\w+):\s*(.+)$",
            content,
            re.MULTILINE,
        ):
            self._entries.append({
                "date": match.group(1),
                "type": match.group(2),
                "content": match.group(3),
            })

    def detect_correction(
        self,
        user_msg: str,
        prev_agent_action: str | None = None,
    ) -> str | None:
        """Detecta si el mensaje del usuario es una corrección.

        Args:
            user_msg: Mensaje del usuario.
            prev_agent_action: Acción previa del agente (para contexto futuro).

        Returns:
            La corrección detectada, o None si no es una corrección.
        """
        user_lower = user_msg.lower().strip()
        for pattern, correction_type in CORRECTION_PATTERNS:
            if re.search(pattern, user_lower):
                correction = self._extract_correction(user_msg, correction_type)
                if correction:
                    return correction
        return None

    def _extract_correction(self, msg: str, correction_type: str) -> str:
        """Extrae la parte util de una corrección."""
        msg = msg.strip()
        if len(msg) > 300:
            msg = msg[:300] + "..."
        return msg

    def add_correction(self, correction: str) -> None:
        """Añade una corrección al archivo de memoria.

        Args:
            correction: Texto de la corrección a persistir.
        """
        # Verificar duplicado
        existing = [e["content"] for e in self._entries]
        if correction in existing:
            return

        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "type": "Correccion",
            "content": correction,
        }
        self._entries.append(entry)
        self._append_to_file(entry)
        logger.info("memory_correction_saved", content=correction[:100])

    def add_pattern(self, pattern: str) -> None:
        """Añade un patron descubierto.

        Args:
            pattern: Texto del patron a persistir.
        """
        existing = [e["content"] for e in self._entries]
        if pattern in existing:
            return

        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "type": "Patron",
            "content": pattern,
        }
        self._entries.append(entry)
        self._append_to_file(entry)

    def _append_to_file(self, entry: dict[str, str]) -> None:
        """Añade una entrada al archivo markdown."""
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.memory_path.exists():
            self.memory_path.write_text(
                "# Memoria del Proyecto\n\n"
                "> Auto-generado por architect. Editable manualmente.\n\n",
                encoding="utf-8",
            )
        with open(self.memory_path, "a", encoding="utf-8") as f:
            f.write(f"- [{entry['date']}] {entry['type']}: {entry['content']}\n")

    def get_context(self) -> str:
        """Retorna el contenido de memoria para inyectar en el prompt.

        Returns:
            String con el contexto de memoria, o "" si no hay nada.
        """
        if not self.memory_path.exists():
            return ""
        content = self.memory_path.read_text(encoding="utf-8")
        if len(content.strip()) < 10:
            return ""
        return f"\n## Memoria del Proyecto (correcciones anteriores)\n\n{content}\n"

    @property
    def entries(self) -> list[dict[str, str]]:
        """Retorna las entradas de memoria cargadas."""
        return list(self._entries)

    def analyze_session_learnings(
        self,
        conversation: list[dict[str, str]],
    ) -> list[str]:
        """Post-sesion: analiza conversación y extrae correcciones.

        Args:
            conversation: Lista de mensajes de la conversación.

        Returns:
            Lista de correcciones detectadas y guardadas.
        """
        corrections_found: list[str] = []
        for i, msg in enumerate(conversation):
            if msg.get("role") == "user" and i > 0:
                content = msg.get("content", "")
                correction = self.detect_correction(content)
                if correction:
                    self.add_correction(correction)
                    corrections_found.append(correction)
        return corrections_found
