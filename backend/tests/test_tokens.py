"""Tests for murdoku.server.tokens: Fernet wrapper, secret resolution."""

import pytest

from murdoku.server import tokens


@pytest.fixture(autouse=True)
def _secret_env(monkeypatch):
    """Deterministic env: real secret, dev mode off (each test may override)."""
    monkeypatch.setenv(tokens.SECRET_ENV, "unit-test-secret")
    monkeypatch.delenv(tokens.DEV_ENV, raising=False)
    monkeypatch.setattr(tokens, "_dev_key", None)


def test_roundtrip():
    payload = {"game_id": "abc123", "solution": {"victim": [1, 2]}}
    token = tokens.make_token(payload)
    assert isinstance(token, str)
    assert tokens.read_token(token) == payload


def test_token_hides_payload():
    token = tokens.make_token({"solution": {"victim": [1, 2]}})
    assert "victim" not in token


def test_tampered_token_rejected():
    token = tokens.make_token({"x": 1})
    bad = token[:-8] + "AAAAAAAA"
    with pytest.raises(tokens.InvalidToken):
        tokens.read_token(bad)


def test_truncated_token_rejected():
    token = tokens.make_token({"x": 1})
    with pytest.raises(tokens.InvalidToken):
        tokens.read_token(token[: len(token) // 2])


def test_garbage_token_rejected():
    with pytest.raises(tokens.InvalidToken):
        tokens.read_token("not-a-fernet-token")


def test_other_secret_rejected(monkeypatch):
    token = tokens.make_token({"x": 1})
    monkeypatch.setenv(tokens.SECRET_ENV, "a-different-secret")
    with pytest.raises(tokens.InvalidToken):
        tokens.read_token(token)


def test_non_json_payload_rejected():
    """A token decrypting to a non-object payload is InvalidToken."""
    fernet = tokens.get_fernet()
    token = fernet.encrypt(b"[1, 2, 3]").decode()
    with pytest.raises(tokens.InvalidToken):
        tokens.read_token(token)


def test_missing_secret_error(monkeypatch):
    monkeypatch.delenv(tokens.SECRET_ENV, raising=False)
    with pytest.raises(tokens.MissingSecretError, match="MURDOKU_SECRET"):
        tokens.make_token({"x": 1})


@pytest.mark.parametrize("dev_value", ["0", "", "yes", "2"])
def test_missing_secret_dev_off_values(dev_value, monkeypatch):
    monkeypatch.delenv(tokens.SECRET_ENV, raising=False)
    monkeypatch.setenv(tokens.DEV_ENV, dev_value)
    with pytest.raises(tokens.MissingSecretError):
        tokens.read_token("whatever")


def test_dev_mode_random_key_and_warning(monkeypatch, capsys):
    monkeypatch.delenv(tokens.SECRET_ENV, raising=False)
    monkeypatch.setenv(tokens.DEV_ENV, "1")

    payload = {"x": 1}
    token = tokens.make_token(payload)
    err = capsys.readouterr().err
    assert "MURDOKU_SECRET" in err and "MURDOKU_DEV" in err

    # Same key for the whole process: token still readable, no new warning.
    assert tokens.read_token(token) == payload
    assert capsys.readouterr().err == ""


def test_dev_key_differs_from_secret_key(monkeypatch):
    monkeypatch.setenv(tokens.SECRET_ENV, "unit-test-secret")
    with_secret = tokens.make_token({"x": 1})
    monkeypatch.delenv(tokens.SECRET_ENV, raising=False)
    monkeypatch.setenv(tokens.DEV_ENV, "1")
    with pytest.raises(tokens.InvalidToken):
        tokens.read_token(with_secret)


def test_get_fernet_returns_working_fernet():
    fernet = tokens.get_fernet()
    token = fernet.encrypt(b"{}").decode()
    assert tokens.read_token(token) == {}
