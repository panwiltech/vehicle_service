# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from vehicle_service.analytics import get_detailed_wip_data


def execute(filters=None):
	filters = filters or {}
	view_mode = filters.get("view_mode") or "Order Summary"
	wip_data = get_detailed_wip_data(filters)

	if view_mode == "Parts Details":
		columns = get_parts_columns()
		data = wip_data.get("parts_details", [])
		chart = None
		summary = get_parts_summary(data)
	elif view_mode == "Labour Details":
		columns = get_labour_columns()
		data = wip_data.get("labour_details", [])
		chart = None
		summary = get_labour_summary(data)
	elif view_mode == "Branch Reconciliation":
		columns = get_reconciliation_columns()
		data = wip_data.get("branch_reconciliation", [])
		chart = get_reconciliation_chart(data)
		summary = get_reconciliation_summary(data)
	else:
		# Default: Order Summary
		columns = get_order_columns()
		data = wip_data.get("orders", [])
		chart = get_order_chart(wip_data.get("aging_summary", {}))
		summary = get_order_summary(wip_data.get("summary", {}))

	return columns, data, None, chart, summary


def get_order_columns():
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
			"fieldname": "make_model",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"label": _("Customer"),
			"fieldname": "customer",
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
			"label": _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"label": _("Days in WIP"),
			"fieldname": "days_in_wip",
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"label": _("Aging Bucket"),
			"fieldname": "aging_bucket",
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"label": _("Parts WIP Cost"),
			"fieldname": "parts_wip_cost",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Labour WIP Cost"),
			"fieldname": "labour_wip_cost",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Sublet WIP Cost"),
			"fieldname": "sublet_wip_cost",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Total WIP Cost"),
			"fieldname": "total_wip_cost",
			"fieldtype": "Currency",
			"width": 140,
		},
	]


def get_parts_columns():
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
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Link",
			"options": "Branch",
			"width": 120,
		},
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 140,
		},
		{
			"label": _("Item Name"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Qty Issued"),
			"fieldname": "qty_issued",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("Qty Returned"),
			"fieldname": "qty_returned",
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"label": _("Net Consumed Qty"),
			"fieldname": "net_consumed_qty",
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"label": _("Unit Valuation Rate"),
			"fieldname": "unit_valuation_rate",
			"fieldtype": "Currency",
			"width": 140,
		},
		{
			"label": _("Total Parts Cost"),
			"fieldname": "total_parts_cost",
			"fieldtype": "Currency",
			"width": 140,
		},
	]


def get_labour_columns():
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
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Link",
			"options": "Branch",
			"width": 120,
		},
		{
			"label": _("Job Title"),
			"fieldname": "job_title",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Technician"),
			"fieldname": "technician",
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"label": _("Actual Hours"),
			"fieldname": "actual_hours",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Labour Cost Rate"),
			"fieldname": "labour_cost_rate",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Total Labour Cost"),
			"fieldname": "total_labour_cost",
			"fieldtype": "Currency",
			"width": 140,
		},
	]


def get_reconciliation_columns():
	return [
		{
			"label": _("Branch"),
			"fieldname": "branch",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("WIP Warehouse"),
			"fieldname": "wip_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"width": 180,
		},
		{
			"label": _("Operational Parts WIP"),
			"fieldname": "operational_parts_wip",
			"fieldtype": "Currency",
			"width": 160,
		},
		{
			"label": _("Warehouse Stock Valuation"),
			"fieldname": "warehouse_stock_valuation",
			"fieldtype": "Currency",
			"width": 180,
		},
		{
			"label": _("Variance"),
			"fieldname": "variance",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Status"),
			"fieldname": "status",
			"fieldtype": "Data",
			"width": 140,
		},
	]


def get_order_chart(aging_summary):
	labels = ["0-7 Days", "8-14 Days", "15-30 Days", "30+ Days"]
	values = [aging_summary.get(k, 0) for k in labels]
	return {
		"data": {
			"labels": labels,
			"datasets": [{"name": _("Active Orders"), "values": values}],
		},
		"type": "bar",
		"colors": ["#28a745", "#ffc107", "#fd7e14", "#dc3545"],
	}


def get_reconciliation_chart(data):
	if not data:
		return None
	labels = [r["branch"] for r in data]
	ops = [r["operational_parts_wip"] for r in data]
	gl = [r["warehouse_stock_valuation"] for r in data]
	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Operational Parts WIP"), "values": ops},
				{"name": _("Warehouse Valuation"), "values": gl},
			],
		},
		"type": "bar",
		"colors": ["#17a2b8", "#6f42c1"],
	}


def get_order_summary(summary):
	return [
		{"value": summary.get("total_orders", 0), "label": _("Active WIP Orders"), "datatype": "Int"},
		{"value": summary.get("total_parts_wip", 0.0), "label": _("Total Parts WIP"), "datatype": "Currency"},
		{"value": summary.get("total_labour_wip", 0.0), "label": _("Total Labour WIP"), "datatype": "Currency"},
		{"value": summary.get("total_sublet_wip", 0.0), "label": _("Total Sublet WIP"), "datatype": "Currency"},
		{"value": summary.get("total_wip", 0.0), "label": _("Total WIP Valuation"), "datatype": "Currency"},
	]


def get_parts_summary(data):
	total_cost = sum(r.get("total_parts_cost", 0.0) for r in data)
	return [
		{"value": len(data), "label": _("Parts Line Items"), "datatype": "Int"},
		{"value": round(total_cost, 2), "label": _("Total Parts WIP Value"), "datatype": "Currency"},
	]


def get_labour_summary(data):
	total_cost = sum(r.get("total_labour_cost", 0.0) for r in data)
	total_hours = sum(r.get("actual_hours", 0.0) for r in data)
	return [
		{"value": round(total_hours, 2), "label": _("Total Actual Hours Logged"), "datatype": "Float"},
		{"value": round(total_cost, 2), "label": _("Total Labour WIP Value"), "datatype": "Currency"},
	]


def get_reconciliation_summary(data):
	total_ops = sum(r.get("operational_parts_wip", 0.0) for r in data)
	total_wh = sum(r.get("warehouse_stock_valuation", 0.0) for r in data)
	total_var = sum(r.get("variance", 0.0) for r in data)
	return [
		{"value": round(total_ops, 2), "label": _("Total Operational Parts"), "datatype": "Currency"},
		{"value": round(total_wh, 2), "label": _("Total Warehouse Valuation"), "datatype": "Currency"},
		{"value": round(total_var, 2), "label": _("Net Variance"), "datatype": "Currency"},
	]
