# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from vehicle_service.state import INVOICED, READY_FOR_BILLING, READY_FOR_COLLECTION, vehicle_status_for


def validate_sales_invoice(doc, method=None):
	"""Restricts Service Advisors from deleting or altering parts on a Sales Invoice linked to a Service Order."""
	if not getattr(doc, "vs_service_order", None):
		return

	user = frappe.session.user
	if not user or user == "Administrator":
		return

	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or bool(roles & {"Parts Controller", "Parts Manager", "Accounts Manager"}):
		return

	if "Service Advisor" in roles:
		so = frappe.get_doc("Service Order", doc.vs_service_order)
		so_parts_map = {
			p.name: p for p in so.get("parts", [])
			if p.approval_status == "Approved" and flt(p.qty_used) > 0
		}

		inv_parts = {}
		for item in doc.get("items", []):
			part_row = getattr(item, "vs_part_row", None)
			if part_row:
				inv_parts[part_row] = item
			elif not getattr(item, "vs_job", None):
				# Stock part added directly outside Service Order
				if frappe.db.get_value("Item", item.item_code, "is_stock_item"):
					frappe.throw(
						frappe._(
							"Service Advisors are not permitted to add stock parts ({0}) directly to Sales Invoice {1}. Parts must be added by a Parts Consultant or Parts Manager on Service Order {2}."
						).format(item.item_code, doc.name or "New", so.name),
						frappe.ValidationError,
					)

		for part_row, so_part in so_parts_map.items():
			if part_row not in inv_parts:
				frappe.throw(
					frappe._(
						"Service Advisors are not permitted to remove parts from Sales Invoice {0} that were added from Service Order {1} (Part: {2}). Please contact the Parts Consultant or Parts Manager."
					).format(doc.name or "New", so.name, so_part.item_code),
					frappe.ValidationError,
				)

			inv_item = inv_parts[part_row]
			if flt(inv_item.qty) != flt(so_part.qty_used):
				frappe.throw(
					frappe._(
						"Service Advisors are not permitted to change the quantity of part {0} on Sales Invoice {1} (Service Order: {2}). Expected quantity: {3}, found: {4}. Only labour hours can be modified on the invoice."
					).format(so_part.item_code, doc.name or "New", so.name, so_part.qty_used, inv_item.qty),
					frappe.ValidationError,
				)

			if flt(inv_item.rate) != flt(so_part.rate):
				frappe.throw(
					frappe._(
						"Service Advisors are not permitted to change the rate of part {0} on Sales Invoice {1} (Service Order: {2}). Expected rate: {3}, found: {4}. Only labour hours can be modified on the invoice."
					).format(so_part.item_code, doc.name or "New", so.name, so_part.rate, inv_item.rate),
					frappe.ValidationError,
				)


def handle_sales_invoice_submit(doc, method=None):
	# 1. Credit Note (Return against an existing Sales Invoice)
	if getattr(doc, "is_return", 0) and getattr(doc, "return_against", None):
		orig_inv = doc.return_against
		order_name = getattr(doc, "vs_service_order", None) or frappe.db.get_value("Sales Invoice", orig_inv, "vs_service_order")
		if order_name:
			order = frappe.get_doc("Service Order", order_name)
			order.flags.ignore_invoice_lock = True
			order.status = "In Progress"
			order.sales_invoice = None
			order.add_comment(
				"Comment",
				frappe._("Sales Invoice {0} was credited via Credit Note {1}. Service Order is re-opened in 'In Progress' status and is now editable.").format(
					orig_inv, doc.name
				),
			)
			order.save(ignore_permissions=True)
			if order.vehicle:
				frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", "In Workshop")
		return

	# 2. Standard Sales Invoice submit
	if getattr(doc, "vs_service_order", None):
		order = frappe.get_doc("Service Order", doc.vs_service_order)
		customer_credit = frappe.db.get_value("Customer", order.customer, "vs_credit_release") or 0

		if flt(doc.outstanding_amount) <= 0 or customer_credit or order.credit_released:
			order.status = READY_FOR_COLLECTION
		else:
			order.status = INVOICED

		# 3. Synchronize labour line quantity, rate, and amount to linked Service Job
		for item in doc.get("items", []):
			if getattr(item, "vs_job", None):
				sj_name = item.vs_job
				new_hours = flt(item.qty)
				new_rate = flt(item.rate)
				new_amount = flt(item.amount)

				frappe.db.set_value(
					"Service Job",
					sj_name,
					{
						"estimated_hours": new_hours,
						"rate": new_rate,
						"amount": new_amount,
					},
					update_modified=False,
				)

				for row in order.get("jobs", []):
					if row.service_job == sj_name:
						row.estimated_hours = new_hours
						row.rate = new_rate
						row.amount = new_amount

		order.flags.ignore_invoice_lock = True
		order.flags.ignore_job_lock = True
		order.save(ignore_permissions=True)
		if order.vehicle:
			v_status = vehicle_status_for(order.status)
			frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", v_status)


