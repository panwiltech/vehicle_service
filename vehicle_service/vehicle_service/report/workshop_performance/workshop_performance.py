# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, time_diff_in_hours


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
			"label": _("Order Type"),
			"fieldname": "order_type",
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"label": _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"label": _("Checked In"),
			"fieldname": "checked_in_on",
			"fieldtype": "Datetime",
			"width": 140,
		},
		{
			"label": _("Delivered"),
			"fieldname": "delivered_on",
			"fieldtype": "Datetime",
			"width": 140,
		},
		{
			"label": _("Turnaround (Days)"),
			"fieldname": "turnaround_days",
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"label": _("On Hold"),
			"fieldname": "on_hold",
			"fieldtype": "Check",
			"width": 80,
		},
		{
			"label": _("Revenue ($)"),
			"fieldname": "revenue",
			"fieldtype": "Currency",
			"width": 120,
		},
	]


def get_data(filters):
	order_filters = {}
	if filters.get("status"):
		order_filters["status"] = filters.get("status")
	if filters.get("from_date") and filters.get("to_date"):
		order_filters["creation"] = ["between", [filters.get("from_date"), filters.get("to_date") + " 23:59:59"]]

	orders = frappe.get_all(
		"Service Order",
		filters=order_filters,
		fields=[
			"name",
			"vehicle",
			"customer",
			"order_type",
			"status",
			"checked_in_on",
			"delivered_on",
			"creation",
			"on_hold",
			"sales_invoice",
		],
		order_by="creation desc",
	)

	if not orders:
		return []

	# Get invoice revenues if linked
	invoices = {}
	inv_names = [o.sales_invoice for o in orders if o.sales_invoice]
	if inv_names:
		inv_docs = frappe.get_all("Sales Invoice", filters={"name": ["in", inv_names]}, fields=["name", "grand_total"])
		invoices = {i.name: flt(i.grand_total) for i in inv_docs}

	now = now_datetime()
	data = []
	for o in orders:
		start = o.checked_in_on or o.creation
		end = o.delivered_on or now
		diff_hours = time_diff_in_hours(end, start)
		turnaround_days = round(diff_hours / 24.0, 1)

		revenue = invoices.get(o.sales_invoice, 0.0)

		data.append({
			"service_order": o.name,
			"vehicle": o.vehicle,
			"customer": o.customer,
			"order_type": o.order_type or "Regular",
			"status": o.status,
			"checked_in_on": o.checked_in_on,
			"delivered_on": o.delivered_on,
			"turnaround_days": turnaround_days,
			"on_hold": 1 if o.on_hold else 0,
			"revenue": revenue,
		})

	return data


def get_chart(data):
	if not data:
		return None

	status_counts = {}
	for d in data:
		st = d["status"]
		status_counts[st] = status_counts.get(st, 0) + 1

	return {
		"data": {
			"labels": list(status_counts.keys()),
			"datasets": [{"name": _("Orders"), "values": list(status_counts.values())}],
		},
		"type": "donut",
	}


def get_summary(data):
	if not data:
		return []

	total = len(data)
	completed = sum(1 for d in data if d["status"] in ["Delivered", "Ready for Collection", "Invoiced"])
	delivered = [d["turnaround_days"] for d in data if d["delivered_on"]]
	avg_turnaround = round(sum(delivered) / len(delivered), 1) if delivered else 0.0
	total_rev = round(sum(d["revenue"] for d in data), 2)

	return [
		{"value": total, "label": _("Total Vehicles Processed"), "datatype": "Int"},
		{"value": completed, "label": _("Completed Throughput"), "datatype": "Int"},
		{"value": avg_turnaround, "label": _("Avg Turnaround Days"), "datatype": "Float"},
		{"value": total_rev, "label": _("Total Revenue Billed"), "datatype": "Currency"},
	]
