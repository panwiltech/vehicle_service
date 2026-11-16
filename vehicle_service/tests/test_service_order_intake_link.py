import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake import (
	complete_check_in,
	create_service_order_from_intake,
)

class TestServiceOrderIntakeLink(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Vehicle Intake", {"vehicle": "LINK-TEST-001"})
		frappe.db.delete("Service Order", {"vehicle": "LINK-TEST-001"})
		frappe.db.delete("Service Vehicle", {"registration_no": "LINK-TEST-001"})

		if not frappe.db.exists("Customer", "Test Link Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Link Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		v = frappe.new_doc("Service Vehicle")
		v.registration_no = "LINK-TEST-001"
		v.vin = "VINLINK12345678"
		v.make = "Honda"
		v.model = "Civic"
		v.year = 2021
		v.customer = "Test Link Customer"
		v.current_mileage = 30000
		v.insert(ignore_permissions=True)

	def test_service_order_created_from_intake_has_link_and_snapshot(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "LINK-TEST-001"
		intake.odometer_in = 32000
		intake.fuel_level = "1/2"
		intake.customer_complaint = "Brake fluid replacement"
		intake.existing_damage = "None"
		intake.vehicle_contents = "All standard items"
		intake.customer_signature = "data:image/png;base64,sample_signature"
		intake.insert(ignore_permissions=True)
		complete_check_in(intake.name)

		res = create_service_order_from_intake(intake.name)
		order = frappe.get_doc("Service Order", res["service_order"])

		self.assertEqual(order.vehicle_intake, intake.name)
		self.assertEqual(order.odometer_in, 32000)
		self.assertEqual(order.customer_signature, "data:image/png;base64,sample_signature")

	def test_service_order_cannot_move_to_in_progress_without_intake(self):
		order = frappe.new_doc("Service Order")
		order.vehicle = "LINK-TEST-001"
		order.customer = "Test Link Customer"
		order.status = "In Progress"  # Attempt to move to In Progress directly without intake
		order.flags.strict_intake_validation = True

		with self.assertRaises(frappe.ValidationError):
			order.insert(ignore_permissions=True)

	def test_service_order_cannot_link_draft_intake(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "LINK-TEST-001"
		intake.insert(ignore_permissions=True)  # Still Draft

		order = frappe.new_doc("Service Order")
		order.vehicle = "LINK-TEST-001"
		order.customer = "Test Link Customer"
		order.vehicle_intake = intake.name
		order.status = "In Progress"

		with self.assertRaises(frappe.ValidationError):
			order.insert(ignore_permissions=True)

	def test_service_order_cannot_be_created_without_vehicle_intake(self):
		order = frappe.new_doc("Service Order")
		order.vehicle = "LINK-TEST-001"
		order.customer = "Test Link Customer"
		order.status = "Draft"
		order.flags.strict_intake_validation = True

		with self.assertRaises(frappe.ValidationError):
			order.insert(ignore_permissions=True)
