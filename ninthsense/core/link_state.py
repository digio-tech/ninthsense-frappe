"""What the portal is told about a link (R10, data-model "Link state"). Frappe-free."""

from datetime import datetime

OPEN = "open"
SUBMITTED = "submitted"
EXPIRED = "expired"
REVOKED = "revoked"


def link_state(
	status: str | None,
	link_delivered_on: datetime | None,
	link_expires_on: datetime | None,
	now: datetime,
) -> str:
	"""Cancelled beats delivered, delivered beats expired."""
	if status == "Cancelled":
		return REVOKED
	if status == "Completed" or link_delivered_on:
		return SUBMITTED
	if link_expires_on and now > link_expires_on:
		return EXPIRED
	return OPEN
