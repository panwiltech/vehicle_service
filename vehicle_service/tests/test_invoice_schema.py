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

	def test_sales_invoice_form_section_placement(self):
		cf_vehicle = frappe.db.get_value("Custom Field", "Sales Invoice-vs_section_vehicle", "insert_after")
		cf_remarks = frappe.db.get_value("Custom Field", "Sales Invoice-vs_section_remarks", "insert_after")

		self.assertEqual(
			cf_vehicle,
			"has_subcontracted",
			"Vehicle section must be inserted after customer_section to keep company, posting date/time, POS, return, and debit note intact in the header section",
		)
		self.assertEqual(
			cf_remarks,
			"net_total",
			"Remarks section must be inserted after net_total to be located directly between the Items and Taxes sections",
		)
