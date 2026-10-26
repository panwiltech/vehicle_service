// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.query_reports["WIP Valuation"] = {
	filters: [
		{
			fieldname: "view_mode",
			label: __("View Mode"),
			fieldtype: "Select",
			options: ["Order Summary", "Parts Details", "Labour Details", "Branch Reconciliation"],
			default: "Order Summary",
			reqd: 1,
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Approved", "Waiting for Parts", "Ready for Work", "In Progress", "Paused", "QC", "Ready for Billing"],
		},
		{
			fieldname: "aging_bucket",
			label: __("Aging Bucket"),
			fieldtype: "Select",
			options: ["", "0-7 Days", "8-14 Days", "15-30 Days", "30+ Days"],
		},
	],
};
