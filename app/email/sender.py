import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import FROM_EMAIL, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

logger = logging.getLogger("app.email")


class EmailSender(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    """Records only delivery metadata when SMTP is not configured.

    Email bodies often contain one-time reset or verification tokens and must
    never be copied into logs. Tests use a dedicated fake sender to inspect
    messages without writing secrets to a process log.
    """

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("EMAIL queued to=%s subject=%r body=[REDACTED]", to, subject)


class SMTPEmailSender:
    def __init__(self, host: str, port: int, username: str, password: str, from_email: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.from_email
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.host, self.port) as server:
            server.starttls()
            if self.username and self.password:
                server.login(self.username, self.password)
            server.send_message(message)


def get_email_sender() -> EmailSender:
    if SMTP_HOST:
        return SMTPEmailSender(
            host=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            from_email=FROM_EMAIL,
        )
    return ConsoleEmailSender()
