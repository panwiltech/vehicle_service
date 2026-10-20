# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, time_diff_in_seconds
from vehicle_service.job_control import _require_board_viewer, _require_job_controller
from vehicle_service.state import JOB_COMPLETED, JOB_IN_PROGRESS


def get_tab_order_names(tab) -> list[str]:
	"""Return names of Service Orders that belong in `tab`, without duplicates.

	An order matches if its status is one of the tab's order statuses, or if the tab is
	job-driven and any of the order's Service Jobs is In Progress. Cancelled orders are
	only included when the tab explicitly lists Cancelled.
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

	if tab.include_if_any_job_in_progress:
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
		fields=["name", "service_order", "status", "actual_hours", "started_on"],
	)
	completed: dict[str, int] = {}
	running: set[str] = set()
	actual_hours_map: dict[str, float] = {}

	for job in jobs:
		if job.status == JOB_COMPLETED:
			completed[job.service_order] = completed.get(job.service_order, 0) + 1
		if job.status == JOB_IN_PROGRESS:
			running.add(job.service_order)
		actual_hours_map[job.service_order] = round(
			actual_hours_map.get(job.service_order, 0.0) + flt(job.actual_hours or 0.0), 2
		)

	# Fetch active running time logs for jobs
	clock_starts: dict[str, object] = {}
	job_names = [j.name for j in jobs]
	if job_names:
		active_logs = frappe.db.sql(
			"""
			SELECT parent, from_time
			FROM `tabService Job Time Log`
			WHERE parent IN %s AND (to_time IS NULL OR to_time = '')
			ORDER BY from_time ASC
			""",
			(tuple(job_names),),
			as_dict=True,
		)
		job_to_order = {j.name: j.service_order for j in jobs}
		for al in active_logs:
			so = job_to_order.get(al.parent)
			if so and so not in clock_starts and al.from_time:
				clock_starts[so] = al.from_time

	# Fallback to started_on if in running and no active log record
	for j in jobs:
		if j.status == JOB_IN_PROGRESS and j.service_order not in clock_starts and j.started_on:
			clock_starts[j.service_order] = j.started_on

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
	cards = []
	for name in names:
		order = by_name.get(name)
		if not order:
			continue
		actual_h = actual_hours_map.get(name, 0.0)
		actual_s = int(round(actual_h * 3600))
		is_running = name in running
		cs_dt = clock_starts.get(name) if is_running else None
		running_sec = 0
		if is_running and cs_dt:
			try:
				running_sec = max(0, int(round(time_diff_in_seconds(now, cs_dt))))
			except Exception:
				running_sec = 0

		total_elapsed_sec = actual_s + running_sec
		cs_ms = _to_timestamp_ms(cs_dt) if is_running else None
		cs_iso = cs_dt.isoformat() if (cs_dt and hasattr(cs_dt, "isoformat")) else (str(cs_dt) if cs_dt else None)

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

