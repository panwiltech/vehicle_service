// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (!frm.doc.vs_service_order) return;

		const userRoles = frappe.user_roles || [];
		const isAuthorizedPartsModifier = userRoles.includes("System Manager") ||
			userRoles.includes("Parts Controller") ||
			userRoles.includes("Parts Manager") ||
			userRoles.includes("Accounts Manager") ||
			frappe.session.user === "Administrator";

		const isAuthorizedCreditModifier = userRoles.includes("System Manager") ||
			userRoles.includes("Accounts Manager") ||
			userRoles.includes("Accounts User") ||
			userRoles.includes("Service Accounts") ||
			userRoles.includes("Service Manager") ||
			frappe.session.user === "Administrator";

		if (!isAuthorizedPartsModifier && userRoles.includes("Service Advisor")) {
			// Disallow row deletion on items table
			frm.set_df_property("items", "cannot_delete_rows", true);
		}

		if (!isAuthorizedCreditModifier && userRoles.includes("Service Advisor")) {
			// Service Advisors cannot create Credit Notes or toggle is_return
			frm.set_df_property("is_return", "read_only", true);
			frm.set_df_property("is_return", "hidden", true);
		} else if (!frm.doc.is_return && frm.doc.docstatus === 0) {
			// A draft invoice created from Service Order cannot be toggled into a Credit Note
			frm.set_df_property("is_return", "read_only", true);
		}
	}
});

frappe.ui.form.on("Sales Invoice Item", {
	qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row && row.vs_part_row && frm.doc.vs_service_order) {
			const userRoles = frappe.user_roles || [];
			const isAuthorizedPartsModifier = userRoles.includes("System Manager") ||
				userRoles.includes("Parts Controller") ||
				userRoles.includes("Parts Manager") ||
				userRoles.includes("Accounts Manager") ||
				frappe.session.user === "Administrator";

			if (!isAuthorizedPartsModifier && userRoles.includes("Service Advisor")) {
				frappe.msgprint({
					title: __("Modification Restricted"),
					message: __("Service Advisors cannot modify parts quantities on an invoice linked to a Service Order. Only labour hours can be adjusted."),
					indicator: "orange"
				});
				frm.reload_doc();
			}
		}
	},

	rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row && row.vs_part_row && frm.doc.vs_service_order) {
			const userRoles = frappe.user_roles || [];
			const isAuthorizedPartsModifier = userRoles.includes("System Manager") ||
				userRoles.includes("Parts Controller") ||
				userRoles.includes("Parts Manager") ||
				userRoles.includes("Accounts Manager") ||
				frappe.session.user === "Administrator";

			if (!isAuthorizedPartsModifier && userRoles.includes("Service Advisor")) {
				frappe.msgprint({
					title: __("Modification Restricted"),
					message: __("Service Advisors cannot modify parts rates on an invoice linked to a Service Order. Only labour hours can be adjusted."),
					indicator: "orange"
				});
				frm.reload_doc();
			}
		}
	}
});
