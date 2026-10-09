"""The two edge decorators. No endpoint body repeats the role, Settings or error handling."""

import functools
import time

import frappe
from frappe import _

from ninthsense.core.config import HR_ROLES
from ninthsense.core.reasons import OnboardingError, guest_answer, hr_text
from ninthsense.document_collection import wiring
from ninthsense.document_collection.log import log_event, log_failure, portal_request_id

# The refusals. Each is also a SecurityException, which Frappe never snapshots into Error Log
# (v16 excludes the class; develop reads its `skip_error_log`). That snapshot is written for every
# exception on a developer-mode site, and would store the request and the traceback's locals with
# the candidate's payload in them (FR-032). `portal_guest` logs what matters itself.


class PortalUnauthorized(frappe.AuthenticationError, frappe.SecurityException):
	http_status_code = 401


class PortalBadRequest(frappe.ValidationError, frappe.SecurityException):
	http_status_code = 400


class PortalNotFound(frappe.PermissionError, frappe.SecurityException):
	"""The generic refusal, answered 404 as the contract says (a PermissionError is a 403)."""

	http_status_code = 404


class PortalRejected(frappe.ValidationError, frappe.SecurityException):
	"""A candidate-safe 417."""

	http_status_code = 417


_GUEST_EXCEPTIONS = {
	401: PortalUnauthorized,
	400: PortalBadRequest,
	404: PortalNotFound,
	417: PortalRejected,
}


def _require_hr():
	if not set(HR_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only HR users can do this."), frappe.PermissionError)


def hr_read(fn):
	"""Refuse non-HR users. For reads that must work while the Settings are incomplete."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		_require_hr()
		return fn(*args, **kwargs)

	return wrapper


def hr_action(fn):
	"""Refuse non-HR users, load the Settings, and hand them to the body as `config`."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		_require_hr()
		try:
			config = wiring.load_config()
			return fn(*args, config=config, **kwargs)
		except OnboardingError as exc:
			frappe.throw(hr_text(exc.code, translate=_, **exc.context))

	return wrapper


# Set by service.resolve_link, so a failure after it can be logged with the request's name.
REQUEST_FLAG = "ninthsense_request"

# Refusals that point at the portal or an attacker get an Error Log. A bad, expired or used
# code and the candidate's own 417 mistakes are only counted in the event log, by category.
_ERROR_LOGGED = ("signature", "stale_ref", "schema")
# Our own drift, answered like a bad code but logged.
_ERROR_LOGGED_CATEGORIES = ("descriptor_schema",)


def _refusal_title(fn_name: str, exc: OnboardingError, category: str) -> str:
	if exc.code == "signature":
		return f"Document collection portal: CALLBACK SIGNATURE REJECTED ({category})"
	return f"Document collection portal: {fn_name}"


def _forget_request_input():
	"""Leave only the method name in the form dict, for whatever logs the refusal after us."""
	form_dict = getattr(frappe.local, "form_dict", None)
	frappe.local.form_dict = frappe._dict(cmd=form_dict.get("cmd")) if form_dict else frappe._dict()


def portal_guest(fn):
	"""Turn every failure into the portal's answer, logging the real cause first.

	OnboardingError is its own class (not frappe.AuthenticationError) because that is a bare
	Exception here and would be swallowed by the catch-all below and answered with the generic
	404 -- the one answer a signature failure must not share.

	Frappe's own errors (a timestamp clash, a value too long, a missing record) are logged and
	answered generically; their text is not the portal's to show.

	A refusal is raised after the `except` blocks, with the call's arguments dropped and only the
	method name left in the form dict, so nothing that records the exception can reach the
	payload through it: no chained context, no locals holding it.

	Every call, refused or not, leaves one `portal_call` event with its timing.
	"""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		started = time.monotonic()
		frappe.flags[REQUEST_FLAG] = None
		outcome, category, code = "ok", None, None
		try:
			return fn(*args, **kwargs)
		except OnboardingError as exc:
			frappe.db.rollback()
			outcome, category, code = "refused", exc.context.get("category") or exc.code, exc.code
			if exc.code in _ERROR_LOGGED or category in _ERROR_LOGGED_CATEGORIES:
				log_failure(
					_refusal_title(fn.__name__, exc, category),
					category,
					request=frappe.flags.get(REQUEST_FLAG),
					pointer=exc.context.get("pointer"),
				)
		except Exception as exc:
			frappe.db.rollback()
			outcome, category, code = "error", "unexpected", "link_invalid"
			log_failure(
				f"Document collection portal: {fn.__name__}",
				"unexpected",
				exc=exc,
				request=frappe.flags.get(REQUEST_FLAG),
			)
		finally:
			log_event(
				"portal_call",
				op=fn.__name__,
				outcome=outcome,
				category=category,
				duration_ms=int((time.monotonic() - started) * 1000),
				portal_request_id=portal_request_id(),
				request=frappe.flags.get(REQUEST_FLAG),
			)

		# Only a refusal gets here. Outside the except blocks, the raise has no chained context.
		# Dropped: a traceback printed with its locals would show them.
		args = kwargs = None
		_forget_request_input()
		frappe.clear_messages()
		status, message = guest_answer(code)
		frappe.local.response["http_status_code"] = status
		frappe.throw(_(message), _GUEST_EXCEPTIONS[status])

	return wrapper
