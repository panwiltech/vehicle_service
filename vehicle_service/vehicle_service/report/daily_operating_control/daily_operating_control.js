// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.query_reports["Daily Operating Control"] = {
	filters: [
		{
			fieldname: "view_mode",
			label: __("View Mode"),
			fieldtype: "Select",
			options: ["Daily Operating Trend", "Executive Summary"],
			default: "Daily Operating Trend",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
	],
};
