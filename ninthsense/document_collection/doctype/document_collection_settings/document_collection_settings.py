import frappe
from frappe import _
from frappe.model.document import Document

from ninthsense.document_collection.wiring import settings_problem


class DocumentCollectionSettings(Document):
	def validate(self):
		problem = settings_problem(self)
		if problem:
			frappe.throw(problem)
