// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Order", {
	refresh(frm) {
		frm.trigger("render_status_stepper");
		frm.trigger("setup_jobs_tab_actions");
		frm.trigger("setup_parts_tab_actions");
		frm.trigger("setup_custom_buttons");

		const isPartsAuthorized = frappe.user_roles.includes("Parts Controller") ||
			frappe.user_roles.includes("Parts Manager") ||
			frappe.user_roles.includes("System Manager") ||
			frappe.session.user === "Administrator";
		const isRestrictedRole = frappe.user_roles.includes("Job Controller") ||
			frappe.user_roles.includes("Service Advisor");

		if (isRestrictedRole && !isPartsAuthorized) {
			frm.set_df_property("parts", "cannot_add_rows", true);
			frm.set_df_property("parts", "cannot_delete_rows", true);
		}
	},

	vehicle(frm) {
		if (frm.doc.vehicle) {
			frappe.db.get_value(
				"Service Vehicle",
				frm.doc.vehicle,
				["customer", "customer_name", "make", "model", "year", "current_mileage", "driver_name", "driver_phone", "current_location"],
				(r) => {
					if (r) {
						if (r.customer && (!frm.doc.customer || frm.doc.customer !== r.customer)) {
							frm.set_value("customer", r.customer);
						}
						const descParts = [r.make, r.model, r.year ? `(${r.year})` : ""].filter(Boolean).join(" ");
						if (descParts && !frm.doc.vehicle_description) {
							frm.set_value("vehicle_description", descParts);
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
						if (r.current_location && !frm.doc.current_location) {
							frm.set_value("current_location", r.current_location);
						}
					}
				}
			);
		}
	},

	render_status_stepper(frm) {
		if (frm.is_new()) {
			frm.set_df_property("status_html", "options", "");
			return;
		}

		let html = "";

		if (frm.doc.status === "Paused") {
			html += `<div class="alert alert-warning" style="margin-bottom:15px;"><strong>⏸ PAUSED:</strong> ${frappe.utils.escape_html(frm.doc.pause_reason || 'Awaiting Approval')}</div>`;
		}
		if (frm.doc.on_hold) {
			html += `<div class="alert alert-warning" style="margin-bottom:15px;"><strong>⚠ ON HOLD:</strong> ${frappe.utils.escape_html(frm.doc.hold_reason || 'No reason specified')}</div>`;
		}
		if (frm.doc.disputed) {
			html += `<div class="alert alert-danger" style="margin-bottom:15px;"><strong>⚠ DISPUTED:</strong> ${frappe.utils.escape_html(frm.doc.dispute_notes || 'Invoice under dispute')}</div>`;
		}

		frm.set_df_property("status_html", "options", html);

		if (frm.doc.sales_invoice) {
			frappe.db.get_value("Sales Invoice", frm.doc.sales_invoice, ["docstatus"]).then(r => {
				if (r && r.message) {
					const inv = r.message;
					if (inv.docstatus === 1) {
						frappe.db.get_value("Sales Invoice", {
							return_against: frm.doc.sales_invoice,
							is_return: 1,
							docstatus: 1
						}, "name").then(cnRes => {
							const hasCreditNote = cnRes && cnRes.message && cnRes.message.name;
							if (!hasCreditNote) {
								frm.disable_save();
								frm.set_read_only();
							}
						});
					}
				}
			});
		}
	},

	setup_custom_buttons(frm) {
		if (frm.is_new()) return;

		const userRoles = frappe.user_roles || [];
		const isJobController = userRoles.includes("Job Controller") || userRoles.includes("System Manager");
		const isCompleted = ["Ready for Billing", "Invoiced", "Ready for Collection", "Delivered"].includes(frm.doc.status) || frm.doc.board_status === "Completed";

		// If order is completed and user is Job Controller (and not System Manager), disable form
		if (isCompleted && userRoles.includes("Job Controller") && !userRoles.includes("System Manager")) {
			frm.disable_form();
		}

		// Job Control button group for Job Controller
		if (isJobController && !isCompleted && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Add Job"), () => {
				frm.trigger("show_add_job_dialog");
			}, __("Job Control"));

			frm.add_custom_button(__("Assign Technician"), () => {
				frm.trigger("show_assign_job_dialog");
			}, __("Job Control"));

			frm.add_custom_button(__("Start Clock"), () => {
				frm.trigger("start_selected_job");
			}, __("Job Control"));

			frm.add_custom_button(__("Pause Clock"), () => {
				frm.trigger("pause_selected_job");
			}, __("Job Control"));

			frm.add_custom_button(__("Complete Job"), () => {
				frappe.confirm(
					__("Mark all workshop jobs as completed and move this Service Order to Ready for Billing?"),
					() => {
						frappe.call({
							method: "vehicle_service.job_control.complete_service_order",
							args: { order_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Completing Service Order..."),
							callback: (r) => {
								if (!r.exc) {
									frappe.show_alert({ message: __("Service Order marked Completed (Ready for Billing)"), indicator: "green" });
									frm.reload_doc();
								}
							}
						});
					}
				);
			}, __("Job Control")).addClass("btn-primary");
		}

		// 1. Check-in Button (if Draft)
		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Check In Vehicle"), () => {
				frm.trigger("show_check_in_dialog");
			}).addClass("btn-primary");
		}

		// 2. Correct Intake Button (if intake frozen & active)
		if (frm.doc.intake_frozen && frm.doc.status !== "Delivered" && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Correct Intake"), () => {
				frm.trigger("show_intake_correction_dialog");
			}, __("Actions"));
		}

		// 3. Dynamic Quotation Buttons (Create vs View vs Approval)
		frappe.db.get_list("Quotation", {
			filters: { vs_service_order: frm.doc.name, docstatus: ["!=", 2] },
			fields: ["name", "docstatus"],
			order_by: "creation desc",
			limit: 1
		}).then((qRes) => {
			const hasQuotation = qRes && qRes.length > 0;
			const qName = hasQuotation ? qRes[0].name : null;

			if (hasQuotation) {
				frm.add_custom_button(__("View Quotation"), () => {
					frappe.set_route("Form", "Quotation", qName);
				}).addClass("btn-secondary");

				if (["Paused", "Awaiting Approval", "In Progress"].includes(frm.doc.status)) {
					frm.add_custom_button(__("Record Customer Approval"), () => {
						frm.trigger("show_approval_dialog");
					}).addClass("btn-primary");
				}
			} else if (["Draft", "Checked In", "In Progress"].includes(frm.doc.status)) {
				frm.add_custom_button(__("Create Quotation"), () => {
					frappe.call({
						method: "vehicle_service.vehicle_service.doctype.service_order.service_order.make_service_quotation",
						args: { order_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Preparing Quotation..."),
						callback: (r) => {
							if (!r.exc && r.message && r.message.quotation) {
								frappe.set_route("Form", "Quotation", r.message.quotation);
							}
						}
					});
				}).addClass("btn-primary");
			}
		});

		// 3b. Create / Revise Estimate in Actions menu
		if (["Checked In", "Awaiting Approval", "Approved", "Waiting for Parts", "Ready for Work", "In Progress", "Paused"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Create / Update Estimate"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.create_estimate",
					args: { order_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating Quotation Estimate..."),
					callback: (r) => {
						if (!r.exc) {
							frappe.show_alert({ message: __("Estimate Quotation {0} created", [r.message.quotation]), indicator: "green" });
							frm.reload_doc();
						}
					}
				});
			}, __("Actions"));
		}

		// 5. Parts Issue / Return actions
		if (["Checked In", "Approved", "Waiting for Parts", "Ready for Work", "In Progress"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Issue Selected Parts"), () => {
				frm.trigger("show_parts_issue_dialog");
			}, __("Parts Control"));

			frm.add_custom_button(__("Return Parts from Workshop"), () => {
				frm.trigger("show_parts_return_dialog");
			}, __("Parts Control"));
		}

		// 6. Workshop Completion & QC actions
		if (["Approved", "Waiting for Parts", "Ready for Work", "In Progress", "QC"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Complete & Create Invoice"), () => {
				frappe.confirm(
					__("Complete all workshop jobs and generate the Sales Invoice directly?"),
					() => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_order.service_order.complete_and_create_invoice",
							args: { order_name: frm.doc.name },
							freeze: true,
							freeze_message: __("Completing Workshop & Generating Sales Invoice..."),
							callback: (r) => {
								if (!r.exc && r.message && r.message.sales_invoice) {
									frappe.show_alert({ message: __("Sales Invoice {0} created", [r.message.sales_invoice]), indicator: "green" });
									frappe.set_route("Form", "Sales Invoice", r.message.sales_invoice);
								} else {
									frm.reload_doc();
								}
							}
						});
					}
				);
			}).addClass("btn-primary");

			frm.add_custom_button(__("Complete Workshop (Ready for Billing)"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.complete_and_ready_for_billing",
					args: { order_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Marking Workshop Completed..."),
					callback: (r) => {
						if (!r.exc) {
							frappe.show_alert({ message: __("Service Order marked Ready for Billing"), indicator: "green" });
							frm.reload_doc();
						}
					}
				});
			}, __("Actions"));
		}

		if (frm.doc.status === "QC") {
			frm.add_custom_button(__("Start QC Inspection"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_qc.service_qc.create_qc_inspection",
					args: { service_order: frm.doc.name },
					freeze: true,
					callback: (r) => {
						if (!r.exc && r.message && r.message.qc_name) {
							frappe.set_route("Form", "Service QC", r.message.qc_name);
						}
					}
				});
			}, __("Actions"));
		}

		// 7. Create Sales Invoice (if Ready for Billing)
		if (frm.doc.status === "Ready for Billing") {
			frm.add_custom_button(__("Create Sales Invoice"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.create_sales_invoice_from_order",
					args: { order_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Generating Sales Invoice..."),
					callback: (r) => {
						if (!r.exc && r.message && r.message.sales_invoice) {
							frappe.set_route("Form", "Sales Invoice", r.message.sales_invoice);
						}
					}
				});
			}).addClass("btn-primary");
		}

		if (frm.doc.sales_invoice) {
			frm.add_custom_button(__("View Sales Invoice"), () => {
				frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice);
			});
		}

		// 8. Release on Credit (if Invoiced)
		if (frm.doc.status === "Invoiced" && !frm.doc.credit_released) {
			frm.add_custom_button(__("Authorise Release on Credit"), () => {
				frappe.prompt(
					[
						{
							fieldname: "reason",
							label: __("Credit Release Reason / Fleet Reference"),
							fieldtype: "Small Text",
							reqd: 1
						}
					],
					(vals) => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_order.service_order.release_on_credit",
							args: { order_name: frm.doc.name, reason: vals.reason },
							freeze: true,
							callback: () => frm.reload_doc()
						});
					},
					__("Authorise Release on Credit"),
					__("Authorise")
				);
			}, __("Actions"));
		}

		// 9. Deliver Vehicle (if Ready for Collection)
		if (frm.doc.status === "Ready for Collection") {
			frm.add_custom_button(__("Deliver Vehicle"), () => {
				frm.trigger("show_delivery_dialog");
			}).addClass("btn-success");
		}

		// 10. Cancel Order (if not already closed)
		if (frm.doc.status !== "Delivered" && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Cancel Service Order"), () => {
				frappe.prompt(
					[
						{
							fieldname: "reason",
							label: __("Cancellation Reason"),
							fieldtype: "Small Text",
							reqd: 1
						}
					],
					(vals) => {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_order.service_order.cancel_order",
							args: { order_name: frm.doc.name, reason: vals.reason },
							freeze: true,
							callback: () => frm.reload_doc()
						});
					},
					__("Confirm Order Cancellation"),
					__("Cancel Order")
				);
			}, __("Actions"));
		}
	},

	show_check_in_dialog(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Vehicle Check-in & Intake Intake"),
			fields: [
				{ fieldname: "odometer_in", label: __("Odometer In (km)"), fieldtype: "Int", reqd: 1, default: frm.doc.odometer_in },
				{ fieldname: "fuel_level", label: __("Fuel Level"), fieldtype: "Select", options: "\nEmpty\n1/4\n1/2\n3/4\nFull", reqd: 1, default: frm.doc.fuel_level || "1/2" },
				{ fieldname: "col_brk_1", fieldtype: "Column Break" },
				{ fieldname: "customer_complaint", label: __("Customer Complaint"), fieldtype: "Small Text", reqd: 1, default: frm.doc.customer_complaint },
				{ fieldname: "sec_brk_1", label: __("Vehicle Inspection on Arrival"), fieldtype: "Section Break" },
				{ fieldname: "existing_damage", label: __("Existing Scratches / Dents / Damage"), fieldtype: "Small Text", default: frm.doc.existing_damage },
				{ fieldname: "col_brk_2", fieldtype: "Column Break" },
				{ fieldname: "vehicle_contents", label: __("Valuables / Spare Wheel / Tools Present"), fieldtype: "Small Text", default: frm.doc.vehicle_contents },
				{ fieldname: "sec_brk_2", label: __("Confirmation"), fieldtype: "Section Break" },
				{ fieldname: "intake_confirmed", label: __("Customer verbally agreed or confirmed condition"), fieldtype: "Check", default: 1 }
			],
			primary_action_label: __("Complete Check-In"),
			primary_action: (values) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.check_in_vehicle",
					args: {
						order_name: frm.doc.name,
						odometer_in: values.odometer_in,
						fuel_level: values.fuel_level,
						customer_complaint: values.customer_complaint,
						existing_damage: values.existing_damage,
						vehicle_contents: values.vehicle_contents,
						intake_confirmed: values.intake_confirmed
					},
					freeze: true,
					freeze_message: __("Processing Intake & Freezing Details..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frm.reload_doc();
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
			{ label: __("Existing Damage"), value: "existing_damage" },
			{ label: __("Vehicle Contents"), value: "vehicle_contents" }
		];

		const d = new frappe.ui.Dialog({
			title: __("Correct Intake Information (Audited)"),
			fields: [
				{
					fieldname: "field",
					label: __("Field to Correct"),
					fieldtype: "Select",
					options: fields.map(f => f.label).join("\n"),
					reqd: 1,
					onchange: () => {
						const sel = d.get_value("field");
						const match = fields.find(f => f.label === sel);
						if (match) {
							d.set_value("current_val", frm.doc[match.value] || "");
						}
					}
				},
				{ fieldname: "current_val", label: __("Current Value"), fieldtype: "Data", read_only: 1 },
				{ fieldname: "new_value", label: __("New Correct Value"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "reason", label: __("Reason for Correction (Mandatory)"), fieldtype: "Small Text", reqd: 1 }
			],
			primary_action_label: __("Save Correction"),
			primary_action: (vals) => {
				const match = fields.find(f => f.label === vals.field);
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.correct_intake",
					args: {
						order_name: frm.doc.name,
						fieldname: match.value,
						new_value: vals.new_value,
						reason: vals.reason
					},
					freeze: true,
					callback: () => {
						d.hide();
						frm.reload_doc();
					}
				});
			}
		});
		d.show();
	},

	show_approval_dialog(frm) {
		// Find latest quotation for this order
		frappe.db.get_list("Quotation", {
			filters: { vs_service_order: frm.doc.name, docstatus: ["in", [0, 1]] },
			fields: ["name"],
			order_by: "creation desc",
			limit: 1
		}).then((res) => {
			if (!res || !res.length) {
				frappe.msgprint(__("No open Quotation found for this order. Please create an estimate first."));
				return;
			}
			const qName = res[0].name;

			frappe.model.with_doc("Quotation", qName, () => {
				const qDoc = frappe.get_doc("Quotation", qName);
				let dialogFields = [
					{ fieldname: "approval_method", label: __("Approval Method"), fieldtype: "Select", options: "Phone\nIn Person\nEmail\nWhatsApp\nSigned", default: "Phone", reqd: 1 },
					{ fieldname: "approved_by_customer", label: __("Customer Contact Name"), fieldtype: "Data", default: frm.doc.driver_name || frm.doc.customer_name },
					{ fieldname: "notes", label: __("Approval Notes"), fieldtype: "Small Text" },
					{ fieldname: "sb_items", label: __("Line-by-Line Customer Decisions"), fieldtype: "Section Break" }
				];

				qDoc.items.forEach((item, idx) => {
					let catLabel = item.vs_category ? `[${item.vs_category}] ` : "";
					dialogFields.push({
						fieldname: `item_${item.name}`,
						label: `${catLabel}${item.item_name || item.item_code} (Qty: ${item.qty} × ${item.rate} = ${item.amount})`,
						fieldtype: "Select",
						options: "Approved\nDeclined",
						default: "Approved",
						reqd: 1
					});
				});

				const d = new frappe.ui.Dialog({
					title: __("Record Customer Approval ({0})", [qName]),
					fields: dialogFields,
					primary_action_label: __("Confirm Customer Approval"),
					primary_action: (values) => {
						let decisions = {};
						qDoc.items.forEach((item) => {
							decisions[item.name] = values[`item_${item.name}`] || "Approved";
						});

						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_order.service_order.record_customer_approval",
							args: {
								order_name: frm.doc.name,
								quotation_name: qName,
								approvals_json: JSON.stringify(decisions),
								approval_method: values.approval_method,
								approved_by_customer: values.approved_by_customer,
								notes: values.notes
							},
							freeze: true,
							freeze_message: __("Submitting Quotation and Generating Sales Order..."),
							callback: (r) => {
								if (!r.exc) {
									d.hide();
									frm.reload_doc();
								}
							}
						});
					}
				});
				d.show();
			});
		});
	},

	setup_parts_tab_actions(frm) {
		if (frm.fields_dict.parts && frm.fields_dict.parts.grid) {
			const grid = frm.fields_dict.parts.grid;
			// Top toolbar buttons for immediate visibility
			grid.add_custom_button(__("Add Part"), () => {
				frm.trigger("show_add_part_dialog");
			}, "top");
			grid.add_custom_button(__("Issue Selected Parts"), () => {
				frm.trigger("show_parts_issue_dialog");
			}, "top");
			grid.add_custom_button(__("Substitute Part"), () => {
				frm.trigger("show_part_substitution_dialog");
			}, "top");
			grid.add_custom_button(__("Return Parts"), () => {
				frm.trigger("show_parts_return_dialog");
			}, "top");

			// Bottom toolbar buttons
			grid.add_custom_button(__("Add Part"), () => {
				frm.trigger("show_add_part_dialog");
			});
			grid.add_custom_button(__("Issue Selected Parts"), () => {
				frm.trigger("show_parts_issue_dialog");
			});
			grid.add_custom_button(__("Substitute Part"), () => {
				frm.trigger("show_part_substitution_dialog");
			});
			grid.add_custom_button(__("Return Parts"), () => {
				frm.trigger("show_parts_return_dialog");
			});

			// Rebind click handlers directly on existing buttons to prevent stale references
			if (grid.custom_buttons) {
				Object.keys(grid.custom_buttons).forEach(label => {
					const $btn = grid.custom_buttons[label];
					if ($btn && $btn.length) {
						if (label.indexOf("Add Part") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("show_add_part_dialog");
							});
						} else if (label.indexOf("Issue") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("show_parts_issue_dialog");
							});
						} else if (label.indexOf("Substitute") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("show_part_substitution_dialog");
							});
						} else if (label.indexOf("Return") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("show_parts_return_dialog");
							});
						}
					}
				});
			}
		}
	},

	show_add_part_dialog(frm) {
		const isPartsAuthorized = frappe.user_roles.includes("Parts Controller") ||
			frappe.user_roles.includes("Parts Manager") ||
			frappe.user_roles.includes("System Manager") ||
			frappe.session.user === "Administrator";
		if (!isPartsAuthorized) {
			frappe.msgprint(__("Access denied: only Parts Consultants (Parts Controllers) and Parts Managers can add parts."));
			return;
		}

		if (frm.is_new()) {
			frappe.msgprint(__("Please save the Service Order before adding parts."));
			return;
		}

		const d = new frappe.ui.Dialog({
			title: __("Add Part to Service Order"),
			fields: [
				{
					fieldname: "item_code",
					label: __("Item (Part)"),
					fieldtype: "Link",
					options: "Item",
					reqd: 1,
					get_query: () => {
						return {
							filters: {
								is_stock_item: 1
							}
						};
					}
				},
				{
					fieldname: "qty_required",
					label: __("Quantity Required"),
					fieldtype: "Float",
					default: 1.0,
					reqd: 1
				},
				{
					fieldname: "rate",
					label: __("Rate / Unit Price (Optional)"),
					fieldtype: "Currency"
				},
				{
					fieldname: "col_brk_1",
					fieldtype: "Column Break"
				},
				{
					fieldname: "job",
					label: __("Link to Job (Optional)"),
					fieldtype: "Link",
					options: "Service Job",
					get_query: () => {
						return {
							filters: {
								service_order: frm.doc.name
							}
						};
					}
				},
				{
					fieldname: "reason_for_adding",
					label: __("Reason for Adding"),
					fieldtype: "Small Text",
					description: __("Explanation for adding part directly outside initial quotation")
				}
			],
			primary_action_label: __("Add Part"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.add_manual_part",
					args: {
						service_order: frm.doc.name,
						item_code: vals.item_code,
						qty_required: vals.qty_required,
						rate: vals.rate || 0,
						job: vals.job || null,
						reason: vals.reason_for_adding || null
					},
					freeze: true,
					freeze_message: __("Adding Part..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({
								message: __("Part {0} added to order", [vals.item_code]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();
	},

	show_part_substitution_dialog(frm, part_row_name = null) {
		if (frm.is_new()) {
			frappe.msgprint(__("Please save the Service Order before substituting parts."));
			return;
		}

		if (typeof part_row_name !== "string" || part_row_name === frm.doctype) {
			part_row_name = null;
		}

		if (!part_row_name && frm.fields_dict.parts && frm.fields_dict.parts.grid) {
			const grid = frm.fields_dict.parts.grid;
			let selected = grid.get_selected_children ? grid.get_selected_children() : [];
			if (!selected.length && grid.get_selected) {
				const names = grid.get_selected() || [];
				selected = (frm.doc.parts || []).filter(p => names.includes(p.name));
			}
			if (!selected.length) {
				grid.wrapper.find(".grid-body .grid-row-check:checked").each(function () {
					const name = $(this).closest(".grid-row").attr("data-name");
					if (name) {
						const match = (frm.doc.parts || []).find(p => p.name === name);
						if (match) selected.push(match);
					}
				});
			}
			if (selected && selected.length === 1) {
				part_row_name = selected[0].name;
			}
		}

		const eligibleParts = (frm.doc.parts || []).filter(p => p.part_status !== "Substituted");
		if (!eligibleParts.length) {
			frappe.msgprint(__("No parts available to substitute on this service order."));
			return;
		}

		const partOptions = eligibleParts.map(p => ({
			label: `${p.item_name || p.item_code} (${p.item_code}) - Qty: ${p.qty_required}`,
			value: p.name
		}));

		const defaultPart = part_row_name || (eligibleParts.length ? eligibleParts[0].name : "");

		const d = new frappe.ui.Dialog({
			title: __("Substitute Part"),
			fields: [
				{
					fieldname: "part_row",
					label: __("Original Part to Substitute"),
					fieldtype: "Select",
					options: partOptions,
					default: defaultPart,
					reqd: 1,
					onchange: () => {
						const selName = d.get_value("part_row");
						const sel = eligibleParts.find(p => p.name === selName);
						if (sel) {
							d.set_value("qty", sel.qty_required);
						}
					}
				},
				{
					fieldname: "substitute_item",
					label: __("Substitute Item"),
					fieldtype: "Link",
					options: "Item",
					reqd: 1,
					get_query: () => {
						return {
							filters: {
								is_stock_item: 1
							}
						};
					}
				},
				{
					fieldname: "qty",
					label: __("Quantity"),
					fieldtype: "Float",
					default: 1.0,
					reqd: 1
				},
				{
					fieldname: "reason",
					label: __("Reason for Substitution"),
					fieldtype: "Small Text",
					reqd: 1
				}
			],
			primary_action_label: __("Substitute Part"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.request_part_substitution",
					args: {
						service_order: frm.doc.name,
						part_row: vals.part_row,
						substitute_item: vals.substitute_item,
						qty: vals.qty,
						reason: vals.reason
					},
					freeze: true,
					freeze_message: __("Processing Part Substitution..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({
								message: __("Part substituted successfully with {0}", [vals.substitute_item]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();

		if (defaultPart) {
			const sel = eligibleParts.find(p => p.name === defaultPart);
			if (sel) {
				d.set_value("qty", sel.qty_required);
			}
		}
	},

	show_parts_issue_dialog(frm) {
		if (frm.is_new()) {
			frappe.msgprint(__("Please save the Service Order before issuing parts."));
			return;
		}

		if (frm.is_dirty()) {
			frappe.confirm(
				__("You have unsaved changes. Would you like to save the Service Order first and proceed to issue parts?"),
				() => {
					let pre_selected = [];
					if (frm.fields_dict.parts && frm.fields_dict.parts.grid) {
						const g = frm.fields_dict.parts.grid;
						if (g.get_selected) pre_selected = g.get_selected() || [];
						if (!pre_selected.length && g.get_selected_children) {
							pre_selected = (g.get_selected_children() || []).map(r => r.name || r.docname);
						}
					}
					frm._pre_selected_parts = pre_selected.filter(Boolean);
					frm.save().then(() => {
						frm.trigger("show_parts_issue_dialog");
					});
				}
			);
			return;
		}

		let selected_rows = [];
		if (frm._pre_selected_parts && frm._pre_selected_parts.length) {
			const saved_names = frm._pre_selected_parts;
			delete frm._pre_selected_parts;
			selected_rows = (frm.doc.parts || []).filter(p => saved_names.includes(p.name));
		}

		if (!selected_rows.length && frm.fields_dict.parts && frm.fields_dict.parts.grid) {
			const grid = frm.fields_dict.parts.grid;
			if (grid.get_selected_children) {
				selected_rows = grid.get_selected_children() || [];
			}
			if (!selected_rows.length && grid.get_selected) {
				const names = grid.get_selected() || [];
				if (names.length) {
					selected_rows = (frm.doc.parts || []).filter(p => names.includes(p.name));
				}
			}
			if (!selected_rows.length) {
				const checked_names = [];
				grid.wrapper.find(".grid-body .grid-row-check:checked").each(function () {
					const name = $(this).closest(".grid-row").attr("data-name");
					if (name) checked_names.push(name);
				});
				if (checked_names.length) {
					selected_rows = (frm.doc.parts || []).filter(p => checked_names.includes(p.name));
				}
			}
		}

		let approvedParts = (frm.doc.parts || []).filter(p => p.approval_status === "Approved" && (flt(p.qty_required) - (flt(p.qty_issued) - flt(p.qty_returned || 0))) > 0);

		if (Array.isArray(selected_rows) && selected_rows.length > 0) {
			const selectedNames = new Set(selected_rows.map(r => (typeof r === "string" ? r : (r.name || r.docname || ""))).filter(Boolean));
			const unapproved = (frm.doc.parts || []).filter(p => selectedNames.has(p.name) && p.approval_status !== "Approved");
			if (unapproved.length > 0 && unapproved.length === selected_rows.length) {
				frappe.msgprint(__("The selected part(s) are not approved for workshop issuance."));
				return;
			}
			const filtered = approvedParts.filter(p => selectedNames.has(p.name));
			if (!filtered.length) {
				frappe.msgprint(__("The selected part(s) have no pending quantities to issue."));
				return;
			}
			approvedParts = filtered;
		}

		if (!approvedParts.length) {
			frappe.msgprint(__("No pending approved parts to issue for this order."));
			return;
		}

		let fields = [];
		approvedParts.forEach((p, idx) => {
			let max = flt(p.qty_required) - (flt(p.qty_issued) - flt(p.qty_returned || 0));
			fields.push({
				fieldname: `check_${idx}`,
				label: `${p.item_name || p.item_code} (${p.item_code})`,
				fieldtype: "Check",
				default: 1
			});
			fields.push({
				fieldname: `col_${idx}`,
				fieldtype: "Column Break"
			});
			fields.push({
				fieldname: `qty_${idx}`,
				label: __("Qty to Issue (Pending: {0})", [max]),
				fieldtype: "Float",
				default: max
			});
			fields.push({
				fieldname: `sec_${idx}`,
				fieldtype: "Section Break"
			});
		});

		const d = new frappe.ui.Dialog({
			title: __("Issue Parts to Workshop WIP"),
			fields: fields,
			primary_action_label: __("Issue Parts"),
			primary_action: (values) => {
				const vals = values || d.get_values() || {};
				let payload = [];
				approvedParts.forEach((p, idx) => {
					let isChecked = vals[`check_${idx}`] !== undefined ? vals[`check_${idx}`] : 1;
					let max = flt(p.qty_required) - (flt(p.qty_issued) - flt(p.qty_returned || 0));
					let qty = vals[`qty_${idx}`] !== undefined ? flt(vals[`qty_${idx}`]) : max;
					if (isChecked && qty > 0) {
						payload.push({ part_row: p.name, qty: qty });
					}
				});

				if (!payload.length) {
					frappe.msgprint(__("Please select at least one part with quantity > 0."));
					return;
				}

				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.issue_parts_to_workshop",
					args: { order_name: frm.doc.name, items_json: JSON.stringify(payload) },
					freeze: true,
					freeze_message: __("Issuing Parts to Workshop WIP..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({
								message: __("Parts issued successfully via Stock Entry {0}", [r.message.stock_entry]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}
		});

		d.show();

		approvedParts.forEach((p, idx) => {
			let max = flt(p.qty_required) - (flt(p.qty_issued) - flt(p.qty_returned || 0));
			d.set_value(`check_${idx}`, 1);
			d.set_value(`qty_${idx}`, max);
		});
	},

	show_parts_return_dialog(frm) {
		if (frm.is_new()) {
			frappe.msgprint(__("Please save the Service Order before returning parts."));
			return;
		}

		if (frm.is_dirty()) {
			frappe.confirm(
				__("You have unsaved changes. Would you like to save the Service Order first and proceed to return parts?"),
				() => {
					let pre_selected = [];
					if (frm.fields_dict.parts && frm.fields_dict.parts.grid) {
						const g = frm.fields_dict.parts.grid;
						if (g.get_selected) pre_selected = g.get_selected() || [];
						if (!pre_selected.length && g.get_selected_children) {
							pre_selected = (g.get_selected_children() || []).map(r => r.name || r.docname);
						}
					}
					frm._pre_selected_parts_return = pre_selected.filter(Boolean);
					frm.save().then(() => {
						frm.trigger("show_parts_return_dialog");
					});
				}
			);
			return;
		}

		let selected_rows = [];
		if (frm._pre_selected_parts_return && frm._pre_selected_parts_return.length) {
			const saved_names = frm._pre_selected_parts_return;
			delete frm._pre_selected_parts_return;
			selected_rows = (frm.doc.parts || []).filter(p => saved_names.includes(p.name));
		}

		if (!selected_rows.length && frm.fields_dict.parts && frm.fields_dict.parts.grid) {
			const grid = frm.fields_dict.parts.grid;
			if (grid.get_selected_children) {
				selected_rows = grid.get_selected_children() || [];
			}
			if (!selected_rows.length && grid.get_selected) {
				const names = grid.get_selected() || [];
				if (names.length) {
					selected_rows = (frm.doc.parts || []).filter(p => names.includes(p.name));
				}
			}
			if (!selected_rows.length) {
				const checked_names = [];
				grid.wrapper.find(".grid-body .grid-row-check:checked").each(function () {
					const name = $(this).closest(".grid-row").attr("data-name");
					if (name) checked_names.push(name);
				});
				if (checked_names.length) {
					selected_rows = (frm.doc.parts || []).filter(p => checked_names.includes(p.name));
				}
			}
		}

		let issuedParts = (frm.doc.parts || []).filter(p => (flt(p.qty_issued) - flt(p.qty_returned || 0)) > 0);
		if (!issuedParts.length) {
			frappe.msgprint(__("No parts currently issued on vehicle to return."));
			return;
		}

		if (Array.isArray(selected_rows) && selected_rows.length > 0) {
			const selectedNames = new Set(selected_rows.map(r => (typeof r === "string" ? r : (r.name || r.docname || ""))).filter(Boolean));
			const filtered = issuedParts.filter(p => selectedNames.has(p.name));
			if (filtered.length > 0) {
				issuedParts = filtered;
			}
		}

		let fields = [];
		issuedParts.forEach((p, idx) => {
			let onVeh = flt(p.qty_issued) - flt(p.qty_returned || 0);
			fields.push({
				fieldname: `check_${idx}`,
				label: `${p.item_name || p.item_code} (${p.item_code})`,
				fieldtype: "Check",
				default: 1
			});
			fields.push({
				fieldname: `col_${idx}`,
				fieldtype: "Column Break"
			});
			fields.push({
				fieldname: `qty_${idx}`,
				label: __("Qty to Return (In WIP: {0})", [onVeh]),
				fieldtype: "Float",
				default: onVeh
			});
			fields.push({
				fieldname: `sec_${idx}`,
				fieldtype: "Section Break"
			});
		});

		const d = new frappe.ui.Dialog({
			title: __("Return Parts from Workshop to Store"),
			fields: fields,
			primary_action_label: __("Return Parts"),
			primary_action: () => {
				const vals = d.get_values() || {};
				let payload = [];
				issuedParts.forEach((p, idx) => {
					let isChecked = vals[`check_${idx}`] !== undefined ? vals[`check_${idx}`] : 1;
					let onVeh = flt(p.qty_issued) - flt(p.qty_returned || 0);
					let qty = vals[`qty_${idx}`] !== undefined ? flt(vals[`qty_${idx}`]) : onVeh;
					if (isChecked && qty > 0) {
						payload.push({ part_row: p.name, qty: qty });
					}
				});

				if (!payload.length) {
					frappe.msgprint(__("Please select at least one part with quantity > 0 to return."));
					return;
				}

				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.return_parts_from_workshop",
					args: { order_name: frm.doc.name, items_json: JSON.stringify(payload) },
					freeze: true,
					freeze_message: __("Returning Parts to Store..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({
								message: __("Parts returned successfully via Stock Entry {0}", [r.message.stock_entry]),
								indicator: "green"
							});
							frm.reload_doc();
						}
					}
				});
			}
		});

		d.show();

		issuedParts.forEach((p, idx) => {
			let onVeh = flt(p.qty_issued) - flt(p.qty_returned || 0);
			d.set_value(`check_${idx}`, 1);
			d.set_value(`qty_${idx}`, onVeh);
		});
	},

	show_delivery_dialog(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Deliver Vehicle to Customer"),
			fields: [
				{ fieldname: "odometer_out", label: __("Final Odometer Out (km)"), fieldtype: "Int", reqd: 1, default: frm.doc.odometer_in },
				{ fieldname: "collected_by", label: __("Collected By (Person / ID)"), fieldtype: "Data", reqd: 1, default: frm.doc.driver_name || frm.doc.customer_name },
				{ fieldname: "delivery_notes", label: __("Delivery Notes & Recommendations"), fieldtype: "Small Text" },
				{ fieldname: "delivery_signature", label: __("Customer Sign-off"), fieldtype: "Signature" }
			],
			primary_action_label: __("Complete Delivery"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.deliver_vehicle",
					args: {
						order_name: frm.doc.name,
						odometer_out: vals.odometer_out,
						collected_by: vals.collected_by,
						delivery_notes: vals.delivery_notes,
						delivery_signature: vals.delivery_signature
					},
					freeze: true,
					freeze_message: __("Finalising Delivery & Scheduling Follow-up..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();
	},

	setup_jobs_tab_actions(frm) {
		if (frm.fields_dict.jobs && frm.fields_dict.jobs.grid) {
			const grid = frm.fields_dict.jobs.grid;

			frm.set_query("service_item", "jobs", () => {
				return {
					filters: {
						is_stock_item: 0
					}
				};
			});

			// Add custom action buttons to the jobs grid
			grid.add_custom_button(__("Assign Technician"), () => {
				frm.trigger("show_assign_job_dialog");
			}, "top");
			grid.add_custom_button(__("Start Clock"), () => {
				frm.trigger("start_selected_job");
			}, "top");
			grid.add_custom_button(__("Pause Clock"), () => {
				frm.trigger("pause_selected_job");
			}, "top");
			grid.add_custom_button(__("Complete Job"), () => {
				frm.trigger("complete_selected_job");
			}, "top");

			// Bottom toolbar buttons
			grid.add_custom_button(__("Assign Technician"), () => {
				frm.trigger("show_assign_job_dialog");
			});
			grid.add_custom_button(__("Start Clock"), () => {
				frm.trigger("start_selected_job");
			});
			grid.add_custom_button(__("Pause Clock"), () => {
				frm.trigger("pause_selected_job");
			});
			grid.add_custom_button(__("Complete Job"), () => {
				frm.trigger("complete_selected_job");
			});

			// Rebind click handlers directly on existing buttons to prevent stale references
			if (grid.custom_buttons) {
				Object.keys(grid.custom_buttons).forEach(label => {
					const $btn = grid.custom_buttons[label];
					if ($btn && $btn.length) {
						if (label.indexOf("Assign") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("show_assign_job_dialog");
							});
						} else if (label.indexOf("Start") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("start_selected_job");
							});
						} else if (label.indexOf("Pause") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("pause_selected_job");
							});
						} else if (label.indexOf("Complete") !== -1) {
							$btn.off("click").on("click", (e) => {
								e.preventDefault();
								frm.trigger("complete_selected_job");
							});
						}
					}
				});
			}
		}
	},

	get_selected_jobs(frm) {
		if (!frm.fields_dict.jobs || !frm.fields_dict.jobs.grid) return [];
		const grid = frm.fields_dict.jobs.grid;
		let selected = [];
		if (grid.get_selected_children) {
			selected = grid.get_selected_children() || [];
		}
		if (!selected.length && grid.get_selected) {
			const names = grid.get_selected() || [];
			if (names.length) {
				selected = (frm.doc.jobs || []).filter(j => names.includes(j.name));
			}
		}
		if (!selected.length) {
			const checked_names = [];
			grid.wrapper.find(".grid-body .grid-row-check:checked").each(function () {
				const name = $(this).closest(".grid-row").attr("data-name");
				if (name) checked_names.push(name);
			});
			if (checked_names.length) {
				selected = (frm.doc.jobs || []).filter(j => checked_names.includes(j.name));
			}
		}
		return selected;
	},

	start_selected_job(frm) {
		const selected = frm.trigger("get_selected_jobs") || [];
		if (!selected.length) {
			frappe.msgprint(__("Please select a job row first."));
			return;
		}
		const jobName = selected[0].service_job;
		if (!jobName) {
			frappe.msgprint(__("Please save the Service Order first so the job doc is created."));
			return;
		}
		frappe.call({
			method: "vehicle_service.vehicle_service.doctype.service_job.service_job.start_job",
			args: { job_name: jobName },
			freeze: true,
			freeze_message: __("Starting Job Clock..."),
			callback: (r) => {
				if (!r.exc) {
					frappe.show_alert({ message: __("Job clock started for {0}", [jobName]), indicator: "green" });
					frm.reload_doc();
				}
			}
		});
	},

	pause_selected_job(frm) {
		const selected = frm.trigger("get_selected_jobs") || [];
		if (!selected.length) {
			frappe.msgprint(__("Please select a job row first."));
			return;
		}
		const jobName = selected[0].service_job;
		if (!jobName) {
			frappe.msgprint(__("Please save the Service Order first so the job doc is created."));
			return;
		}
		frappe.prompt(
			[{ fieldname: "reason", label: __("Pause Reason"), fieldtype: "Small Text", reqd: 1 }],
			(vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_job.service_job.pause_job",
					args: { job_name: jobName, reason: vals.reason },
					freeze: true,
					freeze_message: __("Pausing Job Clock..."),
					callback: (r) => {
						if (!r.exc) {
							frappe.show_alert({ message: __("Job clock paused for {0}", [jobName]), indicator: "orange" });
							frm.reload_doc();
						}
					}
				});
			},
			__("Pause Job Clock ({0})", [jobName]),
			__("Pause")
		);
	},

	complete_selected_job(frm) {
		const selected = frm.trigger("get_selected_jobs") || [];
		if (!selected.length) {
			frappe.msgprint(__("Please select a job row first."));
			return;
		}
		const jobName = selected[0].service_job;
		if (!jobName) {
			frappe.msgprint(__("Please save the Service Order first so the job doc is created."));
			return;
		}
		frappe.confirm(__("Are you sure you want to mark job {0} as completed?", [jobName]), () => {
			frappe.call({
				method: "vehicle_service.vehicle_service.doctype.service_job.service_job.complete_job",
				args: { job_name: jobName },
				freeze: true,
				freeze_message: __("Completing Job..."),
				callback: (r) => {
					if (!r.exc) {
						frappe.show_alert({ message: __("Job {0} completed successfully", [jobName]), indicator: "green" });
						frm.reload_doc();
					}
				}
			});
		});
	},

	show_add_job_dialog(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Add Workshop Job"),
			fields: [
				{
					fieldname: "service_item",
					label: __("Service Item"),
					fieldtype: "Link",
					options: "Item",
					default: "LABOUR",
					reqd: 1,
					get_query: () => ({ filters: { is_stock_item: 0 } }),
					onchange: () => {
						const itm = d.get_value("service_item");
						if (itm) {
							frappe.db.get_value("Item", itm, "item_name").then(r => {
								if (r && r.message && r.message.item_name && !d.get_value("job_title")) {
									d.set_value("job_title", r.message.item_name);
								}
							});
						}
					}
				},
				{ fieldname: "job_title", label: __("Job Description"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "estimated_hours", label: __("Labour Qty (Hours)"), fieldtype: "Float", default: 1.0, reqd: 1 },
				{ fieldname: "rate", label: __("Rate / Unit Price"), fieldtype: "Currency", default: 50.0 },
				{ fieldname: "col_brk_1", fieldtype: "Column Break" },
				{ fieldname: "category", label: __("Category"), fieldtype: "Select", options: "Essential\nRecommended\nOptional", default: "Essential", reqd: 1 },
				{ fieldname: "priority", label: __("Priority"), fieldtype: "Select", options: "Low\nMedium\nHigh\nUrgent", default: "Medium", reqd: 1 },
				{ fieldname: "technician", label: __("Assign Technician"), fieldtype: "Link", options: "Employee" },
				{ fieldname: "bay", label: __("Workshop Bay"), fieldtype: "Link", options: "Workshop Location" },
				{ fieldname: "reason_for_adding", label: __("Reason for Adding"), fieldtype: "Small Text", description: __("Explanation for adding job directly") },
				{ fieldname: "sec_sublet", label: __("Sublet Details (If Outsourced)"), fieldtype: "Section Break" },
				{ fieldname: "supplier", label: __("Sublet Supplier"), fieldtype: "Link", options: "Supplier" },
				{ fieldname: "supplier_cost", label: __("Supplier Cost"), fieldtype: "Currency" },
				{ fieldname: "supplier_invoice_ref", label: __("Supplier Invoice Ref"), fieldtype: "Data" },
				{ fieldname: "description", label: __("Detailed Scope / Notes"), fieldtype: "Small Text" }
			],
			primary_action_label: __("Create Job"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.add_ad_hoc_job",
					args: {
						service_order: frm.doc.name,
						job_title: vals.job_title,
						service_item: vals.service_item,
						category: vals.category,
						estimated_hours: vals.estimated_hours,
						rate: vals.rate,
						description: vals.description,
						technician: vals.technician,
						bay: vals.bay,
						priority: vals.priority,
						reason: vals.reason_for_adding,
						supplier: vals.supplier,
						supplier_cost: vals.supplier_cost,
						supplier_invoice_ref: vals.supplier_invoice_ref
					},
					freeze: true,
					freeze_message: __("Creating Job..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({ message: __("Job {0} created", [r.message.job]), indicator: "green" });
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();
	},

	show_assign_job_dialog(frm, jobName) {
		if (!jobName) {
			const selected = frm.trigger("get_selected_jobs") || [];
			if (selected.length) {
				jobName = selected[0].service_job;
			}
		}
		if (!jobName) {
			frappe.msgprint(__("Please select a saved job row to assign a technician."));
			return;
		}
		const d = new frappe.ui.Dialog({
			title: __("Assign Technician & Bay ({0})", [jobName]),
			fields: [
				{ fieldname: "technician", label: __("Technician"), fieldtype: "Link", options: "Employee", reqd: 1 },
				{ fieldname: "bay", label: __("Workshop Bay"), fieldtype: "Link", options: "Workshop Location" }
			],
			primary_action_label: __("Assign"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.assign_job",
					args: {
						job_name: jobName,
						technician: vals.technician,
						bay: vals.bay
					},
					freeze: true,
					freeze_message: __("Assigning Job..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({ message: __("Technician assigned to {0}", [jobName]), indicator: "green" });
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();
	}
});

frappe.ui.form.on("Service Order Part", {
	parts_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		row.qty_required = 1.0;
		row.category = "Essential";
		row.source = frm.doc.quotation ? "Additional Part" : "Manually Added";
		row.approval_status = "Approved";
		row.part_status = "Required";
		frm.refresh_field("parts");
	},

	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;

		row.qty_required = row.qty_required || 1.0;
		row.category = row.category || "Essential";
		row.source = row.source || (frm.doc.quotation ? "Additional Part" : "Manually Added");
		row.approval_status = "Approved";
		row.part_status = "Required";

		frappe.db.get_value("Item", row.item_code, ["item_name", "valuation_rate", "is_stock_item"])
			.then(r => {
				if (r && r.message) {
					if (!r.message.is_stock_item) {
						frappe.msgprint(__("Item {0} is not a stock item.", [row.item_code]));
						frappe.model.set_value(cdt, cdn, "item_code", "");
						return;
					}
					frappe.model.set_value(cdt, cdn, "item_name", r.message.item_name || row.item_code);

					// Fetch standard selling price list rate
					frappe.db.get_value("Item Price", {
						item_code: row.item_code,
						price_list: "Standard Selling"
					}, "price_list_rate").then(pr => {
						const rate = (pr && pr.message && pr.message.price_list_rate) ? pr.message.price_list_rate : (r.message.valuation_rate || 0);
						frappe.model.set_value(cdt, cdn, "rate", rate);
						frappe.model.set_value(cdt, cdn, "approval_status", "Approved");
						frappe.model.set_value(cdt, cdn, "part_status", "Required");
						frappe.model.set_value(cdt, cdn, "source", frm.doc.quotation ? "Additional Part" : "Manually Added");
					});
				}
			});
	}
});

frappe.ui.form.on("Service Order Job", {
	jobs_add(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		row.service_item = "LABOUR";
		row.category = "Essential";
		row.priority = "Medium";
		row.status = "Approved";
		row.source = "Manually Added";
		row.estimated_hours = 1.0;
		row.rate = 50.0;
		row.amount = 50.0;
		row.actual_hours = 0.0;
		frm.refresh_field("jobs");
	},

	service_item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.service_item) return;

		frappe.db.get_value("Item", row.service_item, ["item_name", "is_stock_item"]).then(r => {
			if (r && r.message) {
				if (r.message.is_stock_item) {
					frappe.msgprint(__("Item {0} is a stock inventory item. Workshop jobs must be non-stock service items.", [row.service_item]));
					frappe.model.set_value(cdt, cdn, "service_item", "LABOUR");
					return;
				}
				if (!row.job_title || row.job_title === "LABOUR") {
					frappe.model.set_value(cdt, cdn, "job_title", r.message.item_name || row.service_item);
				}
			}
		});

		frappe.db.get_value("Item Price", { item_code: row.service_item, price_list: "Standard Selling" }, "price_list_rate").then(pr => {
			if (pr && pr.message && pr.message.price_list_rate) {
				frappe.model.set_value(cdt, cdn, "rate", pr.message.price_list_rate);
				frappe.model.set_value(cdt, cdn, "amount", round((flt(row.estimated_hours) || 1.0) * pr.message.price_list_rate, 2));
			}
		});
	},

	estimated_hours(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const amt = round((flt(row.estimated_hours) || 0) * (flt(row.rate) || 0), 2);
		frappe.model.set_value(cdt, cdn, "amount", amt);
	},

	rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const amt = round((flt(row.estimated_hours) || 0) * (flt(row.rate) || 0), 2);
		frappe.model.set_value(cdt, cdn, "amount", amt);
	},

	technician(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.technician) {
			frappe.model.set_value(cdt, cdn, "technician_name", "");
			return;
		}
		frappe.db.get_value("Employee", row.technician, "employee_name")
			.then(r => {
				if (r && r.message) {
					frappe.model.set_value(cdt, cdn, "technician_name", r.message.employee_name);
				}
			});
	}
});

