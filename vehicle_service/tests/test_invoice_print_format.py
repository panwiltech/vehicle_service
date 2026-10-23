import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.job_control import add_job, complete_service_order
from vehicle_service.vehicle_service.doctype.service_order.service_order import (
	create_sales_invoice_from_order,
)


class TestInvoicePrintFormat(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Customer", "Print Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Print Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Standard Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

	def _order_with_job(self, **kwargs):
		veh = f"TST-P-{frappe.generate_hash(length=6).upper()}"
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = veh
		v.customer = "Print Test Customer"
		v.vin = f"VIN-{veh}"
		v.make = "Isuzu"
		v.model = "D-Max"
		v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh
		so.customer = "Print Test Customer"
		so.customer_po_no = kwargs.get("customer_po_no", "PO-998877")
		so.odometer_in = kwargs.get("odometer_in", 32000)
		so.odometer_out = kwargs.get("odometer_out", 32050)
		so.driver_name = kwargs.get("driver_name", "Jane Smith")
		so.driver_phone = kwargs.get("driver_phone", "+260955998877")
		so.customer_complaint = kwargs.get("customer_complaint", "Scheduled maintenance check")
		so.insert(ignore_permissions=True)
		add_job(so.name, job_title="Engine Tuneup", estimated_hours=2.0)
		return so

	def test_print_format_renders_all_sections_correctly(self):
		so = self._order_with_job()
		complete_service_order(so.name)
		res = create_sales_invoice_from_order(so.name)
		inv = frappe.get_doc("Sales Invoice", res["sales_invoice"])
		inv.vs_invoice_remarks = "All scheduled items replaced. Front pads at 70%."
		inv.save(ignore_permissions=True)

		html = frappe.get_print("Sales Invoice", inv.name, "Vehicle Service Invoice")

		# Section A: Customer & Invoice Info
		self.assertIn("Print Test Customer", html)
		self.assertIn("PO-998877", html)

		# Section B: Vehicle & Driver Info
		self.assertIn(so.vehicle, html)
		self.assertIn(f"VIN-{so.vehicle}", html)
		self.assertIn("Isuzu D-Max", html)
		self.assertIn("32,000", html)
		self.assertIn("32,050", html)
		self.assertIn("Jane Smith", html)
		self.assertIn("+260955998877", html)

		# Section C: Items and Charges
		self.assertIn("Engine Tuneup", html)

		# Section D: Service Advisor Remarks
		self.assertIn("All scheduled items replaced. Front pads at 70%.", html)

	def test_print_format_graceful_handling_of_empty_optional_fields(self):
		so = self._order_with_job(customer_po_no="", odometer_out=0, driver_name="", driver_phone="")
		complete_service_order(so.name)
		res = create_sales_invoice_from_order(so.name)

		# Clear remarks
		inv = frappe.get_doc("Sales Invoice", res["sales_invoice"])
		inv.vs_invoice_remarks = ""
		inv.save(ignore_permissions=True)

		html = frappe.get_print("Sales Invoice", inv.name, "Vehicle Service Invoice")

		# Must render cleanly with "Not recorded" / placeholders
		self.assertIn("Not recorded", html)
		self.assertIn("Not provided", html)
