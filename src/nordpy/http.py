"""HTTP session factory — uses curl_cffi for browser TLS fingerprinting."""

from __future__ import annotations

import requests
from curl_cffi.requests import Session

HttpSession = Session | requests.Session
"""Type alias for the HTTP session used throughout the app."""


def create_session(*, proxy: str | None = None, impersonate: str = "chrome") -> HttpSession:
    """Create an HTTP session that impersonates a real browser's TLS fingerprint.

    Uses curl_cffi under the hood so that the TLS handshake (JA3/JA4 hash)
    matches a genuine Chrome browser, preventing server-side bot detection.
    """
    proxies = None
    if proxy:
        proxies = {"http": f"socks5://{proxy}", "https": f"socks5://{proxy}"}
    return Session(impersonate=impersonate, proxies=proxies)
