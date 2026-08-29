"""Minimal JSON protocol executed only inside the handler sandbox container."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path


def main() -> None:
    try:
        entrypoint = sys.argv[1]
        module_name, callable_name = entrypoint.split(":", 1)
        module_path = Path("/opt/handler") / (
            module_name.replace(".", "/") + ".py"
        )
        payload = json.load(sys.stdin)
        synthetic_name = "_djq_sandbox_handler"
        specification = importlib.util.spec_from_file_location(
            synthetic_name, module_path
        )
        if specification is None or specification.loader is None:
            raise RuntimeError("Handler entrypoint cannot be loaded")
        module = importlib.util.module_from_spec(specification)
        with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(
            sys.stderr
        ):
            specification.loader.exec_module(module)
            handler = getattr(module, callable_name, None)
            if not callable(handler):
                raise RuntimeError("Handler entrypoint is not callable")
            result = handler(payload)
        json.dump({"ok": True, "result": result}, sys.stdout)
    except Exception as exc:
        json.dump(
            {
                "ok": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc)[:2_000],
                },
            },
            sys.stdout,
        )


if __name__ == "__main__":
    main()
