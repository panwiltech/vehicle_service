# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestServiceOrderActions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Customer", "Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Standard Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

	def _order_with_job(self):
		from vehicle_service.job_control import add_job

		# Unique vehicle per order: only one active order per vehicle is allowed
		veh = f"TST-ACT-{frappe.generate_hash(length=6).upper()}"
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = veh
		v.customer = "Test Customer"
		v.vin = f"VIN-{veh}"
		v.make = "Toyota"
		v.model = "Hilux"
		v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh
		so.customer = "Test Customer"
		so.insert(ignore_permissions=True)
		add_job(so.name, job_title="Action Test Job", estimated_hours=1.0)
		return so

	def test_repeated_invoice_creation_yields_single_draft(self):
		from vehicle_service.job_control import complete_service_order
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			create_sales_invoice_from_order,
		)

		so = self._order_with_job()
		complete_service_order(so.name)

		first = create_sales_invoice_from_order(so.name)
		second = create_sales_invoice_from_order(so.name)

		self.assertEqual(first["sales_invoice"], second["sales_invoice"])
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"vs_service_order": so.name, "docstatus": ["!=", 2]}), 1
		)
		# Creating an invoice must never submit it
		self.assertEqual(frappe.db.get_value("Sales Invoice", first["sales_invoice"], "docstatus"), 0)

	def test_complete_and_create_invoice_is_idempotent(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			complete_and_create_invoice,
		)

		so = self._order_with_job()
		first = complete_and_create_invoice(so.name)
		status_after_first = frappe.db.get_value("Service Order", so.name, "status")

		# A repeated call must return the same invoice instead of erroring or re-completing
		second = complete_and_create_invoice(so.name)

		self.assertEqual(first["sales_invoice"], second["sales_invoice"])
		self.assertEqual(frappe.db.get_value("Service Order", so.name, "status"), status_after_first)
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"vs_service_order": so.name, "docstatus": ["!=", 2]}), 1
		)
