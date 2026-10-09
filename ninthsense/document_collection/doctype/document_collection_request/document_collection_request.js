// The request as HR reads it: a summary, the documents, what 9thSense read and the last fill.
// Every panel renders from the stored fields; nothing is fetched and nothing writes. The raw
// fields and tables stay on the doctype, hidden where a panel shows them.

const NSO_REQUEST_STATUS_COLOURS = {
	"Link Sent": "blue",
	"Data Received": "green",
	Completed: "gray",
	Cancelled: "red",
};

// verification_result is the provider's case status mapped to three words (FR-017).
const NSO_RESULT_COLOURS = { Passed: "green", "Needs Review": "orange", Failed: "red" };

// Lists 9thSense may put in a step's result for HR to act on, read in this order.
const NSO_RAISED_KEYS = ["rfis", "issues", "flags", "reasons", "requests"];
const NSO_RAISED_PREVIEW = 5;

const NSO_FILL_ORDER = [
	"Filled",
	"Skipped – already filled",
	"Skipped – invalid",
	"Attach failed",
];

// Words a sentence-cased key would otherwise spell wrong ("Pan", "Ifsc").
const NSO_ACRONYMS = {
	pan: "PAN",
	ifsc: "IFSC",
	micr: "MICR",
	uan: "UAN",
	dob: "DOB",
	id: "ID",
	pf: "PF",
	rag: "RAG",
	rfi: "RFI",
	rfis: "RFIs",
};

const NSO_CSS = `
	.nso-card{border:1px solid var(--border-color);border-radius:var(--border-radius-md);
		padding:12px 16px;background:var(--card-bg)}
	.nso-row{display:flex;flex-wrap:wrap;gap:8px 28px;align-items:flex-start}
	.nso-eyebrow{font-size:var(--text-xs);color:var(--text-muted);margin-bottom:2px}
	.nso-value{font-weight:600}
	.nso-case{display:flex;align-items:center;gap:6px}
	.nso-case code{font-size:var(--text-sm);padding:2px 6px;border-radius:var(--border-radius);
		background:var(--bg-color);color:var(--text-color)}
	.nso-copy{border:1px solid var(--border-color);background:transparent;border-radius:var(--border-radius);
		padding:2px 5px;line-height:0;color:var(--text-muted);cursor:pointer}
	.nso-raised{margin-top:10px;padding-top:8px;border-top:1px solid var(--border-color)}
	.nso-raised ul{margin:2px 0 0;padding-left:18px}
	.nso-raised summary,.nso-group summary{cursor:pointer}
	.nso-raised summary{color:var(--text-muted);font-size:var(--text-sm)}
	.nso-line{margin-top:8px;font-size:var(--text-sm)}
	.nso-table{width:100%;border-collapse:collapse}
	.nso-table th,.nso-table td{padding:6px 12px 6px 0;border-bottom:1px solid var(--border-color);
		text-align:left;vertical-align:top;font-size:var(--text-md);overflow-wrap:anywhere}
	.nso-table thead th{font-size:var(--text-sm);color:var(--text-muted);font-weight:normal}
	.nso-table tr:last-child td,.nso-table tr:last-child th{border-bottom:none}
	.nso-kv{table-layout:fixed}
	.nso-kv th{width:35%;color:var(--text-muted);font-weight:normal}
	.nso-group{margin-bottom:10px}
	.nso-group summary{font-weight:600;margin-bottom:4px}
	.nso-fill h6{margin:12px 0 4px;font-size:var(--text-md);font-weight:600}
	.nso-fill ul{margin:0;padding-left:18px}
`;

frappe.ui.form.on("Document Collection Request", {
	refresh(frm) {
		// Every field is written by the app (SERVICE_FIELDS), so Save has nothing to save.
		frm.disable_save();
		const colour = NSO_REQUEST_STATUS_COLOURS[frm.doc.status];
		if (colour) frm.page.set_indicator(__(frm.doc.status), colour);
		nso_render_summary(frm);
		nso_render_documents(frm);
		nso_render_extracted(frm);
		nso_render_fill(frm);
	},
});

// ------------------------------------------------------------------ helpers

function nso_esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

