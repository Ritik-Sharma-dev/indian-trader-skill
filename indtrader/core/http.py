"""HTTP access with retries, pacing, a disk cache, and offline replay.

Every request names an *offline file*. With ``offline=DIR`` the client reads
``DIR/<name>`` (or ``<name>.gz``) instead of the network, so tests run with
no internet and give the same answers every time. ``INDTRADER_RECORD=DIR``
saves each live response under the same name: a snapshot of the market that
can be replayed later.

NSE's website APIs are public but unofficial: they want browser-like headers
and a Referer, and can rate-limit or change without notice.
"""

import gzip
import http.cookiejar
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from indtrader.core import settings
from indtrader.core.errors import DataError, NetworkError

log = logging.getLogger(__name__)

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NSE_REFERER = "https://www.nseindia.com/option-chain"
RETRYABLE_STATUS = frozenset((429, 500, 502, 503, 504))


class HttpClient:
    """A small, polite HTTP client shared by all data sources."""

    def __init__(self, offline: Optional[str] = None, pause: float = 0.25, timeout: float = 20,
                 retries: int = 3, use_cache: bool = True) -> None:
        self.offline = offline
        self.pause = pause
        self.timeout = timeout
        self.retries = retries
        self.use_cache = use_cache and not offline
        self._last_request = 0.0
        self._pace_lock = threading.Lock()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    # -- public API -------------------------------------------------------------

    def get(self, url: str, name: Optional[str] = None, nse: bool = False, ttl: float = 0,
            headers: Optional[Dict[str, str]] = None) -> bytes:
        """Raw bytes of ``url``; ``ttl`` seconds of disk cache when > 0."""
        if self.offline:
            return self._read_offline(name)
        cached = self._read_cache(name, ttl)
        if cached is not None:
            log.debug("cache hit %s", name)
            self._record(name, cached)
            return cached
        data = self._fetch(url, self._headers(nse, headers))
        self._write_cache(name, data, ttl)
        self._record(name, data)
        return data

    def text(self, url: str, name: Optional[str] = None, **kwargs: Any) -> str:
        return self.get(url, name, **kwargs).decode("utf-8", "replace")

    def json(self, url: str, name: Optional[str] = None, **kwargs: Any) -> Any:
        data = self.get(url, name, **kwargs)
        try:
            return json.loads(data.decode("utf-8", "replace"))
        except ValueError as exc:
            raise DataError("%s did not return JSON (blocked or changed?)" % url) from exc

    # -- network ---------------------------------------------------------------

    @staticmethod
    def _headers(nse: bool, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        headers = {"User-Agent": BROWSER_UA, "Accept": "*/*",
                   "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip"}
        if nse:
            headers["Referer"] = NSE_REFERER
        headers.update(extra or {})
        return headers

    def _wait_turn(self) -> None:
        with self._pace_lock:
            wait = self.pause - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.time()

    def _fetch(self, url: str, headers: Dict[str, str]) -> bytes:
        reason = "no attempt made"
        for attempt in range(1, self.retries + 1):
            self._wait_turn()
            started = time.time()
            try:
                request = urllib.request.Request(url, headers=headers)
                with self._opener.open(request, timeout=self.timeout) as response:
                    data = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                log.debug("GET %s -> %d bytes in %.0f ms", url, len(data), (time.time() - started) * 1000)
                return data
            except urllib.error.HTTPError as exc:
                reason = "HTTP %s" % exc.code
                if exc.code not in RETRYABLE_STATUS:
                    break
                log.warning("GET %s: %s (attempt %d of %d)", url, reason, attempt, self.retries)
                time.sleep(1.5 * attempt)
            except (urllib.error.URLError, OSError) as exc:
                reason = str(getattr(exc, "reason", exc))
                log.warning("GET %s: %s (attempt %d of %d)", url, reason, attempt, self.retries)
                time.sleep(1.0 * attempt)
        # a 4xx is an answer ("not found", "forbidden"), not an outage
        (log.warning if reason.startswith("HTTP 4") else log.error)("GET %s failed: %s", url, reason)
        raise NetworkError("could not fetch %s (%s)" % (url, reason))

    # -- offline, cache, recording ---------------------------------------------------

    def _read_offline(self, name: Optional[str]) -> bytes:
        if not name:
            raise DataError("offline mode: this request has no offline file name")
        for candidate in (name, name + ".gz"):
            full = os.path.join(self.offline, candidate)
            if os.path.exists(full):
                with open(full, "rb") as fh:
                    data = fh.read()
                return gzip.decompress(data) if candidate.endswith(".gz") else data
        raise DataError("offline file not found: %s" % os.path.join(self.offline, name))

    @staticmethod
    def _cache_path(name: str) -> str:
        return settings.path("cache", "http", name.replace("/", "_"))

    def _read_cache(self, name: Optional[str], ttl: float) -> Optional[bytes]:
        if not (self.use_cache and ttl and name):
            return None
        path = self._cache_path(name)
        try:
            if time.time() - os.path.getmtime(path) <= ttl:
                with open(path, "rb") as fh:
                    return fh.read()
        except OSError:
            return None
        return None

    def _write_cache(self, name: Optional[str], data: bytes, ttl: float) -> None:
        if self.use_cache and ttl and name:
            with open(self._cache_path(name), "wb") as fh:
                fh.write(data)

    @staticmethod
    def _record(name: Optional[str], data: bytes) -> None:
        folder = os.environ.get("INDTRADER_RECORD")
        if folder and name:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, name), "wb") as fh:
                fh.write(data)
