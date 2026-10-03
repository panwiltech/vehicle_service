# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, nowdate
from vehicle_service.tasks import (
	check_service_reminders,
	check_post_service_followups,
)


class TestServiceReminders(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_test_data()

	def setup_test_data(self):
		cust_name = "Reminder Customer"
		if not frappe.db.exists("Customer", cust_name):
			c = frappe.new_doc("Customer")
			c.customer_name = cust_name
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create vehicles
		# Vehicle A: Due soon by date (5 days)
		reg_a = "REMIND-01"
		if not frappe.db.exists("Service Vehicle", reg_a):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = reg_a
			v.vin = "VIN-REMIND-0001"
			v.make = "Toyota"
			v.model = "Camry"
			v.year = 2021
			v.customer = cust_name
			v.current_mileage = 50000
			v.vehicle_status = "Outside Workshop"
			v.next_service_date = add_days(nowdate(), 5)
			v.next_service_mileage = 60000
			v.insert(ignore_permissions=True)
		else:
			frappe.db.set_value(
				"Service Vehicle",
				reg_a,
				{
					"next_service_date": add_days(nowdate(), 5),
					"vehicle_status": "Outside Workshop",
				},
			)

		# Vehicle B: Due soon by mileage (within 400 km)
		reg_b = "REMIND-02"
		if not frappe.db.exists("Service Vehicle", reg_b):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = reg_b
			v.vin = "VIN-REMIND-0002"
			v.make = "Honda"
			v.model = "CR-V"
			v.year = 2022
			v.customer = cust_name
			v.current_mileage = 99650
			v.vehicle_status = "Outside Workshop"
			v.next_service_date = add_days(nowdate(), 45)
			v.next_service_mileage = 100000
			v.insert(ignore_permissions=True)
		else:
			frappe.db.set_value(
				"Service Vehicle",
				reg_b,
				{
					"current_mileage": 99650,
					"next_service_mileage": 100000,
					"next_service_date": add_days(nowdate(), 45),
					"vehicle_status": "Outside Workshop",
				},
			)

		# Vehicle C: Not due
		reg_c = "REMIND-03"
		if not frappe.db.exists("Service Vehicle", reg_c):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = reg_c
			v.vin = "VIN-REMIND-0003"
			v.make = "Mazda"
			v.model = "CX-5"
			v.year = 2023
			v.customer = cust_name
			v.current_mileage = 30000
			v.vehicle_status = "Outside Workshop"
			v.next_service_date = add_days(nowdate(), 120)
			v.next_service_mileage = 40000
			v.insert(ignore_permissions=True)

	def test_service_due_date_and_mileage_reminders(self):
		# Clear existing todos for test vehicles
		frappe.db.delete("ToDo", {"reference_name": ["in", ["REMIND-01", "REMIND-02", "REMIND-03"]]})

		reminders = check_service_reminders()

		todos_a = frappe.get_all("ToDo", filters={"reference_name": "REMIND-01"})
		todos_b = frappe.get_all("ToDo", filters={"reference_name": "REMIND-02"})
		todos_c = frappe.get_all("ToDo", filters={"reference_name": "REMIND-03"})

		# Vehicle A and B must receive reminders
		self.assertTrue(len(todos_a) > 0, "Vehicle A due by date should have a reminder ToDo")
		self.assertTrue(len(todos_b) > 0, "Vehicle B due by mileage should have a reminder ToDo")
		# Vehicle C must not
		self.assertEqual(len(todos_c), 0, "Vehicle C not due should not have a reminder ToDo")

	def test_post_service_three_day_followup(self):
		# Create an order delivered exactly 3 days ago
		reg_no = "REMIND-01"
		# Ensure no open orders
		for o in frappe.get_all("Service Order", filters={"vehicle": reg_no, "status": ["not in", ["Delivered", "Cancelled"]]}, pluck="name"):
			frappe.db.set_value("Service Order", o, "status", "Delivered")

		order = frappe.new_doc("Service Order")
		order.vehicle = reg_no
		order.customer = "Reminder Customer"
		order.status = "Delivered"
		order.delivered_on = add_to_date(now_datetime(), days=-3)
		order.insert(ignore_permissions=True)

		followups = check_post_service_followups()

		# Must find follow-up ToDo for this order
		todos = frappe.get_all(
			"ToDo",
			filters={"reference_type": "Service Order", "reference_name": order.name},
		)
		self.assertTrue(len(todos) > 0, "Delivered order after 3 days should have a CSAT follow-up ToDo")
		todo = frappe.get_doc("ToDo", todos[0].name)
		self.assertIn("Customer Satisfaction", todo.description)
