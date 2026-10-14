"""Application exceptions.

Services raise these; a single handler in main.py turns them into JSON
responses. The status codes follow the project's error-code convention.
"""


class AppError(Exception):
    status_code = 400
    default_detail = "Invalid request"

    def __init__(self, detail: str | None = None, headers: dict | None = None):
        self.detail = detail or self.default_detail
        self.headers = headers
        super().__init__(self.detail)


class BadRequestError(AppError):
    """400 - the operation is not allowed by the business rules."""

    status_code = 400
    default_detail = "Invalid operation"


class UnauthorizedError(AppError):
    """401 - missing, invalid or expired credentials."""

    status_code = 401
    default_detail = "Authentication required"

    def __init__(self, detail: str | None = None):
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    """403 - authenticated but not allowed."""

    status_code = 403
    default_detail = "You do not have permission to perform this action"


class NotFoundError(AppError):
    """404 - resource does not exist."""

    status_code = 404
    default_detail = "Resource not found"


class ConflictError(AppError):
    """409 - duplicate resource or booking conflict."""

    status_code = 409
    default_detail = "Conflict with existing data"


class PayloadTooLargeError(AppError):
    """413 - uploaded file is too large."""

    status_code = 413
    default_detail = "File is too large"


class UnsupportedMediaTypeError(AppError):
    """415 - uploaded file type is not allowed."""

    status_code = 415
    default_detail = "Unsupported file type"
