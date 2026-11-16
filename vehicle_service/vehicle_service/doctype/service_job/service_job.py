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
				row.hours = max(0.0, round(flt(time_diff_in_hours(row.to_time, row.from_time)), 2))
				total_hours += row.hours
		self.actual_hours = max(0.0, round(total_hours, 2))
		self.variance_hours = round(self.actual_hours - flt(self.estimated_hours or 0), 2)


def get_current_employee_for_user(user: str):
	emp = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, ["name", "employee_name"], as_dict=True)
	return emp


@frappe.whitelist()
def start_job(job_name: str):
	from vehicle_service.job_control import start_clock
	return start_clock(job_name)


@frappe.whitelist()
def pause_job(job_name: str, reason: str | None = None):
	from vehicle_service.job_control import pause_clock
	return pause_clock(job_name, reason)


@frappe.whitelist()
def complete_job(job_name: str):
	from vehicle_service.job_control import _complete_jobs

	job = frappe.db.get_value("Service Job", job_name, ["service_order", "technician"], as_dict=True)
	if not job:
		frappe.throw(_("Service Job {0} not found.").format(job_name))

	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	is_controller = user == "Administrator" or bool(roles & {"Job Controller", "Workshop Supervisor", "Service Manager", "System Manager"})
	if not is_controller:
		emp = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
		if not emp or emp != job.technician:
			frappe.throw(_("Access denied: only Job Controllers or the assigned technician can complete this job."), frappe.PermissionError)

	res = _complete_jobs(job.service_order, [job_name])
	return {"status": "success", "job_status": JOB_COMPLETED, "order_status": res["order_status"]}


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
