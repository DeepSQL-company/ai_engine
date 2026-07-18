import ast

# ======Settings=========
BLOCKED_ROOT_MODULES = frozenset(
    {
        "os",
        "subprocess",
        "shutil",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "pathlib",
        "sys",
        "importlib",
        "builtins",
        "ctypes",
        "multiprocessing",
        "threading",
        "signal",
        "pty",
        "fcntl",
        "resource",
        "pickle",
        "shelve",
        "tempfile",
        "glob",
        "ftplib",
        "smtplib",
        "webbrowser",
    }
)
BLOCKED_CALLS = frozenset({"eval", "exec", "compile", "__import__", "input"})
# ========================


class CodeValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _module_root(name: str | None) -> str:
    if not name:
        return ""
    return name.split(".", 1)[0]


def validate_python_code(code: str) -> None:
    if not code.strip():
        raise CodeValidationError("Python-код пустой.")

    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as error:
        raise CodeValidationError(f"Синтаксическая ошибка Python: {error}") from error

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_root(alias.name) in BLOCKED_ROOT_MODULES:
                    raise CodeValidationError(f"Импорт запрещён: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if _module_root(node.module) in BLOCKED_ROOT_MODULES:
                raise CodeValidationError(f"Импорт запрещён: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                raise CodeValidationError(f"Вызов запрещён: {node.func.id}()")
            if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALLS:
                raise CodeValidationError(f"Вызов запрещён: {node.func.attr}()")
