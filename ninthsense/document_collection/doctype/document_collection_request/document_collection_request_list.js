const NSO_STATUS_COLOURS = {
	"Link Sent": "blue",
	"Data Received": "green",
	Completed: "gray",
	Cancelled: "red",
};

frappe.listview_settings["Document Collection Request"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colour = NSO_STATUS_COLOURS[doc.status];
		if (colour) return [__(doc.status), colour, `status,=,${doc.status}`];
	},
};
