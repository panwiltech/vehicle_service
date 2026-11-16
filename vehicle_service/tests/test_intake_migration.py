import frappe
from frappe.tests.utils import FrappeTestCase

class TestIntakeMigration(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Vehicle Intake", {"vehicle": "MIG-TEST-001"})
		frappe.db.delete("Service Order", {"vehicle": "MIG-TEST-001"})
		frappe.db.delete("Service Vehicle", {"registration_no": "MIG-TEST-001"})

		if not frappe.db.exists("Customer", "Test Migration Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Migration Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		v = frappe.new_doc("Service Vehicle")
		v.registration_no = "MIG-TEST-001"
		v.vin = "VINMIG12345678"
		v.make = "Nissan"
		v.model = "X-Trail"
		v.year = 2019
		v.customer = "Test Migration Customer"
		v.current_mileage = 70000
		v.insert(ignore_permissions=True)

	def test_migration_creates_intakes_and_preserves_signatures(self):
		from vehicle_service.patches.v1_0.migrate_service_orders_to_vehicle_intakes import execute

		order = frappe.new_doc("Service Order")
		order.vehicle = "MIG-TEST-001"
		order.customer = "Test Migration Customer"
		order.odometer_in = 71500
		order.fuel_level = "1/4"
		order.customer_complaint = "Clutch shudder on uphill start"
		order.existing_damage = "Dent on rear door and cracked reflector"
		order.vehicle_contents = "Luggage net and first aid kit"
		sample_sig = "data:image/png;base64,sample_migrated_signature_12345"
		order.customer_signature = sample_sig
		order.flags.in_migration = True
		order.flags.ignore_permissions = True
		order.insert()

		# Run migration
		execute()

		order.reload()
		self.assertTrue(bool(order.vehicle_intake), "Order should have vehicle_intake linked after migration")

		intake = frappe.get_doc("Vehicle Intake", order.vehicle_intake)
		self.assertEqual(intake.vehicle, "MIG-TEST-001")
		self.assertEqual(intake.customer, "Test Migration Customer")
		self.assertEqual(intake.odometer_in, 71500)
		self.assertEqual(intake.fuel_level, "1/4")
		self.assertEqual(intake.existing_damage, "Dent on rear door and cracked reflector")
		self.assertEqual(intake.vehicle_contents, "Luggage net and first aid kit")
		self.assertEqual(intake.customer_signature, sample_sig)
		self.assertEqual(intake.status, "Checked In")
		self.assertEqual(intake.service_order, order.name)

		# Idempotency check: running execute again does not duplicate intake
		execute()
		matching_intakes = frappe.get_all("Vehicle Intake", filters={"service_order": order.name})
		self.assertEqual(len(matching_intakes), 1)
