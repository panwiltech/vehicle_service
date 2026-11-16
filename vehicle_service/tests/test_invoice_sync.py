import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.job_control import add_job, complete_service_order
from vehicle_service.vehicle_service.doctype.service_order.service_order import (
	create_sales_invoice_from_order,
	sync_draft_invoice_from_order,
	deliver_vehicle,
)


class TestInvoiceSync(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Customer", "Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Customer"
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
		veh = f"TST-V-{frappe.generate_hash(length=6).upper()}"
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = veh
		v.customer = "Test Customer"
		v.vin = f"VIN-{veh}"
		v.make = "Toyota"
		v.model = "Hilux"
		v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh
		so.customer = "Test Customer"
		so.customer_po_no = kwargs.get("customer_po_no", "PO-12345")
		so.odometer_in = kwargs.get("odometer_in", 45000)
		so.driver_name = kwargs.get("driver_name", "John Doe")
		so.driver_phone = kwargs.get("driver_phone", "+260971234567")
		so.customer_complaint = kwargs.get("customer_complaint", "Engine oil service and brake check")
		so.insert(ignore_permissions=True)
		add_job(so.name, job_title="Action Test Job", estimated_hours=1.0)
		return so

	def test_invoice_creation_snapshots_vehicle_driver_po_and_remarks(self):
		so = self._order_with_job()
		complete_service_order(so.name)

		res = create_sales_invoice_from_order(so.name)
		inv = frappe.get_doc("Sales Invoice", res["sales_invoice"])

		self.assertEqual(inv.po_no, "PO-12345")
		self.assertEqual(inv.vs_license_plate, so.vehicle)
		self.assertEqual(inv.vs_chassis_no, f"VIN-{so.vehicle}")
		self.assertIn("Toyota Hilux", inv.vs_vehicle_model)
		self.assertEqual(inv.vs_mileage_in, 45000)
		self.assertEqual(inv.vs_driver_name, "John Doe")
		self.assertEqual(inv.vs_driver_phone, "+260971234567")
		self.assertEqual(inv.vs_invoice_remarks, "Engine oil service and brake check")

	def test_sync_draft_invoice_preserves_customized_advisor_remarks(self):
		so = self._order_with_job()
		complete_service_order(so.name)

		res = create_sales_invoice_from_order(so.name)
		inv = frappe.get_doc("Sales Invoice", res["sales_invoice"])

		# Advisor modifies remarks on draft invoice
		inv.vs_invoice_remarks = "Special discount applied per Manager approval. Client requested extra filter check."
		inv.save(ignore_permissions=True)

		# Subsequent sync from order must NOT overwrite the advisor's remarks
		so_doc = frappe.get_doc("Service Order", so.name)
		sync_draft_invoice_from_order(so_doc)

		inv.reload()
		self.assertEqual(
			inv.vs_invoice_remarks,
			"Special discount applied per Manager approval. Client requested extra filter check.",
		)

	def test_deliver_vehicle_syncs_mileage_out_to_draft_invoice(self):
		so = self._order_with_job()
		complete_service_order(so.name)
		res = create_sales_invoice_from_order(so.name)

		so_doc = frappe.get_doc("Service Order", so.name)
		so_doc.status = "Ready for Collection"
		so_doc.flags.ignore_invoice_lock = True
		so_doc.save(ignore_permissions=True)

		deliver_vehicle(so.name, odometer_out=45120, collected_by="John Doe")

		inv = frappe.get_doc("Sales Invoice", res["sales_invoice"])
		self.assertEqual(inv.vs_mileage_out, 45120)

	def test_historical_snapshot_preservation_on_vehicle_update(self):
		so = self._order_with_job()
		complete_service_order(so.name)
		res = create_sales_invoice_from_order(so.name)

		# Modify vehicle vin/model and order odometer_in after invoice creation
		v = frappe.get_doc("Service Vehicle", so.vehicle)
		v.vin = "ALTERED-VIN-999"
		v.save(ignore_permissions=True)

		inv = frappe.get_doc("Sales Invoice", res["sales_invoice"])
		self.assertEqual(inv.vs_chassis_no, f"VIN-{so.vehicle}")
		self.assertNotEqual(inv.vs_chassis_no, "ALTERED-VIN-999")
