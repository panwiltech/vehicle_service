# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
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
			"width": 140,
		},
		{
			"label": _("Technician Name"),
			"fieldname": "technician_name",
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"label": _("Assigned"),
			"fieldname": "jobs_assigned",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("Completed"),
			"fieldname": "jobs_completed",
			"fieldtype": "Int",
			"width": 110,
		},
		{
			"label": _("Est Hours"),
			"fieldname": "total_estimated_hours",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Act Hours"),
			"fieldname": "total_actual_hours",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Variance Hours"),
			"fieldname": "variance_hours",
			"fieldtype": "Float",
			"width": 120,
		},
		{
			"label": _("Efficiency Rate %"),
			"fieldname": "efficiency_rate",
			"fieldtype": "Percent",
			"width": 130,
		},
		{
			"label": _("QC Reworks"),
			"fieldname": "qc_fails",
			"fieldtype": "Int",
			"width": 110,
		},
	]


def get_data(filters):
	job_filters = {"status": ["not in", ["Cancelled"]]}
	if filters.get("technician"):
		job_filters["technician"] = filters.get("technician")
	if filters.get("from_date") and filters.get("to_date"):
		job_filters["creation"] = ["between", [filters.get("from_date"), filters.get("to_date") + " 23:59:59"]]

	jobs = frappe.get_all(
		"Service Job",
		filters=job_filters,
		fields=[
			"name",
			"technician",
			"technician_name",
			"status",
			"estimated_hours",
			"actual_hours",
			"qc_fail_reason",
		],
	)

	if not jobs:
		return []

	# Group by technician
	by_tech = {}
	for j in jobs:
		tech = j.technician or "Unassigned"
		name = j.technician_name or tech
		if tech not in by_tech:
			by_tech[tech] = {
				"technician": tech if tech != "Unassigned" else None,
				"technician_name": name,
				"jobs_assigned": 0,
				"jobs_completed": 0,
				"total_estimated_hours": 0.0,
				"total_actual_hours": 0.0,
				"qc_fails": 0,
			}
		by_tech[tech]["jobs_assigned"] += 1
		if j.status == "Completed":
			by_tech[tech]["jobs_completed"] += 1
		by_tech[tech]["total_estimated_hours"] += flt(j.estimated_hours)
		by_tech[tech]["total_actual_hours"] += flt(j.actual_hours)
		if j.qc_fail_reason or j.status == "QC Failed":
			by_tech[tech]["qc_fails"] += 1

	data = []
	for tech, stats in by_tech.items():
		est = round(stats["total_estimated_hours"], 2)
		act = round(stats["total_actual_hours"], 2)
		var = round(act - est, 2)
		eff = round((est / act * 100.0), 1) if act > 0 else 0.0

		data.append({
			"technician": stats["technician"],
			"technician_name": stats["technician_name"],
			"jobs_assigned": stats["jobs_assigned"],
			"jobs_completed": stats["jobs_completed"],
			"total_estimated_hours": est,
			"total_actual_hours": act,
			"variance_hours": var,
			"efficiency_rate": eff,
			"qc_fails": stats["qc_fails"],
		})

	data.sort(key=lambda x: x["efficiency_rate"], reverse=True)
	return data


def get_chart(data):
	if not data:
		return None

	labels = [d["technician_name"] for d in data[:8]]
	eff_data = [d["efficiency_rate"] for d in data[:8]]

	return {
		"data": {
			"labels": labels,
			"datasets": [{"name": _("Efficiency Rate %"), "values": eff_data}],
		},
		"type": "bar",
	}


def get_summary(data):
	if not data:
		return []

	total_techs = len(data)
	total_completed = sum(d["jobs_completed"] for d in data)
	total_actual = sum(d["total_actual_hours"] for d in data)
	total_est = sum(d["total_estimated_hours"] for d in data)
	avg_eff = round((total_est / total_actual * 100.0), 1) if total_actual > 0 else 0.0

	return [
		{"value": total_techs, "label": _("Active Technicians"), "datatype": "Int"},
		{"value": total_completed, "label": _("Total Jobs Completed"), "datatype": "Int"},
		{"value": total_actual, "label": _("Total Clocked Hours"), "datatype": "Float"},
		{"value": avg_eff, "label": _("Average Efficiency"), "datatype": "Percent", "indicator": "Green" if avg_eff >= 90 else "Orange"},
	]
