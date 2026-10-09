def get_dashboard_data(data=None):
	"""Add the onboarding's Document Collection Request to the data HRMS returns."""
	data = dict(data or {})
	data.setdefault("fieldname", "employee_onboarding")
	data.setdefault("non_standard_fieldnames", {})
	data["non_standard_fieldnames"] = {
		**data["non_standard_fieldnames"],
		"Document Collection Request": "employee_onboarding",
	}
	data["transactions"] = [
		*(data.get("transactions") or []),
		{"label": "Document Collection", "items": ["Document Collection Request"]},
	]
	return data
