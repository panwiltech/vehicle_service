import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake import complete_check_in

class TestVehicleIntakePrint(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Vehicle Intake", {"vehicle": "PRINT-TEST-001"})
		frappe.db.delete("Service Vehicle", {"registration_no": "PRINT-TEST-001"})

		if not frappe.db.exists("Customer", "Test Print Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Print Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		v = frappe.new_doc("Service Vehicle")
		v.registration_no = "PRINT-TEST-001"
		v.vin = "VINPRINT12345678"
		v.make = "Volkswagen"
		v.model = "Golf"
		v.year = 2020
		v.colour = "Deep Blue"
		v.customer = "Test Print Customer"
		v.current_mileage = 60000
		v.insert(ignore_permissions=True)

	def test_vehicle_intake_sheet_renders_with_signature(self):
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "PRINT-TEST-001"
		intake.odometer_in = 62500
		intake.fuel_level = "3/4"
		intake.customer_complaint = "Air conditioning not blowing cold"
		intake.existing_damage = "Stone chips on windscreen"
		intake.vehicle_contents = "Child safety seat in rear"
		sample_sig = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
		intake.customer_signature = sample_sig
		intake.insert(ignore_permissions=True)
		complete_check_in(intake.name)

		# Test that Print Format is linked to Vehicle Intake DocType
		pf_doctype = frappe.db.get_value("Print Format", "Vehicle Intake Sheet", "doc_type")
		self.assertEqual(pf_doctype, "Vehicle Intake", "Print Format 'Vehicle Intake Sheet' must belong to DocType 'Vehicle Intake'")

		# Test rendering print format for Vehicle Intake
		html = frappe.get_print("Vehicle Intake", intake.name, "Vehicle Intake Sheet")
		self.assertTrue("PRINT-TEST-001" in html, "Vehicle registration missing from print")
		self.assertTrue("62,500" in html or "62500" in html, "Odometer reading missing from print")
		self.assertTrue("Stone chips on windscreen" in html, "Damages missing from print")
		self.assertTrue("Child safety seat in rear" in html, "Contents missing from print")
		self.assertTrue(sample_sig in html, "Customer signature missing from rendered print")
