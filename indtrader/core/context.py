"""The application context handed to every command and agent."""

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from indtrader.core import clock, settings
from indtrader.core.http import HttpClient

if TYPE_CHECKING:
    from indtrader.models.data.market_data import MarketData


@dataclass
class AppContext:
    """Settings, the clock and the data layer for one run.

    ``now`` is the real IST clock or a pinned time (``--now``) for replays
    and tests; ``offline`` points the HTTP client at a recorded snapshot.
    """

    cfg: settings.Settings
    now: dt.datetime
    http: HttpClient
    market: Optional["MarketData"] = field(default=None)
    pinned: bool = False

    @classmethod
    def create(cls, now: Optional[str] = None, offline: Optional[str] = None,
               cfg: Optional[settings.Settings] = None) -> "AppContext":
        from indtrader.models.data.market_data import MarketData   # local import: data depends on core

        http = HttpClient(offline=offline)
        ctx = cls(cfg=cfg if cfg is not None else settings.load(), now=clock.parse_now(now), http=http, pinned=bool(now))
        ctx.market = MarketData(http, ctx.cfg)
        return ctx

    @property
    def offline(self) -> bool:
        return bool(self.http.offline)

    @property
    def replaying(self) -> bool:
        """A pinned past time on live data: candles can be cut at ``now``, but quotes and option
        prices would be today's, not that moment's, so callers must not use them."""
        return self.pinned and not self.offline

    def at(self, now: dt.datetime) -> "AppContext":
        """The same context at another moment (replays step the clock)."""
        return AppContext(cfg=self.cfg, now=now, http=self.http, market=self.market, pinned=True)
