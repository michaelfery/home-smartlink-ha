"""Exceptions raised by the Home-SmartLink client."""

from __future__ import annotations


class HomeSmartLinkError(Exception):
    """Base class for every error raised by this package."""


class AuthenticationError(HomeSmartLinkError):
    """Credentials were rejected, or the session could not be renewed."""


class CannotConnectError(HomeSmartLinkError):
    """The cloud could not be reached or answered with a server error."""


class RateLimitError(HomeSmartLinkError):
    """The cloud asked us to slow down (HTTP 429)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UnsupportedCommandError(HomeSmartLinkError):
    """The requested state cannot be encoded safely (outside observed behavior)."""


class CommandFailedError(HomeSmartLinkError):
    """The cloud accepted the request but did not report success."""
