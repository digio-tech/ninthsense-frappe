import re

import frappe
from frappe import _
from frappe.model.document import Document


class EmployeeDocumentType(Document):
	CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

	def validate(self):
		if not self.CODE.match(self.document_code or "") or self.document_code == "unfiled":
			frappe.throw(
				_(
					"Document Code must be lowercase letters, digits and underscores, starting with a letter, "
					"2 to 64 characters, and not 'unfiled'."
				)
			)
