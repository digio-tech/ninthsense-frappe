"""Employee Onboarding hooks (R18): cancelling or deleting it closes the request's link."""

from ninthsense.document_collection import service


def on_cancel(doc, method=None):
	service.cancel_for_onboarding(doc.name, deleted=False)


def on_trash(doc, method=None):
	# Runs before Frappe checks links, so clearing the request's link lets the delete through.
	service.cancel_for_onboarding(doc.name, deleted=True)
