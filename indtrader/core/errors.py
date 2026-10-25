"""Exception hierarchy.

Every error a user can act on derives from :class:`IndianTraderError`. The
command line prints its message and exits with ``exit_code``; anything else
is a bug and is logged with a traceback.

    IndianTraderError
    +-- ConfigError        the settings file is invalid
    +-- ValidationError    bad input: a symbol, date, rule or missing file
    +-- DataError          a data source returned nothing usable
        +-- NetworkError   the request itself failed (HTTP error, timeout)
"""


class IndianTraderError(Exception):
    """Base class for errors the user should read."""

    exit_code = 1


class ConfigError(IndianTraderError):
    """workspace/config.json is missing a value or has a wrong one."""


class ValidationError(IndianTraderError):
    """The request cannot be carried out as given."""


class DataError(IndianTraderError):
    """A data source returned nothing usable."""


class NetworkError(DataError):
    """An HTTP request failed after its retries."""
