import frappe
from frappe.tests.utils import FrappeTestCase

class TestInvoiceSchema(FrappeTestCase):
	def test_service_order_has_customer_po_no_field(self):
		meta = frappe.get_meta("Service Order")
		self.assertTrue(meta.has_field("customer_po_no"), "Service Order missing 'customer_po_no' field")
		field = meta.get_field("customer_po_no")
		self.assertEqual(field.fieldtype, "Data")
		self.assertEqual(field.label, "Customer PO No")

	def test_sales_invoice_has_vehicle_and_remarks_custom_fields(self):
		meta = frappe.get_meta("Sales Invoice")
		expected_fields = [
			("vs_license_plate", "Data"),
			("vs_chassis_no", "Data"),
			("vs_vehicle_model", "Data"),
			("vs_mileage_in", "Int"),
			("vs_mileage_out", "Int"),
			("vs_driver_name", "Data"),
			("vs_driver_phone", "Data"),
			("vs_invoice_remarks", "Small Text"),
		]
		for fname, ftype in expected_fields:
			self.assertTrue(meta.has_field(fname), f"Sales Invoice missing custom field '{fname}'")
			self.assertEqual(meta.get_field(fname).fieldtype, ftype, f"Field '{fname}' has unexpected fieldtype")
