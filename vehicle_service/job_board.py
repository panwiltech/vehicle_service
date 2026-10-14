# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from vehicle_service.job_control import _require_job_controller
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
	_require_job_controller()
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
	_require_job_controller()
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
		fields=["service_order", "status"],
	)
	completed: dict[str, int] = {}
	running: set[str] = set()
	for job in jobs:
		if job.status == JOB_COMPLETED:
			completed[job.service_order] = completed.get(job.service_order, 0) + 1
		if job.status == JOB_IN_PROGRESS:
			running.add(job.service_order)

	cards = []
	for name in names:
		order = by_name.get(name)
		if not order:
			continue
		cards.append(
			{
				"name": order.name,
				"status": order.status,
				"customer_name": order.customer_name,
				"vehicle": order.vehicle,
				"technicians": order.technicians,
				"job_count": order.job_count or 0,
				"jobs_completed": completed.get(name, 0),
				"has_running_clock": name in running,
			}
		)
	return cards
