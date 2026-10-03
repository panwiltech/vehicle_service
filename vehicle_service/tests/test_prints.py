# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestWorkshopPrintFormats(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_test_data()

	def setup_test_data(self):
		# Create customer
		if not frappe.db.exists("Customer", "Print Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Print Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create vehicle
		reg_no = "PRINT-TEST-01"
		if not frappe.db.exists("Service Vehicle", reg_no):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = reg_no
			v.vin = "VIN-PRINT-TEST-0001"
			v.make = "Toyota"
			v.model = "Land Cruiser 300"
			v.year = 2024
			v.customer = "Print Test Customer"
			v.current_mileage = 45000
			v.fuel_type = "Diesel"
			v.transmission = "Automatic"
			v.colour = "Pearl White"
			v.engine_no = "ENG-V6-998822"
			v.insert(ignore_permissions=True)

		# Create item
		if not frappe.db.exists("Item", "PRINT-OIL-FILTER"):
			it = frappe.new_doc("Item")
			it.item_code = "PRINT-OIL-FILTER"
			it.item_name = "Engine Oil Filter"
			it.item_group = "Products"
			it.stock_uom = "Nos"
			it.insert(ignore_permissions=True)

	def create_test_order(self, reg_no="PRINT-TEST-01"):
		# Ensure no open order for this vehicle
		open_orders = frappe.get_all(
			"Service Order",
			filters={"vehicle": reg_no, "status": ["not in", ["Delivered", "Cancelled"]]},
			pluck="name",
		)
		for o in open_orders:
			frappe.db.set_value("Service Order", o, "status", "Delivered")

		order = frappe.new_doc("Service Order")
		order.vehicle = reg_no
		order.customer = "Print Test Customer"
		order.driver_name = "Alex Driver"
		order.driver_phone = "+1-555-0199"
		order.order_type = "Customer"
		order.priority = "Normal"
		order.odometer_in = 45200
		order.fuel_level = "1/2"
		order.customer_complaint = "Squeaking noise from brakes on deceleration"
		order.existing_damage = "Minor scratch on rear bumper"
		order.vehicle_contents = "Spare wheel, tool kit, warning triangle"
		order.intake_confirmed = 1
		order.insert(ignore_permissions=True)
		return order

	def test_vehicle_intake_sheet_print(self):
		order = self.create_test_order()

		# Render Vehicle Intake Sheet
		html = frappe.get_print("Service Order", order.name, "Vehicle Intake Sheet")

		self.assertIn("Vehicle Intake Sheet", html)
		self.assertIn("PRINT-TEST-01", html)
		self.assertIn("Toyota", html)
		self.assertIn("Land Cruiser 300", html)
		self.assertIn("45,200", html.replace(" ", "") if "45,200" in html else html)
		self.assertIn("Squeaking noise from brakes", html)
		self.assertIn("Minor scratch on rear bumper", html)
		self.assertIn("Customer Signature", html)

	def test_workshop_job_card_print(self):
		order = self.create_test_order()

		# Add job
		job = frappe.new_doc("Service Job")
		job.service_order = order.name
		job.job_title = "Replace Front Brake Pads and Rotors"
		job.category = "Essential"
		job.estimated_hours = 2.5
		job.status = "Assigned"
		job.insert(ignore_permissions=True)

		# Add part
		order.append(
			"parts",
			{
				"item_code": "PRINT-OIL-FILTER",
				"item_name": "Engine Oil Filter",
				"job": job.name,
				"qty_required": 2,
				"qty_issued": 1,
				"part_status": "Partially Issued",
			},
		)
		order.save(ignore_permissions=True)

		# Render Workshop Job Card
		html = frappe.get_print("Service Order", order.name, "Workshop Job Card")

		self.assertIn("Workshop Job Card", html)
		self.assertIn(order.name, html)
		self.assertIn("Replace Front Brake Pads and Rotors", html)
		self.assertIn("PRINT-OIL-FILTER", html)
		self.assertIn("Technician Signature", html)
		self.assertIn("Supervisor Signature", html)

	def test_qc_inspection_report_print(self):
		order = self.create_test_order()

		qc = frappe.new_doc("Service QC")
		qc.service_order = order.name
		qc.vehicle = order.vehicle
		qc.inspector = "Administrator"
		qc.inspected_on = now_datetime()
		qc.result = "Pass"
		qc.road_test_done = 1
		qc.road_test_km = 8.5
		qc.findings = "Vehicle drives smooth, brake pedal firm and linear."
		qc.append(
			"checklist",
			{
				"check_item": "Brake pad thickness & rotor surface",
				"passed": 1,
				"remarks": "New pads installed, discs resurfaced",
			},
		)
		qc.append(
			"checklist",
			{
				"check_item": "Wheel lug nuts torqued to spec",
				"passed": 1,
				"remarks": "Torqued to 130 Nm",
			},
		)
		qc.insert(ignore_permissions=True)

		# Render QC Inspection Report
		html = frappe.get_print("Service QC", qc.name, "QC Inspection Report")

		self.assertIn("QC Inspection Report", html)
		self.assertIn(qc.name, html)
		self.assertIn("PRINT-TEST-01", html)
		self.assertIn("Brake pad thickness", html)
		self.assertIn("Torqued to 130 Nm", html)
		self.assertIn("Road Test", html)
		self.assertIn("Inspector Signature", html)

	def test_vehicle_gate_pass_print(self):
		order = self.create_test_order()
		order.status = "Ready for Collection"
		order.odometer_out = 45220
		order.collected_by = "Alex Driver"
		order.delivery_notes = "Customer paid by card. Handed over key fob and receipt."
		order.save(ignore_permissions=True)

		# Render Vehicle Gate Pass
		html = frappe.get_print("Service Order", order.name, "Vehicle Gate Pass")

		self.assertIn("Vehicle Gate Pass", html)
		self.assertIn(order.name, html)
		self.assertIn("PRINT-TEST-01", html)
		self.assertIn("Alex Driver", html)
		self.assertIn("Gate Security", html)
		self.assertIn("Customer Signature", html)