// "needs_review" -> "Needs review": 9thSense's word, made readable, never replaced.
function nso_humanise(value) {
	const text = String(value == null ? "" : value).trim();
	if (!text || !/[_]|^[a-z0-9]+$/.test(text)) return text;
	const words = text.split(/[_\s]+/).filter(Boolean);
	return words
		.map((word, i) => {
			const lower = word.toLowerCase();
			if (NSO_ACRONYMS[lower]) return NSO_ACRONYMS[lower];
			return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
		})
		.join(" ");
}

function nso_date(value) {
	return value ? frappe.datetime.str_to_user(value) : "";
}

// The document-collection step of the stored (already masked) completion, or the first step.
function nso_step(frm) {
	if (!frm.doc.verification_response) return null;
	try {
		const payload = JSON.parse(frm.doc.verification_response);
		const steps = (payload && Array.isArray(payload.steps) && payload.steps) || [];
		const objects = steps.filter((s) => s && typeof s === "object");
		return objects.find((s) => s.type === "document_collection") || objects[0] || null;
	} catch (e) {
		return null;
	}
}

function nso_document_names(frm) {
	const names = {};
	(frm.doc.requested_documents || []).forEach((row) => {
		if (row.document_code && row.document_type) names[row.document_code] = row.document_type;
	});
	return names;
}

function nso_raised_text(item) {
	if (item == null) return "";
	if (typeof item !== "object") return String(item);
	return item.message || item.title || item.description || "";
}

function nso_raised_items(result) {
	if (!result || typeof result !== "object" || Array.isArray(result)) return [];
	const items = [];
	NSO_RAISED_KEYS.forEach((key) => {
		const value = result[key];
		const list = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
		list.map(nso_raised_text)
			.filter((text) => String(text).trim())
			.forEach((text) => items.push(text));
	});
	return items;
}

function nso_list(items) {
	return `<ul>${items.map((item) => `<li>${nso_esc(item)}</li>`).join("")}</ul>`;
}

// ------------------------------------------------------------------ summary

function nso_render_summary(frm) {
	const field = frm.get_field("summary_html");
	if (!field) return;
	const style = `<style>${NSO_CSS}</style>`;
	const body = frm.doc.documents_received_on ? nso_result_card(frm) : nso_waiting_line(frm);
	field.$wrapper.html(style + body);
	field.$wrapper.find(".nso-copy").on("click", function () {
		frappe.utils.copy_to_clipboard($(this).attr("data-value"));
	});
}

function nso_status_line(frm) {
	if (frm.doc.status === "Cancelled") {
		return nso_esc(__("Cancelled with its onboarding. The link no longer works."));
	}
	if (frm.doc.status === "Completed") {
		const employee = frm.doc.employee
			? ` — ${nso_esc(__("Employee"))} <a href="/app/employee/${encodeURIComponent(
					frm.doc.employee
			  )}">${nso_esc(frm.doc.employee)}</a>`
			: "";
		return `${nso_esc(__("Completed"))}${employee}`;
	}
	return "";
}

function nso_waiting_line(frm) {
	const status = nso_status_line(frm);
	if (status) return `<div>${status}</div>`;
	const parts = [__("Waiting for the candidate.")];
	if (frm.doc.link_sent_on && frm.doc.link_expires_on) {
		parts.push(
			__("Link sent {0}, expires {1}.", [
				nso_date(frm.doc.link_sent_on),
				nso_date(frm.doc.link_expires_on),
			])
		);
	} else if (frm.doc.link_sent_on) {
		parts.push(__("Link sent {0}.", [nso_date(frm.doc.link_sent_on)]));
	}
	const emailed = frm.doc.link_emailed
		? ""
		: `<div class="text-muted">${nso_esc(__("Not emailed: the link was shown to HR"))}</div>`;
	return `<div>${nso_esc(parts.join(" "))}</div>${emailed}`;
}

function nso_fact(label, value_html) {
	return `<div><div class="nso-eyebrow">${nso_esc(label)}</div>
		<div class="nso-value">${value_html}</div></div>`;
}

