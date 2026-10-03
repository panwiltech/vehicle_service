// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Vehicle", {
	refresh(frm) {
		if (frm.is_new()) return;

		// 1. Move Location
		frm.add_custom_button(__("Move Location"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Move Vehicle Location"),
				fields: [
					{ fieldname: "to_location", label: __("New Location"), fieldtype: "Link", options: "Workshop Location", reqd: 1 },
					{ fieldname: "reason", label: __("Reason / Movement Note"), fieldtype: "Data" }
				],
				primary_action_label: __("Move"),
				primary_action: (vals) => {
					frappe.call({
						method: "vehicle_service.vehicle_service.doctype.service_vehicle.service_vehicle.move_vehicle",
						args: { vehicle: frm.doc.name, to_location: vals.to_location, reason: vals.reason },
						freeze: true,
						callback: () => {
							d.hide();
							frm.reload_doc();
						}
					});
				}
			});
			d.show();
		}, __("Actions"));

		// 2. Start New Service Order
		if (!frm.doc.current_service_order) {
			frm.add_custom_button(__("+ New Service Order"), () => {
				frappe.new_doc("Service Order", {
					vehicle: frm.doc.name,
					customer: frm.doc.customer,
					driver_name: frm.doc.driver_name,
					driver_phone: frm.doc.driver_phone
				});
			}).addClass("btn-primary");
		} else {
			frm.add_custom_button(__("View Open Service Order"), () => {
				frappe.set_route("Form", "Service Order", frm.doc.current_service_order);
			}).addClass("btn-info");
		}
	}
});
