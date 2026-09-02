"""Tests for nordpy.session — save/load/validate, expiry calculation.

The cookies live in the XDG config directory now, not the working directory,
so every test that touches the disk points XDG_CONFIG_HOME at a tmp path. That
is as much the behaviour under test as the round trip is: nordpy is run with
uvx from wherever you happen to be standing, and a session file resolved
against the working directory would land wherever that was.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime

import pytest
import requests
import responses
from freezegun import freeze_time

from nordpy.session import SessionManager, log_path


@pytest.fixture
def sm(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return SessionManager()


# ── where things land ──


def test_session_path_follows_xdg(sm, tmp_path):
    assert sm.session_path == tmp_path / "nordpy" / "nordnet-session.json"


def test_session_path_ignores_the_working_directory(sm, tmp_path, monkeypatch):
    """The file that used to be ./.nordnet_session.json is the whole point.

    Run with uvx, nordpy's working directory is whatever the user was standing
    in, so a credential resolved against it lands in a stranger's project.
    """
    monkeypatch.chdir(tmp_path / "..")
    assert sm.session_path.is_absolute()
    assert tmp_path in sm.session_path.parents


def test_log_path_follows_xdg_state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert log_path() == tmp_path / "nordpy" / "nordpy.log"


# ── saving and loading ──


def test_save_writes_json(sm, mock_session):
    mock_session.cookies.set("JSESSIONID", "abc123", domain="nordnet.dk", path="/")
    sm.save(mock_session)

    assert sm.session_path.exists()
    data = json.loads(sm.session_path.read_text())
    assert {c["name"]: c["value"] for c in data["cookies"]} == {"JSESSIONID": "abc123"}
    # The domain and path go too - a name and a value cannot reconstruct them.
    assert data["cookies"][0]["domain"] == "nordnet.dk"
    assert "saved_at" in data


def test_save_sets_permissions(sm, mock_session):
    sm.save(mock_session)

    mode = os.stat(sm.session_path).st_mode
    assert mode & stat.S_IRUSR  # Owner read
    assert mode & stat.S_IWUSR  # Owner write
    assert not (mode & stat.S_IRGRP)  # No group read
    assert not (mode & stat.S_IROTH)  # No other read


def test_a_loose_mode_is_tightened_on_the_next_write(sm, mock_session):
    sm.save(mock_session)
    sm.session_path.chmod(0o644)
    sm.save(mock_session)
    assert stat.S_IMODE(sm.session_path.stat().st_mode) == 0o600


def test_save_sets_authenticated_at(sm, mock_session):
    assert sm.authenticated_at is None

    sm.save(mock_session)
    assert sm.authenticated_at is not None
    assert isinstance(sm.authenticated_at, datetime)


def test_load_restores_cookies_and_headers(sm, mock_session):
    mock_session.cookies.set("session_id", "xyz", domain="nordnet.dk", path="/")
    mock_session.headers["X-Custom"] = "test-val"
    sm.save(mock_session)

    fresh = requests.Session()
    result = sm.load(fresh)

    assert result is True
    assert fresh.cookies.get("session_id") == "xyz"
    assert fresh.headers.get("X-Custom") == "test-val"


def test_load_restores_authenticated_at(sm, mock_session):
    sm.save(mock_session)
    saved_at = sm.authenticated_at

    sm2 = SessionManager()
    sm2.load(requests.Session())
    assert sm2.authenticated_at is not None
    assert saved_at is not None
    # saved_at is written to the second, so compare at that resolution.
    assert sm2.authenticated_at == saved_at.replace(microsecond=0)


def test_load_missing_file(sm, mock_session):
    assert sm.load(mock_session) is False


def test_load_malformed_json(sm, mock_session):
    sm.session_path.parent.mkdir(parents=True, exist_ok=True)
    sm.session_path.write_text("not valid json {{{")
    assert sm.load(mock_session) is False


def test_forget_removes_the_file(sm, mock_session):
    sm.save(mock_session)
    assert sm.forget() is True
    assert not sm.session_path.exists()
    assert sm.authenticated_at is None
    # Nothing left to forget the second time.
    assert sm.forget() is False


# ── validate ──


@responses.activate
def test_validate_success(sm, mock_session):
    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        json=[{"accid": 1}],
        status=200,
    )
    assert sm.validate(mock_session) is True


@responses.activate
def test_validate_empty_list(sm, mock_session):
    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        json=[],
        status=200,
    )
    assert sm.validate(mock_session) is False


@responses.activate
def test_validate_error(sm, mock_session):
    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        body="Forbidden",
        status=403,
    )
    assert sm.validate(mock_session) is False


@responses.activate
def test_validate_survives_a_transport_error(sm, mock_session):
    """curl_cffi raises OSError subclasses, not requests exceptions.

    A session that cannot reach Nordnet is an invalid session, not a crash,
    and which of the two libraries raised is not the caller's problem.
    """
    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        body=OSError("connection reset"),
    )
    assert sm.validate(mock_session) is False


@responses.activate
def test_load_and_validate_success(sm, mock_session):
    mock_session.cookies.set("sid", "valid", domain="nordnet.dk", path="/")
    sm.save(mock_session)

    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        json=[{"accid": 1}],
        status=200,
    )

    fresh = requests.Session()
    assert sm.load_and_validate(fresh) is True


def test_load_and_validate_no_file(sm, mock_session):
    assert sm.load_and_validate(mock_session) is False


# ── session_seconds_remaining ──


def test_session_seconds_remaining_none(sm):
    assert sm.session_seconds_remaining is None


@freeze_time("2024-06-15 12:00:00")
def test_session_seconds_remaining_countdown(sm, mock_session):
    sm.save(mock_session)  # Sets authenticated_at to "now" (frozen)

    assert sm.session_seconds_remaining == 30 * 60  # Full 30 minutes


@freeze_time("2024-06-15 12:00:00")
def test_session_seconds_remaining_expired(sm):
    sm.authenticated_at = datetime(2024, 6, 15, 11, 0, 0)  # 1 hour ago

    assert sm.session_seconds_remaining == 0
