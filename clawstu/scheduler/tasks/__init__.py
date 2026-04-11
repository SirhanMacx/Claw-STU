"""Phase 6 task modules.

Each module defines an async `run(ctx, learner_id) -> TaskReport` and
exports a module-level `SPEC: TaskSpec` constant. `default_registry()`
in `clawstu.scheduler.registry` imports the five SPECs from here.
"""
