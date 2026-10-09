// Document Collection Template: the place document requirements and field mapping are authored.
//
// The mapping is a fixed list of fields (core/field_catalogue.py), grouped by section, each
// with a Source and a Fallback dropdown. A field is listed only when one of this
// template's documents can supply it, and each dropdown offers only those documents. The
// server never offers a previous employer's offer letter or pay slip for the new job's terms
// (core/mapping_rules.py), and the template's validate re-checks every row on save.
// The catalogue decides everything else about a field -- its target, child row,
// shaping and where the value sits in 9thSense's answer -- so a row stores the field,
// its source and its fallback, and nothing more.
//
// Choices are written into the hidden `field_mapping` table through the normal
// dirty/save cycle. Create Employee reads the request's template mapping as it stands then.

frappe.ui.form.on("Document Collection Template", {
	onload(frm) {
		// Read once per form load, so a type enabled meanwhile shows after a reload.
		frm.__nso_mapping_options = null;
	},

	refresh(frm) {
		render_mapping(frm);
		hide_builtin_template_button(frm);

		if (!frm.is_new()) {
			frm.add_custom_button(__("Requests Using This"), () =>
				frappe.set_route("List", "Document Collection Request", {
					template: frm.doc.name,
				})
			);
		}
	},

});

// Frappe sends a table's add, remove and bulk-delete events to the child doctype's handlers.
// Removing a document can leave a field mapped to it; the row shows that.
frappe.ui.form.on("Template Document", {
	document_type(frm) {
		render_mapping(frm);
	},
	documents_add(frm) {
		render_mapping(frm);
	},
	documents_remove(frm) {
		render_mapping(frm);
	},
	documents_delete(frm) {
		render_mapping(frm);
	},
});

// Frappe adds its own "Save as Template" from toolbar.js for every doctype, with no
// per-doctype opt-out. Two template mechanisms on the same screen is confusing, so the
// built-in one is hidden here.
function hide_builtin_template_button(frm) {
	frm.page.wrapper
		.find(".btn")
		.filter(function () {
			return $(this).text().trim() === __("Save as Template");
		})
		.addClass("hide");
}

/* ----------------------------------------------------------- field mapping */

// One call per form load. A failure is cached too, as no options, so it is shown once rather
// than at every render.
function mapping_options(frm) {
	if (!frm.__nso_mapping_options) {
		const empty = { sections: [], fields: [] };
		frm.__nso_mapping_options = new Promise((resolve) => {
			frappe.call({
				method: "ninthsense.document_collection.hr_api.get_mapping_options",
				callback: (r) => resolve(r.message || empty),
				error: () => resolve(empty),
			});
		});
	}
	return frm.__nso_mapping_options;
}

const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

function render_mapping(frm) {
	const field = frm.get_field("field_mapping_html");
	if (!field) return;

	mapping_options(frm).then((opts) => {
		// HR User reads templates but cannot save them, so the dropdowns are not offered.
		const read_only = !frm.perm?.[0]?.write;
		const requested = new Set(
			(frm.doc.documents || []).map((r) => r.document_type).filter(Boolean)
		);
		const rows_by_key = {};
		(frm.doc.field_mapping || []).forEach((r) => (rows_by_key[r.field_key] = r));
		const known = new Set(opts.fields.map((f) => f.key));

		const sections = opts.sections
			.map((section) => {
				const fields = opts.fields
					.filter((f) => f.section === section.value)
					.map((f) => ({
						...f,
						available: f.documents.filter((d) => requested.has(d)),
						row: rows_by_key[f.key],
					}))
					// A field stays listed while it is mapped, so a removed document
					// shows up as a problem rather than silently vanishing.
					.filter((f) => f.available.length || f.row);

				return fields.length ? section_html(section.label, fields, read_only) : "";
			})
			.join("");

		const orphans = (frm.doc.field_mapping || []).filter((r) => !known.has(r.field_key));

		field.$wrapper.html(`
			<div class="ns-mapping">
				${sections || empty_html(requested.size)}
				${orphans.length ? orphans_html(orphans, read_only) : ""}
			</div>
		`);

		if (!read_only) wire_mapping(frm, field.$wrapper);
	});
}

function empty_html(document_count) {
	const text = document_count
		? __("None of these documents carry fields to map.")
		: __("Add documents above to map fields.");
	return `<div class="text-muted" style="font-size:13px">${text}</div>`;
}

const GRID = "display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:10px;align-items:center";

