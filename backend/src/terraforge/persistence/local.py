from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4


async def atomic_write_text(path: Path, content: str, attempts: int = 6) -> None:
    """Atomically replace a local state file without sharing temporary filenames.

    Windows does not allow replacing a file while another handle is open. A short,
    bounded retry handles readers such as SSE/API requests, while a unique temporary
    path prevents concurrent writers from attempting to move the same file.
    """
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    try:
        for attempt in range(attempts):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(0.02 * (2**attempt))
    finally:
        temporary.unlink(missing_ok=True)
