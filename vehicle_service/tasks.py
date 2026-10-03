# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate


def daily():
	check_service_reminders()


def check_service_reminders():
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	lead_days = settings.next_service_reminder_days or 7
	target_date = add_days(nowdate(), lead_days)

	due_vehicles = frappe.get_all(
		"Service Vehicle",
		filters={"next_service_date": ["<=", target_date], "vehicle_status": "Outside Workshop"},
		fields=["name", "registration_no", "make", "model", "customer", "customer_name", "driver_phone", "next_service_date"],
	)

	for v in due_vehicles:
		# Prevent spamming: check if a ToDo already exists for this vehicle created in the last 30 days
		cutoff = add_days(nowdate(), -30)
		existing_todo = frappe.db.sql(
			"""
			SELECT name FROM `tabToDo`
			WHERE reference_type = 'Service Vehicle' AND reference_name = %s AND creation >= %s
			LIMIT 1
		""",
			(v.name, cutoff),
		)

		if not existing_todo:
			# Assign to system manager or first Service Advisor found
			advisor = frappe.db.get_value("Has Role", {"role": "Service Advisor"}, "parent") or "Administrator"
			todo = frappe.new_doc("ToDo")
			todo.allocated_to = advisor
			todo.date = nowdate()
			todo.description = _("Next Service Due Reminder: Vehicle {0} ({1} {2}) - Customer: {3} (Tel: {4}) due by {5}").format(
				v.registration_no, v.make or "", v.model or "", v.customer_name or "", v.driver_phone or "", v.next_service_date
			)
			todo.reference_type = "Service Vehicle"
			todo.reference_name = v.name
			todo.insert(ignore_permissions=True)
