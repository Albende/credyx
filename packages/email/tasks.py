"""Celery tasks for transactional emails.

Tasks are sync inside the worker (no asyncio required). Retries on
``smtplib.SMTPException`` with exponential backoff via Celery's built-in
``max_retries`` / ``default_retry_delay``.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from packages.email.templates import (
    render_password_reset,
    render_subscription_receipt,
    render_verify_email,
)
from packages.ingestion.celery_app import celery_app

logger = logging.getLogger(__name__)


def _send_email(to: str, subject: str, html: str, text: str) -> None:
    # Lazy import so the module is importable without a configured Settings env.
    from apps.api.app.config import get_settings

    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        if s.smtp_user and s.smtp_password:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


@celery_app.task(bind=True, max_retries=5, default_retry_delay=60)
def send_verification_email(self, to_email: str, first_name: str, verify_url: str) -> None:
    try:
        subject, html, text = render_verify_email(first_name, verify_url)
        _send_email(to_email, subject, html, text)
        logger.info("verification_email_sent to=%s", to_email)
    except smtplib.SMTPException as exc:
        logger.warning("verification_email_failed to=%s err=%s", to_email, exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=5, default_retry_delay=60)
def send_password_reset(self, to_email: str, first_name: str, reset_url: str) -> None:
    try:
        subject, html, text = render_password_reset(first_name, reset_url)
        _send_email(to_email, subject, html, text)
        logger.info("password_reset_sent to=%s", to_email)
    except smtplib.SMTPException as exc:
        logger.warning("password_reset_failed to=%s err=%s", to_email, exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3)
def send_subscription_receipt(
    self,
    to_email: str,
    first_name: str,
    invoice_url: str,
    amount_cents: int,
    currency: str,
) -> None:
    try:
        subject, html, text = render_subscription_receipt(
            first_name, invoice_url, amount_cents, currency
        )
        _send_email(to_email, subject, html, text)
        logger.info("receipt_sent to=%s", to_email)
    except smtplib.SMTPException as exc:
        logger.warning("receipt_failed to=%s err=%s", to_email, exc)
        raise self.retry(exc=exc)
