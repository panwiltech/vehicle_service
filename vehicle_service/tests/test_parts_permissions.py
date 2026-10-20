# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate
from vehicle_service.state import READY_FOR_BILLING
from vehicle_service.job_control_setup import (
	create_all_test_users,
	cleanup_test_data,
)
from vehicle_service.install import setup_service_advisor_permissions


class TestPartsPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup_service_advisor_permissions()
		self.users = create_all_test_users()

		# Ensure Parts Manager test user exists
		if not frappe.db.exists("User", "partsmanager.test@example.com"):
			pm = frappe.new_doc("User")
			pm.email = "partsmanager.test@example.com"
			pm.first_name = "Parts Manager"
			pm.enabled = 1
			pm.user_type = "System User"
			pm.roles = []
			pm.append("roles", {"role": "Parts Manager"})
			pm.new_password = "PartsManager123!"
			pm.insert(ignore_permissions=True)
		else:
			pm = frappe.get_doc("User", "partsmanager.test@example.com")
			pm.roles = []
			pm.append("roles", {"role": "Parts Manager"})
			pm.save(ignore_permissions=True)

		# Use existing data from the environment
		self.customer = frappe.db.get_value("Customer", {}, "name")
		if not self.customer:
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Workshop Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
			self.customer = c.name

		self.vehicle = frappe.db.get_value("Service Vehicle", {}, "name")
		if not self.vehicle:
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = "TST-VEH-01"
			v.customer = self.customer
			v.vin = "VIN-TST-001"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)
			self.vehicle = v.name

		self.part_item = frappe.db.get_value("Item", {"is_stock_item": 1}, "name")
		if not self.part_item:
			p = frappe.new_doc("Item")
			p.item_code = "TST-STOCK-PART"
			p.item_name = "Standard Test Part"
			p.item_group = "Raw Material"
			p.is_stock_item = 1
			p.valuation_rate = 100.0
			p.insert(ignore_permissions=True)
			self.part_item = p.name

		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Standard Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

		self.created_orders = []
		self.created_invoices = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for inv in self.created_invoices:
			if frappe.db.exists("Sales Invoice", inv):
				try:
					frappe.delete_doc("Sales Invoice", inv, force=True, ignore_permissions=True)
				except Exception:
					pass

		for order_name in self.created_orders:
			if frappe.db.exists("Service Order", order_name):
				try:
					frappe.db.set_value("Service Order", order_name, "status", "Cancelled")
					frappe.delete_doc("Service Order", order_name, force=True, ignore_permissions=True)
				except Exception:
					frappe.db.delete("Service Order Part", {"parent": order_name})
					frappe.db.delete("Service Order Job", {"parent": order_name})
					frappe.db.delete("Service Order", {"name": order_name})

		frappe.db.commit()

	def create_test_order(self, with_part=False, completed=False):
		frappe.set_user("Administrator")
		so = frappe.new_doc("Service Order")
		so.vehicle = self.vehicle
		so.customer = self.customer
		so.status = "In Progress"
		so.append("jobs", {
			"job_title": "General Inspection",
			"estimated_hours": 2.0,
			"rate": 50.0,
		})
		if with_part:
			so.append("parts", {
				"item_code": self.part_item,
				"qty_required": 2.0,
				"qty_issued": 2.0,
				"qty_used": 2.0,
				"rate": 100.0,
				"approval_status": "Approved",
				"part_status": "Issued",
			})
		so.insert(ignore_permissions=True)
		self.created_orders.append(so.name)

		if completed:
			for row in so.jobs:
				row.status = "Completed"
				if row.service_job:
					frappe.db.set_value("Service Job", row.service_job, "status", "Completed")
			so.status = READY_FOR_BILLING
			so.flags.ignore_job_lock = True
			so.save(ignore_permissions=True)

		return so

	def test_parts_controller_and_manager_can_add_parts_via_api(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import add_manual_part
		so = self.create_test_order()

		# Parts Controller can add parts
		frappe.set_user("partscontroller.test@example.com")
		res_pc = add_manual_part(
			service_order=so.name,
			item_code=self.part_item,
			qty_required=1.0,
			rate=120.0,
			reason="Added by Parts Controller"
		)
		self.assertEqual(res_pc["status"], "success")

		# Parts Manager can add parts
		frappe.set_user("partsmanager.test@example.com")
		res_pm = add_manual_part(
			service_order=so.name,
			item_code=self.part_item,
			qty_required=1.0,
			rate=120.0,
			reason="Added by Parts Manager"
		)
		self.assertEqual(res_pm["status"], "success")

	def test_job_controller_and_service_advisor_cannot_add_parts_via_api(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import add_manual_part
		so = self.create_test_order()

		frappe.set_user("jobcontroller.test@example.com")
		self.assertRaises(
			frappe.PermissionError,
			add_manual_part,
			service_order=so.name,
			item_code=self.part_item,
			qty_required=1.0,
		)

		frappe.set_user("serviceadvisor.test@example.com")
		self.assertRaises(
			frappe.PermissionError,
			add_manual_part,
			service_order=so.name,
			item_code=self.part_item,
			qty_required=1.0,
		)

	def test_parts_controller_can_add_parts_on_service_order_save(self):
		so = self.create_test_order()

		frappe.set_user("partscontroller.test@example.com")
		so_pc = frappe.get_doc("Service Order", so.name)
		so_pc.append("parts", {
			"item_code": self.part_item,
			"qty_required": 1.0,
			"rate": 100.0,
		})
		so_pc.save()
		so_pc.reload()
		self.assertTrue(any(p.item_code == self.part_item for p in so_pc.parts))

	def test_service_advisor_cannot_add_or_remove_parts_on_service_order(self):
		so = self.create_test_order(with_part=True)

		frappe.set_user("serviceadvisor.test@example.com")
		so_sa = frappe.get_doc("Service Order", so.name)

		# Adding parts must be blocked
		so_sa.append("parts", {
			"item_code": self.part_item,
			"qty_required": 1.0,
		})
		self.assertRaises(frappe.ValidationError, so_sa.save)

		# Removing parts must be blocked
		so_sa.reload()
		so_sa.parts = []
		self.assertRaises(frappe.ValidationError, so_sa.save)

	def test_service_advisor_can_change_labour_hours_on_service_order(self):
		so = self.create_test_order(with_part=True)

		frappe.set_user("serviceadvisor.test@example.com")
		so_sa = frappe.get_doc("Service Order", so.name)
		so_sa.jobs[0].estimated_hours = 3.5
		so_sa.save()
		so_sa.reload()
		self.assertEqual(flt(so_sa.jobs[0].estimated_hours), 3.5)

	def test_service_advisor_cannot_modify_parts_on_sales_invoice(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import create_sales_invoice_from_order
		so = self.create_test_order(with_part=True, completed=True)

		res = create_sales_invoice_from_order(so.name)
		inv_name = res["sales_invoice"]
		self.created_invoices.append(inv_name)

		frappe.set_user("serviceadvisor.test@example.com")
		inv = frappe.get_doc("Sales Invoice", inv_name)

		# 1. Removing parts row must be blocked
		inv.items = [it for it in inv.items if not getattr(it, "vs_part_row", None)]
		self.assertRaises(frappe.ValidationError, inv.save)

		# 2. Reducing quantity must be blocked
		inv.reload()
		part_item = next(it for it in inv.items if getattr(it, "vs_part_row", None))
		part_item.qty = flt(part_item.qty) - 1.0
		self.assertRaises(frappe.ValidationError, inv.save)

		# 3. Increasing quantity must also be blocked
		inv.reload()
		part_item = next(it for it in inv.items if getattr(it, "vs_part_row", None))
		part_item.qty = flt(part_item.qty) + 2.0
		self.assertRaises(frappe.ValidationError, inv.save)

		# 4. Modifying rate must be blocked
		inv.reload()
		part_item = next(it for it in inv.items if getattr(it, "vs_part_row", None))
		part_item.rate = flt(part_item.rate) + 10.0
		self.assertRaises(frappe.ValidationError, inv.save)

	def test_service_advisor_can_modify_labour_on_sales_invoice(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import create_sales_invoice_from_order
		so = self.create_test_order(with_part=True, completed=True)

		res = create_sales_invoice_from_order(so.name)
		inv_name = res["sales_invoice"]
		self.created_invoices.append(inv_name)

		frappe.set_user("serviceadvisor.test@example.com")
		inv = frappe.get_doc("Sales Invoice", inv_name)
		labour_item = next(it for it in inv.items if getattr(it, "vs_job", None))
		labour_item.qty = 4.0
		inv.save()
		inv.reload()
		updated_labour = next(it for it in inv.items if getattr(it, "vs_job", None))
		self.assertEqual(flt(updated_labour.qty), 4.0)

	def test_quotation_permissions_for_service_advisor_and_parts_controller(self):
		# Service Advisor has read, write, create on Quotation
		self.assertTrue(frappe.has_permission("Quotation", "read", user="serviceadvisor.test@example.com"))
		self.assertTrue(frappe.has_permission("Quotation", "write", user="serviceadvisor.test@example.com"))
		self.assertTrue(frappe.has_permission("Quotation", "create", user="serviceadvisor.test@example.com"))

		# Parts Controller has read on Quotation
		self.assertTrue(frappe.has_permission("Quotation", "read", user="partscontroller.test@example.com"))
		self.assertTrue(frappe.has_permission("Quotation", "write", user="partscontroller.test@example.com"))

	def test_job_board_page_access_for_service_advisor_and_parts_controller(self):
		page = frappe.get_doc("Page", "job-board")
		page_roles = {r.role for r in page.roles}
		self.assertIn("Service Advisor", page_roles)
		self.assertIn("Parts Controller", page_roles)
		self.assertIn("Job Controller", page_roles)
