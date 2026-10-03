// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Booking", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status === "Open" || frm.doc.status === "Confirmed") {
			frm.add_custom_button(__("Check In Vehicle"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_booking.service_booking.check_in_booking",
					args: { booking_name: frm.doc.name },
					freeze: true,
					callback: (r) => {
						if (!r.exc && r.message && r.message.service_order) {
							frappe.set_route("Form", "Service Order", r.message.service_order);
						}
					}
				}).addClass("btn-primary");
			});

			frm.add_custom_button(__("Cancel Booking"), () => {
				frappe.prompt(
					[{ fieldname: "reason", label: __("Cancellation Reason"), fieldtype: "Small Text", reqd: 1 }],
					(vals) => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_booking.service_booking.cancel_booking",
							args: { booking_name: frm.doc.name, reason: vals.reason },
							freeze: true,
							callback: () => frm.reload_doc()
						});
					},
					__("Cancel Booking"),
					__("Cancel")
				);
			}, __("Actions"));
		}
	}
});
