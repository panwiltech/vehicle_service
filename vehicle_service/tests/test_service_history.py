# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.job_control import add_job


class TestServiceHistorySchema(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Customer", "History Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "History Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Workshop Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

	def _create_vehicle(self, reg_no: str, vin: str):
		if frappe.db.exists("Service Vehicle", reg_no):
			return frappe.get_doc("Service Vehicle", reg_no)
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = reg_no
		v.vin = vin
		v.make = "Toyota"
		v.model = "Hilux"
		v.year = 2022
		v.customer = "History Test Customer"
		v.current_mileage = 15000
		v.insert(ignore_permissions=True)
		return v

	def test_vehicle_rename_tracks_previous_registrations_idempotently(self):
		old_reg = f"OLD-{frappe.generate_hash(length=5).upper()}"
		mid_reg = f"MID-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(old_reg, f"VIN-{old_reg}")

		frappe.rename_doc("Service Vehicle", old_reg, f" {mid_reg.lower()} ", force=True)
		doc = frappe.get_doc("Service Vehicle", mid_reg)
		self.assertEqual(doc.registration_no, mid_reg)
		self.assertEqual(doc.previous_registration_nos, old_reg)

		frappe.rename_doc("Service Vehicle", mid_reg, old_reg, force=True)
		frappe.rename_doc("Service Vehicle", old_reg, mid_reg, force=True)
		doc.reload()
		tokens = [t.strip() for t in (doc.previous_registration_nos or "").split(",") if t.strip()]
		self.assertEqual(sorted(tokens), sorted([old_reg]))
		self.assertNotIn(mid_reg, tokens)

	def test_vehicle_rename_allowed_without_force_and_preserves_multi_hop_history(self):
		p1 = f"P1-{frappe.generate_hash(length=5).upper()}"
		p2 = f"P2-{frappe.generate_hash(length=5).upper()}"
		p3 = f"P3-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(p1, f"VIN-{p1}")

		# allow_rename=1 permits renaming without force=True
		frappe.rename_doc("Service Vehicle", p1, p2)
		frappe.rename_doc("Service Vehicle", p2, f"  {p3.lower()}  ")
		doc = frappe.get_doc("Service Vehicle", p3)
		self.assertEqual(doc.registration_no, p3)
		self.assertEqual(doc.previous_registration_nos, f"{p1}, {p2}")

		# Cycling back to p1 removes p1 from previous_registration_nos
		frappe.rename_doc("Service Vehicle", p3, p1)
		doc = frappe.get_doc("Service Vehicle", p1)
		self.assertEqual(doc.previous_registration_nos, f"{p2}, {p3}")

		# Blank/whitespace-only plate is rejected
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Service Vehicle", p1, "   ")

	def test_follows_up_job_mirrors_between_service_job_and_order(self):
		reg = f"FUP-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(reg, f"VIN-{reg}")
		so1 = frappe.new_doc("Service Order")
		so1.vehicle = reg
		so1.customer = "History Test Customer"
		so1.insert(ignore_permissions=True)
		orig_job = add_job(so1.name, job_title="Replace Rear Brake Pads", category="Recommended")
		so1.reload()
		so1.status = "Delivered"
		so1.flags.ignore_job_lock = True
		so1.save(ignore_permissions=True)

		so2 = frappe.new_doc("Service Order")
		so2.vehicle = reg
		so2.customer = "History Test Customer"
		so2.insert(ignore_permissions=True)
		follow_job = add_job(
			so2.name,
			job_title="Replace Rear Brake Pads (Follow-Up)",
			follows_up_job=orig_job["job"],
		)

		sj2 = frappe.get_doc("Service Job", follow_job["job"])
		self.assertEqual(sj2.follows_up_job, orig_job["job"])
		so2.reload()
		matching_rows = [r for r in so2.jobs if r.service_job == sj2.name]
		self.assertEqual(len(matching_rows), 1)
		self.assertEqual(matching_rows[0].follows_up_job, orig_job["job"])

	def test_follows_up_job_syncs_bidirectionally_on_service_order_save(self):
		reg = f"SYN-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(reg, f"VIN-{reg}")
		so1 = frappe.new_doc("Service Order")
		so1.vehicle = reg
		so1.customer = "History Test Customer"
		so1.insert(ignore_permissions=True)
		rec_job_a = add_job(so1.name, job_title="Flush Brake Fluid", category="Recommended")
		rec_job_b = add_job(so1.name, job_title="Align Wheels", category="Recommended")
		so1.reload()
		so1.status = "Delivered"
		so1.flags.ignore_job_lock = True
		so1.save(ignore_permissions=True)

		so2 = frappe.new_doc("Service Order")
		so2.vehicle = reg
		so2.customer = "History Test Customer"
		so2.insert(ignore_permissions=True)

		# Direction 1: Service Job -> Service Order Job when standalone Service Job is created
		sj_standalone = frappe.new_doc("Service Job")
		sj_standalone.service_order = so2.name
		sj_standalone.vehicle = reg
		sj_standalone.job_title = "Standalone Follow-Up"
		sj_standalone.follows_up_job = rec_job_a["job"]
		sj_standalone.insert(ignore_permissions=True)

		so2.reload()
		so2.save(ignore_permissions=True)
		row_standalone = next(r for r in so2.jobs if r.service_job == sj_standalone.name)
		self.assertEqual(row_standalone.follows_up_job, rec_job_a["job"])

		# Direction 1b: Service Job -> Service Order Job when existing Service Job is updated directly
		sj_direct = frappe.new_doc("Service Job")
		sj_direct.service_order = so2.name
		sj_direct.vehicle = reg
		sj_direct.job_title = "Direct Update Follow-Up"
		sj_direct.insert(ignore_permissions=True)
		so2.reload()
		so2.save(ignore_permissions=True)

		sj_direct.reload()
		sj_direct.follows_up_job = rec_job_b["job"]
		sj_direct.save(ignore_permissions=True)
		so2.reload()
		so2.save(ignore_permissions=True)
		row_direct = next(r for r in so2.jobs if r.service_job == sj_direct.name)
		self.assertEqual(row_direct.follows_up_job, rec_job_b["job"])

		# Direction 2: Service Order Job -> Service Job when child row is updated on Service Order
		row_direct.follows_up_job = rec_job_a["job"]
		so2.save(ignore_permissions=True)
		sj_direct.reload()
		self.assertEqual(sj_direct.follows_up_job, rec_job_a["job"])
