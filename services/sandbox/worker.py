import contextlib
import io
import json
import sys
import traceback

from services.sandbox.code_guard import CodeValidationError, validate_python_code


def _build_namespace() -> dict:
    import math
    import statistics

    import numpy as np
    import pandas as pd

    safe_open = open

    return {
        "__builtins__": __builtins__,
        "__name__": "__main__",
        "json": json,
        "math": math,
        "statistics": statistics,
        "np": np,
        "numpy": np,
        "pd": pd,
        "pandas": pd,
        "open": safe_open,
    }


def main() -> None:
    namespace = _build_namespace()

    for line in sys.stdin:
        if not line.strip():
            continue

        request = json.loads(line)
        code = request.get("code", "")
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()

        try:
            validate_python_code(code)
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(compile(code, "<sandbox>", "exec"), namespace, namespace)
            response = {
                "ok": True,
                "stdout": stdout_buffer.getvalue(),
                "stderr": stderr_buffer.getvalue(),
            }
        except CodeValidationError as error:
            response = {
                "ok": False,
                "stdout": stdout_buffer.getvalue(),
                "stderr": stderr_buffer.getvalue(),
                "error_type": "code_validation_error",
                "message": error.message,
            }
        except Exception as error:
            response = {
                "ok": False,
                "stdout": stdout_buffer.getvalue(),
                "stderr": stderr_buffer.getvalue(),
                "error_type": "python_error",
                "message": str(error),
                "traceback": traceback.format_exc(),
            }

        sys.stdout.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
