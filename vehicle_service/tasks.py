# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	add_to_date,
	cint,
	getdate,
	now_datetime,
	nowdate,
)


def daily():
	"""Daily maintenance scheduler for Vehicle Service module."""
	check_service_reminders()
	check_post_service_followups()


def get_default_advisor():
	"""Finds a Service Advisor User or falls back to Administrator."""
	return (
		frappe.db.get_value("Has Role", {"role": "Service Advisor", "parenttype": "User"}, "parent")
		or "Administrator"
	)


def check_service_reminders():
	"""
	Scans vehicles due for routine periodic maintenance based on:
	1) Service due date (within lead_days, default 7 days)
	2) Odometer mileage (within 500 km of next_service_mileage)
	Dispatches customer notifications and allocates follow-up ToDos.
	"""
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	lead_days = cint(settings.next_service_reminder_days) or 7
	target_date = add_days(nowdate(), lead_days)

	vehicles = frappe.get_all(
		"Service Vehicle",
		filters={"vehicle_status": "Outside Workshop"},
		fields=[
			"name",
			"registration_no",
			"make",
			"model",
			"customer",
			"customer_name",
			"driver_phone",
			"current_mileage",
			"next_service_date",
			"next_service_mileage",
		],
	)

	processed = []
	for v in vehicles:
		due_by_date = False
		due_by_km = False
		reason = ""

		if v.next_service_date and getdate(v.next_service_date) <= getdate(target_date):
			due_by_date = True
			reason = _("Scheduled date approaching ({0})").format(v.next_service_date)

		if (
			v.next_service_mileage
			and v.current_mileage
			and cint(v.next_service_mileage) > 0
			and cint(v.current_mileage) >= (cint(v.next_service_mileage) - 500)
		):
			due_by_km = True
			km_diff = cint(v.next_service_mileage) - cint(v.current_mileage)
			reason = _("Target mileage approaching ({0} km left until {1} km)").format(
				max(0, km_diff), v.next_service_mileage
			)

		if not (due_by_date or due_by_km):
			continue

		# Anti-spam: check if a ToDo already exists for this vehicle created in the last 30 days
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
			advisor = get_default_advisor()
			todo = frappe.new_doc("ToDo")
			todo.allocated_to = advisor
			todo.date = nowdate()
			todo.description = _(
				"Service Due Reminder: Vehicle {0} ({1} {2}) - Customer: {3} (Phone: {4}). Reason: {5}"
			).format(
				v.registration_no,
				v.make or "",
				v.model or "",
				v.customer_name or v.customer,
				v.driver_phone or "N/A",
				reason,
			)
			todo.reference_type = "Service Vehicle"
			todo.reference_name = v.name
			todo.insert(ignore_permissions=True)

			# Also create courtesy communication
			comm = frappe.new_doc("Communication")
			comm.communication_type = "Communication"
			comm.communication_medium = "Email"
			comm.sent_or_received = "Sent"
			comm.subject = f"Upcoming Service Reminder for {v.registration_no}"
			comm.content = f"Dear {v.customer_name or v.customer},\n\nYour vehicle {v.make or ''} {v.model or ''} ({v.registration_no}) is approaching its scheduled service interval ({reason}). Please contact us to schedule your service appointment."
			comm.reference_doctype = "Service Vehicle"
			comm.reference_name = v.name
			comm.sender = advisor
			comm.recipients = frappe.db.get_value("User", advisor, "email") or "service@workshop.com"
			comm.status = "Linked"
			comm.insert(ignore_permissions=True)

			processed.append(v.name)

	return processed


def check_post_service_followups():
	"""
	Scans vehicles delivered 3 days ago and creates a Customer Satisfaction (CSAT)
	follow-up ToDo for the Service Advisor.
	"""
	three_days_ago_start = add_to_date(now_datetime(), days=-4)
	three_days_ago_end = add_to_date(now_datetime(), days=-2)

	delivered_orders = frappe.get_all(
		"Service Order",
		filters={
			"status": "Delivered",
			"delivered_on": ["between", [three_days_ago_start, three_days_ago_end]],
		},
		fields=[
			"name",
			"vehicle",
			"vehicle_description",
			"customer",
			"customer_name",
			"driver_phone",
			"service_advisor",
			"delivered_on",
		],
	)

	processed = []
	for o in delivered_orders:
		# Check if already followed up
		existing = frappe.db.get_value(
			"ToDo",
			{"reference_type": "Service Order", "reference_name": o.name},
			"name",
		)
		if existing:
			continue

		advisor = o.service_advisor or get_default_advisor()
		todo = frappe.new_doc("ToDo")
		todo.allocated_to = advisor
		todo.date = nowdate()
		todo.description = _(
			"3-Day Customer Satisfaction Follow-Up: Call customer {0} ({1}) regarding service on {2} ({3}). Verify vehicle is running smoothly and log feedback."
		).format(
			o.customer_name or o.customer,
			o.driver_phone or "On File",
			o.vehicle,
			o.name,
		)
		todo.reference_type = "Service Order"
		todo.reference_name = o.name
		todo.insert(ignore_permissions=True)

		# Log courtesy post-service communication
		comm = frappe.new_doc("Communication")
		comm.communication_type = "Communication"
		comm.communication_medium = "Email"
		comm.sent_or_received = "Sent"
		comm.subject = f"Post-Service Care Check: {o.vehicle} - Order {o.name}"
		comm.content = f"Dear {o.customer_name or o.customer},\n\nIt has been 3 days since your vehicle {o.vehicle} was serviced with us. We want to ensure everything is performing smoothly and you are fully satisfied with our craftsmanship."
		comm.reference_doctype = "Service Order"
		comm.reference_name = o.name
		comm.sender = advisor
		comm.recipients = frappe.db.get_value("User", advisor, "email") or "service@workshop.com"
		comm.status = "Linked"
		comm.insert(ignore_permissions=True)

		processed.append(o.name)

	return processed
