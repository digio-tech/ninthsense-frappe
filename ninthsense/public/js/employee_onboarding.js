const NSO_HR_API = "ninthsense.document_collection.hr_api";
const NSO_REQUEST = "Document Collection Request";
const NSO_REQUEST_COLOURS = {
	"Link Sent": "blue",
	"Data Received": "green",
	Completed: "gray",
	Cancelled: "red",
};

frappe.ui.form.on("Employee Onboarding", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus >= 2 || frm.doc.employee) return;
		if (!frappe.user.has_role(["HR User", "HR Manager"])) return;
		nso_load_send_button(frm);
	},
});

function nso_load_send_button(frm) {
	frappe.call({
		method: `${NSO_HR_API}.get_onboarding_request`,
		args: { employee_onboarding: frm.doc.name },
		// A failure should not raise a dialog on every form open.
		// Pressing the button shows the real refusal.
		silent: true,
		callback({ message: request }) {
			nso_add_send_button(frm, request);
		},
		error() {
			nso_add_send_button(frm, null);
		},
	});
}

function nso_add_send_button(frm, request) {
	frm.remove_custom_button(__("Send onboarding link"));
	frm.remove_custom_button(__("Resend onboarding link"));
	nso_show_request_status(frm, request);
	const status = request && request.status;
	if (status === "Completed" || status === "Cancelled") return;

	const resend = status === "Link Sent" || status === "Data Received";
	const label = resend ? __("Resend onboarding link") : __("Send onboarding link");
	frm.add_custom_button(label, () => nso_pick_template(frm, label));
}

// The request's status, linked to the request, in the form's dashboard (hr-actions.md).
function nso_show_request_status(frm, request) {
	if (frm.__nso_status_indicator) frm.__nso_status_indicator.remove();
	frm.__nso_status_indicator = null;
	if (!request || !request.name) return;
	const colour = NSO_REQUEST_COLOURS[request.status] || "gray";
	const label = `<a href="${frappe.utils.get_form_link(NSO_REQUEST, request.name)}">${__(
		"Document collection: {0}",
		[frappe.utils.escape_html(__(request.status))]
	)}</a>`;
	frm.__nso_status_indicator = frm.dashboard.add_indicator(label, colour);
}

// With several enabled templates HR picks one, the current or default preselected (FR-040).
// With one or none the server decides: it uses the only one, or says to create one.
function nso_pick_template(frm, title) {
	frappe.call({
		method: `${NSO_HR_API}.get_send_options`,
		args: { employee_onboarding: frm.doc.name },
		callback({ message: options }) {
			const templates = (options && options.templates) || [];
			if (templates.length < 2) {
				nso_send_link(frm, null);
				return;
			}
			const names = templates.map((t) => t.name);
			const fallback = templates.find((t) => t.is_default) || templates[0];
			const preselected = names.includes(options.current_template)
				? options.current_template
				: fallback.name;
			const dialog = new frappe.ui.Dialog({
				title: title,
				fields: [
					{
						fieldname: "template",
						fieldtype: "Select",
						label: __("Document Collection Template"),
						options: names,
						default: preselected,
						reqd: 1,
						description: __("The documents the candidate is asked for."),
					},
				],
				primary_action_label: __("Send"),
				primary_action({ template }) {
					dialog.hide();
					nso_send_link(frm, template);
				},
			});
			dialog.show();
		},
	});
}

function nso_send_link(frm, template) {
	frappe.call({
		method: `${NSO_HR_API}.send_onboarding_link`,
		type: "POST",
		// No `template` key at all when the server is to decide: a null would arrive as "null".
		args: template
			? { employee_onboarding: frm.doc.name, template }
			: { employee_onboarding: frm.doc.name },
		freeze: true,
		freeze_message: __("Sending the onboarding link…"),
		callback({ message: result }) {
			if (!result) return;
			if (result.email_sent) {
				// The answer carries no address; HR can read it on the Job Applicant.
				frappe.db
					.get_value("Job Applicant", frm.doc.job_applicant, "email_id")
					.then(({ message }) => {
						frappe.msgprint({
							title: __("Onboarding link sent"),
							message: __("Emailed {0}", [
								frappe.utils.escape_html((message && message.email_id) || ""),
							]),
							indicator: "green",
						});
					});
			} else {
				nso_show_link(result.link);
			}
			// Only the button, the status and the request count change. Reloading would throw
			// away HR's unsaved edits.
			nso_load_send_button(frm);
			frm.dashboard._fetched_counts = false;
			frm.dashboard.set_open_count();
		},
	});
}

function nso_show_link(link) {
	const safe = frappe.utils.escape_html(link || "");
	const dialog = frappe.msgprint({
		title: __("Onboarding link ready"),
		message: `<p>${__("The email could not be sent. Give the candidate this link:")}</p>
			<p><code class="nso-link" style="word-break:break-all">${safe}</code></p>
			<button class="btn btn-default btn-sm nso-copy">${__("Copy link")}</button>`,
		indicator: "orange",
	});
	dialog.$wrapper.find(".nso-copy").on("click", () => frappe.utils.copy_to_clipboard(link));
}
