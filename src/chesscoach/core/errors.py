"""Domain errors raised by services and mapped to HTTP responses in the API layer."""


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(DomainError):
    status_code = 422
    code = "validation_failed"


class PayloadTooLargeError(DomainError):
    status_code = 413
    code = "payload_too_large"
