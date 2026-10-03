# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import flt
from vehicle_service.state import INVOICED, READY_FOR_BILLING, READY_FOR_COLLECTION, vehicle_status_for


def handle_sales_invoice_submit(doc, method=None):
	if getattr(doc, "vs_service_order", None):
		order = frappe.get_doc("Service Order", doc.vs_service_order)
		customer_credit = frappe.db.get_value("Customer", order.customer, "vs_credit_release") or 0

		if flt(doc.outstanding_amount) <= 0 or customer_credit or order.credit_released:
			order.status = READY_FOR_COLLECTION
		else:
			order.status = INVOICED

		order.save(ignore_permissions=True)
		if order.vehicle:
			v_status = vehicle_status_for(order.status)
			frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", v_status)


def handle_sales_invoice_cancel(doc, method=None):
	if getattr(doc, "vs_service_order", None):
		order = frappe.get_doc("Service Order", doc.vs_service_order)
		if order.status not in ("Delivered", "Cancelled"):
			order.status = READY_FOR_BILLING
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
					order.status = INVOICED
					order.save(ignore_permissions=True)
					if order.vehicle:
						frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", vehicle_status_for(order.status))
