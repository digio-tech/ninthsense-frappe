app_name = "ninthsense"
app_title = "9thSense Onboarding"
app_publisher = "Digio Labs"
app_description = "9thSense employee onboarding: collect documents from a candidate and fill the Employee"
app_email = "digio-labs@digio.in"
app_license = "mit"

# Never list frappe here: the pilot validator rejects it (R16).
required_apps = ["erpnext", "hrms"]

# The portal calls ninthsense.document_collection.portal_api.* directly; only HRMS's
# Create > Employee is wrapped (R3).
override_whitelisted_methods = {
	"hrms.hr.doctype.employee_onboarding.employee_onboarding.make_employee": (
		"ninthsense.document_collection.employee.make_employee"
	),
}

doc_events = {
	"Employee Onboarding": {
		"on_cancel": "ninthsense.document_collection.lifecycle.on_cancel",
		"on_trash": "ninthsense.document_collection.lifecycle.on_trash",
	},
	"Employee": {
		"validate": "ninthsense.document_collection.employee.validate",
		"after_insert": "ninthsense.document_collection.employee.after_insert",
	},
}

doctype_js = {"Employee Onboarding": "public/js/employee_onboarding.js"}

override_doctype_dashboards = {
	"Employee Onboarding": "ninthsense.document_collection.dashboard.get_dashboard_data",
}

# Seeds the document types, the invite email and the default template (R15, FR-044).
after_install = "ninthsense.install.after_install"
# v16's migrate deletes app-level navigation records whose `app` (hrms, R14) does not ship them;
# this puts the app's own back after it.
after_migrate = ["ninthsense.install.ship_desk_navigation"]
# Those two records are filed under hrms, so uninstall would leave them behind; this removes them.
before_uninstall = "ninthsense.install.before_uninstall"
