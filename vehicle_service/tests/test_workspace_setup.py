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

	def test_crm_dock_item(self):
		"""CRM must be in the vehicle_service dock and visible."""
		dock = frappe.get_doc("Dock", "vehicle_service")
		crm_items = [it for it in dock.items if it.link_to == "CRM" or it.title == "CRM"]
		self.assertTrue(len(crm_items) > 0, "CRM must be present in vehicle_service dock")
		self.assertEqual(crm_items[0].hidden, 0, "CRM dock item must not be hidden")

	def test_crm_desktop_icon(self):
		"""CRM Desktop Icon must be top-level and not hidden."""
		icon = frappe.get_doc("Desktop Icon", "CRM")
		self.assertEqual(icon.hidden, 0, "CRM desktop icon must not be hidden")
		self.assertIsNone(icon.parent_icon, "CRM desktop icon must be top-level (no parent_icon)")

	def test_desk_sidebar_not_forced_in_css_and_js(self):
		"""Desktop home screen (data-route="desktop") must not have sidebar forced visible."""
		import os
		app_path = frappe.get_app_path("vehicle_service")
		css_path = os.path.join(app_path, "public", "css", "job_board.css")
		js_path = os.path.join(app_path, "public", "js", "job_board.js")

		with open(css_path) as f:
			css_content = f.read()
		with open(js_path) as f:
			js_content = f.read()

		# Ensure unqualified global .body-sidebar-container { display: flex !important } does not exist
		self.assertNotIn("\n.body-sidebar-container {\n\tdisplay: flex !important;", css_content)
		# Ensure desktop route is specifically handled to hide sidebar
		self.assertIn('data-route="desktop"', css_content)
		# Ensure JS checks for desktop route before opening sidebar
		self.assertIn("isDesktopPage", js_content)

	def test_crm_in_primary_desk_apps(self):
		"""CRM must be in extend_bootinfo primary_desk_apps."""
		from vehicle_service.boot import extend_bootinfo
		bootinfo = frappe._dict()
		extend_bootinfo(bootinfo)
		app_titles = [app["app_title"] for app in bootinfo.app_data]
		self.assertIn("CRM", app_titles)

