from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from beamng_telemetry_dashboard.frontend.dashboard import run_app


if __name__ == "__main__":
    run_app()
