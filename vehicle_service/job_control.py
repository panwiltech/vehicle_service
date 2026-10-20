# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, time_diff_in_hours
from vehicle_service.state import (
	COMPLETED_STATES,
	JOB_ASSIGNED,
	JOB_COMPLETED,
	JOB_IN_PROGRESS,
	JOB_PAUSED,
	JOB_QC_FAILED,
	READY_FOR_BILLING,
)


def _require_job_controller():
	user = frappe.session.user
	if user == "Administrator":
		return
	roles = set(frappe.get_roles(user))
	if not (roles & {"Job Controller", "Workshop Supervisor", "Service Manager", "System Manager"}):
		frappe.throw(_("Access denied: only Job Controllers or System Managers can perform this action."), frappe.PermissionError)


def _require_board_viewer():
	user = frappe.session.user
	if user == "Administrator":
		return
	roles = set(frappe.get_roles(user))
	allowed_roles = {
		"Job Controller",
		"Workshop Supervisor",
		"Service Manager",
		"Service Advisor",
		"Parts Controller",
		"Parts Manager",
		"System Manager",
	}
	if not (roles & allowed_roles):
		frappe.throw(_("Access denied: you do not have permission to view the Job Control Board."), frappe.PermissionError)


def _assert_jobs_editable(order):
	if order.status in COMPLETED_STATES:
		frappe.throw(
			_("Service Order {0} is in status '{1}' and is locked. Jobs cannot be modified.").format(
				order.name, order.status
			)
		)
	if order.status == "Cancelled":
		frappe.throw(_("Cannot modify jobs on cancelled Service Order {0}.").format(order.name))
	if order.is_locked_by_invoice():
		frappe.throw(
			_("Cannot modify jobs: Service Order {0} is locked by submitted Sales Invoice {1}.").format(
				order.name, order.sales_invoice
			)
		)


def _mirror_job_to_order(job, order=None):
	if not order:
		order = frappe.get_doc("Service Order", job.service_order)
	found = False
	for row in order.get("jobs", []):
		if row.service_job == job.name:
			row.job_title = job.job_title
			row.category = job.category
			row.priority = job.priority
			row.estimated_hours = job.estimated_hours
			row.actual_hours = job.actual_hours
			row.rate = job.rate
			row.amount = job.amount
			row.status = job.status
			row.technician = job.technician
			row.technician_name = job.technician_name
			row.bay = job.bay
			row.source = job.source
			row.reason_for_adding = job.reason_for_adding
			found = True
			break

	if not found:
		order.append(
			"jobs",
			{
				"service_job": job.name,
				"job_title": job.job_title,
				"category": job.category,
				"priority": job.priority,
				"estimated_hours": job.estimated_hours,
				"actual_hours": job.actual_hours,
				"service_item": job.service_item or "LABOUR",
				"rate": job.rate,
				"amount": job.amount,
				"status": job.status,
				"technician": job.technician,
				"technician_name": job.technician_name,
				"bay": job.bay,
				"source": job.source,
				"reason_for_adding": job.reason_for_adding,
			},
		)

	order.flags.ignore_job_lock = True
	order.save(ignore_permissions=True)
	order.sync_status_from_jobs_and_parts()
	return order


@frappe.whitelist()
def add_job(
	service_order: str,
	job_title: str,
	description: str | None = None,
	estimated_hours: float = 1.0,
	category: str = "Essential",
	priority: str = "Medium",
	technician: str | None = None,
	reason: str | None = None,
	service_item: str | None = None,
	rate: float | None = None,
	bay: str | None = None,
	supplier: str | None = None,
	supplier_cost: float | None = None,
	supplier_invoice_ref: str | None = None,
):
	_require_job_controller()
	order = frappe.get_doc("Service Order", service_order)
	_assert_jobs_editable(order)

	settings = frappe.get_cached_doc("Vehicle Service Settings")
	srv_item = service_item or settings.labour_item or "LABOUR"
	srv_rate = flt(rate) if rate is not None and flt(rate) > 0 else (flt(settings.labour_rate) or 50.0)
	calc_amount = round(flt(estimated_hours or 1.0) * srv_rate, 2)
	has_quote = bool(frappe.db.exists("Quotation", {"vs_service_order": order.name, "docstatus": 1}))
	source = "Additional Work" if has_quote else "Manually Added"

	job = frappe.new_doc("Service Job")
	job.service_order = order.name
	job.vehicle = order.vehicle
	job.job_title = job_title
	job.category = category
	job.priority = priority
	job.service_item = srv_item
	job.estimated_hours = flt(estimated_hours or 1.0)
	job.rate = srv_rate
	job.amount = calc_amount
	job.description = description
	job.reason_for_adding = reason
	job.source = source
	job.raised_by = frappe.session.user
	job.status = "Approved"

	if technician:
		emp = frappe.get_doc("Employee", technician)
		job.technician = emp.name
		job.technician_name = emp.employee_name
		job.technician_user = emp.user_id
		job.status = "Assigned"

	if bay:
		job.bay = bay
	if supplier:
		job.supplier = supplier
		job.supplier_cost = flt(supplier_cost or 0)
		job.supplier_invoice_ref = supplier_invoice_ref

	job.flags.ignore_job_lock = True
	job.insert(ignore_permissions=True)

	_mirror_job_to_order(job, order)
	order.add_comment("Comment", _("Job added: {0} ({1} hrs) by {2}").format(job_title, estimated_hours, frappe.session.user))
	frappe.publish_realtime("job_board_update", {"order": order.name, "action": "add_job"}, after_commit=True)

	return {"status": "success", "job": job.name}