def handle_sales_invoice_cancel(doc, method=None):
	# 1. Credit Note was cancelled: re-lock Service Order with original Sales Invoice
	if getattr(doc, "is_return", 0) and getattr(doc, "return_against", None):
		orig_inv = doc.return_against
		order_name = getattr(doc, "vs_service_order", None) or frappe.db.get_value("Sales Invoice", orig_inv, "vs_service_order")
		if order_name:
			order = frappe.get_doc("Service Order", order_name)
			order.flags.ignore_invoice_lock = True
			order.sales_invoice = orig_inv
			inv_doc = frappe.get_doc("Sales Invoice", orig_inv)
			customer_credit = frappe.db.get_value("Customer", order.customer, "vs_credit_release") or 0
			if flt(inv_doc.outstanding_amount) <= 0 or customer_credit or order.credit_released:
				order.status = READY_FOR_COLLECTION
			else:
				order.status = INVOICED
			order.add_comment(
				"Comment",
				frappe._("Credit Note {0} was cancelled. Service Order is re-locked with original Sales Invoice {1}.").format(
					doc.name, orig_inv
				),
			)
			order.save(ignore_permissions=True)
			if order.vehicle:
				frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", vehicle_status_for(order.status))
		return

	# 2. Standard Sales Invoice cancellation
	if getattr(doc, "vs_service_order", None):
		order = frappe.get_doc("Service Order", doc.vs_service_order)
		if order.status not in ("Delivered", "Cancelled"):
			order.flags.ignore_invoice_lock = True
			order.status = READY_FOR_BILLING
			order.sales_invoice = None
			order.save(ignore_permissions=True)
			if order.vehicle:
				frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", vehicle_status_for(order.status))


def handle_payment_entry_submit(doc, method=None):
	for ref in getattr(doc, "references", []):
		if ref.reference_doctype == "Sales Invoice":
			inv = frappe.get_doc("Sales Invoice", ref.reference_name)
			if inv.vs_service_order and flt(inv.outstanding_amount) <= 0:
				order = frappe.get_doc("Service Order", inv.vs_service_order)
				if order.status == INVOICED:
					order.flags.ignore_invoice_lock = True
					order.status = READY_FOR_COLLECTION
					order.save(ignore_permissions=True)
					if order.vehicle:
						frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", vehicle_status_for(order.status))


def handle_payment_entry_cancel(doc, method=None):
	for ref in getattr(doc, "references", []):
		if ref.reference_doctype == "Sales Invoice":
			inv = frappe.get_doc("Sales Invoice", ref.reference_name)
			if inv.vs_service_order and flt(inv.outstanding_amount) > 0:
				order = frappe.get_doc("Service Order", inv.vs_service_order)
				if order.status == READY_FOR_COLLECTION and not order.credit_released:
					order.flags.ignore_invoice_lock = True
					order.status = INVOICED
					order.save(ignore_permissions=True)
					if order.vehicle:
						frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", vehicle_status_for(order.status))
