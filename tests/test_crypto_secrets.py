"""At-rest token encryption + production-secret guard."""
import importlib

from cci_core import crypto
from cci_core.config import Settings


def _with_key(monkeypatch, key: str | None):
    monkeypatch.setenv("CCI_ENCRYPTION_KEY", key or "")
    # crypto reads settings via a cached getter + its own lru_cache
    from cci_core import config as cfg

    cfg.get_settings.cache_clear()
    crypto._fernet.cache_clear()


def test_passthrough_without_key(monkeypatch):
    _with_key(monkeypatch, None)
    assert crypto.encrypt("token") == "token"  # no key → plaintext passthrough
    assert crypto.decrypt("token") == "token"


def test_roundtrip_with_key(monkeypatch):
    from cryptography.fernet import Fernet

    _with_key(monkeypatch, Fernet.generate_key().decode())
    ct = crypto.encrypt("super-secret-oauth-token")
    assert ct.startswith("enc:v1:") and "super-secret" not in ct
    assert crypto.decrypt(ct) == "super-secret-oauth-token"
    # decrypting plaintext (written before a key existed) passes through
    assert crypto.decrypt("legacy-plaintext") == "legacy-plaintext"
    _with_key(monkeypatch, None)  # reset cache for other tests


def test_production_secret_guard():
    insecure = Settings(admin_token="change-me", encryption_key="",
                        ig_webhook_verify_token="change-me-too")
    problems = insecure.assert_production_secrets()
    assert len(problems) == 3

    secure = Settings(admin_token="a-strong-random-secret",
                      encryption_key="x" * 44, ig_webhook_verify_token="another-secret")
    assert secure.assert_production_secrets() == []


def test_oauth_token_encrypted_at_rest(seeded_creator, session, monkeypatch):
    """The token column stores ciphertext but reads back plaintext."""
    from cryptography.fernet import Fernet
    from sqlalchemy import text

    _with_key(monkeypatch, Fernet.generate_key().decode())
    from cci_core.models import OAuthToken

    tok = OAuthToken(creator_id=seeded_creator.id, platform="instagram",
                     access_token="plaintext-access-token")
    session.add(tok)
    session.commit()

    # raw DB value is ciphertext...
    raw = session.execute(
        text("SELECT access_token FROM oauth_tokens WHERE id = :i"), {"i": tok.id}
    ).scalar()
    assert raw.startswith("enc:v1:") and "plaintext" not in raw
    # ...but the ORM gives plaintext back
    session.expire(tok)
    assert tok.access_token == "plaintext-access-token"
    _with_key(monkeypatch, None)


importlib  # noqa: B018 — kept for parity with other test modules' imports