@frappe.whitelist()
def assign_technician(job_name: str, technician: str, bay: str | None = None):
	_require_job_controller()
	job = frappe.get_doc("Service Job", job_name)
	order = frappe.get_doc("Service Order", job.service_order)
	_assert_jobs_editable(order)

	if job.status in (JOB_IN_PROGRESS, JOB_PAUSED):
		frappe.throw(_("Cannot change technician while clock is active or paused on Job {0}.").format(job.name))

	emp = frappe.get_doc("Employee", technician)
	job.technician = emp.name
	job.technician_name = emp.employee_name
	job.technician_user = emp.user_id
	if bay:
		job.bay = bay
	job.status = "Assigned"
	job.flags.ignore_job_lock = True
	job.save(ignore_permissions=True)

	_mirror_job_to_order(job, order)

	if bay and order.vehicle:
		veh = frappe.get_doc("Service Vehicle", order.vehicle)
		veh.move_location(bay, _("Assigned to bay {0}").format(bay), order.name)

	order.add_comment("Comment", _("Technician {0} assigned to Job {1}").format(emp.employee_name or emp.name, job.job_title))
	frappe.publish_realtime("job_board_update", {"order": order.name, "action": "assign_technician"}, after_commit=True)
	return {"status": "success", "job_status": job.status, "order_status": order.status}


@frappe.whitelist()
def start_clock(job_name: str):
	user = frappe.session.user
	job = frappe.get_doc("Service Job", job_name)
	order = frappe.get_doc("Service Order", job.service_order)
	_assert_jobs_editable(order)

	# Validate technician requirement
	if not job.technician:
		frappe.throw(_("Cannot start clock: Job {0} has no technician assigned.").format(job.name))

	# Authorization check: Job Controller/System Manager OR assigned technician
	roles = set(frappe.get_roles(user))
	is_controller = bool(roles & {"Job Controller", "Workshop Supervisor", "Service Manager", "System Manager"}) or user == "Administrator"
	emp_current = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if not is_controller:
		if not emp_current or emp_current != job.technician:
			frappe.throw(_("Access denied: only Job Controllers or the assigned technician can start this clock."), frappe.PermissionError)

	if order.on_hold:
		frappe.throw(_("Cannot start clock: Service Order {0} is On Hold ({1})").format(order.name, order.hold_reason))

	if job.status not in ("Approved", JOB_ASSIGNED, JOB_PAUSED, JOB_QC_FAILED):
		frappe.throw(_("Job {0} is in status '{1}' and cannot be started.").format(job.name, job.status))

	# Acquire database lock on employee row to prevent race conditions
	frappe.db.sql("SELECT name FROM `tabEmployee` WHERE name = %s FOR UPDATE", (job.technician,))

	# Check for active running clock across ALL jobs
	active_clock = frappe.db.sql(
		"""
		SELECT parent FROM `tabService Job Time Log`
		WHERE technician = %s AND (to_time IS NULL OR to_time = '') AND parent != %s
		LIMIT 1
		""",
		(job.technician, job.name),
	)
	if active_clock:
		frappe.throw(_("Technician already has an active clock on job {0}. Please pause or complete that job first.").format(active_clock[0][0]))

	now = now_datetime()
	job.status = JOB_IN_PROGRESS
	if not job.started_on:
		job.started_on = now

	job.append(
		"time_logs",
		{
			"technician": job.technician,
			"from_time": now,
			"note": _("Clock started by {0}").format(user),
		},
	)
	job.flags.ignore_job_lock = True
	job.save(ignore_permissions=True)

	_mirror_job_to_order(job, order)
	order.add_comment("Comment", _("Clock started on Job {0} by {1}").format(job.job_title, user))
	frappe.publish_realtime("job_board_update", {"order": order.name, "action": "start_clock"}, after_commit=True)

	return {"status": "success", "job_status": job.status, "order_status": order.status}


