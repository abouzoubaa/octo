"""Digest/briefing email delivery: SMTP transport when configured + creator has an
address; log fallback otherwise (content never lost)."""
from cci_core.config import get_settings


class FakeSMTP:
    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, msg):
        FakeSMTP.sent.append({"to": msg["To"], "subject": msg["Subject"],
                              "body": msg.get_content()})


def test_send_email_unconfigured_returns_false():
    from cci_core.mailer import send_email

    assert get_settings().smtp_host == ""  # default: log transport
    assert send_email("a@b.c", "s", "b") is False


def test_send_email_via_smtp(monkeypatch):
    import smtplib

    from cci_core.mailer import send_email

    FakeSMTP.sent = []
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert send_email("alex@example.com", "Digest", "hello") is True
    assert FakeSMTP.sent[0]["to"] == "alex@example.com"
    assert FakeSMTP.sent[0]["subject"] == "Digest"


def test_send_digest_emails_creator_when_configured(seeded_creator, session, monkeypatch):
    import smtplib

    from cci_workers.digest import send_digest
    from cci_workers.radar import build_radar

    build_radar(seeded_creator.id, backlog=True)
    seeded_creator.email = "creator@example.com"
    session.commit()

    FakeSMTP.sent = []
    monkeypatch.setattr(get_settings(), "smtp_host", "smtp.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert send_digest(seeded_creator.id) is True
    assert FakeSMTP.sent and FakeSMTP.sent[0]["to"] == "creator@example.com"
    assert "Demand Radar" in FakeSMTP.sent[0]["body"]


def test_send_digest_falls_back_to_log_without_email(seeded_creator, session):
    from cci_workers.digest import send_digest
    from cci_workers.radar import build_radar

    build_radar(seeded_creator.id, backlog=True)
    session.commit()
    assert send_digest(seeded_creator.id) is True  # logged, not lost
