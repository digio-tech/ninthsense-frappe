"""Document Collection Settings: the one place they are read (R21)."""

import re
from urllib.parse import urlsplit

import frappe
from frappe import _

from ninthsense.core.reasons import OnboardingError

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_SECRET_LENGTH = 32


def _origin_problem(url: str) -> str | None:
	try:
		parts = urlsplit(url)
		host = parts.hostname
	except ValueError:
		return _("Portal URL must be an absolute http(s) address with no path, query or fragment")
	if (
		parts.scheme not in ("http", "https")
		or not host
		or parts.path not in ("", "/")
		or parts.query
		or parts.fragment
	):
		return _("Portal URL must be an absolute http(s) address with no path, query or fragment")
	if parts.scheme == "http" and host != "localhost" and not host.endswith(".localhost"):
		return _("Portal URL must use https unless the host is localhost")
	return None


def settings_problem(settings) -> str | None:
	"""The first problem with the Settings, translated, or None."""
	url = (settings.portal_url or "").strip()
	if not url:
		return _("Portal URL is empty")
	problem = _origin_problem(url)
	if problem:
		return problem
	secret = settings.get_password("callback_secret", raise_exception=False) or ""
	if len(secret) < MIN_SECRET_LENGTH:
		return _("Callback Secret must be at least {0} characters").format(MIN_SECRET_LENGTH)
	support = (settings.support_email or "").strip()
	if support and not EMAIL.match(support):
		return _("Support Email is not a valid email address")
	return None


def load_config() -> dict:
	settings = frappe.get_single("Document Collection Settings")
	problem = settings_problem(settings)
	if problem:
		raise OnboardingError("not_configured", problem, {"setting": problem})
	return {
		"portal_url": settings.portal_url.strip().rstrip("/"),
		"callback_secret": settings.get_password("callback_secret"),
		"support_email": (settings.support_email or "").strip(),
		"portal_accent_color": settings.portal_accent_color or "",
	}
