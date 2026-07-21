"""ale-claw — OpenClaw native (host-side, in-process) agent deployer.

Re-exports the public surface so callers can do:

    from ale_run.agents.ale_claw import AleClawConfig, AleClawDeployer
"""

from typing import TYPE_CHECKING, Any

from .config import AleClawConfig

if TYPE_CHECKING:
    from .deployer import AleClawDeployer


def __getattr__(name: str) -> Any:
    if name == "AleClawDeployer":
        from .deployer import AleClawDeployer

        return AleClawDeployer
    raise AttributeError(name)

__all__ = ["AleClawConfig", "AleClawDeployer"]
