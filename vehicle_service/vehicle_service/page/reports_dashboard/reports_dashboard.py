# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.utils import flt, nowdate
from vehicle_service.analytics import (
	get_completed_orders,
	get_daily_throughput,
	get_doc_summary,
	get_parts_sales,
	get_technician_labour_units,
	get_wip_valuation,
)


@frappe.whitelist()
def get_dashboard_data(filters=None):
	"""Aggregates all executive metrics for the Reports Dashboard."""
	if isinstance(filters, str):
		filters = json.loads(filters)
	filters = filters or {}
	if not filters.get("from_date"):
		filters["from_date"] = frappe.utils.add_months(nowdate(), -1)
	if not filters.get("to_date"):
		filters["to_date"] = nowdate()

	# 1. Fetch from analytics engine
	completed_orders = get_completed_orders(filters)
	throughput_data = get_daily_throughput(filters)
	wip_data = get_wip_valuation(filters)
	tech_stats = get_technician_labour_units(filters)
	parts_sales = get_parts_sales(filters)
	doc_summary = get_doc_summary(filters)

	# 2. Compute Cards
	total_completed = len(completed_orders)
	avg_turn = (
		round(sum(o["turnaround_hours"] for o in completed_orders) / total_completed, 1)
		if total_completed
		else 0.0
	)

	days_count = len(throughput_data) or 1
	avg_throughput_day = round(sum(r["orders_completed"] for r in throughput_data) / days_count, 1)
	current_backlog = throughput_data[-1]["backlog"] if throughput_data else 0

	total_parts_sales = sum(flt(p["net_sales"]) for p in parts_sales)
	parts_units_sold = sum(flt(p["qty"]) for p in parts_sales)

	total_labour_units = sum(flt(t["sold_units"]) for t in tech_stats)
	total_actual_hours = sum(flt(t["actual_hours"]) for t in tech_stats)

	cards = [
		{
			"id": "completed_orders",
			"title": _("Completed Orders"),
			"value": str(total_completed),
			"subtitle": _("Avg {0} hrs turnaround").format(avg_turn),
			"icon": "check-circle",
			"color": "green",
			"report": "Completed Service Orders",
		},
		{
			"id": "throughput",
			"title": _("Daily Throughput"),
			"value": str(avg_throughput_day),
			"subtitle": _("Orders/day | Backlog: {0}").format(current_backlog),
			"icon": "trending-up",
			"color": "blue",
			"report": "Service Order Throughput",
		},
		{
			"id": "wip_value",
			"title": _("Active WIP Valuation"),
			"value": frappe.format_value(wip_data["summary"]["total_wip"], {"fieldtype": "Currency"}),
			"subtitle": _("Parts: {0} | Labour: {1}").format(
				frappe.format_value(wip_data["summary"]["total_parts_wip"], {"fieldtype": "Currency"}),
				frappe.format_value(wip_data["summary"]["total_labour_wip"], {"fieldtype": "Currency"}),
			),
			"icon": "tool",
			"color": "orange",
			"report": "Completed Service Orders",
		},
		{
			"id": "parts_sold",
			"title": _("Parts Sold"),
			"value": frappe.format_value(total_parts_sales, {"fieldtype": "Currency"}),
			"subtitle": _("{0} units sold").format(int(parts_units_sold)),
			"icon": "package",
			"color": "purple",
			"report": "Parts Consumption",
		},
		{
			"id": "labour_sold",
			"title": _("Labour Units Sold"),
			"value": f"{round(total_labour_units, 1)} hrs",
			"subtitle": _("Worked: {0} hrs").format(round(total_actual_hours, 1)),
			"icon": "user-check",
			"color": "teal",
			"report": "Technician Performance",
		},
		{
			"id": "doc_summary",
			"title": _("DOC Performance"),
			"value": frappe.format_value(doc_summary["department_total"]["total_revenue"], {"fieldtype": "Currency"}),
			"subtitle": _("Overall Margin: {0}%").format(doc_summary["department_total"]["overall_gp_percent"]),
			"icon": "activity",
			"color": "cyan",
			"report": "Workshop Performance",
		},
	]

	# 3. Compute Chart Datasets
	# Throughput Trend
	dates = [r["date"] for r in throughput_data]
	received_vals = [r["orders_received"] for r in throughput_data]
	completed_vals = [r["orders_completed"] for r in throughput_data]
	throughput_chart = {
		"title": _("Service Orders: Received vs Completed"),
		"data": {
			"labels": dates,
			"datasets": [
				{"name": _("Received"), "values": received_vals},
				{"name": _("Completed"), "values": completed_vals},
			],
		},
		"type": "line",
		"colors": ["#ffa00a", "#29cd42"],
	}

	# Branch WIP Valuation (Stacked Bar)
	branches = [b["branch"] for b in wip_data["branch_summary"]] or [_("All")]
	parts_wip_vals = [b["parts_wip"] for b in wip_data["branch_summary"]] or [0]
	labour_wip_vals = [b["labour_wip"] for b in wip_data["branch_summary"]] or [0]
	wip_chart = {
		"title": _("Active WIP Valuation by Branch ($)"),
		"data": {
			"labels": branches,
			"datasets": [
				{"name": _("Parts WIP Cost"), "values": parts_wip_vals},
				{"name": _("Labour WIP Cost"), "values": labour_wip_vals},
			],
		},
		"type": "bar",
		"stacked": 1,
		"colors": ["#9b51e0", "#2490ef"],
	}

	# Technician Productivity Chart
	top_techs = tech_stats[:8]
	tech_names = [t["technician_name"] for t in top_techs] or [_("None")]
	tech_sold = [t["sold_units"] for t in top_techs] or [0]
	tech_actual = [t["actual_hours"] for t in top_techs] or [0]
	tech_chart = {
		"title": _("Technician Performance (Sold vs Worked Hours)"),
		"data": {
			"labels": tech_names,
			"datasets": [
				{"name": _("Units Sold"), "values": tech_sold},
				{"name": _("Actual Hours"), "values": tech_actual},
			],
		},
		"type": "bar",
		"colors": ["#00a8ff", "#718093"],
	}

	return {
		"cards": cards,
		"charts": {
			"throughput": throughput_chart,
			"wip": wip_chart,
			"technician": tech_chart,
		},
	}
