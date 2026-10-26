# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from vehicle_service.analytics import get_parts_sales


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_parts_sales(filters)
	chart = get_chart(data)
	summary = get_summary(data)
	return columns, data, None, chart, summary


def get_columns():
	return [
		{
			"label": _("Invoice Number"),
			"fieldname": "invoice_number",
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 140,
		},
		{
			"label": _("Posting Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 110,
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
			"label": _("Sale Type"),
			"fieldname": "sale_type",
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"label": _("Item Code"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 130,
		},
		{
			"label": _("Item Name"),
			"fieldname": "item_name",
			"fieldtype": "Data",
			"width": 170,
		},
		{
			"label": _("Qty"),
			"fieldname": "qty",
			"fieldtype": "Float",
			"width": 80,
		},
		{
			"label": _("Selling Rate"),
			"fieldname": "rate",
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"label": _("Net Sales"),
			"fieldname": "net_sales",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Unit Cost (COGS)"),
			"fieldname": "unit_cost",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Total COGS"),
			"fieldname": "cogs",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Gross Profit"),
			"fieldname": "gross_profit",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Margin %"),
			"fieldname": "gp_percent",
			"fieldtype": "Percent",
			"width": 90,
		},
	]


def get_chart(data):
	if not data:
		return None

	types = [_("Workshop Repair"), _("Over-the-Counter")]
	sales_by_type = {t: 0.0 for t in types}
	gp_by_type = {t: 0.0 for t in types}

	for row in data:
		st = row.get("sale_type")
		if st in sales_by_type:
			sales_by_type[st] += float(row.get("net_sales", 0.0))
			gp_by_type[st] += float(row.get("gross_profit", 0.0))

	return {
		"data": {
			"labels": types,
			"datasets": [
				{"name": _("Net Sales"), "values": [round(sales_by_type[t], 2) for t in types]},
				{"name": _("Gross Profit"), "values": [round(gp_by_type[t], 2) for t in types]},
			],
		},
		"type": "bar",
		"colors": ["#17a2b8", "#28a745"],
	}


def get_summary(data):
	if not data:
		return []

	total_sales = sum(float(r.get("net_sales", 0.0)) for r in data)
	total_cogs = sum(float(r.get("cogs", 0.0)) for r in data)
	total_gp = sum(float(r.get("gross_profit", 0.0)) for r in data)
	overall_margin = round((total_gp / total_sales * 100.0), 1) if total_sales > 0 else 0.0

	return [
		{"value": round(total_sales, 2), "label": _("Total Net Parts Sales"), "datatype": "Currency"},
		{"value": round(total_cogs, 2), "label": _("Total COGS"), "datatype": "Currency"},
		{"value": round(total_gp, 2), "label": _("Total Gross Profit"), "datatype": "Currency"},
		{"value": overall_margin, "label": _("Overall Parts Margin %"), "datatype": "Percent"},
	]
