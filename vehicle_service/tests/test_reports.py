# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.vehicle_service.report.estimate_vs_actual.estimate_vs_actual import (
	execute as execute_estimate_vs_actual,
)
from vehicle_service.vehicle_service.report.technician_performance.technician_performance import (
	execute as execute_technician_performance,
)
from vehicle_service.vehicle_service.report.workshop_performance.workshop_performance import (
	execute as execute_workshop_performance,
)
from vehicle_service.vehicle_service.report.parts_consumption.parts_consumption import (
	execute as execute_parts_consumption,
)


class TestWorkshopReports(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_test_data()

	def setup_test_data(self):
		company = frappe.get_all("Company")[0].name

		# Create customer
		if not frappe.db.exists("Customer", "Report Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Report Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create employee
		if not frappe.db.exists("Employee", {"first_name": "Report", "last_name": "Tech"}):
			emp = frappe.new_doc("Employee")
			emp.first_name = "Report"
			emp.last_name = "Tech"
			emp.company = company
			emp.gender = "Male"
			emp.date_of_birth = "1992-05-15"
			emp.date_of_joining = "2021-01-01"
			emp.insert(ignore_permissions=True)
			self.emp = emp
		else:
			self.emp = frappe.get_doc("Employee", {"first_name": "Report", "last_name": "Tech"})

		# Create vehicle
		reg_no = "RPT 999"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Nissan"
			veh.model = "Navara"
			veh.customer = "Report Customer"
			veh.insert(ignore_permissions=True)

		# Check if active order already exists for vehicle
		existing_order = frappe.db.get_value(
			"Service Order",
			{"vehicle": reg_no, "status": ["not in", ["Delivered", "Cancelled"]]},
			"name",
		)
		if existing_order:
			order = frappe.get_doc("Service Order", existing_order)
		else:
			order = frappe.new_doc("Service Order")
			order.vehicle = reg_no
			order.customer = "Report Customer"
			order.priority = "Normal"
			order.status = "In Progress"
			order.insert(ignore_permissions=True)

		job_name = frappe.db.get_value("Service Job", {"service_order": order.name, "job_title": "Clutch Overhaul"}, "name")
		if not job_name:
			job = frappe.new_doc("Service Job")
			job.service_order = order.name
			job.job_title = "Clutch Overhaul"
			job.technician = self.emp.name
			job.status = "Completed"
			job.estimated_hours = 4.0
			job.append("time_logs", {
				"technician": self.emp.name,
				"from_time": "2026-10-03 08:00:00",
				"to_time": "2026-10-03 11:30:00",
				"hours": 3.5,
			})
			job.insert(ignore_permissions=True)
		else:
			job = frappe.get_doc("Service Job", job_name)

		if not frappe.db.exists("Item", "CLUTCH-KIT-TEST"):
			it = frappe.new_doc("Item")
			it.item_code = "CLUTCH-KIT-TEST"
			it.item_name = "Clutch Kit Heavy Duty"
			it.item_group = "Products"
			it.is_stock_item = 1
			it.stock_uom = "Nos"
			it.insert(ignore_permissions=True)

		if not order.parts:
			order.append("parts", {
				"item_code": "CLUTCH-KIT-TEST",
				"item_name": "Clutch Kit Heavy Duty",
				"job": job.name,
				"qty_required": 1.0,
				"qty_issued": 1.0,
				"qty_returned": 0.0,
				"qty_used": 1.0,
				"rate": 150.0,
				"part_status": "Issued",
				"approval_status": "Approved",
			})
			order.save(ignore_permissions=True)
		self.order = order

	def test_estimate_vs_actual_report(self):
		columns, data, message, chart, summary = execute_estimate_vs_actual(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)
		row = next((r for r in data if r.get("service_order") == self.order.name), None)
		self.assertIsNotNone(row)
		self.assertEqual(row.get("estimated_hours"), 4.0)
		self.assertEqual(row.get("actual_hours"), 3.5)
		self.assertEqual(row.get("variance_hours"), -0.5)

	def test_technician_performance_report(self):
		columns, data, message, chart, summary = execute_technician_performance(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)
		row = next((r for r in data if r.get("technician") == self.emp.name), None)
		self.assertIsNotNone(row)
		self.assertEqual(row.get("jobs_completed"), 1)
		self.assertEqual(row.get("total_actual_hours"), 3.5)

	def test_workshop_performance_report(self):
		columns, data, message, chart, summary = execute_workshop_performance(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)

	def test_parts_consumption_report(self):
		columns, data, message, chart, summary = execute_parts_consumption(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)
		row = next((r for r in data if r.get("item_code") == "CLUTCH-KIT-TEST"), None)
		self.assertIsNotNone(row)
		self.assertEqual(row.get("qty_used"), 1.0)
		self.assertEqual(row.get("net_consumed_amount"), 150.0)
