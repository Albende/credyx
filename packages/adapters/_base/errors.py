class AdapterError(Exception):
    """Base for any adapter-level error."""


class AdapterNotImplementedError(AdapterError):
    """Raised when an adapter is a stub. Endpoint should return 501."""


class InvalidIdentifierError(AdapterError):
    """Identifier did not match expected format for this country."""


class BlockedByRegistryError(AdapterError):
    """Registry returned a CAPTCHA, paywall, or hard block."""


class RateLimitError(AdapterError):
    """Hit a registry rate limit. Caller should back off."""
