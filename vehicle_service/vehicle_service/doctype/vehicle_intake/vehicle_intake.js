// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Vehicle Intake", {
	refresh(frm) {
		if (frm.doc.__islocal) return;

		// 1. Complete Check-In Button (if Draft)
		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Complete Check-In"), () => {
				frappe.confirm(
					__("Are you sure you want to complete check-in? Arrival details and signature will be locked."),
					() => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake.complete_check_in",
							args: {
								intake_name: frm.doc.name,
								customer_signature: frm.doc.customer_signature
							},
							freeze: true,
							freeze_message: __("Finalizing Vehicle Intake..."),
							callback: (r) => {
								if (!r.exc) {
									frappe.show_alert({
										message: __("Vehicle Checked In successfully."),
										indicator: "green"
									});
									frm.reload_doc();
								}
							}
						});
					}
				);
			}).addClass("btn-primary");
		}

		// 2. Service Order Actions (if Checked In)
		if (frm.doc.status === "Checked In") {
			if (frm.doc.service_order) {
				frm.add_custom_button(__("View Service Order"), () => {
					frappe.set_route("Form", "Service Order", frm.doc.service_order);
				}).addClass("btn-secondary");
			} else {
				frm.add_custom_button(__("Create Service Order"), () => {
					frappe.call({
						method: "vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake.create_service_order_from_intake",
						args: { intake_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Creating Service Order..."),
						callback: (r) => {
							if (!r.exc && r.message && r.message.service_order) {
								frappe.set_route("Form", "Service Order", r.message.service_order);
							}
						}
					});
				}).addClass("btn-primary");
			}

			// 3. Correct Intake Button (Actions menu)
			const userRoles = frappe.user_roles || [];
			if (userRoles.includes("Service Advisor") || userRoles.includes("Service Manager") || userRoles.includes("System Manager")) {
				frm.add_custom_button(__("Correct Intake"), () => {
					frm.trigger("show_intake_correction_dialog");
				}, __("Actions"));
			}
		}

		// Read-only controls when checked in
		if (frm.doc.status === "Checked In" || frm.doc.intake_frozen) {
			frm.set_df_property("odometer_in", "read_only", 1);
			frm.set_df_property("fuel_level", "read_only", 1);
			frm.set_df_property("customer_signature", "read_only", 1);
			frm.set_df_property("intake_confirmed", "read_only", 1);
			frm.set_df_property("vehicle", "read_only", 1);
			frm.set_df_property("customer", "read_only", 1);
		}
	},

	show_intake_correction_dialog(frm) {
		const fields = [
			{ label: __("Odometer In (km)"), value: "odometer_in" },
			{ label: __("Fuel Level"), value: "fuel_level" },
			{ label: __("Customer Complaint"), value: "customer_complaint" },
			{ label: __("Existing Damages"), value: "existing_damage" },
			{ label: __("Vehicle Contents"), value: "vehicle_contents" },
			{ label: __("Reception Notes"), value: "reception_notes" }
		];

		const d = new frappe.ui.Dialog({
			title: __("Correct Intake Field"),
			fields: [
				{
					fieldname: "field_to_correct",
					label: __("Field to Correct"),
					fieldtype: "Select",
					options: fields.map(f => f.label).join("\n"),
					reqd: 1,
					onchange: () => {
						const selectedLabel = d.get_value("field_to_correct");
						const fieldMeta = fields.find(f => f.label === selectedLabel);
						if (fieldMeta) {
							d.set_value("current_value", frm.doc[fieldMeta.value] || "");
						}
					}
				},
				{
					fieldname: "current_value",
					label: __("Current Value"),
					fieldtype: "Data",
					read_only: 1
				},
				{
					fieldname: "new_value",
					label: __("New Value"),
					fieldtype: "Small Text",
					reqd: 1
				},
				{
					fieldname: "reason",
					label: __("Reason for Correction (Mandatory Audit)"),
					fieldtype: "Small Text",
					reqd: 1
				}
			],
			primary_action_label: __("Apply Correction"),
			primary_action: (vals) => {
				const selectedField = fields.find(f => f.label === vals.field_to_correct);
				if (!selectedField) return;

				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake.correct_intake",
					args: {
						intake_name: frm.doc.name,
						fieldname: selectedField.value,
						new_value: vals.new_value,
						reason: vals.reason
					},
					freeze: true,
					freeze_message: __("Logging Correction Audit..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({ message: __("Intake corrected successfully."), indicator: "green" });
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();
	}
});
