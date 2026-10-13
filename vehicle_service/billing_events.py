# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from vehicle_service.state import INVOICED, READY_FOR_BILLING, READY_FOR_COLLECTION, vehicle_status_for


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
