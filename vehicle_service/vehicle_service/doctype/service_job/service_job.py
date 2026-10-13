# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, time_diff_in_hours
from vehicle_service.state import (
	COMPLETED_STATES,
	JOB_ASSIGNED,
	JOB_COMPLETED,
	JOB_IN_PROGRESS,
	JOB_PAUSED,
	JOB_QC_FAILED,
	compute_operational_status,
)


class ServiceJob(Document):
	def validate(self):
		self.validate_order_lock()
		self.calculate_actual_hours()

	def validate_order_lock(self):
		if self.is_new() or getattr(self.flags, "ignore_job_lock", False) or getattr(self.flags, "ignore_invoice_lock", False):
			return
		if not self.service_order:
			return
		order_status = frappe.db.get_value("Service Order", self.service_order, "status")
		if order_status in COMPLETED_STATES:
			frappe.throw(
				_("Cannot modify Job {0}: Service Order {1} is Completed ({2}) and jobs are locked.").format(
					self.name, self.service_order, order_status
				)
			)

	def calculate_actual_hours(self):
		total_hours = 0.0
		for row in self.get("time_logs", []):
			if row.from_time and row.to_time:
				row.hours = round(flt(time_diff_in_hours(row.to_time, row.from_time)), 2)
				total_hours += row.hours
		self.actual_hours = round(total_hours, 2)
		self.variance_hours = round(self.actual_hours - flt(self.estimated_hours or 0), 2)


def get_current_employee_for_user(user: str):
	emp = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, ["name", "employee_name"], as_dict=True)
	return emp


@frappe.whitelist()
def start_job(job_name: str):
	job = frappe.get_doc("Service Job", job_name)
	order = frappe.get_doc("Service Order", job.service_order)

	if order.on_hold:
		frappe.throw(_("Cannot start work: Service Order {0} is On Hold ({1})").format(order.name, order.hold_reason))

	if job.status not in (JOB_ASSIGNED, JOB_PAUSED, JOB_QC_FAILED):
		frappe.throw(_("Job {0} is in status '{1}' and cannot be started.").format(job.name, job.status))

	user = frappe.session.user
	emp = get_current_employee_for_user(user)

	# Verify assignment unless user is supervisor or manager
	is_supervisor = bool(set(frappe.get_roles(user)) & {"Workshop Supervisor", "Service Manager", "System Manager"})
	if not is_supervisor and job.technician:
		if not emp or emp.name != job.technician:
			frappe.throw(_("This job is assigned to another technician ({0}).").format(job.technician_name or job.technician))

	# Technicians can run only one clock at a time
	technician_to_log = job.technician or (emp.name if emp else None)
	if technician_to_log:
		active_clock = frappe.db.sql(
			"""
			SELECT parent FROM `tabService Job Time Log`
			WHERE technician = %s AND (to_time IS NULL OR to_time = '') AND parent != %s
			LIMIT 1
		""",
			(technician_to_log, job.name),
		)
		if active_clock:
			frappe.throw(_("Technician already has an active clock on job {0}. Please pause or complete that job first.").format(active_clock[0][0]))

	now = now_datetime()
	job.status = JOB_IN_PROGRESS
	if not job.started_on:
		job.started_on = now

	# Append new time log row
	job.append(
		"time_logs",
		{
			"technician": technician_to_log,
			"from_time": now,
			"note": _("Clock started by {0}").format(user),
		},
	)
	job.save(ignore_permissions=True)

	# Update Service Order & Vehicle
	order.sync_status_from_jobs_and_parts()

	vehicle = frappe.get_doc("Service Vehicle", order.vehicle)
	if job.bay and vehicle.current_location != job.bay:
		vehicle.move_location(job.bay, _("Job started in bay"), order.name)
	vehicle.custodian = user
	vehicle.save(ignore_permissions=True)

	return {"status": "success", "job_status": job.status}


@frappe.whitelist()
def pause_job(job_name: str, reason: str | None = None):
	job = frappe.get_doc("Service Job", job_name)
	if job.status != JOB_IN_PROGRESS:
		frappe.throw(_("Job {0} is not currently In Progress.").format(job.name))

	now = now_datetime()
	open_log_found = False
	for row in job.get("time_logs", []):
		if row.from_time and not row.to_time:
			row.to_time = now
			row.hours = round(flt(time_diff_in_hours(row.to_time, row.from_time)), 2)
			if reason:
				row.note = (row.note or "") + f" [Paused: {reason}]"
			open_log_found = True

	if not open_log_found:
		pass

	job.status = JOB_PAUSED
	job.pause_reason = reason or _("Work paused")
	job.calculate_actual_hours()
	job.save(ignore_permissions=True)

	order = frappe.get_doc("Service Order", job.service_order)
	order.sync_status_from_jobs_and_parts()

	return {"status": "success", "job_status": job.status, "actual_hours": job.actual_hours}


@frappe.whitelist()
def complete_job(job_name: str):
	job = frappe.get_doc("Service Job", job_name)
	if job.status not in (JOB_IN_PROGRESS, JOB_PAUSED):
		frappe.throw(_("Job {0} cannot be completed from status '{1}'.").format(job.name, job.status))

	now = now_datetime()
	# Close open clock if in progress
	for row in job.get("time_logs", []):
		if row.from_time and not row.to_time:
			row.to_time = now
			row.hours = round(flt(time_diff_in_hours(row.to_time, row.from_time)), 2)

	job.status = JOB_COMPLETED
	job.completed_on = now
	job.calculate_actual_hours()
	job.save(ignore_permissions=True)

	order = frappe.get_doc("Service Order", job.service_order)
	order.sync_status_from_jobs_and_parts()

	# If all approved jobs are completed, move vehicle to QC Area
	if order.status == "QC":
		settings = frappe.get_cached_doc("Vehicle Service Settings")
		if settings.qc_location:
			vehicle = frappe.get_doc("Service Vehicle", order.vehicle)
			vehicle.move_location(settings.qc_location, _("All jobs completed, vehicle queued for QC"), order.name)

	return {"status": "success", "job_status": job.status, "order_status": order.status}


@frappe.whitelist()
def report_additional_work(service_order: str, job_title: str, estimated_hours: float, category: str = "Essential", description: str | None = None, parts: str | None = None):
	order = frappe.get_doc("Service Order", service_order)
	user = frappe.session.user

	# Create new pending Job
	new_job = frappe.new_doc("Service Job")
	new_job.service_order = order.name
	new_job.job_title = job_title
	new_job.category = category
	new_job.estimated_hours = flt(estimated_hours) or 1.0
	new_job.description = description
	new_job.status = "Pending Approval"
	new_job.source = "Additional"
	new_job.raised_by = user
	new_job.insert(ignore_permissions=True)

	# If parts specified, append to order
	if parts:
		try:
			parts_list = json.loads(parts) if isinstance(parts, str) else parts
			for p in parts_list:
				order.append(
					"parts",
					{
						"item_code": p.get("item_code"),
						"job": new_job.name,
						"category": category,
						"qty_required": flt(p.get("qty") or 1),
						"approval_status": "Pending",
						"part_status": "Pending Approval",
						"source": "Additional",
					},
				)
			order.save(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(f"Error appending additional parts: {e}", "Additional Work")

	order.sync_status_from_jobs_and_parts()

	# Notify Advisor
	if order.service_advisor:
		frappe.msgprint(
			_("Additional work '{0}' recorded and queued for Service Advisor approval.").format(job_title),
			alert=True,
		)

	return {"status": "success", "job": new_job.name}
