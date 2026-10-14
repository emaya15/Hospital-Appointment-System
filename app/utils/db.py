"""Small database helpers shared by the services."""

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.utils.exceptions import ConflictError

logger = logging.getLogger(__name__)


def commit_or_conflict(db: Session, message: str) -> None:
    """Commit; if a database constraint is violated, roll back and raise HTTP 409.

    The raw database error is logged (type only) but never sent to the client.
    """
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Integrity error on commit: %s", type(exc.orig).__name__)
        raise ConflictError(message) from exc
