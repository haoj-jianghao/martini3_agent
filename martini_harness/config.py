"""Harness configuration: config/harness.json plus the Martini environment.json it points to."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class HarnessConfig:
    path: Path
    raw: dict
    martini_env: Path            # environment.json (references, GROMACS)
    project: Path                # its folder; every reference path is relative to it
    env: dict
    runs_root: Path

    @property
    def prompts(self) -> Path:
        return HARNESS_ROOT / "martini_harness" / "prompts"

    def model_for(self, node: str) -> str:
        return self.raw["models"].get(node) or self.raw["models"]["default"]

    @property
    def fallbacks(self) -> list[str]:
        return list(self.raw["models"].get("fallbacks") or [])

    def limit(self, key: str) -> int:
        return int(self.raw["limits"][key])

    def reference_roots(self) -> list[Path]:
        """Folders the agents may read: the environment's generation_reference_paths."""
        return [(self.project / p).resolve() for p in self.env["generation_reference_paths"]]


def _abs(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (HARNESS_ROOT / p)


def load_config(path: str | Path | None = None) -> HarnessConfig:
    path = _abs(path or "config/harness.json").resolve()
    raw = json.loads(path.read_text())
    env_path = _abs(raw["martini_env"]).resolve()
    env = json.loads(env_path.read_text())
    return HarnessConfig(path=path, raw=raw, martini_env=env_path, project=env_path.parent, env=env,
                         runs_root=_abs(raw["runs_root"]).resolve())
