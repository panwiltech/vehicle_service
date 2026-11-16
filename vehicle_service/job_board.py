# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_seconds
from vehicle_service.job_control import _require_board_viewer, _require_job_controller
from vehicle_service.state import JOB_CANCELLED, JOB_COMPLETED, JOB_IN_PROGRESS, JOB_PAUSED, JOB_PENDING, PART_WAITING


def get_tab_order_names(tab) -> list[str]:
	"""Return names of Service Orders that belong in `tab`, without duplicates.

	An order matches if its status is one of the tab's order statuses, or if the tab is
	job-driven and any of the order's Service Jobs is In Progress, Awaiting Parts, or
	Awaiting Approval. Cancelled orders are only included when the tab explicitly lists Cancelled.
	"""
	statuses = [row.status for row in tab.order_statuses]
	names: list[str] = []
	if statuses:
		names = frappe.get_all(
			"Service Order",
			filters={"status": ["in", statuses]},
			order_by="modified desc",
			pluck="name",
		)

	if getattr(tab, "include_if_any_job_in_progress", False):
		job_orders = frappe.get_all(
			"Service Job",
			filters={"status": JOB_IN_PROGRESS},
			pluck="service_order",
			distinct=True,
		)
		if job_orders:
			active = frappe.get_all(
				"Service Order",
				filters={"name": ["in", job_orders], "status": ["!=", "Cancelled"]},
				order_by="modified desc",
				pluck="name",
			)
			seen = set(names)
			names.extend(n for n in active if n not in seen)

	tab_name = getattr(tab, "name", "")
	tab_label = getattr(tab, "tab_label", "")

	if "Waiting for Parts" in statuses or tab_name == "Awaiting Parts" or tab_label == "Awaiting Parts":
		paused_parts_orders = frappe.db.sql(
			"""
			SELECT DISTINCT service_order FROM `tabService Job`
			WHERE status = %s AND LOWER(pause_reason) LIKE %s
			""",
			(JOB_PAUSED, "%part%"),
			pluck=True,
		)
		stock_parts_orders = frappe.db.sql(
			"""
			SELECT DISTINCT parent FROM `tabService Order Part`
			WHERE approval_status = 'Approved' AND part_status = %s
			""",
			(PART_WAITING,),
			pluck=True,
		)
		matched = set(paused_parts_orders) | set(stock_parts_orders)
		if matched:
			active = frappe.get_all(
				"Service Order",
				filters={"name": ["in", list(matched)], "status": ["not in", ["Cancelled", "Delivered"]]},
				order_by="modified desc",
				pluck="name",
			)
			seen = set(names)
			names.extend(n for n in active if n not in seen)

	if "Awaiting Approval" in statuses or tab_name == "Awaiting Approval" or tab_label == "Awaiting Approval":
		approval_orders = frappe.db.sql(
			"""
			SELECT DISTINCT service_order FROM `tabService Job`
			WHERE (status = %s AND LOWER(pause_reason) LIKE %s)
			   OR status = %s
			""",
			(JOB_PAUSED, "%approv%", JOB_PENDING),
			pluck=True,
		)
		if approval_orders:
			active = frappe.get_all(
				"Service Order",
				filters={"name": ["in", approval_orders], "status": ["not in", ["Cancelled", "Delivered"]]},
				order_by="modified desc",
				pluck="name",
			)
			seen = set(names)
			names.extend(n for n in active if n not in seen)

	return names


def _get_enabled_tab(tab: str):
	if not frappe.db.exists("Job Board Tab", {"name": tab, "enabled": 1}):
		frappe.throw(_("Job Board Tab {0} not found or disabled.").format(tab), frappe.DoesNotExistError)
	return frappe.get_doc("Job Board Tab", tab)


@frappe.whitelist()
def get_board_tabs() -> list[dict]:
	_require_board_viewer()
	tabs = frappe.get_all(
		"Job Board Tab",
		filters={"enabled": 1},
		fields=["name", "tab_label"],
		order_by="sequence asc, tab_label asc",
	)
	return [
		{
			"name": t.name,
			"label": t.tab_label,
			"count": len(get_tab_order_names(frappe.get_doc("Job Board Tab", t.name))),
		}
		for t in tabs
	]