function section_html(label, fields, read_only) {
	return `
		<div style="margin-bottom:18px">
			<div style="background:var(--control-bg);border-radius:6px;padding:6px 10px;font-size:11.5px;
				font-weight:600;letter-spacing:.03em;color:var(--text-muted);margin-bottom:6px">
				${esc(label)}
			</div>
			<div style="${GRID};font-size:11px;color:var(--text-light);padding:0 0 4px">
				<div>${__("Field")}</div><div>${__("Source Document")}</div><div>${__("Fallback Document")}</div>
			</div>
			${fields.map((f) => field_row_html(f, read_only)).join("")}
		</div>`;
}

function field_row_html(f, read_only) {
	const source = f.row ? f.row.source_document : "";
	const fallback = f.row ? f.row.fallback_document : "";

	return `
		<div class="ns-map-row" data-key="${esc(f.key)}" style="${GRID};padding:4px 0">
			<div style="font-size:13px">${esc(f.label)}</div>
			<div>${select_html("source", f.available, source, __("Not collected"), null, read_only)}</div>
			<div>${select_html("fallback", f.available, fallback, __("None"), source, read_only)}</div>
		</div>`;
}

// `exclude` is the source, which the fallback cannot repeat. A saved value that is no
// longer requested stays selectable, marked, so HR sees it rather than losing it.
function select_html(role, documents, selected, blank_label, exclude, read_only) {
	const options = documents.filter((d) => d !== exclude);
	if (selected && !options.includes(selected)) options.push(selected);

	const disabled = read_only || (role === "fallback" && !exclude);

	const option_html = options
		.map((d) => {
			const label = documents.includes(d) ? d : __("{0} (not requested)", [d]);
			return `<option value="${esc(d)}"${d === selected ? " selected" : ""}>${esc(label)}</option>`;
		})
		.join("");

	// Frappe's own Select markup, so the dropdown shows its caret. A disabled one shows none
	// and is greyed, so it does not read as a choice.
	const select = `<select class="form-control input-xs ellipsis ns-map-${role}"
		style="font-size:12.5px${disabled ? ";color:var(--disabled-text-color)" : ""}"
		${disabled ? "disabled" : ""}><option value="">${esc(blank_label)}</option>${option_html}</select>`;
	const caret = disabled
		? ""
		: `<div class="select-icon xs">${frappe.utils.icon("select", "xs")}</div>`;
	return `<div class="frappe-control" data-fieldtype="Select">
		<div class="control-input flex align-center">${select}${caret}</div></div>`;
}

function orphans_html(rows, read_only) {
	return `
		<div style="font-size:12px;color:var(--text-muted);margin-top:4px">
			${__("Mapped fields this site cannot fill:")}
			${rows
				.map(
					(r) => `<span style="margin-left:6px">${esc(r.field_key)}${
						read_only
							? ""
							: ` <a href="#" class="ns-map-drop" data-key="${esc(r.field_key)}">&times;</a>`
					}</span>`
				)
				.join("")}
		</div>`;
}

function wire_mapping(frm, $wrapper) {
	const key_of = (el) => $(el).closest(".ns-map-row").data("key");

	$wrapper.find(".ns-map-source").on("change", (e) => {
		const key = key_of(e.currentTarget);
		const value = e.currentTarget.value;
		const row = find_row(frm, key);

		if (!value) {
			remove_row(frm, key);
		} else if (row) {
			row.source_document = value;
			if (row.fallback_document === value) row.fallback_document = null;
		} else {
			frm.add_child("field_mapping", { field_key: key, source_document: value });
		}

		frm.dirty();
		render_mapping(frm);
	});

	$wrapper.find(".ns-map-fallback").on("change", (e) => {
		const row = find_row(frm, key_of(e.currentTarget));
		if (!row) return;

		row.fallback_document = e.currentTarget.value || null;
		frm.dirty();
		render_mapping(frm);
	});

	$wrapper.find(".ns-map-drop").on("click", (e) => {
		e.preventDefault();
		remove_row(frm, $(e.currentTarget).data("key"));
		frm.dirty();
		render_mapping(frm);
	});
}

function find_row(frm, key) {
	return (frm.doc.field_mapping || []).find((r) => r.field_key === key);
}

function remove_row(frm, key) {
	frm.doc.field_mapping = (frm.doc.field_mapping || []).filter((r) => r.field_key !== key);
	frm.doc.field_mapping.forEach((r, i) => (r.idx = i + 1));
}
