# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.workspace_setup import setup_production_workspaces


class TestWorkspaceSetup(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		setup_production_workspaces()

	def test_vehicle_service_parent_workspace(self):
		"""Parent workspace must be top-level with icon 'car' and sequence_id 1.0."""
		ws = frappe.get_doc("Workspace", "Vehicle Service")
		self.assertIn(ws.parent_page or "", ["", None])
		self.assertEqual(ws.sequence_id, 1.0)
		self.assertEqual(ws.icon, "car")
		self.assertEqual(ws.is_hidden, 0)
		self.assertEqual(ws.public, 1)

	def test_child_workspaces_hierarchy(self):
		"""All 5 child portals must have parent_page 'Vehicle Service' with correct sequence and icons."""
		expected = {
			"Service Advisor": {"seq": 1.1, "icon": "clipboard-list"},
			"Job Control Board": {"seq": 1.2, "icon": "circle-gauge"},
			"Technician Portal": {"seq": 1.3, "icon": "wrench"},
			"Quality Control": {"seq": 1.4, "icon": "clipboard-check"},
			"Parts Store": {"seq": 1.5, "icon": "package"},
		}
		for name, conf in expected.items():
			ws = frappe.get_doc("Workspace", name)
			self.assertEqual(ws.parent_page, "Vehicle Service", f"{name} parent_page mismatch")
			self.assertEqual(ws.sequence_id, conf["seq"], f"{name} sequence_id mismatch")
			self.assertEqual(ws.icon, conf["icon"], f"{name} icon mismatch")
			self.assertEqual(ws.is_hidden, 0, f"{name} should not be hidden")
			self.assertEqual(ws.public, 1, f"{name} should be public")

	def test_job_control_board_content(self):
		"""Job Control Board content and shortcuts must not be empty."""
		ws = frappe.get_doc("Workspace", "Job Control Board")
		self.assertTrue(ws.content and ws.content != "[]", "Job Control Board content cannot be empty")
		self.assertTrue(len(ws.shortcuts) > 0, "Job Control Board must have shortcuts")
		self.assertTrue(len(ws.links) > 0, "Job Control Board must have links")
