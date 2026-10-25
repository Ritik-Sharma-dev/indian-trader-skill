"""JSON files on disk: atomic writes, tolerant reads, stable fingerprints."""

import hashlib
import json
import logging
import os
from typing import Any

from indtrader.core.errors import ConfigError

log = logging.getLogger(__name__)


def read_json(path: str, default: Any = None) -> Any:
    """The parsed file, or ``default`` when it does not exist.

    ``utf-8-sig`` accepts the byte-order mark Windows Notepad and PowerShell
    put at the start of files they save.
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except ValueError as exc:
        raise ConfigError("%s is not valid JSON: %s" % (path, exc)) from exc


def write_json(path: str, data: Any) -> None:
    """Write through a temporary file and rename, so a crash never leaves half a file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
        fh.write("\n")
    os.replace(tmp, path)
    log.debug("wrote %s", path)


def fingerprint(obj: Any) -> str:
    """A short hash of a JSON-able value; dictionary key order does not matter."""
    text = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
