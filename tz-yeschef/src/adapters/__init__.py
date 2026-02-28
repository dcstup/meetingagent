from src.adapters.base import TranscriptAdapter

_registry: dict[str, type[TranscriptAdapter]] = {}


def register(name: str, cls: type[TranscriptAdapter]) -> None:
    _registry[name] = cls


def get_adapter(name: str, **config) -> TranscriptAdapter:
    if name not in _registry:
        raise KeyError(f"Unknown adapter: {name!r}. Registered: {list(_registry)}")
    return _registry[name](**config)


def _auto_register() -> None:
    """Import adapter modules so they self-register."""
    from src.adapters.recall import RecallAdapter  # noqa: F401
    from src.adapters.deepgram import DeepgramAdapter  # noqa: F401


_auto_register()
