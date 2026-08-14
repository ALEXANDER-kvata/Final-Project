"""Development-grade email delivery for share links.

With ``SMTP_HOST`` set (MailHog in docker compose) the message is delivered over
SMTP; otherwise the link is logged so local development needs no mail server at
all. Delivery never fails the request — the caller also gets the link back.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Literal

from app.core.config import settings

logger = logging.getLogger(__name__)

DeliveryMode = Literal["smtp", "logged"]

SMTP_TIMEOUT_SECONDS = 10


def _build_message(recipient: str, project_name: str, invite_url: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = f"You have been invited to the project '{project_name}'"
    message.set_content(
        f"You have been invited to collaborate on '{project_name}'.\n\n"
        f"Open this link while signed in to accept:\n{invite_url}\n\n"
        f"The link expires in {settings.invite_token_expire_minutes} minutes.\n"
    )
    return message


def _send_over_smtp(message: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
        smtp.send_message(message)


async def send_invite_email(recipient: str, project_name: str, invite_url: str) -> DeliveryMode:
    if not settings.smtp_host:
        logger.info("Invite link for %s: %s", recipient, invite_url)
        return "logged"

    message = _build_message(recipient, project_name, invite_url)
    try:
        # smtplib is blocking, so keep it off the event loop.
        await asyncio.to_thread(_send_over_smtp, message)
    except (OSError, smtplib.SMTPException):
        logger.warning(
            "SMTP delivery to %s failed; invite link: %s", recipient, invite_url, exc_info=True
        )
        return "logged"

    return "smtp"
