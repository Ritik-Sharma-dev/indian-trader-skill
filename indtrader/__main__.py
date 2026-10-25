"""``python -m indtrader`` runs the command line."""

import sys

from indtrader.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
