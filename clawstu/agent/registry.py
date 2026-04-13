"""Tool registry with auto-discovery for the Stuart agent loop.

Scans ``agent/tools/`` for Python modules, imports each one, and
registers any class that subclasses `BaseTool`. New tools are added
by dropping a file in the tools directory -- no wiring required.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any

from clawstu.agent.base_tool import BaseTool, ToolContext

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Discovers, registers, and dispatches agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance by its name."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name."""
        return self._tools.get(name)

    def tool_names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def tool_definitions(self) -> list[dict[str, Any]]:
        """Return Anthropic tool-use format definitions for the LLM."""
        return [t.schema() for t in self._tools.values()]

    async def execute(
        self, name: str, args: dict[str, Any], context: ToolContext,
    ) -> str:
        """Execute a tool by name. Returns text for the LLM."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool: {name}"
        try:
            return await tool.execute(args, context)
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return f"Tool '{name}' failed: {exc}"

    def discover_from(self, package_path: Path) -> None:
        """Auto-discover BaseTool subclasses from a package directory.

        Each ``.py`` file in *package_path* (skipping ``_``-prefixed
        files) is imported. Any class that is a concrete subclass of
        `BaseTool` and is defined in that module is instantiated and
        registered.
        """
        package_path = Path(package_path)
        # Build the dotted package name by walking up __init__.py chain
        parts: list[str] = []
        cur = package_path
        while True:
            if not (cur / "__init__.py").exists():
                break
            parts.insert(0, cur.name)
            cur = cur.parent
        pkg = ".".join(parts) if parts else ""

        for py_file in sorted(package_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            fq = f"{pkg}.{module_name}" if pkg else module_name
            try:
                mod = importlib.import_module(fq)
            except Exception as exc:
                logger.warning("Skipping broken tool module %s: %s", fq, exc)
                continue
            for _attr, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, BaseTool)
                    and obj is not BaseTool
                    and obj.__module__ == mod.__name__
                ):
                    try:
                        instance = obj()
                        self.register(instance)
                        logger.debug("Discovered tool: %s", instance.name)
                    except Exception as exc:
                        logger.warning(
                            "Failed to instantiate tool %s: %s", _attr, exc,
                        )
