import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake import (
	complete_check_in,
	correct_intake,
	create_service_order_from_intake,
)

class TestVehicleIntake(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Vehicle Intake", {"vehicle": "INTAKE-TEST-001"})
		frappe.db.delete("Service Vehicle", {"registration_no": "INTAKE-TEST-001"})

		# Create test customer if not exists
		if not frappe.db.exists("Customer", "Test Intake Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Intake Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create test vehicle if not exists
		if not frappe.db.exists("Service Vehicle", "INTAKE-TEST-001"):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = "INTAKE-TEST-001"
			v.vin = "VIN1234567890"
			v.make = "Toyota"
			v.model = "Corolla"
			v.year = 2022
			v.customer = "Test Intake Customer"
			v.current_mileage = 40000
			v.insert(ignore_permissions=True)
		else:
			v = frappe.get_doc("Service Vehicle", "INTAKE-TEST-001")
			v.current_mileage = 40000
			v.save(ignore_permissions=True)

	def test_draft_intake_creation_and_defaults(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "INTAKE-TEST-001"
		intake.insert(ignore_permissions=True)

		self.assertEqual(intake.customer, "Test Intake Customer")
		self.assertEqual(intake.status, "Draft")
		self.assertEqual(intake.license_plate, "INTAKE-TEST-001")

	def test_complete_check_in_validates_odometer(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "INTAKE-TEST-001"
		intake.odometer_in = 35000  # Lower than current 40,000
		intake.insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			complete_check_in(intake.name)

	def test_complete_check_in_success_and_locks(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "INTAKE-TEST-001"
		intake.odometer_in = 45000
		intake.fuel_level = "3/4"
		intake.customer_complaint = "Squeaking brakes on sudden stop"
		intake.existing_damage = "Scratch on left front wing"
		intake.vehicle_contents = "Spare wheel, jack, emergency triangle"
		sample_sig = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
		intake.customer_signature = sample_sig
		intake.insert(ignore_permissions=True)

		res = complete_check_in(intake.name)
		self.assertEqual(res["status"], "success")

		intake.reload()
		self.assertEqual(intake.status, "Checked In")
		self.assertEqual(intake.intake_frozen, 1)
		self.assertTrue(bool(intake.checked_in_on))
		self.assertEqual(intake.customer_signature, sample_sig)

		# Check vehicle updated
		veh = frappe.get_doc("Service Vehicle", "INTAKE-TEST-001")
		self.assertEqual(veh.current_mileage, 45000)
		self.assertEqual(veh.vehicle_status, "In Workshop")

	def test_correct_intake(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "INTAKE-TEST-001"
		intake.odometer_in = 46000
		intake.insert(ignore_permissions=True)
		complete_check_in(intake.name)

		# Admin has System Manager role so allowed
		correct_intake(intake.name, "odometer_in", "47500", "Customer corrected dashboard reading")

		intake.reload()
		self.assertEqual(intake.odometer_in, 47500)
		self.assertTrue(len(intake.corrections) >= 1)
		corr = intake.corrections[-1]
		self.assertEqual(corr.fieldname, "odometer_in")
		self.assertEqual(corr.new_value, "47500")
		self.assertEqual(corr.reason, "Customer corrected dashboard reading")

		# Check vehicle mileage updated as well
		veh = frappe.get_doc("Service Vehicle", "INTAKE-TEST-001")
		self.assertEqual(veh.current_mileage, 47500)

	def test_create_service_order_from_intake(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "INTAKE-TEST-001"
		intake.odometer_in = 48000
		intake.fuel_level = "1/2"
		intake.customer_complaint = "100k major service inspection"
		sample_sig = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
		intake.customer_signature = sample_sig
		intake.insert(ignore_permissions=True)
		complete_check_in(intake.name)

		res = create_service_order_from_intake(intake.name)
		order_name = res["service_order"]
		self.assertTrue(bool(order_name))

		order = frappe.get_doc("Service Order", order_name)
		self.assertEqual(order.vehicle_intake, intake.name)
		self.assertEqual(order.vehicle, intake.vehicle)
		self.assertEqual(order.customer, intake.customer)
		self.assertEqual(order.odometer_in, 48000)
		self.assertEqual(order.customer_signature, sample_sig)

		intake.reload()
		self.assertEqual(intake.service_order, order_name)

		# Test double creation returns existing
		res2 = create_service_order_from_intake(intake.name)
		self.assertEqual(res2["service_order"], order_name)
