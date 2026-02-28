from src.adapters.deepgram.adapter import DeepgramAdapter
import src.adapters as _registry_mod

_registry_mod.register("deepgram", DeepgramAdapter)

__all__ = ["DeepgramAdapter"]
