class PlatformError(Exception):
    code = "platform_error"
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)


class NotFound(PlatformError):
    code = "not_found"
    status_code = 404


class Forbidden(PlatformError):
    code = "forbidden"
    status_code = 403


class Conflict(PlatformError):
    code = "conflict"
    status_code = 409


class SessionQueueFull(Conflict):
    """The session already holds the maximum number of queued Runs."""
    code = "session_queue_full"


class InvalidConfiguration(PlatformError):
    code = "invalid_configuration"
    status_code = 422


class ServiceUnavailable(PlatformError):
    code = "service_unavailable"
    status_code = 503


class Unauthenticated(PlatformError):
    """No valid login session or the session expired; the client must sign in again."""

    code = "unauthorized"
    status_code = 401
