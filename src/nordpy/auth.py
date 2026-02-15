"""AuthManager — wraps BrowserClient for TUI integration."""

from __future__ import annotations

import base64
import json
import secrets
import string
import time
import uuid
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from loguru import logger

from nordpy.BrowserClient.Helpers import get_authentication_code
from nordpy.http import HttpSession
from nordpy.session import SessionManager


def _cookies_to_dict(session: object) -> dict[str, str]:
    """Safely convert session cookies to a dict for logging.

    Supports both ``HttpSession`` and ``curl_cffi.HttpSession``.
    """
    cookies = session.cookies
    # curl_cffi: iterate via .jar for full Cookie objects; fallback to dict()
    if hasattr(cookies, "jar"):
        return {c.name: c.value or "" for c in cookies.jar}
    # requests: iterate raw cookie objects to avoid CookieConflictError
    try:
        return {c.name: c.value or "" for c in cookies}
    except AttributeError:
        return dict(cookies)


class AuthError(Exception):
    """Raised when authentication fails."""


class AuthManager:
    """Orchestrates MitID authentication, adapted from the original nordnet.py flow."""

    def __init__(
        self, session: HttpSession, session_manager: SessionManager
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

    @staticmethod
    def _follow_redirects_to_code(
        session: HttpSession,
        response: requests.Response,
        *,
        max_hops: int = 15,
    ) -> str:
        """Manually follow redirects and SAML forms, extracting the OIDC code
        from a Location header WITHOUT loading the nordnet.dk page.

        This is critical: if we let curl_cffi follow the final redirect to
        nordnet.dk/login?code=..., the Next.js SSR consumes the one-time OIDC
        code during page rendering, and our subsequent POST to /sessions fails
        with 401.  Instead, we stop at the 302 pointing to nordnet.dk and read
        the code from the Location header.
        """
        for hop in range(max_hops):
            # ── Check if this is an HTTP redirect ──
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location", "")
                logger.debug(
                    "Redirect hop {}: {} → {}",
                    hop + 1,
                    response.status_code,
                    location,
                )

                # If the Location points to nordnet.dk with a code, STOP.
                loc_parsed = urlparse(location)
                loc_qs = parse_qs(loc_parsed.query)
                if "code" in loc_qs and "nordnet" in loc_parsed.netloc:
                    code = loc_qs["code"][0]
                    logger.info(
                        "Redirect hop {}: intercepted OIDC code (len={}) — "
                        "NOT loading nordnet.dk page",
                        hop + 1,
                        len(code),
                    )
                    return code

                # Follow the redirect manually (without loading nordnet.dk)
                response = session.get(
                    location, allow_redirects=False, timeout=30
                )
                continue

            # ── Check if this is a loaded page with code in URL ──
            page_parsed = urlparse(str(response.url))
            page_qs = parse_qs(page_parsed.query)
            if "code" in page_qs:
                logger.warning(
                    "Redirect hop {}: page was loaded WITH code in URL "
                    "(SSR may have consumed it): {}",
                    hop + 1,
                    response.url,
                )
                return page_qs["code"][0]

            # ── Check for SAML POST binding (auto-submitting HTML form) ──
            if response.status_code == 200 and response.text:
                soup = BeautifulSoup(response.text, "lxml")
                form = soup.find("form")
                if isinstance(form, Tag):
                    action = str(form.get("action", ""))
                    if action:
                        fields: dict[str, str] = {}
                        for inp in form.find_all("input"):
                            name = inp.get("name")
                            if name:
                                fields[str(name)] = str(inp.get("value", ""))

                        method = str(form.get("method", "GET")).upper()
                        logger.info(
                            "SAML form hop {}: {} {} (fields={})",
                            hop + 1,
                            method,
                            action,
                            list(fields.keys()),
                        )
                        if method == "POST":
                            response = session.post(
                                action,
                                data=fields,
                                allow_redirects=False,
                                timeout=30,
                            )
                        else:
                            response = session.get(
                                action,
                                params=fields,
                                allow_redirects=False,
                                timeout=30,
                            )
                        continue

            # No redirect, no form, no code — give up
            logger.error(
                "Redirect hop {}: stuck at {} (status={}, body[:300]={})",
                hop + 1,
                response.url,
                response.status_code,
                response.text[:300],
            )
            raise AuthError(
                f"Could not extract OIDC code from redirect chain "
                f"(stuck at {response.url})"
            )

        raise AuthError("Redirect chain too long — could not extract OIDC code")

    def _do_full_login(
        self,
        session: HttpSession,
        method: str,
        user_id: str,
        password: str | None,
        *,
        on_status: object = None,
        on_input_needed: object = None,
        on_qr_display: object = None,
    ) -> None:
        """Perform full MitID login flow.

        Follows the helmstedt/MitID-BrowserClient reference implementation
        as closely as possible, with the addition of CPR verification handling.
        """
        _status = on_status or (lambda msg: None)
        _input = on_input_needed or input

        nem_login_state = uuid.uuid4()
        digits = string.digits
        form_digits = "".join(secrets.choice(digits) for _ in range(29))

        # Pre-visit nordnet.dk/logind to establish cookies and extract
        # the page-embedded CSRF token (data-csrf attribute on a script tag).
        logger.info("Step 0: GET nordnet.dk/logind to establish cookies")
        pre_resp = session.get("https://www.nordnet.dk/logind", timeout=30)
        logger.debug(
            "Step 0 response: status={}, cookies={}",
            pre_resp.status_code,
            _cookies_to_dict(session),
        )
        # Extract the page-embedded CSRF token (may differ from _csrf cookie)
        pre_soup = BeautifulSoup(pre_resp.text, "lxml")
        csrf_script = pre_soup.find("script", attrs={"data-csrf": True})
        page_csrf_token = str(csrf_script["data-csrf"]) if csrf_script else None
        logger.debug("Step 0: page data-csrf={}", page_csrf_token)

        # Set cookies normally created by client-side JavaScript.
        # The browser has these but HttpSession doesn't (no JS engine).
        # consent_cookie must include all categories — the browser JS sets all
        # four: analytics, functional, marketing, necessary.
        session.cookies.set(
            "consent_cookie",
            "analytics,functional,marketing,necessary",
            domain="www.nordnet.dk",
            path="/",
        )
        session.cookies.set("lang", "da", domain="www.nordnet.dk", path="/")
        # _dcid: device/client ID — format: dcid.1.<timestamp_ms>.<random>
        dcid = f"dcid.1.{int(time.time() * 1000)}.{secrets.randbelow(10**9)}"
        session.cookies.set("_dcid", dcid, domain="www.nordnet.dk", path="/")
        logger.debug("Step 0: set consent_cookie, lang=da, _dcid={}", dcid)

        # Step 0.5: Call signicatStart to register the OIDC flow server-side.
        # The browser calls POST /authentication/v2/methods/signicat/start
        # before redirecting to signicat. The server returns the authorize URL.
        oidc_state = f"NEXT_OIDC_STATE_{nem_login_state}"
        redirect_uri = "https://www.nordnet.dk/login"
        start_payload = {
            "redirectUri": redirect_uri,
            "state": oidc_state,
            "idp": "MITID",
        }

        # signicatStart lives on a SEPARATE API domain (api.prod.nntech.io),
        # not on www.nordnet.dk.  This cross-origin request registers the OIDC
        # flow server-side via PAR (Pushed Authorization Request, RFC 9126) and
        # returns the authorize URL with a server-generated request_uri reference.
        #
        # IMPORTANT: We must send compact JSON (no spaces) to match the browser's
        # exact 123-byte payload.  Using json= with curl_cffi adds spaces (128
        # bytes) which the server may reject.  We also avoid the double
        # Content-Type header that can occur when json= and explicit headers both
        # set content-type.
        start_body = json.dumps(start_payload, separators=(",", ":"))
        start_headers = {
            "content-type": "application/json",
            "x-locale": "da-DK",
            "accept": "*/*",
            "origin": "https://www.nordnet.dk",
            "referer": "https://www.nordnet.dk/",
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "dnt": "1",
        }

        start_url = "https://api.prod.nntech.io/authentication/v2/methods/signicat/start"
        logger.info("Step 0.5: POST signicatStart: {}", start_url)
        logger.debug("Step 0.5 body ({} bytes): {}", len(start_body), start_body)
        logger.debug("Step 0.5 headers: {}", start_headers)
        start_resp = session.post(
            start_url, data=start_body, headers=start_headers, timeout=30,
        )
        logger.debug(
            "Step 0.5 response: status={}, headers={}, body={}",
            start_resp.status_code,
            dict(start_resp.headers),
            start_resp.text[:500],
        )

        login_url = None
        if start_resp.status_code == 200:
            try:
                start_data = start_resp.json()
                # Response: {"data": {"requestUri": "..."}} or {"requestUri": "..."}
                request_uri = None
                if isinstance(start_data, dict):
                    if "data" in start_data and isinstance(start_data["data"], dict):
                        request_uri = start_data["data"].get("requestUri")
                    if not request_uri:
                        request_uri = start_data.get("requestUri")
                if request_uri:
                    login_url = request_uri
                    logger.info(
                        "Step 0.5: got requestUri from signicatStart (len={})",
                        len(login_url),
                    )
                else:
                    logger.warning(
                        "Step 0.5: 200 but no requestUri in response: {}", start_data,
                    )
            except Exception as e:
                logger.warning("Step 0.5: failed to parse response: {}", e)
        else:
            logger.warning(
                "Step 0.5: signicatStart failed: status={}", start_resp.status_code,
            )

        # Fallback: construct the authorize URL manually if signicatStart failed.
        # NOTE: This fallback will NOT work for PAR-based flows because we
        # don't have the server-generated request_uri.  The real OIDC provider
        # is nordnet-login.app.signicat.com (client_id=prod-joyous-bag-934),
        # discovered from Chrome net-export HAR analysis.  This fallback uses
        # the old id.signicat.com endpoint with inline params as a last resort.
        if not login_url:
            logger.warning(
                "Step 0.5: signicatStart FAILED — fallback URL will likely not work!",
            )
            login_url = (
                f"https://nordnet-login.app.signicat.com/auth/open/connect/authorize?"
                f"client_id=prod-joyous-bag-934&response_type=code"
                f"&redirect_uri={redirect_uri}"
                f"&scope=openid+nin"
                f"&state={oidc_state}"
            )

        _status("Initiating MitID login...")
        logger.info("Step 1: GET signicat authorize")
        request = session.get(login_url, timeout=30)
        logger.debug("Step 1 response: status={}, url={}", request.status_code, request.url)
        if request.status_code != 200:
            raise AuthError(f"Failed session setup: {request.status_code}")

        soup = BeautifulSoup(request.text, "lxml")
        div = soup.find("div", attrs={"data-index-url": True})
        if not isinstance(div, Tag):
            logger.error("No <div data-index-url> found. Page text:\n{}", request.text[:2000])
            raise AuthError("Login page missing data-index-url — page structure may have changed")
        next_url = str(div["data-index-url"])
        logger.info("Step 2: GET data-index-url: {}", next_url)
        request = session.get(next_url, timeout=30)
        logger.debug("Step 2 response: status={}, url={}", request.status_code, request.url)
        soup = BeautifulSoup(request.text, "lxml")

        nxt = soup.find(attrs={"data-base-url": True})
        if not isinstance(nxt, Tag):
            logger.error("No element with data-base-url found. Page text:\n{}", request.text[:2000])
            raise AuthError("Auth page missing data-base-url — page structure may have changed")
        base_url = str(nxt["data-base-url"])
        logger.debug("base_url={}", base_url)

        init_auth_url = base_url + str(nxt["data-init-auth-path"])
        logger.info("Step 3: POST init-auth: {}", init_auth_url)
        request = session.post(init_auth_url, timeout=30)
        logger.debug("Step 3 response: status={}", request.status_code)
        if request.status_code != 200:
            raise AuthError(f"Failed auth init: {request.status_code}")

        aux = json.loads(base64.b64decode(request.json()["aux"]))
        _status("Waiting for MitID authentication...")
        logger.info("Step 4: MitID authentication (method={})", method)
        authorization_code = get_authentication_code(
            session, aux, method, user_id, password, on_qr_display=on_qr_display
        )
        logger.info("Step 4 complete: got authorization_code (len={})", len(str(authorization_code)))
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
        auth_code_url = base_url + str(nxt["data-auth-code-path"])
        logger.info("Step 5: POST auth-code: {}", auth_code_url)
        resp_auth_code = session.post(
            auth_code_url,
            data=payload,
            headers=headers,
            timeout=30,
        )
        logger.debug("Step 5 response: status={}, body={}", resp_auth_code.status_code, resp_auth_code.text[:500])

        finalize_auth_url = base_url + str(nxt["data-finalize-auth-path"])
        logger.info("Step 6: GET finalize-auth (no auto-redirect): {}", finalize_auth_url)
        request = session.get(finalize_auth_url, allow_redirects=False, timeout=30)
        logger.debug("Step 6 response: status={}, url={}", request.status_code, request.url)

        # Step 6 may redirect to the CPR page or start the SAML chain.
        # Follow redirects manually until we reach /cpr or get a 200.
        while request.status_code in (301, 302, 303, 307, 308):
            loc = request.headers.get("Location", "")
            if "/cpr" in loc:
                logger.info("Step 6: redirect to CPR page: {}", loc)
                # Allow auto-redirects here — we need to load the CPR HTML form.
                # This is within the signicat domain, not nordnet.dk.
                request = session.get(loc, timeout=30)
                break
            logger.debug("Step 6 redirect: {} → {}", request.status_code, loc)
            request = session.get(loc, allow_redirects=False, timeout=30)

        if "/cpr" in request.url:
            _status("CPR verification required")
            logger.info("Step 7: CPR verification required (url={})", request.url)
            cpr_soup = BeautifulSoup(request.text, "lxml")
            cpr_number = _input("Please enter your CPR number (DDMMYYXXXX): ")

            cpr_form = cpr_soup.find("main", {"id": "cpr-form"})
            if not isinstance(cpr_form, Tag):
                raise AuthError("CPR form not found")

            cpr_base_url = str(cpr_form["data-base-url"])
            verify_path = str(cpr_form["data-verify-path"])
            finalize_path = str(cpr_form["data-finalize-cpr-path"])

            verify_url = cpr_base_url + verify_path
            logger.info("Step 7a: POST CPR verify: {}", verify_url)
            cpr_payload = {"cpr": cpr_number, "remember": "false"}
            request = session.post(verify_url, data=cpr_payload, timeout=30)
            logger.debug("Step 7a response: status={}, body={}", request.status_code, request.text[:500])

            if request.status_code != 200 or '"success":false' in request.text:
                raise AuthError(f"CPR verification failed: {request.text}")

            _status("CPR verified successfully")
            finalize_url = cpr_base_url + finalize_path
            logger.info("Step 7b: GET CPR finalize (no auto-redirect): {}", finalize_url)
            request = session.get(finalize_url, allow_redirects=False, timeout=30)
            logger.debug("Step 7b response: status={}, url={}", request.status_code, request.url)

        # Follow the redirect/SAML chain manually, intercepting the OIDC code
        # from the Location header WITHOUT loading the nordnet.dk page.
        # This prevents the SSR from consuming the one-time OIDC code.
        _status("Completing authentication...")
        code = self._follow_redirects_to_code(session, request)
        logger.info("Step 8: Intercepted OIDC code (len={})", len(code))
        logger.debug("After redirect interception — cookies: {}", _cookies_to_dict(session))

        # Step 8.5: Refresh cookies by loading /logind (without the code param).
        # The browser loads nordnet.dk/logind?code=... and the page sets fresh
        # cookies (including possibly refreshing _csrf).  We load without the
        # code to avoid any SSR consumption risk, but still get fresh cookies.
        logger.info("Step 8.5: GET /logind to refresh cookies before sessions POST")
        refresh_resp = session.get("https://www.nordnet.dk/logind", timeout=30)
        logger.debug(
            "Step 8.5 response: status={}, cookies={}",
            refresh_resp.status_code,
            _cookies_to_dict(session),
        )

        payload_json = {
            "authenticationProvider": "SIGNICAT",
            "countryCode": "DK",
            "signicat": {
                "authorizationCode": code,
                "redirectUri": redirect_uri,
                "useDtp": True,
            },
        }

        # Set API headers for the Nordnet sessions POST — matching what the
        # browser actually sends (verified from Chrome net-export HAR).
        # NOTE: The browser does NOT send a Csrf-Token header; only the _csrf
        # cookie is sent.  The server uses Origin for CSRF protection instead.
        session.headers["client-id"] = "NEXT"
        session.headers["ntag"] = "NO_NTAG_RECEIVED_YET"
        session.headers["accept"] = "application/json"
        session.headers["content-type"] = "application/json"
        session.headers["origin"] = "https://www.nordnet.dk"
        session.headers["referer"] = "https://www.nordnet.dk/"
        session.headers["sec-fetch-site"] = "same-origin"
        session.headers["sec-fetch-mode"] = "cors"
        session.headers["sec-fetch-dest"] = "empty"
        session.headers["dnt"] = "1"
        logger.debug(
            "Step 9: _csrf cookie={}",
            _cookies_to_dict(session),
        )

        body_bytes = json.dumps(payload_json, separators=(",", ":"))
        logger.info("Step 9: POST /nnxapi/authentication/v2/sessions")
        logger.debug("Step 9 payload ({} bytes): {}", len(body_bytes), body_bytes)
        logger.debug("Step 9 cookies: {}", _cookies_to_dict(session))
        logger.debug("Step 9 headers: {}", {k: v for k, v in session.headers.items()})
        request = session.post(
            "https://www.nordnet.dk/nnxapi/authentication/v2/sessions",
            data=body_bytes,
            timeout=30,
        )
        logger.debug(
            "Step 9 response: status={}, headers={}, body={}",
            request.status_code,
            dict(request.headers),
            request.text[:1000],
        )
        if request.status_code != 200:
            logger.error(
                "Sessions endpoint failed! status={}, body={}", request.status_code, request.text
            )
            raise AuthError(f"Sessions failed: {request.status_code}")

        logger.info("Step 10: POST /api/2/authentication/nnx-session/login")
        request = session.post(
            "https://www.nordnet.dk/api/2/authentication/nnx-session/login",
            json={},
            timeout=30,
        )
        logger.debug("Step 10 response: status={}, body={}", request.status_code, request.text[:500])
        if request.status_code != 200:
            logger.error("Login failed! status={}, body={}", request.status_code, request.text)
            raise AuthError(f"Login failed: {request.status_code}")

        session.headers["ntag"] = request.headers["ntag"]
        logger.info("Auth complete — ntag set")
        _status("Successfully logged in to Nordnet!")
