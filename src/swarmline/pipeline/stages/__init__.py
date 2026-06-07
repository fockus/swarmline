"""Stage kinds for the typed data-flow pipeline.

Importing a stage module registers its runner in the engine's type→runner registry, so a stage
type is executable as soon as it is imported. Re-export each kind here for a single import surface.
"""

from swarmline.pipeline.stages.conditional_stage import ConditionalStage
from swarmline.pipeline.stages.fanout_stage import FanOutStage
from swarmline.pipeline.stages.guard_stage import GuardStage
from swarmline.pipeline.stages.loop import LoopStage
from swarmline.pipeline.stages.parallel import ParallelStage
from swarmline.pipeline.stages.typed_stage import TypedStage

__all__ = [
    "ConditionalStage",
    "FanOutStage",
    "GuardStage",
    "LoopStage",
    "ParallelStage",
    "TypedStage",
]
