"""A named set of documents to ask for, and which document fills each Employee field (R24)."""

import frappe
from frappe import _
from frappe.model.document import Document

from ninthsense.core.field_catalogue import get_entry
from ninthsense.core.mapping_rules import mapping_problems

TEMPLATE = "Document Collection Template"
DOCUMENT_TYPE = "Employee Document Type"
ALLOWED_TYPES = ("pdf", "jpg", "jpeg", "png")


class DocumentCollectionTemplate(Document):
	def validate(self):
		self._validate_documents()
		self._validate_mapping()
		self._validate_default()

	def on_update(self):
		# The only default (FR-041), in one UPDATE: it locks the rows it clears, so two saves that
		# each make their template the default cannot both keep it. The others' checks are not
		# this save's.
		if self.is_default:
			frappe.db.set_value(TEMPLATE, {"is_default": 1, "name": ("!=", self.name)}, "is_default", 0)

	def on_trash(self):
		"""Deleting the default hands it to the oldest other enabled template (FR-041)."""
		if not self.is_default:
			return
		heir = frappe.get_all(
			TEMPLATE,
			filters={"is_enabled": 1, "name": ("!=", self.name)},
			order_by="creation asc",
			pluck="name",
			limit=1,
		)
		if heir:
			frappe.db.set_value(TEMPLATE, heir[0], "is_default", 1)

	# ------------------------------------------------------------------ documents

	def _validate_documents(self):
		if not self.documents:
			frappe.throw(_("Add at least one document."))
		seen = set()
		for row in self.documents:
			if row.document_type in seen:
				frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, row.document_type))
			seen.add(row.document_type)
			if row.document_type and not frappe.db.get_value(DOCUMENT_TYPE, row.document_type, "is_enabled"):
				frappe.throw(_("Row {0}: {1} is disabled.").format(row.idx, row.document_type))
			if row.allowed_file_types:
				kinds = [k.strip().lower() for k in row.allowed_file_types.split(",") if k.strip()]
				if not kinds or any(k not in ALLOWED_TYPES for k in kinds):
					frappe.throw(
						_("Row {0}: allowed file types must be from {1}.").format(
							row.idx, ", ".join(ALLOWED_TYPES)
						)
					)
			if row.max_file_size_mb and not 1 <= row.max_file_size_mb <= 10:
				frappe.throw(_("Row {0}: max file size must be between 1 and 10 MB.").format(row.idx))

	# -------------------------------------------------------------------- mapping

	def _validate_mapping(self):
		"""Every row checked against the catalogue and this template's documents (FR-042, FR-043)."""
		names = {row.document_type for row in self.documents if row.document_type}
		for row in self.field_mapping:
			names.update(n for n in (row.source_document, row.fallback_document) if n)
		code_of = (
			dict(
				frappe.get_all(
					DOCUMENT_TYPE,
					filters={"name": ("in", list(names))},
					fields=["name", "document_code"],
					as_list=True,
				)
			)
			if names
			else {}
		)

		# Stored as the catalogue spells it: the fill keys candidates that way (FR-022's guard).
		for row in self.field_mapping:
			entry = get_entry(row.field_key)
			if entry:
				row.field_key = entry.key

		template_codes = {
			code_of[row.document_type] for row in self.documents if row.document_type in code_of
		}
		rows = [
			(
				row.field_key,
				code_of.get(row.source_document, row.source_document),
				code_of.get(row.fallback_document, row.fallback_document) or None,
			)
			for row in self.field_mapping
		]
		problems = mapping_problems(
			rows, template_codes, labels={c: n for n, c in code_of.items()}, translate=_
		)
		if problems:
			frappe.throw(
				"<br>".join(frappe.utils.escape_html(p) for p in problems),
				title=_("The field mapping has problems"),
			)

	# -------------------------------------------------------------------- default

	def _validate_default(self):
		"""While any enabled template exists, exactly one enabled template is the default (FR-041).

		The default moves only by marking another template. A save that would leave no enabled
		default makes this template the default when it is enabled.
		"""
		was_default = not self.is_new() and frappe.db.get_value(TEMPLATE, self.name, "is_default")
		others = {"name": ("!=", self.name), "is_enabled": 1}
		other_enabled = frappe.db.exists(TEMPLATE, others)

		if not self.is_enabled:
			if self.is_default and not was_default:
				frappe.throw(_("A disabled template cannot be the default."))
			if self.is_default and other_enabled:
				frappe.throw(
					_("The default template cannot be disabled. Make another one the default first.")
				)
			# The last enabled template: with none enabled, there is no default to keep.
			self.is_default = 0
			return

		if was_default and not self.is_default and other_enabled:
			frappe.throw(_("There must be a default template. Make another one the default instead."))
		if not self.is_default and not frappe.db.exists(TEMPLATE, {**others, "is_default": 1}):
			self.is_default = 1
