# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from vehicle_service.analytics import get_completed_orders


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_completed_orders(filters)
	chart = get_chart(data)
	summary = get_summary(data)
	return columns, data, None, chart, summary


def get_columns():
	return [
		{
			"label": _("Service Order"),
			"fieldname": "service_order",
			"fieldtype": "Link",
			"options": "Service Order",
			"width": 150,
		},
		{
			"label": _("Vehicle"),
			"fieldname": "vehicle",
			"fieldtype": "Link",
			"options": "Service Vehicle",
			"width": 120,
		},
		{
			"label": _("Make / Model"),
			"fieldname": "vehicle_description",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Customer"),
			"fieldname": "customer_name",
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Link",
			"options": "Branch",
			"width": 120,
		},
		{
			"label": _("Service Advisor"),
			"fieldname": "service_advisor",
			"fieldtype": "Link",
			"options": "User",
			"width": 130,
		},
		{
			"label": _("Technician(s)"),
			"fieldname": "technicians",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Type"),
			"fieldname": "order_type",
			"fieldtype": "Data",
			"width": 100,
		},
		{
			"label": _("Checked In"),
			"fieldname": "checked_in_on",
			"fieldtype": "Datetime",
			"width": 140,
		},
		{
			"label": _("Work Started"),
			"fieldname": "work_started_on",
			"fieldtype": "Datetime",
			"width": 140,
		},
		{
			"label": _("Work Completed"),
			"fieldname": "work_completed_on",
			"fieldtype": "Datetime",
			"width": 140,
		},
		{
			"label": _("Turnaround (Hrs)"),
			"fieldname": "turnaround_hours",
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"label": _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Sales Invoice"),
			"fieldname": "sales_invoice",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 140,
		},
	]


def get_chart(data):
	if not data:
		return None

	branch_counts = {}
	for row in data:
		br = row.get("branch") or _("Unassigned")
		branch_counts[br] = branch_counts.get(br, 0) + 1

	return {
		"data": {
			"labels": list(branch_counts.keys()),
			"datasets": [{"name": _("Completed Orders"), "values": list(branch_counts.values())}],
		},
		"type": "bar",
		"colors": ["#2490ef"],
	}


def get_summary(data):
	if not data:
		return []

	total = len(data)
	avg_turnaround = round(sum(r.get("turnaround_hours", 0.0) for r in data) / total, 1) if total else 0.0
	invoiced_count = sum(1 for r in data if r.get("sales_invoice") or r.get("status") in ("Invoiced", "Delivered"))

	return [
		{"value": total, "label": _("Total Completed Orders"), "datatype": "Int"},
		{"value": avg_turnaround, "label": _("Avg Turnaround (Hours)"), "datatype": "Float"},
		{"value": invoiced_count, "label": _("Orders Invoiced"), "datatype": "Int"},
	]
