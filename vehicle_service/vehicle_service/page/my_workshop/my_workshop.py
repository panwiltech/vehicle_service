# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import (
	cint,
	flt,
	get_datetime,
	now_datetime,
	nowdate,
	time_diff_in_seconds,
)
from vehicle_service.vehicle_service.doctype.service_job.service_job import (
	start_job,
	pause_job,
	complete_job,
)


def get_current_employee(employee=None):
	"""Resolves the active technician Employee record."""
	if employee:
		return employee

	user = frappe.session.user
	emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if not emp and user == "Administrator":
		# Fallback to any active employee if available for testing/admin preview
		emp = frappe.db.get_value("Employee", {"status": "Active"}, "name")
	return emp


@frappe.whitelist()
def get_technician_jobs(employee=None):
	"""Returns the list of assigned, active, and completed jobs for the technician."""
	emp_name = get_current_employee(employee)
	if not emp_name:
		return {
			"technician": None,
			"active_clock": None,
			"assigned_jobs": [],
			"completed_today": [],
		}

	emp_doc = frappe.db.get_value("Employee", emp_name, ["name", "employee_name"], as_dict=True)

	# Fetch assigned / active / paused jobs
	jobs = frappe.get_all(
		"Service Job",
		filters={"technician": emp_name, "status": ["in", ["Assigned", "In Progress", "Paused"]]},
		fields=[
			"name",
			"service_order",
			"job_title",
			"category",
			"status",
			"bay",
			"estimated_hours",
			"actual_hours",
			"started_on",
			"pause_reason",
			"creation",
		],
		order_by="idx asc, creation asc",
	)

	active_clock = None
	assigned_jobs = []

	for j in jobs:
		# Fetch vehicle and order info
		so_info = frappe.db.get_value(
			"Service Order",
			j["service_order"],
			["vehicle", "vehicle_description", "priority", "customer_name", "customer_complaint"],
			as_dict=True,
		) or {}

		j["vehicle_reg"] = so_info.get("vehicle")
		j["vehicle_desc"] = so_info.get("vehicle_description")
		j["priority"] = so_info.get("priority", "Normal")
		j["customer_name"] = so_info.get("customer_name")
		j["customer_complaint"] = so_info.get("customer_complaint")

		if j["status"] == "In Progress":
			# Calculate running elapsed seconds
			elapsed = 0
			if j["started_on"]:
				elapsed = time_diff_in_seconds(now_datetime(), get_datetime(j["started_on"]))
			j["elapsed_seconds"] = max(0, int(elapsed))
			active_clock = j
		else:
			assigned_jobs.append(j)

	# Completed today
	today_start = f"{nowdate()} 00:00:00"
	completed = frappe.get_all(
		"Service Job",
		filters={
			"technician": emp_name,
			"status": "Completed",
			"completed_on": [">=", today_start],
		},
		fields=[
			"name",
			"service_order",
			"job_title",
			"category",
			"status",
			"bay",
			"estimated_hours",
			"actual_hours",
			"completed_on",
		],
		order_by="completed_on desc",
	)

	for c in completed:
		v_reg = frappe.db.get_value("Service Order", c["service_order"], "vehicle")
		c["vehicle_reg"] = v_reg

	return {
		"technician": emp_doc,
		"active_clock": active_clock,
		"assigned_jobs": assigned_jobs,
		"completed_today": completed,
	}


@frappe.whitelist()
def clock_job_action(job_name, action, pause_reason=None, employee=None):
	"""
	Enforces single-clock rule and transitions job clock state.
	action: 'start' | 'pause' | 'complete'
	"""
	job = frappe.get_doc("Service Job", job_name)
	emp_name = employee or job.technician or get_current_employee()

	if action == "start":
		# SINGLE ACTIVE CLOCK RULE:
		# Check if this technician has ANY job currently In Progress
		active_jobs = frappe.get_all(
			"Service Job",
			filters={
				"technician": emp_name,
				"status": "In Progress",
				"name": ["!=", job.name],
			},
			fields=["name", "job_title"],
		)
		if active_jobs:
			running = active_jobs[0]
			frappe.throw(
				_(
					"You already have job {0} ('{1}') currently running. "
					"Single-clock policy requires you to pause or complete it before clocking into another job."
				).format(frappe.bold(running.name), running.job_title),
				frappe.ValidationError,
			)

		# Ensure technician is assigned
		if not job.technician:
			job.technician = emp_name
			job.save(ignore_permissions=True)

		start_job(job.name)

	elif action == "pause":
		pause_job(job.name, reason=pause_reason or _("Paused by technician"))

	elif action == "complete":
		complete_job(job.name)

	else:
		frappe.throw(_("Invalid clock action: {0}").format(action))

	return get_technician_jobs(employee=emp_name)


@frappe.whitelist()
def report_additional_work(
	service_order,
	parent_job=None,
	job_title=None,
	category="Recommended",
	estimated_hours=1.0,
	description=None,
	photo=None,
):
	"""Creates a new Service Job with source='Additional' for advisor approval."""
	if not service_order:
		frappe.throw(_("Service Order is mandatory"), frappe.MandatoryError)
	if not job_title:
		frappe.throw(_("Job Title is mandatory"), frappe.MandatoryError)

	new_job = frappe.new_doc("Service Job")
	new_job.service_order = service_order
	new_job.job_title = job_title
	new_job.category = category or "Recommended"
	new_job.estimated_hours = flt(estimated_hours) if estimated_hours else 1.0
	new_job.description = description
	new_job.source = "Additional"
	new_job.status = "Pending Approval"
	new_job.raised_by = frappe.session.user

	# Link technician from parent job or current user if available
	if parent_job and frappe.db.exists("Service Job", parent_job):
		p = frappe.get_doc("Service Job", parent_job)
		new_job.technician = p.technician
		new_job.bay = p.bay

	new_job.insert(ignore_permissions=True)

	if photo:
		# Attach photo to job
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_url": photo,
				"attached_to_doctype": "Service Job",
				"attached_to_name": new_job.name,
				"is_private": 0,
			}
		)
		file_doc.insert(ignore_permissions=True)

	return new_job.name