// 9thSense's own words for the case. Ours (verification_result) only when it gave none.
function nso_result_html(frm, result) {
	const facts = [];
	if (result && typeof result === "object" && !Array.isArray(result)) {
		if (result.decision != null && result.decision !== "") {
			facts.push(nso_fact(__("9thSense decision"), nso_esc(nso_humanise(result.decision))));
		}
		if (result.rag_status != null && result.rag_status !== "") {
			facts.push(nso_fact(__("RAG status"), nso_esc(nso_humanise(result.rag_status))));
		}
		const score = result.overall_score;
		if (score != null && score !== "") {
			const shown =
				typeof score === "number" && score >= 0 && score <= 1
					? `${Math.round(score * 100)}%`
					: String(score);
			facts.push(nso_fact(__("Score"), nso_esc(shown)));
		}
	}
	if (facts.length) return facts.join("");
	const verdict = frm.doc.verification_result;
	if (!verdict) return nso_fact(__("9thSense result"), "—");
	const colour = NSO_RESULT_COLOURS[verdict] || "gray";
	return nso_fact(
		__("9thSense result"),
		`<span class="indicator-pill ${colour}">${nso_esc(__(verdict))}</span>`
	);
}

function nso_result_card(frm) {
	const step = nso_step(frm);
	const result = step && step.result;
	const facts = [nso_result_html(frm, result)];

	const case_id = frm.doc.verification_case_id;
	if (case_id) {
		facts.push(
			nso_fact(
				__("Case ID"),
				`<span class="nso-case"><code>${nso_esc(case_id)}</code>
				<button type="button" class="nso-copy" data-value="${nso_esc(case_id)}"
					title="${nso_esc(__("Copy"))}" aria-label="${nso_esc(__("Copy case ID"))}">
					${frappe.utils.icon("copy", "sm")}</button></span>`
			)
		);
	}
	facts.push(nso_fact(__("Received"), nso_esc(nso_date(frm.doc.documents_received_on))));

	const status = nso_status_line(frm);
	const raised = nso_raised_html(frm, step, result);
	const error = frm.doc.extraction_error
		? `<div class="nso-line text-danger">${nso_esc(frm.doc.extraction_error)}</div>`
		: "";

	return `<div class="nso-card">
		<div class="nso-row">${facts.join("")}</div>
		${status ? `<div class="nso-line">${status}</div>` : ""}
		${raised}
		${error}
	</div>`;
}

function nso_raised_html(frm, step, result) {
	const items = nso_raised_items(result);
	const names = nso_document_names(frm);
	const missing = (
		(step && Array.isArray(step.missing_documents) && step.missing_documents) ||
		[]
	)
		.filter((code) => code != null && code !== "")
		.map((code) => names[code] || nso_humanise(code));
	if (!items.length && !missing.length) return "";

	const not_submitted = missing.length
		? `<div>${nso_esc(__("Not submitted: {0}", [missing.join(", ")]))}</div>`
		: "";
	let list = "";
	if (items.length) {
		const more = items.slice(NSO_RAISED_PREVIEW);
		list =
			nso_list(items.slice(0, NSO_RAISED_PREVIEW)) +
			(more.length
				? `<details><summary>${nso_esc(__("+{0} more", [more.length]))}</summary>
					${nso_list(more)}</details>`
				: "");
	}
	return `<div class="nso-raised">
		<div class="nso-eyebrow">${nso_esc(__("Raised by 9thSense"))}</div>
		${not_submitted}${list}
	</div>`;
}

// ---------------------------------------------------------------- documents

