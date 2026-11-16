// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Vehicle", {
	refresh(frm) {
		if (frm.is_new()) {
			const $hw = frm.fields_dict.history_html && frm.fields_dict.history_html.$wrapper;
			if ($hw) $hw.empty();
			frm._vsh_view = null;
			frm._vsh_wrapper = null;
			return;
		}

		// Guard buttons so repeated refresh or dual script loading never creates duplicates.
		// 1. Move Location
		if (!frm.custom_buttons || !frm.custom_buttons[__("Move Location")]) {
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
		}

		// 2. Start New Service Order
		if (!frm.doc.current_service_order) {
			if (!frm.custom_buttons || !frm.custom_buttons[__("+ New Service Order")]) {
				frm.add_custom_button(__("+ New Service Order"), () => {
					frappe.new_doc("Service Order", {
						vehicle: frm.doc.name,
						customer: frm.doc.customer,
						driver_name: frm.doc.driver_name,
						driver_phone: frm.doc.driver_phone
					});
				}).addClass("btn-primary");
			}
		} else if (!frm.custom_buttons || !frm.custom_buttons[__("View Open Service Order")]) {
			frm.add_custom_button(__("View Open Service Order"), () => {
				frappe.set_route("Form", "Service Order", frm.doc.current_service_order);
			}).addClass("btn-info");
		}

		// 3. Full Service History Page Button
		if (!frm.custom_buttons || !frm.custom_buttons[__("Full Service History")]) {
			frm.add_custom_button(__("Full Service History"), () => {
				frappe.route_options = { vehicle: frm.doc.name };
				frappe.set_route("vehicle-service-history");
			});
		}

		// 4. Embedded Service History Tab View (debounced per tick for dual doctype/public JS safety)
		const $historyWrapper = frm.fields_dict.history_html && frm.fields_dict.history_html.$wrapper;
		if ($historyWrapper && window.vehicle_service && vehicle_service.VehicleServiceHistoryView) {
			if (!frm._vsh_refresh_lock) {
				frm._vsh_refresh_lock = true;
				Promise.resolve().then(() => {
					frm._vsh_refresh_lock = false;
				});
				if (frm._vsh_view && frm._vsh_wrapper === $historyWrapper[0]) {
					frm._vsh_view.load_vehicle(frm.doc.name);
				} else {
					$historyWrapper.empty();
					frm._vsh_wrapper = $historyWrapper[0];
					frm._vsh_view = new vehicle_service.VehicleServiceHistoryView({
						parent: $historyWrapper,
						vehicle: frm.doc.name,
						show_search: false
					});
				}
			}
		}
	}
});
