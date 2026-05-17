"""Read-through wrapper around AppConfig.

Lets us run agent / dispatch code with selected fields overridden
without mutating the underlying SQLAlchemy row. Used by chat/compare
(guardrail on vs off) and by compare-llms (one prompt fanned out to
N providers, each with their own override)."""


class ConfigOverride:
    def __init__(self, base, **overrides):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_overrides", overrides)

    def __getattr__(self, name):
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)
