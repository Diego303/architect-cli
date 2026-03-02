"""
Confirmation policies for tool execution.

Defines when and how to request user confirmation before
executing tools, with special support for headless/CI environments.
"""

import sys
from typing import Any

from ..tools.base import BaseTool


class NoTTYError(Exception):
    """Error raised when confirmation is required but no TTY is available.

    This occurs in headless environments (CI, cron, pipelines) when
    the policy requires confirmation but user interaction is not possible.
    """

    pass


class ConfirmationPolicy:
    """Confirmation policy for tool execution.

    Determines whether a tool requires user confirmation before
    executing, based on the configured mode.

    Modes:
        - "yolo": No confirmation, fully automatic execution
        - "confirm-all": Confirm all tools
        - "confirm-sensitive": Only confirm tools marked as sensitive
    """

    def __init__(self, mode: str):
        """Initialize the policy with a specific mode.

        Args:
            mode: One of "yolo", "confirm-all", "confirm-sensitive"

        Raises:
            ValueError: If the mode is not valid
        """
        valid_modes = {"yolo", "confirm-all", "confirm-sensitive"}
        if mode not in valid_modes:
            raise ValueError(
                f"Invalid mode '{mode}'. " f"Valid modes: {', '.join(valid_modes)}"
            )

        self.mode = mode

    def should_confirm(self, tool: BaseTool) -> bool:
        """Determine whether a tool requires confirmation.

        Args:
            tool: Tool to evaluate

        Returns:
            True if confirmation should be requested, False otherwise
        """
        match self.mode:
            case "yolo":
                return False
            case "confirm-all":
                return True
            case "confirm-sensitive":
                return tool.sensitive
            case _:
                # Should not reach here due to validation in __init__
                return True

    def request_confirmation(
        self,
        tool_name: str,
        args: dict[str, Any],
        dry_run: bool = False,
    ) -> bool:
        """Request user confirmation to execute a tool.

        Args:
            tool_name: Name of the tool
            args: Arguments it will be executed with
            dry_run: If True, indicates this is a simulation

        Returns:
            True if the user confirms, False if they reject

        Raises:
            NoTTYError: If no TTY is available for confirmation

        Note:
            In headless environments (CI, cron), reaching this point is a
            configuration error. The user should use --mode yolo or --dry-run.
        """
        # Check that a TTY is available
        if not sys.stdin.isatty():
            raise NoTTYError(
                f"Confirmation required to execute '{tool_name}' "
                f"but no TTY is available (headless/CI environment). "
                f"Solutions: "
                f"1) Use --mode yolo for automatic execution, "
                f"2) Use --dry-run to simulate without executing, "
                f"3) Change the agent configuration to confirm_mode: yolo"
            )

        # Format arguments for display
        args_str = self._format_args(args)

        # Confirmation message
        if dry_run:
            print(f"\n[DRY-RUN] Would execute: {tool_name}({args_str})")
            return True  # In dry-run always "confirm" so it continues

        print(f"\nExecute {tool_name}({args_str})?")
        print("  [y] Yes, execute")
        print("  [n] No, cancel")
        print("  [a] Abort entire execution")

        while True:
            try:
                response = input("\nResponse: ").strip().lower()

                if response in ("y", "yes"):
                    return True
                elif response in ("n", "no"):
                    print("Operation cancelled by the user")
                    return False
                elif response in ("a", "abort"):
                    print("Execution aborted by the user")
                    sys.exit(130)  # Exit code similar to SIGINT
                else:
                    print("Invalid response. Use 'y' (yes), 'n' (no) or 'a' (abort)")

            except (KeyboardInterrupt, EOFError):
                print("\nExecution interrupted")
                sys.exit(130)

    def _format_args(self, args: dict[str, Any], max_length: int = 100) -> str:
        """Format arguments for user display.

        Args:
            args: Dictionary of arguments
            max_length: Maximum value length before truncating

        Returns:
            Formatted string with the arguments
        """
        if not args:
            return ""

        formatted = []
        for key, value in args.items():
            value_str = str(value)

            # Truncate very long values
            if len(value_str) > max_length:
                value_str = value_str[:max_length] + "..."

            # Escape newlines for single-line display
            value_str = value_str.replace("\n", "\\n")

            formatted.append(f"{key}={repr(value_str)}")

        return ", ".join(formatted)

    def __repr__(self) -> str:
        return f"<ConfirmationPolicy(mode='{self.mode}')>"
