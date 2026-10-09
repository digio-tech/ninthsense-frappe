"""The invitation email (R13), carried over from the old app's links.py."""

import inspect

import frappe
from frappe import _
from frappe.utils import formatdate

from ninthsense.core.config import LINK_VALIDITY_DAYS
from ninthsense.core.invite_email import build_invite_context
from ninthsense.document_collection.log import log_event, log_failure

EMAIL_TEMPLATE = "Document Request Link"


def has_outgoing_email_account() -> bool:
	return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}))


def _queue_sent(queue) -> bool:
	"""Whether the Email Queue row Frappe just built actually went out.

	Read after `queue.send()` has run, so the row carries the outcome. Only `Sent`
	counts: `send()` returns quietly without sending when the queue is suspended or
	mail is muted, and that leaves `Not Sent` -- a retry that might happen later is
	not something to tell HR happened now.
	"""
	name = getattr(queue, "name", None)
	if not name:
		return False

	# Committed by the send context before it returns, so this reads the outcome
	# rather than the status the row was created with.
	return frappe.db.get_value("Email Queue", name, "status") == "Sent"


def send_link_email(doc, link: str, job_title: str | None = None) -> bool:
	"""Send the invite for a Document Collection Request. Returns whether it actually went out.

	`job_title` is the Employee Onboarding's designation; the request does not carry one.
	"""
	sent = _send(doc, link, job_title)
	log_event("link_email", request=doc.name, outcome="sent" if sent else "not_sent")
	return sent


def _send(doc, link: str, job_title: str | None) -> bool:
	"""Frappe swallows outgoing-mail errors, so failure has to be detected rather than
	assumed away -- otherwise HR believes a candidate was emailed when they were not.

	The link goes out as plain text. It must never sit behind a click tracker or a
	shortener: the code in it is the candidate's only identity, and a redirector would
	hand it to a third party.
	"""
	if not has_outgoing_email_account():
		return False

	# link_expires_on is set by the caller one step before this, so the date the
	# candidate is told is the date the portal will actually enforce. Formatted
	# here rather than in the template: it is a datetime in the database, and a
	# candidate should read a date, not a timestamp.
	context = build_invite_context(
		candidate_name=doc.candidate_name,
		company=doc.company,
		job_title=job_title,
		document_count=sum(1 for row in doc.requested_documents if row.is_requested),
		link=link,
		expires_on=formatdate(doc.link_expires_on) if doc.link_expires_on else "",
		valid_days=LINK_VALIDITY_DAYS,
	)

	queue = None
	try:
		if frappe.db.exists("Email Template", EMAIL_TEMPLATE):
			# Rendered through Email Template's own methods, as Frappe renders any Email
			# Template. Its text is written by a System Manager (the only role that can
			# edit one, and Frappe checks the Jinja when it is saved); everything about
			# the candidate goes in as data in `doc`, never as template text. The body
			# is the HTML or the rich-text field, whichever the template's Use HTML picks.
			template = frappe.get_doc("Email Template", EMAIL_TEMPLATE)
			subject = template.get_formatted_subject({"doc": context})
			message = template.get_formatted_response({"doc": context}) or ""
		else:
			# Only reachable if the seeded template was deleted. Deliberately plain:
			# a fallback that tries to reproduce the template is a second body to
			# keep in step with the first, and this one exists to not lose the link.
			subject = _("Complete your onboarding for {0}").format(doc.company)
			message = _("Upload your documents here: {0}").format(link)

		# Deliberately not `now=True`. That flag does not send inline -- it does
		# `frappe.db.after_commit.add(q.send)` (frappe/email/__init__.py), so the
		# SMTP work runs during request teardown, long after this function has
		# returned. A mailbox that rejects the login then raises from inside
		# `frappe.db.commit()`, outside every try/except here and outside Frappe's
		# own error handling: the response HR was about to receive is replaced by a
		# bare 500. The link is minted and the reply that carried it is discarded,
		# which is the one failure HR cannot work around.
		#
		# Building the row and sending it here keeps the failure inside the block
		# below, where it becomes `email_sent: False` and a link on screen.
		queue = frappe.sendmail(
			recipients=[doc.candidate_email],
			subject=subject,
			message=message,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
			now=False,
			**_redact_after_send(),
		)
		if not queue:
			return False

		queue.send()
		if _queue_sent(queue):
			return True
		_stop(queue)
		return False
	except frappe.OutgoingEmailError:
		_stop(queue)
		frappe.clear_messages()
		return False
	except Exception:
		_stop(queue)
		# By id and category only: an SMTP error can quote the recipient address.
		log_failure("Document request link email failed", "email", request=doc.name)
		# The SMTP layer reports a rejected login with frappe.throw, which leaves the
		# message queued for the client even though it was caught here. Left in place
		# it arrives as a second red modal stacked over the dialog showing the link,
		# telling HR the thing failed while the thing they need is underneath it.
		# The failure is already carried back as `email_sent: False`.
		frappe.clear_messages()
		return False


def _redact_after_send() -> dict:
	"""The queued message holds the live code. Frappe drops the body once sent, where the
	installed version supports it (FR-003)."""
	from frappe.email import sendmail

	if "redact_message_after_send" in inspect.signature(sendmail).parameters:
		return {"redact_message_after_send": True}
	return {}


def _stop(queue):
	"""An invite that did not go out now is never retried later: by then HR may have resent it,
	and the candidate would get a dead link. HR has the link on screen instead.

	Error is the queue's one status the scheduler does not retry. The body goes too, since the
	link in it stays live.
	"""
	name = getattr(queue, "name", None)
	if not isinstance(name, str) or not frappe.db.exists("Email Queue", name):
		return
	try:
		frappe.db.set_value("Email Queue", name, "status", "Error", update_modified=False)
		row = frappe.get_doc("Email Queue", name)
		if hasattr(row, "redact_message"):
			row.redact_message()
	except Exception:
		log_failure("Document request link email could not be stopped", "email")
