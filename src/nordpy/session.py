"""Session persistence — keep a login between runs, and know when it is stale.

A MitID login costs a tap on a phone, so it must not happen once per run. What
a login produces is a set of Nordnet cookies, and those are kept by
mitid-client's `CookieStore`: 0600, in the XDG config directory.

That directory is the point. nordpy is meant to be run with `uvx`, from
wherever you happen to be standing, and a session file resolved against the
working directory would follow you around — dropping a live Nordnet login into
whatever project tree you were in at the time, where that project's .gitignore
has never heard of it. The config directory is the same place every run.

What is left here is Nordnet's half: asking whether the session still works,
and the thirty-minute estimate the header counts down. Nordnet publishes no
idle limit and there is nothing to ping, so unlike a register with a documented
timer this is a guess — hence `validate`, which asks rather than assumes.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from loguru import logger
from mitid.store import CookieStore

from nordpy.http import HttpSession

SESSION_FILE = "nordnet-session.json"
ACCOUNTS_URL = "https://www.nordnet.dk/api/2/accounts"


def log_path() -> Path:
    """Where the log goes, following the XDG state convention.

    Not next to the installed package, which is inside site-packages once this
    is installed and may not be writable, and not the working directory, for
    the same reason the session file is not.
    """
    root = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(root).expanduser() / "nordpy" / "nordpy.log"


class SessionManager:
    """Manages saving, loading, and validating authenticated Nordnet sessions."""

    SESSION_LIFETIME_MINUTES = 30

    def __init__(self) -> None:
        self.store = CookieStore("nordpy", SESSION_FILE)
        self.authenticated_at: datetime | None = None

    @property
    def session_path(self) -> Path:
        """Where the cached cookies live."""
        return self.store.path

    @property
    def session_seconds_remaining(self) -> int | None:
        """Seconds until the session expires (estimated), or None if unknown."""
        if not self.authenticated_at:
            return None
        expiry = self.authenticated_at + timedelta(
            minutes=self.SESSION_LIFETIME_MINUTES
        )
        remaining = (expiry - datetime.now()).total_seconds()
        return max(0, int(remaining))

    def save(self, session: HttpSession) -> None:
        """Persist session cookies and headers to disk with restricted permissions."""
        # The headers ride along as an extra: the login flow accumulates some,
        # and the store hands back whatever it was given beside the cookies.
        self.store.save(session, headers=dict(session.headers))
        self.authenticated_at = datetime.now()

    def load(self, session: HttpSession) -> bool:
        """Load session cookies and headers from disk. Returns True if file existed."""
        # session_factory is how the store rebuilds a session to hang the
        # cookies on. nordpy already has one, made with the proxy and the TLS
        # fingerprint it needs, so hand that back rather than let it build a
        # plain requests session that Nordnet would refuse.
        self.store.session_factory = lambda: session
        restored = self.store.restore()
        if restored is None:
            return False

        _, payload = restored
        for name, value in (payload.get("headers") or {}).items():
            session.headers[name] = value
        self.authenticated_at = _parse_time(payload.get("saved_at"))
        return True

    def forget(self) -> bool:
        """Delete the cached cookies. Returns whether there was anything to delete."""
        self.authenticated_at = None
        return self.store.forget()

    def validate(self, session: HttpSession) -> bool:
        """Test if the session is still valid by calling the accounts endpoint."""
        try:
            logger.debug("Validating session via /api/2/accounts")
            response = session.get(ACCOUNTS_URL, timeout=30)
            if response.status_code == 200:
                data = response.json()
                valid = isinstance(data, list) and len(data) > 0
                logger.debug(
                    "Session validation: {} (accounts={})",
                    "valid" if valid else "invalid",
                    len(data) if isinstance(data, list) else "N/A",
                )
                return valid
            logger.debug("Session validation failed: status={}", response.status_code)
            return False
        # curl_cffi's RequestException is an OSError, not a requests one, so
        # both are named here: the session may be either. ValueError covers a
        # 200 whose body is not the JSON it claims to be.
        except (requests.RequestException, OSError, ValueError) as error:
            logger.debug("Session validation error: {}", error)
            return False

    def load_and_validate(self, session: HttpSession) -> bool:
        """Load a saved session and test its validity. Returns True if usable."""
        if not self.load(session):
            return False
        return self.validate(session)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
