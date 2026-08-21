from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


_CONNECTIONS: list[sqlite3.Connection] = []


def persistent_checkpointer(
    path: str | Path = "data/checkpoints/catalyst_graph.sqlite",
) -> Any:
    """Create a process-lifetime SQLite checkpointer for resumable graphs."""
    from langgraph.checkpoint.sqlite import SqliteSaver

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(target), check_same_thread=False)
    _CONNECTIONS.append(connection)
    return SqliteSaver(connection)
