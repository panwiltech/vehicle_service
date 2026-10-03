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
			"label": _("Service Order"),
			"fieldname": "service_order",
			"fieldtype": "Link",
			"options": "Service Order",
			"width": 140,
		},
		{
			"label": _("Vehicle"),
			"fieldname": "vehicle",
			"fieldtype": "Link",
			"options": "Service Vehicle",
			"width": 120,
		},
		{
			"label": _("Customer"),
			"fieldname": "customer",
			"fieldtype": "Link",
			"options": "Customer",
			"width": 160,
		},
		{
			"label": _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"label": _("Est Hours"),
			"fieldname": "estimated_hours",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("Act Hours"),
			"fieldname": "actual_hours",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("Variance Hours"),
			"fieldname": "variance_hours",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Est Parts ($)"),
			"fieldname": "estimated_parts_amount",
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"label": _("Act Parts ($)"),
			"fieldname": "actual_parts_amount",
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"label": _("Parts Variance ($)"),
			"fieldname": "parts_variance",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Labour Efficiency %"),
			"fieldname": "efficiency_pct",
			"fieldtype": "Percent",
			"width": 130,
		},
	]


def get_data(filters):
	order_filters = {}
	if filters.get("customer"):
		order_filters["customer"] = filters.get("customer")
	if filters.get("status"):
		order_filters["status"] = filters.get("status")
	if filters.get("from_date") and filters.get("to_date"):
		order_filters["creation"] = ["between", [filters.get("from_date"), filters.get("to_date") + " 23:59:59"]]

	orders = frappe.get_all(
		"Service Order",
		filters=order_filters,
		fields=["name", "vehicle", "customer", "status"],
		order_by="creation desc",
	)

	if not orders:
		return []

	order_names = [o.name for o in orders]

	# Fetch jobs
	jobs = frappe.get_all(
		"Service Job",
		filters={"service_order": ["in", order_names], "status": ["not in", ["Cancelled"]]},
		fields=["service_order", "estimated_hours", "actual_hours"],
	)
	jobs_by_order = {}
	for j in jobs:
		jobs_by_order.setdefault(j.service_order, []).append(j)

	# Fetch parts
	parts = frappe.get_all(
		"Service Order Part",
		filters={"parent": ["in", order_names]},
		fields=["parent", "qty_required", "qty_used", "rate"],
	)
	parts_by_order = {}
	for p in parts:
		parts_by_order.setdefault(p.parent, []).append(p)

	data = []
	for o in orders:
		o_jobs = jobs_by_order.get(o.name, [])
		o_parts = parts_by_order.get(o.name, [])

		est_hours = round(sum(flt(j.estimated_hours) for j in o_jobs), 2)
		act_hours = round(sum(flt(j.actual_hours) for j in o_jobs), 2)
		var_hours = round(act_hours - est_hours, 2)

		est_parts_amt = round(sum(flt(p.qty_required) * flt(p.rate) for p in o_parts), 2)
		act_parts_amt = round(sum(flt(p.qty_used) * flt(p.rate) for p in o_parts), 2)
		var_parts_amt = round(act_parts_amt - est_parts_amt, 2)

		eff_pct = round((est_hours / act_hours * 100.0), 1) if act_hours > 0 else 100.0

		data.append({
			"service_order": o.name,
			"vehicle": o.vehicle,
			"customer": o.customer,
			"status": o.status,
			"estimated_hours": est_hours,
			"actual_hours": act_hours,
			"variance_hours": var_hours,
			"estimated_parts_amount": est_parts_amt,
			"actual_parts_amount": act_parts_amt,
			"parts_variance": var_parts_amt,
			"efficiency_pct": eff_pct,
		})

	return data


def get_chart(data):
	if not data:
		return None

	labels = [d["service_order"] for d in data[:8]]
	est_data = [d["estimated_hours"] for d in data[:8]]
	act_data = [d["actual_hours"] for d in data[:8]]

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Estimated Hours"), "values": est_data},
				{"name": _("Actual Hours"), "values": act_data},
			],
		},
		"type": "bar",
	}


def get_summary(data):
	if not data:
		return []

	total_orders = len(data)
	total_est_hours = sum(d["estimated_hours"] for d in data)
	total_act_hours = sum(d["actual_hours"] for d in data)
	avg_efficiency = round((total_est_hours / total_act_hours * 100.0), 1) if total_act_hours > 0 else 100.0

	return [
		{"value": total_orders, "label": _("Total Orders Evaluated"), "datatype": "Int"},
		{"value": total_est_hours, "label": _("Total Est Hours"), "datatype": "Float"},
		{"value": total_act_hours, "label": _("Total Act Hours"), "datatype": "Float"},
		{"value": avg_efficiency, "label": _("Overall Labour Efficiency"), "datatype": "Percent", "indicator": "Green" if avg_efficiency >= 100 else "Orange"},
	]
