"""AuthManager — wraps BrowserClient for TUI integration."""

from __future__ import annotations

import base64
import json
import secrets
import string
import uuid
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from nordpy.BrowserClient.Helpers import get_authentication_code
from nordpy.session import SessionManager


class AuthError(Exception):
    """Raised when authentication fails."""


class AuthManager:
    """Orchestrates MitID authentication, adapted from the original nordnet.py flow."""

    def __init__(
        self, session: requests.Session, session_manager: SessionManager
    ) -> None:
        self.session = session
        self.session_manager = session_manager

    def authenticate(
        self,
        user: str,
        method: str,
        password: str | None = None,
        *,
        on_status: object = None,
        on_input_needed: object = None,
        on_qr_display: object = None,
    ) -> None:
        """Run the full MitID login flow. Raises AuthError on failure.

        on_status: optional callable(str) for status updates
        on_input_needed: optional callable(prompt: str) -> str for interactive input
        on_qr_display: optional callable(str) for QR code display updates
        """
        self._do_full_login(
            self.session,
            method,
            user,
            password,
            on_status=on_status,
            on_input_needed=on_input_needed,
            on_qr_display=on_qr_display,
        )
        self.session_manager.save(self.session)

    def _do_full_login(
        self,
        session: requests.Session,
        method: str,
        user_id: str,
        password: str | None,
        *,
        on_status: object = None,
        on_input_needed: object = None,
        on_qr_display: object = None,
    ) -> None:
        """Perform full MitID login flow (extracted from nordnet.py)."""
        _status = on_status or (lambda msg: None)
        _input = on_input_needed or input

        nem_login_state = uuid.uuid4()
        digits = string.digits
        form_digits = "".join(secrets.choice(digits) for _ in range(29))

        login_url = (
            f"https://id.signicat.com/oidc/authorize?"
            f"client_id=prod.nordnet.dk.8x&response_type=code"
            f"&redirect_uri=https://www.nordnet.dk/login"
            f"&scope=openid signicat.national_id"
            f"&acr_values=urn:signicat:oidc:method:mitid-cpr"
            f"&state=NEXT_OIDC_STATE_{nem_login_state}"
        )

        _status("Initiating MitID login...")
        request = session.get(login_url, timeout=30)
        if request.status_code != 200:
            raise AuthError(f"Failed session setup: {request.status_code}")

        soup = BeautifulSoup(request.text, "lxml")
        div = soup.div
        assert isinstance(div, Tag), "Expected <div> in login page"
        next_url = str(div["data-index-url"])
        request = session.get(next_url, timeout=30)
        soup = BeautifulSoup(request.text, "lxml")

        div = soup.div
        assert isinstance(div, Tag), "Expected <div> in auth page"
        nxt = div.next
        assert isinstance(nxt, Tag), "Expected next element in auth page"
        base_url = str(nxt["data-base-url"])

        request = session.post(
            base_url + str(nxt["data-init-auth-path"]),
            timeout=30,
        )
        if request.status_code != 200:
            raise AuthError(f"Failed auth init: {request.status_code}")

        aux = json.loads(base64.b64decode(request.json()["aux"]))
        _status("Waiting for MitID authentication...")
        authorization_code = get_authentication_code(
            session, aux, method, user_id, password, on_qr_display=on_qr_display
        )
        _status("MitID authentication successful")

        payload = (
            f"-----------------------------{form_digits}\r\n"
            f'Content-Disposition: form-data; name="authCode"\r\n\r\n'
            f"{authorization_code}\r\n"
            f"-----------------------------{form_digits}--\r\n"
        )

        headers = {
            "Content-Type": f"multipart/form-data; boundary=---------------------------{form_digits}"
        }
        session.post(
            base_url + str(nxt["data-auth-code-path"]),
            data=payload,
            headers=headers,
            timeout=30,
        )
        request = session.get(
            base_url + str(nxt["data-finalize-auth-path"]),
            timeout=30,
        )

        if "/cpr" in request.url:
            _status("CPR verification required")
            cpr_soup = BeautifulSoup(request.text, "lxml")
            cpr_number = _input("Please enter your CPR number (DDMMYYXXXX): ")

            cpr_form = cpr_soup.find("main", {"id": "cpr-form"})
            if not isinstance(cpr_form, Tag):
                raise AuthError("CPR form not found")

            cpr_base_url = str(cpr_form["data-base-url"])
            verify_path = str(cpr_form["data-verify-path"])
            finalize_path = str(cpr_form["data-finalize-cpr-path"])

            verify_url = cpr_base_url + verify_path
            cpr_payload = {"cpr": cpr_number, "remember": "false"}
            request = session.post(verify_url, data=cpr_payload, timeout=30)

            if request.status_code != 200 or '"success":false' in request.text:
                raise AuthError(f"CPR verification failed: {request.text}")

            _status("CPR verified successfully")
            finalize_url = cpr_base_url + finalize_path
            request = session.get(finalize_url, allow_redirects=True, timeout=30)

        parsed_url = urlparse(request.url)
        code = parse_qs(parsed_url.query)["code"][0]

        payload_json = {
            "authenticationProvider": "SIGNICAT",
            "countryCode": "DK",
            "signicat": {
                "authorizationCode": code,
                "redirectUri": "https://www.nordnet.dk/login",
            },
        }

        session.headers["client-id"] = "NEXT"
        request = session.post(
            "https://www.nordnet.dk/nnxapi/authentication/v2/sessions",
            json=payload_json,
            timeout=30,
        )
        if request.status_code != 200:
            raise AuthError(f"Sessions failed: {request.status_code}")

        request = session.post(
            "https://www.nordnet.dk/api/2/authentication/nnx-session/login",
            json={},
            timeout=30,
        )
        if request.status_code != 200:
            raise AuthError(f"Login failed: {request.status_code}")

        session.headers["ntag"] = request.headers["ntag"]
        _status("Successfully logged in to Nordnet!")
