// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Job", {
	refresh(frm) {
		frm.trigger("setup_job_buttons");
	},

	setup_job_buttons(frm) {
		if (frm.is_new()) return;

		// 1. Assign Technician (if Approved or Assigned)
		if (["Approved", "Assigned"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Assign Technician / Bay"), () => {
				const d = new frappe.ui.Dialog({
					title: __("Assign Technician & Bay"),
					fields: [
						{ fieldname: "technician", label: __("Technician (Employee)"), fieldtype: "Link", options: "Employee", reqd: 1, default: frm.doc.technician },
						{ fieldname: "bay", label: __("Bay / Workshop Location"), fieldtype: "Link", options: "Workshop Location", default: frm.doc.bay }
					],
					primary_action_label: __("Assign"),
					primary_action: (vals) => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_order.service_order.assign_job",
							args: { job_name: frm.doc.name, technician: vals.technician, bay: vals.bay },
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

		// 2. Start Work (if Assigned or QC Failed)
		if (["Assigned", "QC Failed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Start Work"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_job.service_job.start_job",
					args: { job_name: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc()
				}).addClass("btn-primary");
			});
		}

		// 3. Pause Work (if In Progress)
		if (frm.doc.status === "In Progress") {
			frm.add_custom_button(__("Pause Work"), () => {
				frappe.prompt(
					[{ fieldname: "reason", label: __("Reason for Pausing"), fieldtype: "Small Text", reqd: 1 }],
					(vals) => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_job.service_job.pause_job",
							args: { job_name: frm.doc.name, reason: vals.reason },
							freeze: true,
							callback: () => frm.reload_doc()
						});
					},
					__("Pause Work"),
					__("Pause")
				);
			}).addClass("btn-warning");

			frm.add_custom_button(__("Complete Job"), () => {
				frappe.confirm(__("Are you sure you have finished all work on this job?"), () => {
					frappe.call({
						method: "vehicle_service.vehicle_service.doctype.service_job.service_job.complete_job",
						args: { job_name: frm.doc.name },
						freeze: true,
						callback: () => frm.reload_doc()
					});
				});
			}).addClass("btn-success");
		}

		// 4. Resume Work (if Paused)
		if (frm.doc.status === "Paused") {
			frm.add_custom_button(__("Resume Work"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_job.service_job.start_job",
					args: { job_name: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc()
				}).addClass("btn-primary");
			});

			frm.add_custom_button(__("Complete Job"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_job.service_job.complete_job",
					args: { job_name: frm.doc.name },
					freeze: true,
					callback: () => frm.reload_doc()
				}).addClass("btn-success");
			});
		}

		// 5. Report Additional Work (Technician discovery)
		if (["In Progress", "Paused", "Assigned"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Report Additional Defect / Work"), () => {
				const d = new frappe.ui.Dialog({
					title: __("Report Additional Work Discovered"),
					fields: [
						{ fieldname: "job_title", label: __("Job Title / Finding"), fieldtype: "Data", reqd: 1 },
						{ fieldname: "category", label: __("Urgency / Category"), fieldtype: "Select", options: "Essential\nRecommended\nOptional", default: "Essential" },
						{ fieldname: "estimated_hours", label: __("Estimated Labour Hours"), fieldtype: "Float", default: 1.0 },
						{ fieldname: "description", label: __("Detailed Observation"), fieldtype: "Small Text", reqd: 1 }
					],
					primary_action_label: __("Submit for Customer Approval"),
					primary_action: (vals) => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_job.service_job.report_additional_work",
							args: {
								service_order: frm.doc.service_order,
								job_title: vals.job_title,
								estimated_hours: vals.estimated_hours,
								category: vals.category,
								description: vals.description
							},
							freeze: true,
							callback: () => {
								d.hide();
								frappe.show_alert({ message: __("Additional work logged and submitted for advisor review."), indicator: "orange" });
							}
						});
					}
				});
				d.show();
			}, __("Actions"));
		}
	}
});
