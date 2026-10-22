class NamingError(Exception):
    """Base class for every error the naming engine raises."""


class TemplateError(NamingError):
    """A template does not match the whitelist grammar."""


class MissingToken(NamingError):
    """A token resolved to None or an empty string."""

    def __init__(self, token):
        self.token = token
        super().__init__(f"Token {{{token}}} has no value in this context")


class NumbersExhausted(NamingError):
    """The next number needs more digits than the template's #-run has."""


class TooLong(NamingError):
    """A rendered value exceeds the length of its target field."""


class InvalidTail(NamingError):
    """A tail contains disallowed characters or exceeds tail_max_length."""


class Conflict(NamingError):
    """A rendered value is already taken in its uniqueness domain."""
