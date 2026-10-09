import frappe
from frappe import _
from frappe.model.document import Document

# Written by the app's services only (data-model). Read-only in the form; refused here for any
# other write, the REST API included. The child tables are read-only in the form.
SERVICE_FIELDS = (
	"status",
	"template",
	"employee_onboarding",
	"job_applicant",
	"company",
	"candidate_name",
	"candidate_email",
	"link_code_hash",
	"link_ref",
	"link_delivered_on",
	"replaced_verification_document_ids",
	"verification_response",
	"link_sent_on",
	"link_expires_on",
	"link_emailed",
	"documents_received_on",
	"verification_case_id",
	"verification_result",
	"extraction_error",
	"employee",
	"last_fill_on",
)


class DocumentCollectionRequest(Document):
	def validate(self):
		if self.is_new() or self.flags.via_service:
			return
		if self.has_value_changed("status"):
			frappe.throw(_("Status cannot be changed by hand."))
		changed = [f for f in SERVICE_FIELDS if self.has_value_changed(f)]
		if changed:
			frappe.throw(_("{0} cannot be changed by hand.").format(_(self.meta.get_label(changed[0]))))
