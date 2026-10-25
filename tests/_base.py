"""Shared test setup: a throwaway workspace per test and the recorded market
snapshot of Thursday 22 October 2026 (real NSE / BSE / Yahoo / RSS data)."""

import contextlib
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SNAP = os.path.join(HERE, "fixtures", "snap-2026-10-22")
NOW = "2026-10-22 10:30"


def session(day, closes, start="09:15", step=5, spread=1.0, vol=1000):
    """Synthetic 5-minute bars from a list of closes."""
    from indtrader.core import clock
    first = dt.datetime.strptime("%s %s" % (day, start), "%Y-%m-%d %H:%M").replace(tzinfo=clock.IST)
    out, prev = [], closes[0]
    for i, close in enumerate(closes):
        out.append({"t": first + dt.timedelta(minutes=step * i), "o": prev, "h": max(prev, close) + spread,
                    "l": min(prev, close) - spread, "c": close, "v": vol})
        prev = close
    return out


class WorkspaceTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        from indtrader.core import clock, logs
        self.home = tempfile.mkdtemp(prefix="indtrader-test-")
        self._saved_env = {k: os.environ.get(k) for k in ("INDTRADER_HOME", "INDTRADER_RECORD", "INDTRADER_LOG_FILE")}
        os.environ["INDTRADER_HOME"] = self.home
        os.environ["INDTRADER_LOG_FILE"] = "0"
        os.environ.pop("INDTRADER_RECORD", None)
        clock.set_holidays(None)
        logs.reset()

    def tearDown(self):
        from indtrader.core import logs
        logs.reset()
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    # -- helpers -----------------------------------------------------------------------

    def cli(self, *argv, offline=True, now=NOW):
        from indtrader.cli.main import main
        from indtrader.core import logs
        args = list(argv) + (["--offline", SNAP] if offline else []) + (["--now", now] if now else [])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
            logs.reset()
        return code, out.getvalue(), err.getvalue()

    def config(self, **values):
        with open(os.path.join(self.home, "config.json"), "w", encoding="utf-8") as fh:
            json.dump(values, fh)

    def read(self, name):
        with open(os.path.join(self.home, name), encoding="utf-8") as fh:
            return json.load(fh)

    def ctx(self, now=NOW):
        from indtrader.core.context import AppContext
        return AppContext.create(now=now, offline=SNAP)

    def market(self):
        return self.ctx().market

    def cfg(self):
        from indtrader.core import settings
        return settings.load()

    def now(self, text=NOW):
        from indtrader.core import clock
        return clock.parse_now(text)
