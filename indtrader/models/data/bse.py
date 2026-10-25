"""BSE's public API: the official SENSEX quote and insider-trading disclosures."""

import datetime as dt
import logging
import re
from typing import List, Optional

from indtrader.core.errors import DataError
from indtrader.core.http import HttpClient

log = logging.getLogger(__name__)

SENSEX_URL = "https://api.bseindia.com/RealTimeBseIndiaAPI/api/GetSensexData/w"
INSIDER_URL = "https://api.bseindia.com/BseIndiaAPI/api/InsiderTrade15/w?scripcode=&fromdt=%s&todt=%s"
HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}

# BSE publishes the filer's PAN, address and phone number with every insider
# disclosure. None of that is needed for analysis, so it is dropped on arrival
# and never cached, recorded or printed.
PERSONAL_FIELDS = re.compile(r"Add$|Contact|PAN$|CIN$|DIN$|Email|Phone", re.IGNORECASE)


def strip_personal(record: dict) -> dict:
    return {key: value for key, value in record.items() if not PERSONAL_FIELDS.search(key)}


class BseClient:
    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def sensex(self) -> Optional[dict]:
        """BSE's own SENSEX record (ltp, Prev_Close, I_open, High, Low, dttm)."""
        payload = self.http.json(SENSEX_URL, name="bse-sensex.json", ttl=20, headers=HEADERS)
        return payload[0] if isinstance(payload, list) and payload else None

    def insider_trades(self, start: dt.date, end: dt.date) -> List[dict]:
        """SEBI PIT Reg 7(2) disclosures filed on BSE between two dates, personal fields removed.

        Live responses are fetched without a file name, so the raw payload
        (with personal data) never reaches the disk cache or a recording.
        Offline runs read a sanitised file instead.
        """
        url = INSIDER_URL % (start.strftime("%d/%m/%Y"), end.strftime("%d/%m/%Y"))
        name = "bse-insider-%s-%s.json" % (start.isoformat(), end.isoformat()) if self.http.offline else None
        payload = self.http.json(url, name=name, headers=HEADERS)
        if not isinstance(payload, dict):
            raise DataError("BSE insider feed changed shape")
        return [strip_personal(record) for record in payload.get("Table") or []]
