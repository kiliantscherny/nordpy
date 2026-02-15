"""Session persistence — save, load, and validate Nordnet sessions."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path

import requests
from loguru import logger

from nordpy.http import HttpSession

SESSION_FILE = ".nordnet_session.json"


class SessionManager:
    """Manages saving, loading, and validating authenticated Nordnet sessions."""

    SESSION_LIFETIME_MINUTES = 30

    def __init__(self, session_path: Path | None = None) -> None:
        self.session_path = session_path or Path.cwd() / SESSION_FILE
        self.authenticated_at: datetime | None = None

    @property
    def session_seconds_remaining(self) -> int | None:
        """Seconds until the session expires (estimated), or None if unknown."""
        if not self.authenticated_at:
            return None
        from datetime import timedelta

        expiry = self.authenticated_at + timedelta(
            minutes=self.SESSION_LIFETIME_MINUTES
        )
        remaining = (expiry - datetime.now()).total_seconds()
        return max(0, int(remaining))

    def save(self, session: HttpSession) -> None:
        """Persist session cookies and headers to disk with restricted permissions."""
        now = datetime.now()
        self.authenticated_at = now
        # Support both requests.Session and curl_cffi.requests.Session cookies
        jar = getattr(session.cookies, "jar", None)
        if jar is not None:
            cookies = {c.name: c.value or "" for c in jar}
        else:
            cookies = dict(session.cookies)
        session_data = {
            "cookies": cookies,
            "headers": {k: v for k, v in session.headers.items()},
            "saved_at": now.isoformat(),
        }
        self.session_path.write_text(json.dumps(session_data, indent=2))
        os.chmod(self.session_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

    def load(self, session: HttpSession) -> bool:
        """Load session cookies and headers from disk. Returns True if file existed."""
        if not self.session_path.exists():
            return False

        try:
            session_data = json.loads(self.session_path.read_text())
            for name, value in session_data.get("cookies", {}).items():
                session.cookies.set(name, value)
            for name, value in session_data.get("headers", {}).items():
                session.headers[name] = value
            saved_at = session_data.get("saved_at")
            if saved_at:
                self.authenticated_at = datetime.fromisoformat(saved_at)
            return True
        except (json.JSONDecodeError, KeyError):
            return False

    def validate(self, session: HttpSession) -> bool:
        """Test if the session is still valid by calling the accounts endpoint."""
        try:
            logger.debug("Validating session via /api/2/accounts")
            response = session.get("https://www.nordnet.dk/api/2/accounts", timeout=30)
            if response.status_code == 200:
                data = response.json()
                valid = isinstance(data, list) and len(data) > 0
                logger.debug("Session validation: {} (accounts={})", "valid" if valid else "invalid", len(data) if isinstance(data, list) else "N/A")
                return valid
            logger.debug("Session validation failed: status={}", response.status_code)
            return False
        except (requests.RequestException, Exception) as e:
            logger.debug("Session validation error: {}", e)
            return False

    def load_and_validate(self, session: HttpSession) -> bool:
        """Load a saved session and test its validity. Returns True if usable."""
        if not self.load(session):
            return False
        return self.validate(session)
