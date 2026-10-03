# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.vehicle_service.doctype.service_order.service_order import (
	check_in_vehicle,
	create_estimate,
)
from vehicle_service.vehicle_service.notifications import (
	send_intake_confirmation,
	send_estimate_approval_request,
	send_ready_for_collection,
)


class TestCustomerNotifications(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_test_data()

	def setup_test_data(self):
		# Create customer with contact details
		if not frappe.db.exists("UOM", "Hour"):
			uom = frappe.new_doc("UOM")
			uom.uom_name = "Hour"
			uom.must_be_whole_number = 0
			uom.insert(ignore_permissions=True)
		else:
			frappe.db.set_value("UOM", "Hour", "must_be_whole_number", 0)

		if not frappe.db.exists("Item", "Labour"):
			it = frappe.new_doc("Item")
			it.item_code = "Labour"
			it.item_name = "Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.stock_uom = "Hour"
			it.insert(ignore_permissions=True)
		else:
			frappe.db.set_value("Item", "Labour", "stock_uom", "Hour")

		cust_name = "Notification Test Customer"
		if not frappe.db.exists("Customer", cust_name):
			c = frappe.new_doc("Customer")
			c.customer_name = cust_name
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create vehicle
		reg_no = "NOTIF-001"
		if not frappe.db.exists("Service Vehicle", reg_no):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = reg_no
			v.vin = "VIN-NOTIF-0001"
			v.make = "Toyota"
			v.model = "Prado TX"
			v.year = 2022
			v.customer = cust_name
			v.current_mileage = 75000
			v.insert(ignore_permissions=True)

		# Ensure Workshop Location exists
		if not frappe.db.exists("Workshop Location", "Bay 1 - Lift"):
			loc = frappe.new_doc("Workshop Location")
			loc.location_name = "Bay 1 - Lift"
			loc.location_type = "Bay"
			loc.is_active = 1
			loc.insert(ignore_permissions=True)

		# Ensure no open orders
		for o in frappe.get_all("Service Order", filters={"vehicle": reg_no, "status": ["not in", ["Delivered", "Cancelled"]]}, pluck="name"):
			frappe.db.set_value("Service Order", o, "status", "Delivered")

		order = frappe.new_doc("Service Order")
		order.vehicle = reg_no
		order.customer = cust_name
		order.driver_name = "Sam Driver"
		order.driver_phone = "+260977112233"
		order.priority = "Normal"
		order.odometer_in = 75400
		order.fuel_level = "3/4"
		order.customer_complaint = "Air conditioning not blowing cold air"
		order.insert(ignore_permissions=True)
		self.order = order

	def test_send_intake_confirmation(self):
		comm_name = send_intake_confirmation(self.order.name, channel="Email")
		self.assertTrue(frappe.db.exists("Communication", comm_name))

		comm = frappe.get_doc("Communication", comm_name)
		self.assertEqual(comm.reference_doctype, "Service Order")
		self.assertEqual(comm.reference_name, self.order.name)
		self.assertIn("NOTIF-001", comm.content)
		self.assertIn("Toyota", comm.content)
		self.assertIn("75,400", comm.content)
		self.assertIn("Air conditioning not blowing cold", comm.content)

	def test_send_estimate_approval_request(self):
		# Create a job on order
		job = frappe.new_doc("Service Job")
		job.service_order = self.order.name
		job.job_title = "AC Compressor Regas & Leak Test"
		job.estimated_hours = 1.5
		job.category = "Essential"
		job.status = "Pending Approval"
		job.insert(ignore_permissions=True)

		# Create estimate
		res = create_estimate(self.order.name)
		quotation_name = res.get("quotation") if isinstance(res, dict) else res

		comm_name = send_estimate_approval_request(self.order.name, quotation_name=quotation_name, channel="Email")
		self.assertTrue(frappe.db.exists("Communication", comm_name))

		comm = frappe.get_doc("Communication", comm_name)
		self.assertEqual(comm.reference_doctype, "Service Order")
		self.assertEqual(comm.reference_name, self.order.name)
		self.assertIn("Estimate", comm.subject)
		self.assertIn("AC Compressor Regas", comm.content)
		self.assertIn(quotation_name, comm.content)

	def test_send_ready_for_collection(self):
		self.order.status = "Ready for Collection"
		self.order.current_location = "Bay 1 - Lift"
		self.order.save(ignore_permissions=True)

		comm_name = send_ready_for_collection(self.order.name, channel="Email")
		self.assertTrue(frappe.db.exists("Communication", comm_name))

		comm = frappe.get_doc("Communication", comm_name)
		self.assertEqual(comm.reference_doctype, "Service Order")
		self.assertEqual(comm.reference_name, self.order.name)
		self.assertIn("Ready for Collection", comm.subject)
		self.assertIn("NOTIF-001", comm.content)
