# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from vehicle_service.analytics import get_technician_labour_units


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_technician_labour_units(filters)
	chart = get_chart(data)
	summary = get_summary(data)
	return columns, data, None, chart, summary


def get_columns():
	return [
		{
			"label": _("Technician ID"),
			"fieldname": "technician",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 130,
		},
		{
			"label": _("Technician Name"),
			"fieldname": "technician_name",
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
			"label": _("Jobs Completed"),
			"fieldname": "jobs_completed",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Sold Units (Hrs)"),
			"fieldname": "sold_units",
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"label": _("Labour Revenue"),
			"fieldname": "labour_revenue",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Actual Hours"),
			"fieldname": "actual_hours",
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"label": _("Internal Cost"),
			"fieldname": "labour_cost",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Gross Profit"),
			"fieldname": "gross_profit",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Efficiency Rate"),
			"fieldname": "efficiency_rate",
			"fieldtype": "Percent",
			"width": 120,
		},
	]


def get_chart(data):
	if not data:
		return None

	labels = [r.get("technician_name") or r.get("technician") for r in data[:10]]
	sold = [float(r.get("sold_units", 0.0)) for r in data[:10]]
	actual = [float(r.get("actual_hours", 0.0)) for r in data[:10]]

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Sold Units (Hrs)"), "values": sold},
				{"name": _("Actual Hours Logged"), "values": actual},
			],
		},
		"type": "bar",
		"colors": ["#2490ef", "#fd7e14"],
	}


def get_summary(data):
	if not data:
		return []

	total_jobs = sum(int(r.get("jobs_completed", 0)) for r in data)
	total_sold = sum(float(r.get("sold_units", 0.0)) for r in data)
	total_rev = sum(float(r.get("labour_revenue", 0.0)) for r in data)
	total_actual = sum(float(r.get("actual_hours", 0.0)) for r in data)
	total_cost = sum(float(r.get("labour_cost", 0.0)) for r in data)
	avg_eff = round((total_sold / total_actual * 100.0), 1) if total_actual > 0 else 0.0

	return [
		{"value": total_jobs, "label": _("Total Jobs Completed"), "datatype": "Int"},
		{"value": round(total_sold, 2), "label": _("Total Sold Units (Hrs)"), "datatype": "Float"},
		{"value": round(total_rev, 2), "label": _("Total Labour Revenue"), "datatype": "Currency"},
		{"value": round(total_actual, 2), "label": _("Total Actual Hours"), "datatype": "Float"},
		{"value": avg_eff, "label": _("Average Efficiency Rate %"), "datatype": "Percent"},
	]
