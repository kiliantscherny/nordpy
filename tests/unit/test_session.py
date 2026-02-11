"""Tests for nordpy.session — save/load/validate, expiry calculation."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime

import responses
from freezegun import freeze_time

from nordpy.session import SessionManager


@responses.activate
def test_save_writes_json(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)

    mock_session.cookies.set("JSESSIONID", "abc123")
    sm.save(mock_session)

    assert path.exists()
    data = json.loads(path.read_text())
    assert data["cookies"]["JSESSIONID"] == "abc123"
    assert "saved_at" in data


def test_save_sets_permissions(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)
    sm.save(mock_session)

    mode = os.stat(path).st_mode
    assert mode & stat.S_IRUSR  # Owner read
    assert mode & stat.S_IWUSR  # Owner write
    assert not (mode & stat.S_IRGRP)  # No group read
    assert not (mode & stat.S_IROTH)  # No other read


def test_save_sets_authenticated_at(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)
    assert sm.authenticated_at is None

    sm.save(mock_session)
    assert sm.authenticated_at is not None
    assert isinstance(sm.authenticated_at, datetime)


def test_load_restores_cookies_and_headers(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)

    # Save with some data
    mock_session.cookies.set("session_id", "xyz")
    mock_session.headers["X-Custom"] = "test-val"
    sm.save(mock_session)

    # Load into a fresh session
    import requests

    fresh = requests.Session()
    result = sm.load(fresh)

    assert result is True
    assert fresh.cookies.get("session_id") == "xyz"
    assert fresh.headers.get("X-Custom") == "test-val"


def test_load_restores_authenticated_at(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)
    sm.save(mock_session)
    saved_at = sm.authenticated_at

    # Fresh manager loads and restores authenticated_at
    import requests

    sm2 = SessionManager(session_path=path)
    sm2.load(requests.Session())
    assert sm2.authenticated_at is not None
    assert sm2.authenticated_at.isoformat() == saved_at.isoformat()


def test_load_missing_file(tmp_path, mock_session):
    path = tmp_path / "nonexistent.json"
    sm = SessionManager(session_path=path)
    result = sm.load(mock_session)
    assert result is False


def test_load_malformed_json(tmp_path, mock_session):
    path = tmp_path / "bad.json"
    path.write_text("not valid json {{{")
    sm = SessionManager(session_path=path)
    result = sm.load(mock_session)
    assert result is False


@responses.activate
def test_validate_success(mock_session):
    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        json=[{"accid": 1}],
        status=200,
    )
    sm = SessionManager()
    assert sm.validate(mock_session) is True


@responses.activate
def test_validate_empty_list(mock_session):
    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        json=[],
        status=200,
    )
    sm = SessionManager()
    assert sm.validate(mock_session) is False


@responses.activate
def test_validate_error(mock_session):
    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        body="Forbidden",
        status=403,
    )
    sm = SessionManager()
    assert sm.validate(mock_session) is False


@responses.activate
def test_load_and_validate_success(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)
    mock_session.cookies.set("sid", "valid")
    sm.save(mock_session)

    responses.add(
        responses.GET,
        "https://www.nordnet.dk/api/2/accounts",
        json=[{"accid": 1}],
        status=200,
    )

    import requests

    fresh = requests.Session()
    result = sm.load_and_validate(fresh)
    assert result is True


def test_load_and_validate_no_file(tmp_path, mock_session):
    path = tmp_path / "missing.json"
    sm = SessionManager(session_path=path)
    result = sm.load_and_validate(mock_session)
    assert result is False


# ── session_seconds_remaining ──


def test_session_seconds_remaining_none():
    sm = SessionManager()
    assert sm.session_seconds_remaining is None


@freeze_time("2024-06-15 12:00:00")
def test_session_seconds_remaining_countdown(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)
    sm.save(mock_session)  # Sets authenticated_at to "now" (frozen)

    remaining = sm.session_seconds_remaining
    assert remaining == 30 * 60  # Full 30 minutes


@freeze_time("2024-06-15 12:00:00")
def test_session_seconds_remaining_expired(tmp_path, mock_session):
    path = tmp_path / "session.json"
    sm = SessionManager(session_path=path)
    sm.authenticated_at = datetime(2024, 6, 15, 11, 0, 0)  # 1 hour ago

    remaining = sm.session_seconds_remaining
    assert remaining == 0
