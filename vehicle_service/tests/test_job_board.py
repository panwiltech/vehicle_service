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


class TestJobBoardMatching(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		setup_default_board_tabs()
		if not frappe.db.exists("Customer", "Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
	def _new_vehicle(self):
		reg = f"TST-BT-{frappe.generate_hash(length=8).upper()}"
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = reg
		v.customer = "Test Customer"
		v.vin = f"VIN-{reg}"
		v.make = "Toyota"
		v.model = "Hilux"
		v.insert(ignore_permissions=True)
		return reg

	def _make_order(self, status, job_statuses=()):
		so = frappe.new_doc("Service Order")
		so.vehicle = self._new_vehicle()
		so.customer = "Test Customer"
		for i, _ in enumerate(job_statuses):
			so.append("jobs", {"job_title": f"Job {i}", "estimated_hours": 1, "rate": 50})
		so.insert(ignore_permissions=True)
		for row, jstatus in zip(so.jobs, job_statuses):
			frappe.db.set_value("Service Job", row.service_job, "status", jstatus)
		frappe.db.set_value("Service Order", so.name, "status", status)
		return so.name

	def _names(self, tab_label):
		from vehicle_service.job_board import get_tab_order_names

		return get_tab_order_names(frappe.get_doc("Job Board Tab", tab_label))

	def test_multi_job_order_in_two_tabs(self):
		name = self._make_order("Waiting for Parts", ["In Progress", "Approved"])
		self.assertIn(name, self._names("Awaiting Parts"))
		self.assertIn(name, self._names("In Progress"))

	def test_order_without_jobs_matches_by_status_only(self):
		name = self._make_order("Waiting for Parts")
		self.assertIn(name, self._names("Awaiting Parts"))
		self.assertNotIn(name, self._names("In Progress"))

	def test_multiple_in_progress_jobs_single_entry(self):
		name = self._make_order("Approved", ["In Progress", "In Progress"])
		self.assertEqual(self._names("In Progress").count(name), 1)

	def test_cancelled_excluded(self):
		name = self._make_order("Cancelled", ["In Progress"])
		for label in DEFAULT_TABS:
			self.assertNotIn(name, self._names(label))

	def test_empty_tab_returns_empty(self):
		tab = frappe.new_doc("Job Board Tab")
		tab.tab_label = "Empty Test Tab"
		from vehicle_service.job_board import get_tab_order_names

		self.assertEqual(get_tab_order_names(tab), [])

	def test_disabled_or_unknown_tab_raises(self):
		from vehicle_service.job_board import get_board_orders

		self.addCleanup(frappe.db.set_value, "Job Board Tab", "Paused", "enabled", 1)
		frappe.db.set_value("Job Board Tab", "Paused", "enabled", 0)
		with self.assertRaises(frappe.DoesNotExistError):
			get_board_orders("Paused")
		with self.assertRaises(frappe.DoesNotExistError):
			get_board_orders("No Such Tab")

	def test_counts_match_orders(self):
		from vehicle_service.job_board import get_board_orders, get_board_tabs

		self._make_order("QC")
		tabs = {t["label"]: t for t in get_board_tabs()}
		qc = tabs["Quality Control"]
		self.assertEqual(qc["count"], len(get_board_orders(qc["name"])))
		self.assertGreaterEqual(qc["count"], 1)

	def test_card_shape(self):
		from vehicle_service.job_board import get_board_orders

		name = self._make_order("Waiting for Parts", ["In Progress", "Completed"])
		card = next(c for c in get_board_orders("Awaiting Parts") if c["name"] == name)
		self.assertEqual(card["job_count"], 2)
		self.assertEqual(card["jobs_completed"], 1)
		self.assertTrue(card["has_running_clock"])
		for key in ("status", "customer_name", "vehicle", "technicians"):
			self.assertIn(key, card)

	def test_permission_denied(self):
		from vehicle_service.job_board import get_board_orders, get_board_tabs

		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			get_board_tabs()
		with self.assertRaises(frappe.PermissionError):
			get_board_orders("In Progress")