@frappe.whitelist()
def pause_clock(job_name: str, reason: str | None = None):
	user = frappe.session.user
	job = frappe.get_doc("Service Job", job_name)
	order = frappe.get_doc("Service Order", job.service_order)
	_assert_jobs_editable(order)

	# Authorization check
	roles = set(frappe.get_roles(user))
	is_controller = bool(roles & {"Job Controller", "Workshop Supervisor", "Service Manager", "System Manager"}) or user == "Administrator"
	emp_current = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if not is_controller:
		if not emp_current or emp_current != job.technician:
			frappe.throw(_("Access denied: only Job Controllers or the assigned technician can pause this clock."), frappe.PermissionError)

	if job.status != JOB_IN_PROGRESS:
		frappe.throw(_("Job {0} is not currently In Progress.").format(job.name))

	now = now_datetime()
	for row in job.get("time_logs", []):
		if row.from_time and not row.to_time:
			row.to_time = now
			row.hours = round(flt(time_diff_in_hours(row.to_time, row.from_time)), 2)
			if reason:
				row.note = (row.note or "") + f" [Paused: {reason}]"

	job.status = JOB_PAUSED
	job.pause_reason = reason or _("Work paused")
	job.calculate_actual_hours()
	job.flags.ignore_job_lock = True
	job.save(ignore_permissions=True)

	_mirror_job_to_order(job, order)
	order.add_comment("Comment", _("Clock paused on Job {0} ({1})").format(job.job_title, reason or "Paused"))
	frappe.publish_realtime("job_board_update", {"order": order.name, "action": "pause_clock"}, after_commit=True)

	return {"status": "success", "job_status": job.status, "actual_hours": job.actual_hours}


@frappe.whitelist()
def complete_service_order(order_name: str):
	_require_job_controller()
	order = frappe.get_doc("Service Order", order_name)
	_assert_jobs_editable(order)

	# Check for any job in Pending Approval
	all_jobs = frappe.get_all(
		"Service Job",
		filters={"service_order": order.name},
		fields=["name", "job_title", "status"],
	)
	pending = [j for j in all_jobs if j.status == "Pending Approval"]
	if pending:
		titles = ", ".join(j.job_title for j in pending)
		frappe.throw(
			_("Cannot complete Service Order: The following job(s) are still Pending Approval: {0}. Please approve or cancel them first.").format(titles)
		)

	now = now_datetime()

	# Complete all non-terminal jobs & close open logs
	for j_info in all_jobs:
		if j_info.status not in (JOB_COMPLETED, "Passed", "Cancelled", "Declined"):
			j_doc = frappe.get_doc("Service Job", j_info.name)
			for row in j_doc.get("time_logs", []):
				if row.from_time and not row.to_time:
					row.to_time = now
					row.hours = round(flt(time_diff_in_hours(row.to_time, row.from_time)), 2)
			j_doc.status = JOB_COMPLETED
			j_doc.completed_on = now
			j_doc.calculate_actual_hours()
			j_doc.flags.ignore_job_lock = True
			j_doc.save(ignore_permissions=True)

	# Sync child table jobs on order
	for row in order.get("jobs", []):
		if row.status not in (JOB_COMPLETED, "Passed", "Cancelled", "Declined"):
			row.status = JOB_COMPLETED
			sj_hours = frappe.db.get_value("Service Job", row.service_job, "actual_hours")
			row.actual_hours = flt(sj_hours or 0.0)

	order.status = READY_FOR_BILLING
	order.board_status = "Completed"
	order.flags.ignore_job_lock = True

	# Move vehicle to parking bay if configured
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	if settings.parking_location and order.vehicle:
		veh = frappe.get_doc("Service Vehicle", order.vehicle)
		veh.move_location(settings.parking_location, _("Workshop jobs completed. Order ready for billing."), order.name)

	order.save(ignore_permissions=True)
	order.add_comment("Comment", _("Service Order completed by {0}. All jobs marked Completed and transitioned to Ready for Billing.").format(frappe.session.user))
	frappe.publish_realtime("job_board_update", {"order": order.name, "action": "complete_service_order"}, after_commit=True)

	return {"status": "success", "order_status": order.status, "board_status": order.board_status}


def order_has_permission(doc, ptype="read", user=None):
	"""Permission hook for Service Order: denies write if order is completed and user only has Job Controller role."""
	if ptype != "write":
		return True
	user = user or frappe.session.user
	if not user or user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))
	if "System Manager" in roles:
		return True

	if "Job Controller" in roles and doc:
		status = getattr(doc, "status", None)
		if not status and isinstance(doc, str):
			status = frappe.db.get_value("Service Order", doc, "status")
		if status in COMPLETED_STATES:
			return False

	return True
