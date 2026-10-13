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

	def test_compute_operational_status_routes_to_ready_for_billing(self):
		jobs = [{"status": "Completed"}]
		parts = []
		self.assertEqual(compute_operational_status(jobs, parts), "Ready for Billing")
