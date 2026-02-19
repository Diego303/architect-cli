"""
Políticas de confirmación para ejecución de tools.

Define cuándo y cómo solicitar confirmación al usuario antes de
ejecutar tools, con soporte especial para entornos headless/CI.
"""

import sys
from typing import Any

from ..tools.base import BaseTool


class NoTTYError(Exception):
    """Error lanzado cuando se requiere confirmación pero no hay TTY disponible.

    Esto ocurre en entornos headless (CI, cron, pipelines) cuando
    la política requiere confirmación pero no es posible interactuar
    con el usuario.
    """

    pass


class ConfirmationPolicy:
    """Política de confirmación para ejecución de tools.

    Determina si una tool requiere confirmación del usuario antes
    de ejecutarse, basándose en el modo configurado.

    Modos:
        - "yolo": Sin confirmación, ejecución automática total
        - "confirm-all": Confirmar todas las tools
        - "confirm-sensitive": Solo confirmar tools marcadas como sensitive
    """

    def __init__(self, mode: str):
        """Inicializa la política con un modo específico.

        Args:
            mode: Uno de "yolo", "confirm-all", "confirm-sensitive"

        Raises:
            ValueError: Si el mode no es válido
        """
        valid_modes = {"yolo", "confirm-all", "confirm-sensitive"}
        if mode not in valid_modes:
            raise ValueError(
                f"Modo inválido '{mode}'. " f"Modos válidos: {', '.join(valid_modes)}"
            )

        self.mode = mode

    def should_confirm(self, tool: BaseTool) -> bool:
        """Determina si una tool requiere confirmación.

        Args:
            tool: Tool a evaluar

        Returns:
            True si se debe pedir confirmación, False en caso contrario
        """
        match self.mode:
            case "yolo":
                return False
            case "confirm-all":
                return True
            case "confirm-sensitive":
                return tool.sensitive
            case _:
                # No debería llegar aquí por validación en __init__
                return True

    def request_confirmation(
        self,
        tool_name: str,
        args: dict[str, Any],
        dry_run: bool = False,
    ) -> bool:
        """Solicita confirmación al usuario para ejecutar una tool.

        Args:
            tool_name: Nombre de la tool
            args: Argumentos con los que se ejecutará
            dry_run: Si True, indica que es una simulación

        Returns:
            True si el usuario confirma, False si rechaza

        Raises:
            NoTTYError: Si no hay TTY disponible para pedir confirmación

        Note:
            En entornos headless (CI, cron), si se llega aquí es un error
            de configuración. El usuario debe usar --mode yolo o --dry-run.
        """
        # Verificar que haya un TTY disponible
        if not sys.stdin.isatty():
            raise NoTTYError(
                f"Se requiere confirmación para ejecutar '{tool_name}' "
                f"pero no hay TTY disponible (entorno headless/CI). "
                f"Soluciones: "
                f"1) Usa --mode yolo para ejecución automática, "
                f"2) Usa --dry-run para simular sin ejecutar, "
                f"3) Cambia la configuración del agente a confirm_mode: yolo"
            )

        # Formatear argumentos para mostrar al usuario
        args_str = self._format_args(args)

        # Mensaje de confirmación
        if dry_run:
            print(f"\n[DRY-RUN] Se ejecutaría: {tool_name}({args_str})")
            return True  # En dry-run siempre "confirmar" para que continúe

        print(f"\n¿Ejecutar {tool_name}({args_str})?")
        print("  [y] Sí, ejecutar")
        print("  [n] No, cancelar")
        print("  [a] Abortar toda la ejecución")

        while True:
            try:
                response = input("\nRespuesta: ").strip().lower()

                if response in ("y", "yes", "sí", "si", "s"):
                    return True
                elif response in ("n", "no"):
                    print("❌ Operación cancelada por el usuario")
                    return False
                elif response in ("a", "abort", "abortar"):
                    print("🛑 Ejecución abortada por el usuario")
                    sys.exit(130)  # Código similar a SIGINT
                else:
                    print("Respuesta no válida. Usa 'y' (sí), 'n' (no) o 'a' (abortar)")

            except (KeyboardInterrupt, EOFError):
                print("\n🛑 Ejecución interrumpida")
                sys.exit(130)

    def _format_args(self, args: dict[str, Any], max_length: int = 100) -> str:
        """Formatea argumentos para mostrar al usuario.

        Args:
            args: Diccionario de argumentos
            max_length: Longitud máxima de valores antes de truncar

        Returns:
            String formateado con los argumentos
        """
        if not args:
            return ""

        formatted = []
        for key, value in args.items():
            value_str = str(value)

            # Truncar valores muy largos
            if len(value_str) > max_length:
                value_str = value_str[:max_length] + "..."

            # Escapar saltos de línea para mostrar en una línea
            value_str = value_str.replace("\n", "\\n")

            formatted.append(f"{key}={repr(value_str)}")

        return ", ".join(formatted)

    def __repr__(self) -> str:
        return f"<ConfirmationPolicy(mode='{self.mode}')>"
