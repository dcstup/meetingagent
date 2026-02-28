from src.adapters.recall.adapter import RecallAdapter
import src.adapters as _registry_mod

_registry_mod.register("recall", RecallAdapter)

__all__ = ["RecallAdapter"]