function nso_render_documents(frm) {
	const field = frm.get_field("documents_html");
	if (!field) return;
	const rows = frm.doc.requested_documents || [];
	if (!rows.length) {
		field.$wrapper.html(`<p class="text-muted">${nso_esc(__("No documents requested."))}</p>`);
		return;
	}
	const names = nso_document_names(frm);
	const waiting = !frm.doc.documents_received_on && frm.doc.status === "Link Sent";
	const lines = rows.map((row) => {
		let name = nso_esc(row.document_type || nso_humanise(row.document_code));
		if (!row.is_requested) {
			name = `<span class="text-muted">${name} ${nso_esc(__("(earlier link)"))}</span>`;
		}
		const file = row.file
			? `<a href="${encodeURI(row.file)}" target="_blank" rel="noopener">${nso_esc(
					row.file_name || __("Open")
			  )}</a>`
			: `<span class="text-muted">${nso_esc(
					waiting ? __("Waiting") : __("Not received")
			  )}</span>`;
		const notes = [];
		if (!row.is_detected_type_expected && row.detected_document_type) {
			const read_as =
				names[row.detected_document_type] || nso_humanise(row.detected_document_type);
			notes.push(__("Read as {0}", [read_as]));
		}
		if (row.is_low_confidence) notes.push(__("Low confidence"));
		return `<tr>
			<td>${name}</td>
			<td>${row.is_mandatory ? nso_esc(__("Yes")) : ""}</td>
			<td>${file}</td>
			<td>${nso_esc(nso_humanise(row.verification_status || ""))}</td>
			<td>${nso_esc(notes.join("; "))}</td>
		</tr>`;
	});
	field.$wrapper.html(`<table class="nso-table">
		<thead><tr>
			<th>${nso_esc(__("Document"))}</th><th>${nso_esc(__("Required"))}</th>
			<th>${nso_esc(__("File"))}</th><th>${nso_esc(__("9thSense"))}</th>
			<th>${nso_esc(__("Note"))}</th>
		</tr></thead>
		<tbody>${lines.join("")}</tbody>
	</table>`);
}

// -------------------------------------------------------- what 9thSense read

function nso_render_extracted(frm) {
	const field = frm.get_field("extracted_html");
	const rows = frm.doc.extractions || [];
	frm.toggle_display("extracted_section", rows.length > 0);
	if (!field || !rows.length) return;

	const names = nso_document_names(frm);
	const groups = new Map();
	rows.forEach((row) => {
		const code = row.document_code || "";
		if (!groups.has(code)) groups.set(code, []);
		groups.get(code).push(row);
	});

	let first = true;
	const html = [...groups.entries()].map(([code, list]) => {
		const title = names[code] || nso_humanise(code) || __("Other");
		const pairs = list
			.map((row) => {
				const label = String(row.key || "")
					.split(".")
					.map(nso_humanise)
					.join(" › ");
				// As stored: Aadhaar arrives masked and stays exactly so.
				return `<tr><th>${nso_esc(label)}</th><td>${nso_esc(row.value)}</td></tr>`;
			})
			.join("");
		const open = first ? " open" : "";
		first = false;
		return `<details class="nso-group"${open}>
			<summary>${nso_esc(title)}</summary>
			<table class="nso-table nso-kv"><tbody>${pairs}</tbody></table>
		</details>`;
	});
	field.$wrapper.html(html.join(""));
}

// --------------------------------------------------------------- fill report

// The report of the last Create Employee, replaced at each one (FR-024).
function nso_render_fill(frm) {
	const field = frm.get_field("fill_html");
	const rows = frm.doc.fill_results || [];
	frm.toggle_display("fill_section", rows.length > 0);
	if (!field || !rows.length) return;

	const line = {
		Filled: (r) => __("{0}: {1}", [r.label, r.value]),
		"Skipped – already filled": (r) =>
			__("{0}: document says {1}, form has {2}", [r.label, r.value, r.existing_value]),
		"Skipped – invalid": (r) => __("{0}: {1} — {2}", [r.label, r.value, r.reason]),
		"Attach failed": (r) => __("{0} — {1}", [r.label, r.reason]),
	};
	const outcomes = NSO_FILL_ORDER.concat(
		[...new Set(rows.map((r) => r.outcome))].filter((o) => !NSO_FILL_ORDER.includes(o))
	);
	const sections = outcomes
		.map((outcome) => {
			const list = rows
				.filter((r) => r.outcome === outcome)
				.map((r) => {
					const values = {
						label: r.field_label || r.fieldname || "",
						value: r.value || "",
						existing_value: r.existing_value || "",
						reason: r.reason || "",
					};
					return line[outcome] ? line[outcome](values) : values.label;
				});
			if (!list.length) return "";
			return `<h6>${nso_esc(__(outcome))} (${list.length})</h6>${nso_list(list)}`;
		})
		.join("");

	const when = frm.doc.last_fill_on
		? `<div class="text-muted">${nso_esc(
				__("Last filled {0}", [nso_date(frm.doc.last_fill_on)])
		  )}</div>`
		: "";
	field.$wrapper.html(`<div class="nso-fill">${when}${sections}</div>`);
}
