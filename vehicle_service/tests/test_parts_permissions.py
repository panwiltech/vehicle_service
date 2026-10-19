# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate
from vehicle_service.state import READY_FOR_BILLING


class TestPartsPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_roles_and_users()
		self.setup_items_and_customer()
		from vehicle_service.install import setup_service_advisor_permissions
		setup_service_advisor_permissions()

	def setup_roles_and_users(self):
		roles_to_ensure = ["Job Controller", "Service Advisor", "Parts Controller", "Parts Manager", "Service Manager"]
		for r in roles_to_ensure:
			if not frappe.db.exists("Role", r):
				frappe.get_doc({"doctype": "Role", "role_name": r, "desk_access": 1}).insert(ignore_permissions=True)

		self.users = {
			"jc": "test_jc_parts@example.com",
			"sa": "test_sa_parts@example.com",
			"pc": "test_pc_parts@example.com",
			"pm": "test_pm_parts@example.com",
		}
		role_map = {
			"jc": ["Job Controller"],
			"sa": ["Service Advisor"],
			"pc": ["Parts Controller"],
			"pm": ["Parts Manager"],
		}

		for key, email in self.users.items():
			if not frappe.db.exists("User", email):
				u = frappe.new_doc("User")
				u.email = email
				u.first_name = key.upper()
				u.enabled = 1
				u.user_type = "System User"
				u.roles = []
				for r in role_map[key]:
					u.append("roles", {"role": r})
				u.new_password = "Password123!"
				u.insert(ignore_permissions=True)
			else:
				u = frappe.get_doc("User", email)
				u.enabled = 1
				u.roles = []
				for r in role_map[key]:
					u.append("roles", {"role": r})
				u.save(ignore_permissions=True)

	def setup_items_and_customer(self):
		if not frappe.db.exists("Customer", "Test Customer Parts"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Customer Parts"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Standard Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "TEST-PART-PERM-01"):
			p = frappe.new_doc("Item")
			p.item_code = "TEST-PART-PERM-01"
			p.item_name = "Test Brake Pad"
			p.item_group = "Raw Material"
			p.is_stock_item = 1
			p.valuation_rate = 100.0
			p.insert(ignore_permissions=True)

		if not frappe.db.exists("Service Vehicle", "TST-PART-VEH"):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = "TST-PART-VEH"
			v.customer = "Test Customer Parts"
			v.vin = "VIN-TST-PART-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

	def create_test_order(self, with_part=False, completed=False):
		frappe.set_user("Administrator")
		veh_id = f"TST-V-{frappe.generate_hash(length=6)}"
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = veh_id
		v.customer = "Test Customer Parts"
		v.vin = f"VIN-{frappe.generate_hash(length=8)}"
		v.make = "Toyota"
		v.model = "Hilux"
		v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer Parts"
		so.status = "In Progress"
		so.append("jobs", {
			"job_title": "General Service",
			"estimated_hours": 2.0,
			"rate": 50.0,
		})
		if with_part:
			so.append("parts", {
				"item_code": "TEST-PART-PERM-01",
				"item_name": "Test Brake Pad",
				"qty_required": 2.0,
				"qty_issued": 2.0,
				"qty_used": 2.0,
				"rate": 100.0,
				"approval_status": "Approved",
				"part_status": "Issued",
			})
		so.insert(ignore_permissions=True)

		if completed:
			for row in so.jobs:
				row.status = "Completed"
				if row.service_job:
					frappe.db.set_value("Service Job", row.service_job, "status", "Completed")
			so.status = READY_FOR_BILLING
			so.flags.ignore_job_lock = True
			so.save(ignore_permissions=True)

		return so

	def test_job_controller_cannot_add_parts_via_api(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import add_manual_part
		so = self.create_test_order()

		frappe.set_user(self.users["jc"])
		self.assertRaises(
			frappe.PermissionError,
			add_manual_part,
			service_order=so.name,
			item_code="TEST-PART-PERM-01",
			qty_required=1.0,
		)

	def test_service_advisor_cannot_add_parts_via_api(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import add_manual_part
		so = self.create_test_order()

		frappe.set_user(self.users["sa"])
		self.assertRaises(
			frappe.PermissionError,
			add_manual_part,
			service_order=so.name,
			item_code="TEST-PART-PERM-01",
			qty_required=1.0,
		)

	def test_parts_controller_and_manager_can_add_parts_via_api(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import add_manual_part
		so = self.create_test_order()

		# Parts Controller can add
		frappe.set_user(self.users["pc"])
		res_pc = add_manual_part(
			service_order=so.name,
			item_code="TEST-PART-PERM-01",
			qty_required=1.0,
			rate=100.0,
		)
		self.assertEqual(res_pc["status"], "success")

		# Parts Manager can add
		frappe.set_user(self.users["pm"])
		res_pm = add_manual_part(
			service_order=so.name,
			item_code="TEST-PART-PERM-01",
			qty_required=1.0,
			rate=100.0,
		)
		self.assertEqual(res_pm["status"], "success")

	def test_job_controller_and_service_advisor_cannot_modify_parts_on_order_save(self):
		so = self.create_test_order(with_part=True)

		# Job Controller cannot add parts directly to order
		frappe.set_user(self.users["jc"])
		so_jc = frappe.get_doc("Service Order", so.name)
		so_jc.append("parts", {
			"item_code": "TEST-PART-PERM-01",
			"qty_required": 1.0,
		})
		self.assertRaises(frappe.ValidationError, so_jc.save)

		# Service Advisor cannot remove parts from order
		frappe.set_user(self.users["sa"])
		so_sa = frappe.get_doc("Service Order", so.name)
		so_sa.parts = []
		self.assertRaises(frappe.ValidationError, so_sa.save)

	def test_service_advisor_can_change_labour_hours_on_service_order(self):
		so = self.create_test_order(with_part=True)

		frappe.set_user(self.users["sa"])
		so_sa = frappe.get_doc("Service Order", so.name)
		so_sa.jobs[0].estimated_hours = 3.5
		so_sa.save()
		so_sa.reload()
		self.assertEqual(flt(so_sa.jobs[0].estimated_hours), 3.5)

	def test_service_advisor_cannot_remove_or_reduce_parts_on_sales_invoice(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import create_sales_invoice_from_order
		so = self.create_test_order(with_part=True, completed=True)

		res = create_sales_invoice_from_order(so.name)
		inv_name = res["sales_invoice"]

		frappe.set_user(self.users["sa"])
		inv = frappe.get_doc("Sales Invoice", inv_name)

		# 1. Removing parts row must be blocked
		orig_items = [dict(it.as_dict()) for it in inv.items]
		inv.items = [it for it in inv.items if not getattr(it, "vs_part_row", None)]
		self.assertRaises(frappe.ValidationError, inv.save)

		# 2. Reducing quantity or rate of parts row must be blocked
		inv.reload()
		part_item = next(it for it in inv.items if getattr(it, "vs_part_row", None))
		part_item.qty = flt(part_item.qty) - 1.0
		self.assertRaises(frappe.ValidationError, inv.save)

	def test_service_advisor_can_modify_labour_on_sales_invoice(self):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import create_sales_invoice_from_order
		so = self.create_test_order(with_part=True, completed=True)

		res = create_sales_invoice_from_order(so.name)
		inv_name = res["sales_invoice"]

		frappe.set_user(self.users["sa"])
		inv = frappe.get_doc("Sales Invoice", inv_name)
		labour_item = next(it for it in inv.items if getattr(it, "vs_job", None))
		labour_item.qty = 4.0
		inv.save()
		inv.reload()
		updated_labour = next(it for it in inv.items if getattr(it, "vs_job", None))
		self.assertEqual(flt(updated_labour.qty), 4.0)
