// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.listview_settings["Service Order"] = {
	add_fields: ["status", "board_status", "customer", "customer_name", "vehicle", "technicians", "job_count", "order_date"],
	get_indicator(doc) {
		const colors = {
			"Draft": "grey",
			"Checked In": "blue",
			"In Progress": "orange",
			"Paused": "yellow",
			"Awaiting Approval": "purple",
			"Approved": "blue",
			"Waiting for Parts": "red",
			"Ready for Work": "cyan",
			"Ready for Billing": "green",
			"Invoiced": "green",
			"Ready for Collection": "green",
			"Delivered": "green",
			"Cancelled": "darkgrey"
		};
		return [__(doc.status), colors[doc.status] || "grey", "status,=," + doc.status];
	}
};
