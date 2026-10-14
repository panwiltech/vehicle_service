# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.install import setup_default_board_tabs

DEFAULT_TABS = ["In Progress", "Awaiting Parts", "Quality Control", "Paused", "Ready to Start"]


class TestJobBoardTabs(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_default_tabs_seeded(self):
		setup_default_board_tabs()
		for label in DEFAULT_TABS:
			self.assertTrue(frappe.db.exists("Job Board Tab", label), label)
		parts = frappe.get_doc("Job Board Tab", "Awaiting Parts")
		self.assertEqual([r.status for r in parts.order_statuses], ["Waiting for Parts"])
		in_progress = frappe.get_doc("Job Board Tab", "In Progress")
		self.assertEqual(in_progress.include_if_any_job_in_progress, 1)
		ready = frappe.get_doc("Job Board Tab", "Ready to Start")
		self.assertEqual(
			sorted(r.status for r in ready.order_statuses),
			["Approved", "Checked In", "Ready for Work"],
		)

	def test_seed_is_idempotent(self):
		setup_default_board_tabs()
		before = frappe.db.count("Job Board Tab")
		setup_default_board_tabs()
		self.assertEqual(frappe.db.count("Job Board Tab"), before)
