#!/usr/bin/env python3
"""Indian Trader command line. Run from anywhere:

    python "Indian Trader Skill/it.py" clock
    python "Indian Trader Skill/it.py" -h
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")   # the rupee sign on Windows consoles
    except (AttributeError, ValueError):
        pass

from indtrader.cli.main import main  # noqa: E402  (the path must be set first)

if __name__ == "__main__":
    sys.exit(main())
