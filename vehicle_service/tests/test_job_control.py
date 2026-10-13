# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from vehicle_service.state import (
	board_status_for,
	compute_operational_status,
	COMPLETED_STATES,
)


class TestJobControl(FrappeTestCase):
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

	def test_board_status_for(self):
		self.assertEqual(board_status_for("Draft"), "Open")
		self.assertEqual(board_status_for("Checked In"), "Open")
		self.assertEqual(board_status_for("Awaiting Approval"), "Open")
		self.assertEqual(board_status_for("Approved"), "Open")
		self.assertEqual(board_status_for("Waiting for Parts"), "Open")
		self.assertEqual(board_status_for("Ready for Work"), "Open")
		self.assertEqual(board_status_for("In Progress"), "In Progress")
		self.assertEqual(board_status_for("QC"), "In Progress")
		self.assertEqual(board_status_for("Paused"), "Paused")
		self.assertEqual(board_status_for("Ready for Billing"), "Completed")
		self.assertEqual(board_status_for("Invoiced"), "Completed")
		self.assertEqual(board_status_for("Ready for Collection"), "Completed")
		self.assertEqual(board_status_for("Delivered"), "Completed")
		self.assertIsNone(board_status_for("Cancelled"))

	def test_board_fields_and_completed_order_lock(self):
		# Setup vehicle
		veh_id = "TST-BOARD-01"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-BOARD-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.append("jobs", {
			"job_title": "Oil Change",
			"estimated_hours": 1.5,
			"rate": 50.0,
			"technician_name": "John Doe",
		})
		so.insert(ignore_permissions=True)

		self.assertEqual(so.board_status, "Open")
		self.assertEqual(so.job_count, 1)
		self.assertIn("John Doe", so.technicians)
		self.assertIsNotNone(so.order_date)

		# Transition to Ready for Billing (Completed)
		so.status = "Ready for Billing"
		so.save(ignore_permissions=True)
		self.assertEqual(so.board_status, "Completed")

		# Modifying jobs on completed order directly should fail
		so.jobs[0].job_title = "Modified Title"
		self.assertRaises(frappe.ValidationError, so.save)

		# Reload so doc status clean
		so.reload()
		# Direct Service Job edit on completed order should also fail
		sj_name = so.jobs[0].service_job
		sj = frappe.get_doc("Service Job", sj_name)
		sj.job_title = "Modified Title directly"
		self.assertRaises(frappe.ValidationError, sj.save)

	def test_job_control_actions_workflow(self):
		from vehicle_service.job_control import (
			add_job,
			assign_technician,
			start_clock,
			pause_clock,
			complete_service_order,
			order_has_permission,
		)

		veh_id = "TST-JC-01"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-JC-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		# Ensure test employee exists
		emp_name = frappe.db.get_value("Employee", {"first_name": "Alex", "last_name": "Tech"})
		if not emp_name:
			company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company")[0].name
			emp = frappe.new_doc("Employee")
			emp.first_name = "Alex"
			emp.last_name = "Tech"
			emp.gender = "Male"
			emp.company = company
			emp.date_of_birth = "1990-01-01"
			emp.date_of_joining = "2020-01-01"
			emp.status = "Active"
			emp.insert(ignore_permissions=True)
			emp_id = emp.name
		else:
			emp_id = emp_name

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.insert(ignore_permissions=True)

		# 1. Add Job
		res_add = add_job(so.name, job_title="Brake Service", estimated_hours=2.0)
		job_name = res_add["job"]
		job = frappe.get_doc("Service Job", job_name)
		self.assertEqual(job.status, "Approved")
		so.reload()
		self.assertEqual(len(so.jobs), 1)

		# 2. Start Clock without technician should fail
		self.assertRaises(frappe.ValidationError, start_clock, job_name)

		# 3. Assign Technician
		assign_technician(job_name, emp_id)
		job.reload()
		self.assertEqual(job.technician, emp_id)
		self.assertEqual(job.status, "Assigned")

		# 4. Start Clock
		start_clock(job_name)
		job.reload()
		self.assertEqual(job.status, "In Progress")
		self.assertEqual(len(job.time_logs), 1)
		self.assertIsNone(job.time_logs[0].to_time)

		# 5. Starting a second clock for same technician on another job must fail
		res_add2 = add_job(so.name, job_title="Tyre Rotation", technician=emp_id)
		self.assertRaises(frappe.ValidationError, start_clock, res_add2["job"])

		# 6. Pause Clock
		pause_clock(job_name, reason="Lunch break")
		job.reload()
		self.assertEqual(job.status, "Paused")
		self.assertIsNotNone(job.time_logs[0].to_time)

		# 7. Resume Clock
		start_clock(job_name)
		job.reload()
		self.assertEqual(job.status, "In Progress")
		self.assertEqual(len(job.time_logs), 2)

		# 8. Complete Service Order
		complete_service_order(so.name)
		so.reload()
		job.reload()
		self.assertEqual(so.status, "Ready for Billing")
		self.assertEqual(so.board_status, "Completed")
		self.assertEqual(job.status, "Completed")
		self.assertIsNotNone(job.time_logs[1].to_time)

		# 9. Actions on completed order should be rejected
		self.assertRaises(frappe.ValidationError, add_job, so.name, "New Job")
		self.assertRaises(frappe.ValidationError, start_clock, job_name)

		# 10. Permission hook check
		self.assertFalse(order_has_permission(so, ptype="write", user="test_jc_user"))

	def test_sales_invoice_labour_hours_sync(self):
		from vehicle_service.job_control import add_job, complete_service_order
		from vehicle_service.vehicle_service.doctype.service_order.service_order import create_sales_invoice_from_order

		veh_id = "TST-INV-01"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-INV-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.insert(ignore_permissions=True)

		res_add = add_job(so.name, job_title="Engine Diagnostics", estimated_hours=1.0)
		job_name = res_add["job"]

		# Complete order to ready for billing
		complete_service_order(so.name)

		# Create Sales Invoice
		res_inv = create_sales_invoice_from_order(so.name)
		inv = frappe.get_doc("Sales Invoice", res_inv["sales_invoice"])

		# Service advisor modifies labour quantity from 1.0 to 2.5 hours on the invoice
		found_job_item = False
		for item in inv.items:
			if getattr(item, "vs_job", None) == job_name:
				item.qty = 2.5
				found_job_item = True
		self.assertTrue(found_job_item)

		inv.save(ignore_permissions=True)
		inv.submit()

		# Verify that the Service Job estimated_hours and row on order updated to 2.5
		job = frappe.get_doc("Service Job", job_name)
		self.assertEqual(flt(job.estimated_hours), 2.5)

		so.reload()
		for row in so.jobs:
			if row.service_job == job_name:
				self.assertEqual(flt(row.estimated_hours), 2.5)
