import frappe
from frappe.tests.utils import FrappeTestCase

class TestVehicleIntakeSchema(FrappeTestCase):
	def test_vehicle_intake_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Vehicle Intake"), "DocType 'Vehicle Intake' does not exist")
		meta = frappe.get_meta("Vehicle Intake")
		self.assertTrue(meta.has_field("vehicle"))
		self.assertTrue(meta.has_field("customer"))
		self.assertTrue(meta.has_field("odometer_in"))
		self.assertTrue(meta.has_field("fuel_level"))
		self.assertTrue(meta.has_field("existing_damage"))
		self.assertTrue(meta.has_field("vehicle_contents"))
		self.assertTrue(meta.has_field("customer_signature"))
		self.assertEqual(meta.get_field("customer_signature").fieldtype, "Signature")
		self.assertTrue(meta.has_field("intake_photos"))
		self.assertEqual(meta.get_field("intake_photos").fieldtype, "Table")
		self.assertEqual(meta.get_field("intake_photos").options, "Vehicle Intake Photo")

	def test_vehicle_intake_photo_doctype_exists(self):
		self.assertTrue(frappe.db.exists("DocType", "Vehicle Intake Photo"), "DocType 'Vehicle Intake Photo' does not exist")
		meta = frappe.get_meta("Vehicle Intake Photo")
		self.assertTrue(bool(meta.istable), "Vehicle Intake Photo must be a child table")
		self.assertTrue(meta.has_field("photo"))
		self.assertEqual(meta.get_field("photo").fieldtype, "Attach Image")

	def test_vehicle_intake_has_step_sections(self):
		frappe.reload_doc("vehicle_service", "doctype", "vehicle_intake", force=True)
		meta = frappe.get_meta("Vehicle Intake")
		self.assertTrue(meta.has_field("step_progress_html"), "Missing step_progress_html")
		self.assertTrue(meta.has_field("sb_step_1_vehicle"), "Missing sb_step_1_vehicle")
		self.assertTrue(meta.has_field("sb_step_2_customer"), "Missing sb_step_2_customer")
		self.assertTrue(meta.has_field("sb_step_3_condition"), "Missing sb_step_3_condition")
		self.assertTrue(meta.has_field("sb_step_4_review"), "Missing sb_step_4_review")
		self.assertTrue(meta.has_field("step_review_html"), "Missing step_review_html")
