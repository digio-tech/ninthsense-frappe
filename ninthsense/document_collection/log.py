"""The only logging module (R22). Everything goes through `clean_fields`."""

import logging
import re

import frappe
from frappe.utils import get_bench_path

from ninthsense.core.log_fields import clean_fields, exception_site

REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def portal_request_id() -> str | None:
	"""The portal's id for the request that called us, if it sent a well-formed one."""
	value = frappe.get_request_header("X-Request-Id") if getattr(frappe.local, "request", None) else None
	return value if value and REQUEST_ID.match(value) else None


def _logger() -> logging.Logger:
	"""The app's logger, at INFO.

	frappe.logger() creates it at WARNING (dev) or ERROR (production), which would drop
	every event below.
	"""
	logger = frappe.logger("ninthsense")
	if logger.level > logging.INFO or logger.level == logging.NOTSET:
		logger.setLevel(logging.INFO)
	return logger


def log_event(event: str, **fields):
	_logger().info({"event": event, **clean_fields(fields)})


def log_failure(title: str, category: str, exc: BaseException | None = None, **ids):
	"""Error Log entry whose title carries the portal's request id, so the two logs join.

	By keyword, deliberately: frappe.log_error(title, message) swaps two positional strings
	when the first holds a newline, so a single-line message would land in the title slot.
	Passing a message also keeps Frappe from storing the traceback with its locals, so `exc`
	adds only its type and innermost file and line.
	"""
	request_id = portal_request_id()
	suffix = f" [{request_id}]" if request_id else ""
	if exc is not None:
		ids["exception"] = exception_site(exc, get_bench_path())
	pairs = " ".join(f"{k}={v}" for k, v in clean_fields(ids).items())
	# Error Log copies the form dict into its metadata, and a portal delivery carries the
	# candidate's whole payload there. Only the method name is let through.
	form_dict = getattr(frappe.local, "form_dict", None)
	frappe.local.form_dict = frappe._dict(cmd=form_dict.get("cmd")) if form_dict else frappe._dict()
	try:
		frappe.log_error(title=f"{title}{suffix}", message=f"category={category} {pairs}".strip())
	finally:
		frappe.local.form_dict = form_dict
