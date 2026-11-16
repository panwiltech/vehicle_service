// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Vehicle Intake", {
	setup(frm) {
		frm._current_step = 1;
	},

	onload(frm) {
		if (!frm.doc.service_advisor || frm.doc.service_advisor === "frappe.session.user") {
			frm.set_value("service_advisor", frappe.session.user);
		}
		if (frm.doc.vehicle) {
			frm.trigger("fetch_vehicle_meta");
		}
	},

	refresh(frm) {
		if (frm.page && frm.page.wrapper) {
			frm.page.wrapper.addClass("vehicle-intake-wide-form");
			if (!frm._wide_style_injected) {
				frm._wide_style_injected = true;
				const wideStyle = `
					<style id="vehicle-intake-wide-form-style">
						.vehicle-intake-wide-form .std-form-layout .section-head,
						.vehicle-intake-wide-form .std-form-layout .section-body {
							max-width: 100% !important;
							margin-left: 0 !important;
							margin-right: 0 !important;
							padding-left: 14px !important;
							padding-right: 14px !important;
						}
						.vehicle-intake-wide-form .form-section {
							padding-left: 14px !important;
							padding-right: 14px !important;
						}
						.vehicle-intake-wide-form .form-layout .form-page {
							padding-left: 8px !important;
							padding-right: 8px !important;
						}
						.vehicle-intake-wide-form .form-section-description,
						.vehicle-intake-wide-form .form-footer {
							max-width: 100% !important;
						}
					</style>
				`;
				$(wideStyle).appendTo(frm.page.wrapper);
			}
		}

		// 1. Wizard Setup (when Draft or New)
		if (frm.doc.status === "Draft") {
			frm.trigger("setup_wizard");
			frm.add_custom_button(__("+ Register New Vehicle"), () => {
				frm.trigger("show_quick_register_dialog");
			});
		} else {
			// Show all sections when Checked In or Cancelled
			frm.trigger("show_all_sections");
			frm.trigger("render_completed_banner");
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

	vehicle(frm) {
		if (frm.doc.vehicle) {
			frm.trigger("fetch_vehicle_meta");
		}
	},

	fetch_vehicle_meta(frm) {
		if (!frm.doc.vehicle) return;
		frappe.db.get_value(
			"Service Vehicle",
			frm.doc.vehicle,
			["customer", "customer_name", "make", "model", "year", "current_mileage", "driver_name", "driver_phone", "vin", "registration_no"],
			(r) => {
				if (r) {
					frm._vehicle_current_mileage = r.current_mileage || 0;
					if (r.customer && (!frm.doc.customer || frm.doc.customer !== r.customer)) {
						frm.set_value("customer", r.customer);
					}
					if (r.customer_name && !frm.doc.customer_name) {
						frm.set_value("customer_name", r.customer_name);
					}
					if (r.driver_name && !frm.doc.driver_name) {
						frm.set_value("driver_name", r.driver_name);
					}
					if (r.driver_phone && !frm.doc.driver_phone) {
						frm.set_value("driver_phone", r.driver_phone);
					}
					if (r.current_mileage && !frm.doc.odometer_in) {
						frm.set_value("odometer_in", r.current_mileage);
					}
					if (r.vin && !frm.doc.vin) {
						frm.set_value("vin", r.vin);
					}
					if (r.registration_no && !frm.doc.license_plate) {
						frm.set_value("license_plate", r.registration_no);
					}
				}
			}
		);
	},

	setup_wizard(frm) {
		frm._current_step = frm._current_step || 1;
		if (!frm.doc.service_advisor || frm.doc.service_advisor === "frappe.session.user") {
			frm.set_value("service_advisor", frappe.session.user);
		}
		if (!frm.doc.company || (frm.doc.company && frm.doc.company.includes("frappe.defaults"))) {
			const defaultCompany = frappe.defaults.get_default("Company") || frappe.defaults.get_user_default("Company");
			if (defaultCompany) {
				frm.set_value("company", defaultCompany);
			}
		}
		frm.trigger("render_wizard_view");
	},

	show_all_sections(frm) {
		frm.set_df_property("sb_step_1_vehicle", "hidden", 0);
		frm.set_df_property("sb_step_2_condition", "hidden", 0);
		frm.set_df_property("sb_photos", "hidden", 0);
		frm.set_df_property("sb_step_3_review", "hidden", 0);
		frm.set_df_property("sb_signoff", "hidden", 0);
		frm.set_df_property("sb_status", "hidden", 0);
	},

	render_completed_banner(frm) {
		const html = `
			<div class="alert alert-success d-flex align-items-center justify-content-between p-2 mb-2" style="border-radius: 6px;">
				<div>
					<h6 class="mb-0 font-weight-bold" style="color: #155724;"><i class="fa fa-check-circle mr-1 text-success"></i>${__("Vehicle Checked In")}</h6>
					<div class="text-muted small">${__("Checked in on")} <strong>${frm.doc.checked_in_on || frm.doc.modified}</strong> ${__("by")} <strong>${frm.doc.checked_in_by || frm.doc.owner}</strong>. ${__("Arrival details and signature are locked.")}</div>
				</div>
				${frm.doc.service_order ? `<button class="btn btn-xs btn-primary" onclick="frappe.set_route('Form', 'Service Order', '${frm.doc.service_order}')"><i class="fa fa-wrench mr-1"></i>${__("View Service Order")} (${frm.doc.service_order})</button>` : ''}
			</div>
		`;
		frm.set_df_property("step_progress_html", "options", html);
	},

	render_wizard_view(frm) {
		const step = frm._current_step || 1;

		// Toggle section visibility based on step
		frm.set_df_property("sb_step_1_vehicle", "hidden", step === 1 ? 0 : 1);
		frm.set_df_property("sb_step_2_condition", "hidden", step === 2 ? 0 : 1);
		frm.set_df_property("sb_photos", "hidden", step === 2 ? 0 : 1);
		frm.set_df_property("sb_step_3_review", "hidden", step === 3 ? 0 : 1);
		frm.set_df_property("sb_signoff", "hidden", step === 3 ? 0 : 1);
		frm.set_df_property("sb_status", "hidden", 1); // keep status collapsed in wizard mode

		// Render Stepper HTML
		frm.trigger("render_stepper_indicator");

		// If on Step 3, compile review summary
		if (step === 3) {
			frm.trigger("render_review_card");
		}
	},

	render_stepper_indicator(frm) {
		const current = frm._current_step || 1;
		const steps = [
			{ num: 1, title: __("Vehicle & Customer"), desc: __("Vehicle & Owner Info") },
			{ num: 2, title: __("Condition & Scope"), desc: __("Complaint, Fuel & Photos") },
			{ num: 3, title: __("Review & Sign-Off"), desc: __("Summary & Signature") }
		];

		let stepsHtml = steps.map(s => {
			let statusClass = "pending";
			let badge = `<span class="step-num">${s.num}</span>`;
			if (s.num < current) {
				statusClass = "completed";
				badge = `<span class="step-num"><i class="fa fa-check"></i></span>`;
			} else if (s.num === current) {
				statusClass = "active";
			}

			return `
				<div class="intake-step-item ${statusClass}" data-step="${s.num}">
					<div class="step-badge">${badge}</div>
					<div class="step-content">
						<div class="step-title">${s.title}</div>
						<div class="step-desc text-muted">${s.desc}</div>
					</div>
				</div>
			`;
		}).join('<div class="step-connector"></div>');

		let navButtonsHtml = `
			<div class="intake-wizard-nav d-flex justify-content-between align-items-center mt-2 pt-2" style="border-top: 1px solid var(--border-color, #e2e8f0);">
				<div>
					${current > 1 ? `
						<button class="btn btn-secondary btn-sm btn-wizard-back mr-2">
							<i class="fa fa-arrow-left mr-1"></i>${__("Back")}
						</button>
					` : `
						<button class="btn btn-outline-secondary btn-sm btn-quick-reg">
							<i class="fa fa-plus mr-1"></i>${__("Register New Vehicle")}
						</button>
					`}
				</div>
				<div class="text-muted small">
					${__("Step {0} of {1}", [current, 3])}
				</div>
				<div>
					${current < 3 ? `
						<button class="btn btn-primary btn-sm btn-wizard-next">
							${__("Next Step")}<i class="fa fa-arrow-right ml-1"></i>
						</button>
					` : `
						<button class="btn btn-success btn-sm btn-wizard-complete">
							<i class="fa fa-check-circle mr-1"></i>${__("Complete Check-In")}
						</button>
					`}
				</div>
			</div>
		`;

		const fullHtml = `
			<style>
				.intake-stepper-container {
					background: var(--card-bg, #ffffff);
					border: 1px solid var(--border-color, #e2e8f0);
					border-radius: 6px;
					padding: 8px 12px;
					margin-bottom: 8px;
					box-shadow: 0 1px 2px rgba(0,0,0,0.03);
				}
				.intake-stepper-header {
					display: flex;
					align-items: center;
					justify-content: space-between;
				}
				.intake-step-item {
					display: flex;
					align-items: center;
					cursor: pointer;
					gap: 6px;
					user-select: none;
				}
				.step-badge .step-num {
					display: inline-flex;
					align-items: center;
					justify-content: center;
					width: 26px;
					height: 26px;
					border-radius: 50%;
					font-weight: 600;
					font-size: 11px;
					background: var(--bg-light-gray, #f1f5f9);
					color: var(--text-muted, #64748b);
					border: 1.5px solid var(--border-color, #cbd5e1);
					transition: all 0.2s ease;
				}
				.intake-step-item.active .step-badge .step-num {
					background: var(--primary, #1d4ed8);
					color: #ffffff;
					border-color: var(--primary, #1d4ed8);
					box-shadow: 0 0 0 2px rgba(29, 78, 216, 0.2);
				}
				.intake-step-item.completed .step-badge .step-num {
					background: #10b981;
					color: #ffffff;
					border-color: #10b981;
				}
				.intake-step-item .step-title {
					font-weight: 600;
					font-size: 12px;
					color: var(--text-color, #1e293b);
				}
				.intake-step-item.active .step-title {
					color: var(--primary, #1d4ed8);
				}
				.intake-step-item .step-desc {
					font-size: 10px;
					line-height: 1.1;
				}
				.step-connector {
					flex: 1;
					height: 2px;
					background: var(--border-color, #e2e8f0);
					margin: 0 8px;
				}
			</style>
			<div class="intake-stepper-container">
				<div class="intake-stepper-header">
					${stepsHtml}
				</div>
				${navButtonsHtml}
			</div>
		`;

		frm.set_df_property("step_progress_html", "options", fullHtml);

		// Bind events on rendered buttons
		const $wrapper = frm.fields_dict.step_progress_html.$wrapper;
		if ($wrapper) {
			$wrapper.off("click", ".intake-step-item").on("click", ".intake-step-item", function () {
				const target = cint($(this).attr("data-step"));
				if (target < frm._current_step) {
					frm._current_step = target;
					frm.trigger("render_wizard_view");
				} else if (target > frm._current_step) {
					if (frm.trigger("validate_step", frm._current_step)) {
						frm._current_step = target;
						frm.trigger("render_wizard_view");
					}
				}
			});

			$wrapper.off("click", ".btn-wizard-next").on("click", ".btn-wizard-next", function (e) {
				e.preventDefault();
				if (frm.trigger("validate_step", frm._current_step)) {
					frm._current_step = Math.min(3, (frm._current_step || 1) + 1);
					frm.trigger("render_wizard_view");
				}
			});

			$wrapper.off("click", ".btn-wizard-back").on("click", ".btn-wizard-back", function (e) {
				e.preventDefault();
				frm._current_step = Math.max(1, (frm._current_step || 1) - 1);
				frm.trigger("render_wizard_view");
			});

			$wrapper.off("click", ".btn-quick-reg").on("click", ".btn-quick-reg", function (e) {
				e.preventDefault();
				frm.trigger("show_quick_register_dialog");
			});

			$wrapper.off("click", ".btn-wizard-complete").on("click", ".btn-wizard-complete", function (e) {
				e.preventDefault();
				frm.trigger("submit_complete_check_in");
			});
		}
	},

	validate_step(frm, step) {
		if (step === 1) {
			if (!frm.doc.vehicle) {
				frappe.msgprint({
					title: __("Vehicle Required"),
					message: __("Please select a Vehicle or use <strong>Register New Vehicle</strong> to proceed."),
					indicator: "orange"
				});
				return false;
			}
			if (frm.doc.odometer_in === undefined || frm.doc.odometer_in === null || frm.doc.odometer_in === "") {
				frappe.msgprint({
					title: __("Odometer Reading Required"),
					message: __("Please enter the current Odometer In reading."),
					indicator: "orange"
				});
				return false;
			}
			if (frm._vehicle_current_mileage && frm.doc.odometer_in < frm._vehicle_current_mileage) {
				frappe.msgprint({
					title: __("Odometer In Violation"),
					message: __("Odometer In ({0} km) cannot be less than the vehicle's last recorded mileage ({1} km).", [frm.doc.odometer_in, frm._vehicle_current_mileage]),
					indicator: "red"
				});
				return false;
			}
			if (!frm.doc.customer) {
				frappe.msgprint({
					title: __("Customer Required"),
					message: __("Please select or confirm the Customer for this vehicle."),
					indicator: "orange"
				});
				return false;
			}
		}

		if (step === 2) {
			if (!frm.doc.customer_complaint || !frm.doc.customer_complaint.trim()) {
				frappe.msgprint({
					title: __("Customer Complaint Required"),
					message: __("Please document the customer's reported issue or requested service scope."),
					indicator: "orange"
				});
				return false;
			}
			if (!frm.doc.fuel_level) {
				frappe.msgprint({
					title: __("Fuel Level Required"),
					message: __("Please record the vehicle's fuel level upon arrival."),
					indicator: "orange"
				});
				return false;
			}
		}

		if (step === 3) {
			if (!frm.doc.intake_confirmed) {
				frappe.msgprint({
					title: __("Confirmation Required"),
					message: __("Please confirm that the customer has verified the intake details."),
					indicator: "orange"
				});
				return false;
			}
			if (!frm.doc.customer_signature) {
				frappe.msgprint({
					title: __("Customer Signature Required"),
					message: __("A valid Customer Signature is required to finalize vehicle check-in."),
					indicator: "orange"
				});
				return false;
			}
		}

		return true;
	},

	render_review_card(frm) {
		const photoCount = (frm.doc.intake_photos || []).length;
		const html = `
			<div class="card p-2.5 my-1.5" style="background: var(--bg-light-gray, #f8fafc); border: 1px solid var(--border-color, #e2e8f0); border-radius: 6px;">
				<h6 class="font-weight-bold text-uppercase mb-2" style="letter-spacing: 0.5px; font-size: 12px; color: var(--text-color, #1e293b);">
					<i class="fa fa-file-text-o mr-1"></i>${__("Vehicle Intake Summary")}
				</h6>
				<div class="row">
					<div class="col-md-6 mb-2">
						<span class="text-muted small">${__("Vehicle")}:</span>
						<div><strong>${frappe.utils.escape_html(frm.doc.vehicle || "—")}</strong> (${frappe.utils.escape_html(frm.doc.vehicle_description || "")})</div>
					</div>
					<div class="col-md-6 mb-2">
						<span class="text-muted small">${__("Odometer In")}:</span>
						<div><strong>${frm.doc.odometer_in ? frm.doc.odometer_in + " km" : "—"}</strong></div>
					</div>
					<div class="col-md-6 mb-2">
						<span class="text-muted small">${__("Customer")}:</span>
						<div><strong>${frappe.utils.escape_html(frm.doc.customer_name || frm.doc.customer || "—")}</strong></div>
					</div>
					<div class="col-md-6 mb-2">
						<span class="text-muted small">${__("Driver / Contact")}:</span>
						<div><strong>${frappe.utils.escape_html(frm.doc.driver_name || "—")}</strong> (${frappe.utils.escape_html(frm.doc.driver_phone || "No phone")})</div>
					</div>
					<div class="col-md-6 mb-2">
						<span class="text-muted small">${__("Fuel Level")}:</span>
						<div><span class="badge badge-info p-1">${frappe.utils.escape_html(frm.doc.fuel_level || "Not specified")}</span></div>
					</div>
					<div class="col-md-6 mb-2">
						<span class="text-muted small">${__("Inspection Photos")}:</span>
						<div><strong>${photoCount}</strong> ${__("photo(s) attached")}</div>
					</div>
					<div class="col-12 mb-2">
						<span class="text-muted small">${__("Reported Complaint / Scope")}:</span>
						<div class="p-2 bg-white rounded border">${frappe.utils.escape_html(frm.doc.customer_complaint || "—")}</div>
					</div>
					${frm.doc.existing_damage ? `
						<div class="col-12 mb-2">
							<span class="text-muted small">${__("Existing Damages Noted")}:</span>
							<div class="p-2 bg-white rounded border text-danger">${frappe.utils.escape_html(frm.doc.existing_damage)}</div>
						</div>
					` : ''}
					${frm.doc.vehicle_contents ? `
						<div class="col-12 mb-2">
							<span class="text-muted small">${__("Declared Contents / Valuables")}:</span>
							<div class="p-2 bg-white rounded border">${frappe.utils.escape_html(frm.doc.vehicle_contents)}</div>
						</div>
					` : ''}
				</div>
			</div>
		`;
		frm.set_df_property("step_review_html", "options", html);
	},

	submit_complete_check_in(frm) {
		if (!frm.trigger("validate_step", 3)) return;

		const proceed_with_finalize = () => {
			if (frm.is_new()) {
				frappe.msgprint({
					title: __("Save Required"),
					message: __("Please save the Vehicle Intake before completing check-in."),
					indicator: "orange"
				});
				return;
			}
			frappe.confirm(
				__("Are you sure you want to complete check-in? Arrival details and signature will be permanently locked."),
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
		};

		if (frm.is_new() || frm.is_dirty()) {
			frm.save().then(() => {
				if (!frm.is_new()) {
					proceed_with_finalize();
				}
			});
		} else {
			proceed_with_finalize();
		}
	},

	show_quick_register_dialog(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Quick Register Service Vehicle"),
			fields: [
				{
					fieldname: "registration_no",
					label: __("Registration No / License Plate"),
					fieldtype: "Data",
					reqd: 1
				},
				{
					fieldname: "make",
					label: __("Make"),
					fieldtype: "Data",
					reqd: 1
				},
				{
					fieldname: "model",
					label: __("Model"),
					fieldtype: "Data",
					reqd: 1
				},
				{
					fieldname: "year",
					label: __("Year"),
					fieldtype: "Int"
				},
				{
					fieldname: "col_brk_1",
					fieldtype: "Column Break"
				},
				{
					fieldname: "vin",
					label: __("VIN / Chassis No"),
					fieldtype: "Data"
				},
				{
					fieldname: "colour",
					label: __("Colour"),
					fieldtype: "Data"
				},
				{
					fieldname: "current_mileage",
					label: __("Current Mileage (km)"),
					fieldtype: "Int",
					default: frm.doc.odometer_in || 0
				},
				{
					fieldname: "sec_brk_owner",
					label: __("Owner & Driver"),
					fieldtype: "Section Break"
				},
				{
					fieldname: "customer",
					label: __("Customer (Owner)"),
					fieldtype: "Link",
					options: "Customer",
					reqd: 1,
					default: frm.doc.customer || ""
				},
				{
					fieldname: "col_brk_2",
					fieldtype: "Column Break"
				},
				{
					fieldname: "driver_name",
					label: __("Driver / Agent Name"),
					fieldtype: "Data",
					default: frm.doc.driver_name || ""
				},
				{
					fieldname: "driver_phone",
					label: __("Driver Phone"),
					fieldtype: "Data",
					default: frm.doc.driver_phone || ""
				}
			],
			primary_action_label: __("Register Vehicle"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake.quick_register_vehicle",
					args: {
						registration_no: vals.registration_no,
						make: vals.make,
						model: vals.model,
						year: vals.year,
						vin: vals.vin,
						colour: vals.colour,
						current_mileage: vals.current_mileage,
						customer: vals.customer,
						driver_name: vals.driver_name,
						driver_phone: vals.driver_phone
					},
					freeze: true,
					freeze_message: __("Registering Service Vehicle..."),
					callback: (r) => {
						if (!r.exc && r.message && r.message.vehicle) {
							d.hide();
							frappe.show_alert({
								message: __("Vehicle {0} registered successfully", [r.message.vehicle]),
								indicator: "green"
							});
							frm.set_value("vehicle", r.message.vehicle);
							if (vals.current_mileage && !frm.doc.odometer_in) {
								frm.set_value("odometer_in", vals.current_mileage);
							}
						}
					}
				});
			}
		});
		d.show();
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
