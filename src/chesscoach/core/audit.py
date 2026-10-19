"""Audit trail helper. Callers commit; details must not contain PGN content or secrets."""

import uuid

from sqlalchemy.orm import Session

from chesscoach.db.models import AuditEvent


def record_audit(
    db: Session,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details or {},
        )
    )
