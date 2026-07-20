"""Transactional email templates. Plain HTML strings with `{placeholder}` substitution.

Each ``render_*`` function returns ``(subject, html, text)``. Keep formatting
inline-only — many corporate mail clients strip `<style>` blocks.
"""
from __future__ import annotations


_BASE = """<!doctype html><html><body style="font-family:-apple-system,Segoe UI,sans-serif;background:#0f1218;color:#f4f4f5;padding:32px;margin:0;">
  <div style="max-width:520px;margin:0 auto;background:#16191f;border:1px solid #2a2e36;border-radius:12px;padding:32px;">
    <h1 style="color:#7d6bff;margin:0 0 16px;font-size:22px;font-weight:600;">{heading}</h1>
    <p style="line-height:1.6;color:#cdd1d9;margin:0 0 12px;">Hi {first_name},</p>
    {body}
    <p style="color:#8a8f9b;font-size:12px;margin-top:32px;border-top:1px solid #2a2e36;padding-top:16px;">CreditLens · B2B credit intelligence</p>
  </div>
</body></html>"""


def render_verify_email(first_name: str, verify_url: str) -> tuple[str, str, str]:
    body = (
        '<p style="line-height:1.6;color:#cdd1d9;">Click the button below to verify your email address. The link expires in 24 hours.</p>'
        f'<p style="margin:24px 0;"><a href="{verify_url}" style="display:inline-block;background:#7d6bff;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">Verify email</a></p>'
        f'<p style="color:#8a8f9b;font-size:13px;line-height:1.5;">Or paste this link: <span style="color:#cdd1d9;word-break:break-all;">{verify_url}</span></p>'
    )
    subject = "Verify your CreditLens account"
    html = _BASE.format(heading="Verify your CreditLens account", first_name=first_name, body=body)
    text = (
        f"Hi {first_name},\n\n"
        f"Verify your email: {verify_url}\n\n"
        "Link expires in 24 hours.\n"
    )
    return subject, html, text


def render_password_reset(first_name: str, reset_url: str) -> tuple[str, str, str]:
    body = (
        '<p style="line-height:1.6;color:#cdd1d9;">We received a request to reset your password. The link below expires in 1 hour. If you didn\'t request this, you can ignore this email.</p>'
        f'<p style="margin:24px 0;"><a href="{reset_url}" style="display:inline-block;background:#7d6bff;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">Reset password</a></p>'
        f'<p style="color:#8a8f9b;font-size:13px;line-height:1.5;">Or paste this link: <span style="color:#cdd1d9;word-break:break-all;">{reset_url}</span></p>'
    )
    subject = "Reset your CreditLens password"
    html = _BASE.format(heading="Reset your password", first_name=first_name, body=body)
    text = (
        f"Hi {first_name},\n\n"
        f"Reset your password: {reset_url}\n\n"
        "Link expires in 1 hour. Ignore this email if you didn't request a reset.\n"
    )
    return subject, html, text


def render_subscription_receipt(
    first_name: str, invoice_url: str, amount_cents: int, currency: str
) -> tuple[str, str, str]:
    amount = f"{amount_cents / 100:.2f} {currency.upper()}"
    body = (
        f'<p style="line-height:1.6;color:#cdd1d9;">Thanks for subscribing to CreditLens. Your payment of <strong style="color:#fff;">{amount}</strong> has been processed.</p>'
        f'<p style="margin:24px 0;"><a href="{invoice_url}" style="display:inline-block;background:#7d6bff;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">View invoice</a></p>'
    )
    subject = "Your CreditLens receipt"
    html = _BASE.format(heading="Payment received", first_name=first_name, body=body)
    text = (
        f"Hi {first_name},\n\n"
        f"Thanks for subscribing to CreditLens. Your payment of {amount} has been processed.\n\n"
        f"Invoice: {invoice_url}\n"
    )
    return subject, html, text
