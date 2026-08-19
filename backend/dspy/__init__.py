"""DSPy package for Mayday.

No-op when the ``dspy:`` master switch is off or dspy is not installed; every
consumer falls back to deterministic behaviour. Exposes the shared bridge plus
the interactive-tier helpers.
"""
from backend.dspy.bridge import (
    DspyBridge,
    get_bridge,
    configure_dspy,
    has_pii,
    dspy_available,
    reset_bridge,
)

__all__ = [
    "DspyBridge",
    "get_bridge",
    "configure_dspy",
    "has_pii",
    "dspy_available",
    "reset_bridge",
]
