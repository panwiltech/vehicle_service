# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
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
