from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .automation import default_arcrift_db_path


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    input_path: Path | None
    arcrift_path: Path | None
    vault_path: Path
    graph_path: Path


def default_app_config(db_path: str | Path) -> AppConfig:
    home = Path.home()
    return AppConfig(
        db_path=Path(db_path),
        input_path=None,
        arcrift_path=default_arcrift_db_path(),
        vault_path=home / "Documents" / "Sporepath Vault",
        graph_path=Path("sporepath_graph.html"),
    )
