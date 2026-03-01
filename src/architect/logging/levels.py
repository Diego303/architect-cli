"""
HUMAN logging level -- Readable agent traceability.

v3-M5: Custom level between INFO (20) and WARNING (30).
Does not indicate severity -- indicates high-level traceability so the user
can follow what the agent does without technical noise.

Hierarchy:
    debug  (10) -> HTTP payloads, full args, timing
    info   (20) -> System operations (config loaded, tool registered)
    human  (25) -> * What the agent does: LLM call, tool use, result
    warn   (30) -> Non-fatal problems
    error  (40) -> Errors
"""

import logging

# Custom level: between INFO (20) and WARNING (30)
HUMAN = 25
logging.addLevelName(HUMAN, "HUMAN")

# Inject the .human() method into Python's Logger class
# This avoids the AttributeError: object has no attribute 'human'
def _human_method(self, message, *args, **kwargs):
    if self.isEnabledFor(HUMAN):
        self._log(HUMAN, message, args, **kwargs)

logging.Logger.human = _human_method

# Register the level in structlog to avoid KeyError: 25
import structlog
if hasattr(structlog, "stdlib"):
    try:
        structlog.stdlib.LEVEL_TO_NAME[HUMAN] = "human"
    except (AttributeError, KeyError):
        pass
