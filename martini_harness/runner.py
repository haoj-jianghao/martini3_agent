"""Call one function of martini_harness.core for one molecule folder, in this process.

Every tool and every deterministic node goes through `call`, so there is one place that turns what a core
function printed and raised into the result an agent or a gate reads:
- printed output (the core functions report by printing) is captured;
- DesignError (a refused decision), StageError (a stage that cannot continue) and SystemExit become a non-zero
  code with their message; any other exception also does, with its traceback, so a bug in the core code is
  visible in the result and in the log instead of ending the run.
Each call is appended to <moldir>/harness/commands.jsonl. `configure` must run first (Pipeline does it).
"""
from __future__ import annotations

import contextlib
import datetime
import io
import json
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import HarnessConfig
from .core import cgbuild
from .core.design import DesignError


@dataclass
class CallResult:
    code: int
    stdout: str
    stderr: str
    call: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def text(self) -> str:
        """Output and error message as one block; on failure it starts with `[exit N]`."""
        parts = [x.rstrip() for x in (self.stdout, self.stderr) if x.strip()]
        body = "\n".join(parts) or "(no output)"
        return body if self.ok else f"[exit {self.code}]\n{body}"


def configure(cfg: HarnessConfig) -> None:
    """Point the core modules at the Martini environment.json (references, force field, GROMACS)."""
    cgbuild.configure(cfg.martini_env, cfg.raw.get("gmx_threads", 4))


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _brief(x) -> str:
    return str(vars(x)) if hasattr(x, "__dict__") and not isinstance(x, type) else str(x)


def call(moldir: Path, fn: Callable, *args, tag: str, **kwargs) -> CallResult:
    """Run fn(*args, **kwargs) with its printed output captured; log it as `tag`.

    Calls run one at a time (_CALL_LOCK): an agent may request several tools in one turn, which LangChain runs in
    parallel threads, but redirect_stdout is process-wide and design.py reads, changes and rewrites design.json."""
    with _CALL_LOCK:
        return _call(moldir, fn, *args, tag=tag, **kwargs)


_CALL_LOCK = threading.Lock()


def _call(moldir: Path, fn: Callable, *args, tag: str, **kwargs) -> CallResult:
    out, err, code = io.StringIO(), io.StringIO(), 0
    t0, start = time.time(), _now()
    with contextlib.redirect_stdout(out):
        try:
            fn(*args, **kwargs)
        except DesignError as e:
            code = e.code
            err.write(f"design: {e}\n")
        except cgbuild.StageError as e:
            code = 1
            err.write(f"{tag}: {e}\n")
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            if e.code not in (None, 0) and not isinstance(e.code, int):
                err.write(f"{e.code}\n")
        except Exception:  # noqa: BLE001  (a bug in the core code; shown in full, the run goes on)
            code = 1
            err.write(traceback.format_exc())
    res = CallResult(code, out.getvalue(), err.getvalue(), f"{getattr(fn, '__module__', '')}.{getattr(fn, '__name__', fn)}")
    log = Path(moldir) / "harness" / "commands.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps({"start_utc": start, "wall_s": round(time.time() - t0, 2), "tag": tag, "call": res.call,
                            "args": [_brief(a) for a in args] + [f"{k}={v}" for k, v in kwargs.items()],
                            "exit": res.code, "stdout_tail": res.stdout[-800:], "stderr_tail": res.stderr[-2000:]},
                           default=str) + "\n")
    return res
