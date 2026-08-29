from __future__ import annotations

import ast

FORBIDDEN_IMPORTS = {"subprocess", "socket", "requests", "urllib", "httpx", "pip"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "system", "popen"}


class UnsafeCodeError(ValueError):
    pass


def validate_code(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise UnsafeCodeError(f"Generated code has invalid syntax: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name.split(".")[0] for alias in node.names]
                if isinstance(node, ast.Import)
                else [(node.module or "").split(".")[0]]
            )
            forbidden = set(names) & FORBIDDEN_IMPORTS
            if forbidden:
                raise UnsafeCodeError(
                    f"Forbidden import: {', '.join(sorted(forbidden))}"
                )
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name in FORBIDDEN_CALLS:
                raise UnsafeCodeError(f"Forbidden call: {name}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.replace("\\", "/")
            if "../" in value or value.startswith("/"):
                # Absolute paths are supplied only through the trusted runner arguments.
                raise UnsafeCodeError(
                    "Literal path traversal or absolute path detected"
                )
