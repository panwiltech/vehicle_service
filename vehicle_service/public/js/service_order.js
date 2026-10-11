// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Order", {
	refresh(frm) {
		frm.trigger("render_status_stepper");
		frm.trigger("render_jobs_html");
		frm.trigger("setup_parts_tab_actions");
		frm.trigger("setup_custom_buttons");
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

		const steps = [
			"Draft",
			"In Progress",
			"QC",
			"Ready for Billing",
			"Invoiced",
			"Ready for Collection",
			"Delivered"
		];

		const current = frm.doc.status;
		let currentIndex = steps.indexOf(current);
		if (["Checked In", "Awaiting Approval", "Approved", "Waiting for Parts", "Ready for Work", "Paused"].includes(current)) {
			currentIndex = steps.indexOf("In Progress");
		}

		let html = `<div class="status-stepper-container" style="display:flex; overflow-x:auto; padding:10px 0; margin-bottom:15px; border-bottom:1px solid var(--border-color);">`;
		steps.forEach((step, idx) => {
			let isCompleted = idx < currentIndex || current === "Delivered";
			let isCurrent = idx === currentIndex && current !== "Delivered";
			let badgeColor = isCurrent ? "var(--primary)" : (isCompleted ? "var(--green-500)" : "var(--text-muted)");
			let bgColor = isCurrent ? "var(--primary-light, #ebf5ff)" : (isCompleted ? "var(--green-50, #f0fdf4)" : "var(--subtle-fg, #f8f9fa)");
			let fontWeight = isCurrent ? "700" : "500";

			html += `
				<div style="display:flex; align-items:center; margin-right:8px; white-space:nowrap;">
					<span style="display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:${badgeColor}; color:#fff; font-size:11px; margin-right:5px;">
						${isCompleted ? "✓" : (idx + 1)}
					</span>
					<span style="font-size:12px; font-weight:${fontWeight}; color:${isCurrent ? 'var(--text-color)' : 'var(--text-muted)'}; background:${bgColor}; padding:2px 8px; border-radius:12px;">
						${step}
					</span>
					${idx < steps.length - 1 ? '<span style="margin-left:8px; color:var(--border-color);">→</span>' : ''}
				</div>
			`;
		});
		html += `</div>`;

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
	},

	setup_custom_buttons(frm) {
		if (frm.is_new()) return;

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
		if (["Approved", "Waiting for Parts", "Ready for Work", "In Progress"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Issue Selected Parts"), () => {
				frm.trigger("show_parts_issue_dialog");
			}, __("Parts Control"));

			frm.add_custom_button(__("Return Parts from Workshop"), () => {
				frm.trigger("show_parts_return_dialog");
			}, __("Parts Control"));
		}

		// 6. Start QC (if QC status)
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
				}).addClass("btn-primary");
			});
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
			grid.add_custom_button(__("+ Add Part"), () => {
				frm.trigger("show_add_part_dialog");
			});
			grid.add_custom_button(__("Substitute Part"), () => {
				frm.trigger("show_part_substitution_dialog");
			});
			grid.add_custom_button(__("Issue Selected Parts"), () => {
				frm.trigger("show_parts_issue_dialog");
			});
			grid.add_custom_button(__("Return Parts"), () => {
				frm.trigger("show_parts_return_dialog");
			});
		}
	},

	show_add_part_dialog(frm) {
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

		if (!part_row_name && frm.fields_dict.parts && frm.fields_dict.parts.grid) {
			const selected = frm.fields_dict.parts.grid.get_selected_children ? frm.fields_dict.parts.grid.get_selected_children() : [];
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

	show_parts_issue_dialog(frm, selected_rows = null) {
		let approvedParts = (frm.doc.parts || []).filter(p => p.approval_status === "Approved" && (flt(p.qty_required) - (flt(p.qty_issued) - flt(p.qty_returned || 0))) > 0);
		if (!approvedParts.length) {
			frappe.msgprint(__("No pending approved parts to issue for this order."));
			return;
		}

		if (!selected_rows && frm.fields_dict.parts && frm.fields_dict.parts.grid) {
			const gridSelected = frm.fields_dict.parts.grid.get_selected_children ? frm.fields_dict.parts.grid.get_selected_children() : [];
			if (gridSelected && gridSelected.length > 0) {
				selected_rows = gridSelected;
			}
		}

		if (selected_rows && selected_rows.length > 0) {
			const selectedNames = new Set(selected_rows.map(r => r.name));
			const filtered = approvedParts.filter(p => selectedNames.has(p.name));
			if (filtered.length > 0) {
				approvedParts = filtered;
			}
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
			primary_action: () => {
				const vals = d.get_values() || {};
				let payload = [];
				approvedParts.forEach((p, idx) => {
					let isChecked = vals[`check_${idx}`] !== undefined ? vals[`check_${idx}`] : 1;
					let qty = vals[`qty_${idx}`] !== undefined ? flt(vals[`qty_${idx}`]) : (flt(p.qty_required) - (flt(p.qty_issued) - flt(p.qty_returned || 0)));
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
		const issuedParts = (frm.doc.parts || []).filter(p => (p.qty_issued - (p.qty_returned || 0)) > 0);
		if (!issuedParts.length) {
			frappe.msgprint(__("No parts currently issued on vehicle to return."));
			return;
		}

		let fields = issuedParts.map((p) => {
			let onVeh = (p.qty_issued - (p.qty_returned || 0));
			return {
				fieldname: `part_${p.name}`,
				label: `${p.item_name || p.item_code} (Currently in WIP: ${onVeh})`,
				fieldtype: "Float",
				default: 0
			};
		});

		const d = new frappe.ui.Dialog({
			title: __("Return Parts from Workshop to Store"),
			fields: fields,
			primary_action_label: __("Return Parts"),
			primary_action: (vals) => {
				let payload = [];
				issuedParts.forEach(p => {
					let qty = vals[`part_${p.name}`];
					if (qty && qty > 0) {
						payload.push({ part_row: p.name, qty: qty });
					}
				});
				if (!payload.length) return;

				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.return_parts_from_workshop",
					args: { order_name: frm.doc.name, items_json: JSON.stringify(payload) },
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

	render_jobs_html(frm) {
		if (frm.is_new()) {
			frm.set_df_property("jobs_html", "options", `<div class="text-muted p-3 text-center border rounded">${__("Please save the Service Order to manage workshop jobs.")}</div>`);
			return;
		}

		frappe.db.get_list("Service Job", {
			filters: { service_order: frm.doc.name },
			fields: ["name", "job_title", "category", "priority", "source", "reason_for_adding", "estimated_hours", "actual_hours", "status", "technician", "technician_name", "bay"],
			order_by: "creation asc",
			limit: 100
		}).then((jobs) => {
			const isClosed = ["Delivered", "Cancelled"].includes(frm.doc.status);
			const canAdd = !isClosed;

			let html = `
				<div class="service-jobs-panel" style="padding: 10px 0;">
					<div class="d-flex justify-content-between align-items-center mb-3">
						<div>
							<h6 class="mb-0" style="font-weight: 600;">${__("Workshop Jobs")} (${jobs ? jobs.length : 0})</h6>
							<small class="text-muted">${__("Manage active labor operations, technician assignments, and job clocks.")}</small>
						</div>
						${canAdd ? `
						<button type="button" class="btn btn-sm btn-primary" data-action="add-job">
							<i class="fa fa-plus"></i> ${__("Add Job")}
						</button>
						` : ''}
					</div>
			`;

			if (!jobs || jobs.length === 0) {
				html += `
					<div class="text-center text-muted p-4 border rounded" style="background: var(--bg-color, #fafbfc);">
						<p class="mb-2">${__("No jobs created yet for this service order.")}</p>
						${canAdd ? `
						<button type="button" class="btn btn-sm btn-outline-primary" data-action="add-job">
							<i class="fa fa-plus"></i> ${__("Add First Job")}
						</button>
						` : ''}
					</div>
				`;
			} else {
				html += `
					<div class="table-responsive border rounded">
						<table class="table table-hover table-bordered mb-0" style="font-size: 13px;">
							<thead style="background: var(--subtle-fg, #f8f9fa);">
								<tr>
									<th>${__("Job Title")}</th>
									<th style="width: 90px;">${__("Priority")}</th>
									<th style="width: 110px;">${__("Source")}</th>
									<th style="width: 105px;">${__("Category")}</th>
									<th style="width: 105px;">${__("Hours (Est / Act)")}</th>
									<th style="width: 120px;">${__("Status")}</th>
									<th style="width: 160px;">${__("Technician / Bay")}</th>
									<th style="width: 180px; text-align: right;">${__("Actions")}</th>
								</tr>
							</thead>
							<tbody>
				`;

				jobs.forEach((job) => {
					let catBadge = "badge-secondary";
					if (job.category === "Essential") catBadge = "badge-danger";
					else if (job.category === "Recommended") catBadge = "badge-info";
					else if (job.category === "Optional") catBadge = "badge-warning";

					let statusClass = "secondary";
					if (job.status === "In Progress") statusClass = "primary";
					else if (job.status === "Completed") statusClass = "success";
					else if (job.status === "Paused") statusClass = "warning";
					else if (job.status === "Assigned") statusClass = "info";
					else if (job.status === "QC Failed") statusClass = "danger";

					let est = job.estimated_hours || 0;
					let act = job.actual_hours || 0;

					let prioColor = "#4b5563";
					let prioBg = "#f3f4f6";
					let prio = job.priority || "Medium";
					if (prio === "Urgent") {
						prioColor = "#b91c1c";
						prioBg = "#fee2e2";
					} else if (prio === "High") {
						prioColor = "#c2410c";
						prioBg = "#ffedd5";
					} else if (prio === "Medium") {
						prioColor = "#1d4ed8";
						prioBg = "#dbeafe";
					} else if (prio === "Low") {
						prioColor = "#4b5563";
						prioBg = "#f3f4f6";
					}
					let prioHtml = `<span style="font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; color: ${prioColor}; background: ${prioBg};">${frappe.utils.escape_html(prio)}</span>`;

					let srcColor = "#4b5563";
					let srcBg = "#f3f4f6";
					let src = job.source || "From Quotation";
					if (src === "From Quotation") {
						srcColor = "#6d28d9";
						srcBg = "#ede9fe";
					} else if (src === "Manually Added") {
						srcColor = "#047857";
						srcBg = "#d1fae5";
					} else if (src === "Additional Work") {
						srcColor = "#b45309";
						srcBg = "#fef3c7";
					}
					let srcHtml = `<span style="font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 4px; color: ${srcColor}; background: ${srcBg};">${frappe.utils.escape_html(src)}</span>`;

					let techBay = [];
					if (job.technician_name || job.technician) {
						techBay.push(`<strong>${frappe.utils.escape_html(job.technician_name || job.technician)}</strong>`);
					}
					if (job.bay) {
						techBay.push(`<span class="text-muted"><i class="fa fa-map-marker"></i> ${frappe.utils.escape_html(job.bay)}</span>`);
					}
					let techBayHtml = techBay.length ? techBay.join("<br>") : `<span class="text-muted italic">${__("Unassigned")}</span>`;

					let actionBtns = [];
					if (!isClosed) {
						if (["Pending Approval", "Assigned", "Paused"].includes(job.status)) {
							actionBtns.push(`<button type="button" class="btn btn-xs btn-default" data-action="assign-job" data-job="${job.name}" title="${__('Assign Technician or Bay')}"><i class="fa fa-user"></i> ${__('Assign')}</button>`);
						}
						if (["Assigned", "Paused", "QC Failed"].includes(job.status)) {
							actionBtns.push(`<button type="button" class="btn btn-xs btn-primary" data-action="start-job" data-job="${job.name}" title="${__('Start Clock')}"><i class="fa fa-play"></i> ${__('Start')}</button>`);
						}
						if (job.status === "In Progress") {
							actionBtns.push(`<button type="button" class="btn btn-xs btn-warning" data-action="pause-job" data-job="${job.name}" title="${__('Pause Clock')}"><i class="fa fa-pause"></i> ${__('Pause')}</button>`);
							actionBtns.push(`<button type="button" class="btn btn-xs btn-success" data-action="complete-job" data-job="${job.name}" title="${__('Complete Job')}"><i class="fa fa-check"></i> ${__('Complete')}</button>`);
						}
					}

					html += `
						<tr>
							<td>
								<a href="/app/service-job/${job.name}" style="font-weight: 600;">${frappe.utils.escape_html(job.job_title || job.name)}</a>
								<div class="text-muted small">${job.name}</div>
								${job.reason_for_adding ? `<div class="text-muted small" style="font-style: italic;"><i class="fa fa-info-circle"></i> ${frappe.utils.escape_html(job.reason_for_adding)}</div>` : ''}
							</td>
							<td>${prioHtml}</td>
							<td>${srcHtml}</td>
							<td><span class="badge ${catBadge}">${frappe.utils.escape_html(job.category || 'Essential')}</span></td>
							<td>${est}h / <strong>${act}h</strong></td>
							<td><span class="indicator-pill ${statusClass}">${frappe.utils.escape_html(job.status)}</span></td>
							<td>${techBayHtml}</td>
							<td style="text-align: right; white-space: nowrap;">
								${actionBtns.join(" ") || '<span class="text-muted text-sm">-</span>'}
							</td>
						</tr>
					`;
				});

				html += `
							</tbody>
						</table>
					</div>
				`;
			}

			html += `</div>`;
			frm.set_df_property("jobs_html", "options", html);

			if (frm.fields_dict.jobs_html && frm.fields_dict.jobs_html.$wrapper) {
				const $wrapper = frm.fields_dict.jobs_html.$wrapper;
				$wrapper.off("click", "[data-action]").on("click", "[data-action]", function (e) {
					e.preventDefault();
					const action = $(this).data("action");
					const jobName = $(this).data("job");

					if (action === "add-job") {
						frm.trigger("show_add_job_dialog");
					} else if (action === "assign-job") {
						frm.trigger("show_assign_job_dialog", jobName);
					} else if (action === "start-job") {
						frappe.call({
							method: "vehicle_service.vehicle_service.doctype.service_job.service_job.start_job",
							args: { job_name: jobName },
							freeze: true,
							freeze_message: __("Starting Job Clock..."),
							callback: (r) => {
								if (!r.exc) {
									frappe.show_alert({ message: __("Job clock started"), indicator: "green" });
									frm.trigger("render_jobs_html");
									frm.reload_doc();
								}
							}
						});
					} else if (action === "pause-job") {
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
											frappe.show_alert({ message: __("Job clock paused"), indicator: "orange" });
											frm.trigger("render_jobs_html");
											frm.reload_doc();
										}
									}
								});
							},
							__("Pause Job Clock"),
							__("Pause")
						);
					} else if (action === "complete-job") {
						frappe.confirm(__("Are you sure you want to mark this job as completed?"), () => {
							frappe.call({
								method: "vehicle_service.vehicle_service.doctype.service_job.service_job.complete_job",
								args: { job_name: jobName },
								freeze: true,
								freeze_message: __("Completing Job..."),
								callback: (r) => {
									if (!r.exc) {
										frappe.show_alert({ message: __("Job completed successfully"), indicator: "green" });
										frm.trigger("render_jobs_html");
										frm.reload_doc();
									}
								}
							});
						});
					}
				});
			}
		});
	},

	show_add_job_dialog(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Add Workshop Job"),
			fields: [
				{ fieldname: "job_title", label: __("Job Title"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "priority", label: __("Priority"), fieldtype: "Select", options: "Low\nMedium\nHigh\nUrgent", default: "Medium", reqd: 1 },
				{ fieldname: "category", label: __("Category"), fieldtype: "Select", options: "Essential\nRecommended\nOptional", default: "Essential", reqd: 1 },
				{ fieldname: "estimated_hours", label: __("Estimated Hours"), fieldtype: "Float", default: 1.0, reqd: 1 },
				{ fieldname: "col_brk_1", fieldtype: "Column Break" },
				{ fieldname: "technician", label: __("Assign Technician"), fieldtype: "Link", options: "Employee" },
				{ fieldname: "bay", label: __("Workshop Bay"), fieldtype: "Link", options: "Workshop Location" },
				{ fieldname: "reason_for_adding", label: __("Reason for Adding"), fieldtype: "Small Text", description: __("Explanation for adding job directly") },
				{ fieldname: "description", label: __("Description"), fieldtype: "Small Text" }
			],
			primary_action_label: __("Create Job"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.vehicle_service.doctype.service_order.service_order.add_ad_hoc_job",
					args: {
						service_order: frm.doc.name,
						job_title: vals.job_title,
						category: vals.category,
						estimated_hours: vals.estimated_hours,
						description: vals.description,
						technician: vals.technician,
						bay: vals.bay,
						priority: vals.priority,
						reason: vals.reason_for_adding
					},
					freeze: true,
					freeze_message: __("Creating Job..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({ message: __("Job {0} created", [r.message.job]), indicator: "green" });
							frm.trigger("render_jobs_html");
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();
	},

	show_assign_job_dialog(frm, jobName) {
		if (!jobName) return;
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
							frm.trigger("render_jobs_html");
							frm.reload_doc();
						}
					}
				});
			}
		});
		d.show();
	}
});
