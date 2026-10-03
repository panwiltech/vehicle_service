# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime
from vehicle_service.vehicle_service.page.my_workshop.my_workshop import (
	get_technician_jobs,
	clock_job_action,
	report_additional_work,
)


class TestTechnicianMyWorkshop(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_test_data()
		# Ensure no leftover in-progress jobs for technician
		for j in frappe.get_all("Service Job", filters={"technician": self.emp.name, "status": "In Progress"}, pluck="name"):
			frappe.db.set_value("Service Job", j, "status", "Completed")

	def setup_test_data(self):
		# Create customer
		if not frappe.db.exists("Customer", "Tech Portal Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Tech Portal Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create technician employee
		company = frappe.get_all("Company")[0].name
		emp_name = frappe.db.get_value("Employee", {"first_name": "Marcus", "last_name": "Wrench"})
		if not emp_name:
			e = frappe.new_doc("Employee")
			e.first_name = "Marcus"
			e.last_name = "Wrench"
			e.company = company
			e.gender = "Male"
			e.date_of_birth = "1992-05-15"
			e.date_of_joining = "2022-01-01"
			e.status = "Active"
			e.insert(ignore_permissions=True)
			emp_name = e.name
		self.emp = frappe.get_doc("Employee", emp_name)

		# Create vehicle
		reg_no = "MW-TECH-01"
		if not frappe.db.exists("Service Vehicle", reg_no):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = reg_no
			v.vin = "VIN-MW-0001"
			v.make = "Ford"
			v.model = "Ranger Wildtrak"
			v.year = 2023
			v.customer = "Tech Portal Customer"
			v.current_mileage = 62000
			v.insert(ignore_permissions=True)

		# Create workshop location
		if not frappe.db.exists("Workshop Location", "Bay 1 - Lift"):
			loc = frappe.new_doc("Workshop Location")
			loc.location_name = "Bay 1 - Lift"
			loc.location_type = "Bay"
			loc.is_active = 1
			loc.insert(ignore_permissions=True)

		# Create order
		open_orders = frappe.get_all(
			"Service Order",
			filters={"vehicle": reg_no, "status": ["not in", ["Delivered", "Cancelled"]]},
			pluck="name",
		)
		for o in open_orders:
			frappe.db.set_value("Service Order", o, "status", "Delivered")

		order = frappe.new_doc("Service Order")
		order.vehicle = reg_no
		order.customer = "Tech Portal Customer"
		order.priority = "Urgent"
		order.current_location = "Bay 1 - Lift"
		order.customer_complaint = "Vibration under heavy braking"
		order.insert(ignore_permissions=True)
		self.order = order

	def test_get_technician_jobs(self):
		job = frappe.new_doc("Service Job")
		job.service_order = self.order.name
		job.job_title = "Front Disc Machining"
		job.technician = self.emp.name
		job.status = "Assigned"
		job.estimated_hours = 2.0
		job.category = "Essential"
		job.insert(ignore_permissions=True)

		data = get_technician_jobs(employee=self.emp.name)
		self.assertIn("assigned_jobs", data)
		self.assertIn("active_clock", data)
		self.assertIsNone(data["active_clock"])

		job_ids = [j["name"] for j in data["assigned_jobs"]]
		self.assertIn(job.name, job_ids)

	def test_single_active_clock_enforcement(self):
		# Create Job A
		job_a = frappe.new_doc("Service Job")
		job_a.service_order = self.order.name
		job_a.job_title = "Job A - Front Suspension"
		job_a.technician = self.emp.name
		job_a.status = "Assigned"
		job_a.estimated_hours = 1.5
		job_a.insert(ignore_permissions=True)

		# Create Job B
		job_b = frappe.new_doc("Service Job")
		job_b.service_order = self.order.name
		job_b.job_title = "Job B - Rear Suspension"
		job_b.technician = self.emp.name
		job_b.status = "Assigned"
		job_b.estimated_hours = 1.5
		job_b.insert(ignore_permissions=True)

		# Start Job A
		clock_job_action(job_a.name, "start", employee=self.emp.name)
		job_a.reload()
		self.assertEqual(job_a.status, "In Progress")

		data = get_technician_jobs(employee=self.emp.name)
		self.assertIsNotNone(data["active_clock"])
		self.assertEqual(data["active_clock"]["name"], job_a.name)

		# Attempting to start Job B must raise error due to single-clock rule
		with self.assertRaises(frappe.ValidationError):
			clock_job_action(job_b.name, "start", employee=self.emp.name)

		# Pause Job A
		clock_job_action(job_a.name, "pause", pause_reason="Waiting for special tool", employee=self.emp.name)
		job_a.reload()
		self.assertEqual(job_a.status, "Paused")

		# Now starting Job B must succeed
		clock_job_action(job_b.name, "start", employee=self.emp.name)
		job_b.reload()
		self.assertEqual(job_b.status, "In Progress")

		# Complete Job B
		clock_job_action(job_b.name, "complete", employee=self.emp.name)
		job_b.reload()
		self.assertEqual(job_b.status, "Completed")

	def test_report_additional_work(self):
		job = frappe.new_doc("Service Job")
		job.service_order = self.order.name
		job.job_title = "Brake Check"
		job.technician = self.emp.name
		job.status = "In Progress"
		job.insert(ignore_permissions=True)

		extra_job_name = report_additional_work(
			service_order=self.order.name,
			parent_job=job.name,
			job_title="Replace Torn Steering Rack Boot",
			category="Recommended",
			estimated_hours=1.2,
			description="Steering rack boot torn on left side, grit entering joint",
		)

		self.assertTrue(frappe.db.exists("Service Job", extra_job_name))
		extra_job = frappe.get_doc("Service Job", extra_job_name)
		self.assertEqual(extra_job.service_order, self.order.name)
		self.assertEqual(extra_job.source, "Additional")
		self.assertEqual(extra_job.status, "Pending Approval")
		self.assertEqual(extra_job.category, "Recommended")
		self.assertEqual(extra_job.estimated_hours, 1.2)