@frappe.whitelist()
def get_board_orders(tab: str) -> list[dict]:
	_require_board_viewer()
	names = get_tab_order_names(_get_enabled_tab(tab))
	if not names:
		return []

	orders = frappe.get_all(
		"Service Order",
		filters={"name": ["in", names]},
		fields=["name", "status", "customer_name", "vehicle", "technicians", "job_count"],
	)
	by_name = {o.name: o for o in orders}

	jobs = frappe.get_all(
		"Service Job",
		filters={"service_order": ["in", names]},
		fields=[
			"name",
			"service_order",
			"job_title",
			"category",
			"status",
			"technician",
			"technician_name",
			"estimated_hours",
			"actual_hours",
			"started_on",
			"pause_reason",
		],
		order_by="creation asc",
	)
	completed: dict[str, int] = {}
	running: set[str] = set()
	actual_hours_map: dict[str, float] = {}
	job_by_name = {j.name: j for j in jobs}

	for job in jobs:
		if job.status == JOB_COMPLETED:
			completed[job.service_order] = completed.get(job.service_order, 0) + 1
		if job.status == JOB_IN_PROGRESS:
			running.add(job.service_order)
		actual_hours_map[job.service_order] = round(
			actual_hours_map.get(job.service_order, 0.0) + flt(job.actual_hours or 0.0), 2
		)

	def _to_timestamp_ms(dt):
		if not dt:
			return None
		if isinstance(dt, str):
			dt = get_datetime(dt)
		try:
			return int(dt.timestamp() * 1000)
		except Exception:
			return None

	now = now_datetime()

	# Fetch active running time logs for jobs
	active_clocks_by_order: dict[str, list[dict]] = {}
	running_job_ids: set[str] = set()
	job_names = [j.name for j in jobs]
	if job_names:
		active_logs = frappe.db.sql(
			"""
			SELECT l.parent, l.from_time, l.technician, e.employee_name
			FROM `tabService Job Time Log` l
			LEFT JOIN `tabEmployee` e ON e.name = l.technician
			WHERE l.parent IN %s AND l.to_time IS NULL
			ORDER BY l.from_time ASC
			""",
			(tuple(job_names),),
			as_dict=True,
		)
		for al in active_logs:
			job = job_by_name.get(al.parent)
			if not job:
				continue
			so = job.service_order
			running_job_ids.add(job.name)
			running.add(so)
			al_dt = al.from_time
			al_sec = max(0, int(round(time_diff_in_seconds(now, al_dt)))) if al_dt else 0
			clock_info = {
				"job": job.name,
				"job_title": job.job_title,
				"technician": al.technician or job.technician,
				"technician_name": al.employee_name or job.technician_name or al.technician or job.technician or _("Unassigned"),
				"clock_start": al_dt.isoformat() if hasattr(al_dt, "isoformat") else (str(al_dt) if al_dt else None),
				"clock_start_ms": _to_timestamp_ms(al_dt),
				"running_seconds": al_sec,
			}
			active_clocks_by_order.setdefault(so, []).append(clock_info)

	# Fallback to started_on if in running and no active log record
	for j in jobs:
		if j.status == JOB_IN_PROGRESS:
			running.add(j.service_order)
			if j.name not in running_job_ids:
				running_job_ids.add(j.name)
				j_dt = j.started_on or now
				j_sec = max(0, int(round(time_diff_in_seconds(now, j_dt)))) if j_dt else 0
				clock_info = {
					"job": j.name,
					"job_title": j.job_title,
					"technician": j.technician,
					"technician_name": j.technician_name or j.technician or _("Unassigned"),
					"clock_start": j_dt.isoformat() if hasattr(j_dt, "isoformat") else (str(j_dt) if j_dt else None),
					"clock_start_ms": _to_timestamp_ms(j_dt),
					"running_seconds": j_sec,
				}
				active_clocks_by_order.setdefault(j.service_order, []).append(clock_info)

	jobs_by_order: dict[str, list[dict]] = {}
	paused_clocks_by_order: dict[str, list[dict]] = {}
	for j in jobs:
		j_running_clock = next((c for c in active_clocks_by_order.get(j.service_order, []) if c["job"] == j.name), None)
		is_j_running = bool(j_running_clock)
		jobs_by_order.setdefault(j.service_order, []).append({
			"name": j.name,
			"job_title": j.job_title,
			"category": j.category,
			"status": j.status,
			"technician": j.technician,
			"technician_name": j.technician_name or j.technician or _("Unassigned"),
			"estimated_hours": flt(j.estimated_hours or 0.0),
			"actual_hours": flt(j.actual_hours or 0.0),
			"pause_reason": j.pause_reason,
			"has_running_clock": is_j_running,
			"running_seconds": j_running_clock["running_seconds"] if j_running_clock else 0,
			"clock_start": j_running_clock["clock_start"] if j_running_clock else None,
			"clock_start_ms": j_running_clock["clock_start_ms"] if j_running_clock else None,
		})

		if (j.status == JOB_PAUSED or j.pause_reason) and not is_j_running and j.status not in (JOB_COMPLETED, JOB_CANCELLED):
			paused_clocks_by_order.setdefault(j.service_order, []).append({
				"job": j.name,
				"job_title": j.job_title,
				"technician": j.technician,
				"technician_name": j.technician_name or j.technician or _("Unassigned"),
				"pause_reason": j.pause_reason or _("Paused"),
				"actual_hours": flt(j.actual_hours or 0.0),
				"actual_seconds": max(0, int(round(flt(j.actual_hours or 0.0) * 3600))),
			})

	cards = []
	for name in names:
		order = by_name.get(name)
		if not order:
			continue
		actual_h = actual_hours_map.get(name, 0.0)
		actual_s = int(round(actual_h * 3600))
		active_clocks = active_clocks_by_order.get(name, [])
		paused_clocks = paused_clocks_by_order.get(name, [])
		clock_count = len(active_clocks)
		is_running = clock_count > 0 or (name in running)

		primary_clock = active_clocks[0] if active_clocks else None
		cs_iso = primary_clock["clock_start"] if primary_clock else None
		cs_ms = primary_clock["clock_start_ms"] if primary_clock else None
		running_sec = sum(c["running_seconds"] for c in active_clocks)
		total_elapsed_sec = actual_s + running_sec

		cards.append(
			{
				"name": order.name,
				"status": order.status,
				"customer_name": order.customer_name,
				"vehicle": order.vehicle,
				"technicians": order.technicians,
				"job_count": order.job_count or 0,
				"jobs_completed": completed.get(name, 0),
				"has_running_clock": is_running,
				"clock_count": clock_count,
				"active_clocks": active_clocks,
				"paused_clocks": paused_clocks,
				"jobs": jobs_by_order.get(name, []),
				"clock_start": cs_iso,
				"clock_start_ms": cs_ms,
				"actual_hours": actual_h,
				"actual_seconds": actual_s,
				"running_seconds": running_sec,
				"total_seconds": total_elapsed_sec,
			}
		)
	return cards


def publish_board_update(doc, method=None) -> None:
	"""Doc-event hook: tell open boards that a Service Order / Service Job changed."""
	frappe.publish_realtime("job_board_update", {"doctype": doc.doctype, "name": doc.name}, after_commit=True)

