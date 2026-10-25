"""Entry point: parse, set up logging, build the context, run the handler.

Exit codes: 0 success, 1 a user-facing error (bad input, missing data) or a
"nothing happened" result (no trigger, a BLOCK), 2 an internal error (logged
with a traceback), 130 interrupted.
"""

import logging
import sys
import time
from typing import List, Optional

from indtrader.core import logs
from indtrader.core.context import AppContext
from indtrader.core.errors import IndianTraderError
from indtrader.cli.parser import build_parser

log = logging.getLogger(__name__)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logs.configure(level=args.log_level, console_level="ERROR")   # the user sees one clean message; the file has the detail
    started = time.time()
    log.debug("command %s %s", args.cmd, argv if argv is not None else sys.argv[1:])
    try:
        ctx = AppContext.create(now=args.now, offline=args.offline)
        code = args.handler(args, ctx) or 0
    except IndianTraderError as exc:
        log.warning("%s: %s", args.cmd, exc)
        print("error: %s" % exc, file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        log.info("%s interrupted", args.cmd)
        return 130
    except Exception as exc:                       # a bug: full traceback to the log, short note to the user
        log.exception("%s failed", args.cmd)
        print("internal error: %s (details in workspace/logs/indtrader.log)" % exc, file=sys.stderr)
        return 2
    log.debug("command %s finished with %d in %.2fs", args.cmd, code, time.time() - started)
    return code
