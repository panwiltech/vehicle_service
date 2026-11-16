# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from vehicle_service.analytics import get_daily_throughput


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_daily_throughput(filters)
	chart = get_chart(data)
	summary = get_summary(data)
	return columns, data, None, chart, summary


def get_columns():
	return [
		{
			"label": _("Date"),
			"fieldname": "date",
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"label": _("Orders Received"),
			"fieldname": "orders_received",
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"label": _("Orders Started"),
			"fieldname": "orders_started",
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"label": _("Orders Completed"),
			"fieldname": "orders_completed",
			"fieldtype": "Int",
			"width": 140,
		},
		{
			"label": _("Avg Turnaround (Hrs)"),
			"fieldname": "avg_turnaround_hours",
			"fieldtype": "Float",
			"width": 160,
		},
		{
			"label": _("Backlog at Day End"),
			"fieldname": "backlog",
			"fieldtype": "Int",
			"width": 150,
		},
	]


def get_chart(data):
	if not data:
		return None

	dates = [r["date"] for r in data]
	received = [r["orders_received"] for r in data]
	completed = [r["orders_completed"] for r in data]

	return {
		"data": {
			"labels": dates,
			"datasets": [
				{"name": _("Received"), "values": received},
				{"name": _("Completed"), "values": completed},
			],
		},
		"type": "bar",
		"colors": ["#ffa00a", "#29cd42"],
	}


def get_summary(data):
	if not data:
		return []

	total_received = sum(r.get("orders_received", 0) for r in data)
	total_completed = sum(r.get("orders_completed", 0) for r in data)
	completed_days = [r for r in data if r.get("orders_completed", 0) > 0]
	avg_turn = (
		round(sum(r.get("avg_turnaround_hours", 0.0) for r in completed_days) / len(completed_days), 1)
		if completed_days
		else 0.0
	)
	latest_backlog = data[-1].get("backlog", 0) if data else 0

	return [
		{"value": total_received, "label": _("Total Orders Received"), "datatype": "Int"},
		{"value": total_completed, "label": _("Total Orders Completed"), "datatype": "Int"},
		{"value": avg_turn, "label": _("Avg Turnaround (Hours)"), "datatype": "Float"},
		{"value": latest_backlog, "label": _("Current Backlog"), "datatype": "Int"},
	]
