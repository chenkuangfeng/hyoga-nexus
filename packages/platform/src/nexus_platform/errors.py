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


class InvalidConfiguration(PlatformError):
    code = "invalid_configuration"
    status_code = 422


class ServiceUnavailable(PlatformError):
    code = "service_unavailable"
    status_code = 503
