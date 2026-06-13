"""Drop-in replacement for the upstream ``mv-rerun/run_ma_vis.py``.

The MAMMA ``inference/`` runner subprocesses ``python <repo_path>/<script>``
for each step. By placing this thin shim at ``visualization/run_ma_vis.py``,
the runner can call ``python visualization/run_ma_vis.py --seq_name ...``
and end up running the polished pipeline -- no behaviour change for the
runner, no dependency on the upstream repo.

Equivalent to ``python -m visualization`` for end users.
"""
from __future__ import annotations

import os
import sys

# Make the parent repo importable when this file is run as a script
# (i.e. ``python visualization/run_ma_vis.py``). Importing
# ``visualization`` requires the parent of this file to be on sys.path.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from visualization.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
    # torch/OpenMP native teardown can fail-fast (0xC0000409) on Windows after
    # all work has completed. os._exit still runs DLL detach via ExitProcess,
    # so use TerminateProcess (skips detach handlers) on Windows.
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(
            ctypes.windll.kernel32.GetCurrentProcess(), 0)
    os._exit(0)
