from __future__ import annotations

from .runtime import AgentRuntime


class AgentRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, AgentRuntime] = {}

    def register(self, runtime: AgentRuntime) -> None:
        self._runtimes[runtime.agent_name] = runtime

    def get(self, agent_name: str) -> AgentRuntime:
        runtime = self._runtimes.get(agent_name)
        if not runtime:
            raise ValueError(f"No runtime registered for agent '{agent_name}'")
        return runtime

    def get_default(self) -> AgentRuntime:
        if not self._runtimes:
            raise ValueError("No runtimes registered")
        # primer runtime como fallback
        return next(iter(self._runtimes.values()))
