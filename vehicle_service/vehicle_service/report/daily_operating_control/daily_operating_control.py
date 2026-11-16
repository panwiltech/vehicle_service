# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from vehicle_service.analytics import get_doc_daily_breakdown, get_doc_summary


def execute(filters=None):
	filters = filters or {}
	view_mode = filters.get("view_mode") or "Daily Operating Trend"

	if view_mode == "Executive Summary":
		columns = get_executive_columns()
		data = get_executive_data(filters)
		chart = get_executive_chart(filters)
		summary = get_executive_summary_cards(filters)
	else:
		# Default: Daily Operating Trend
		columns = get_trend_columns()
		data = get_doc_daily_breakdown(filters)
		chart = get_trend_chart(data)
		summary = get_trend_summary_cards(data)

	return columns, data, None, chart, summary


def get_trend_columns():
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
			"width": 120,
		},
		{
			"label": _("Completed Orders"),
			"fieldname": "orders_completed",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"label": _("Avg Turnaround (Hrs)"),
			"fieldname": "avg_turnaround_hours",
			"fieldtype": "Float",
			"width": 130,
		},
		{
			"label": _("Parts Revenue"),
			"fieldname": "parts_revenue",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Parts GP"),
			"fieldname": "parts_gross_profit",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Labour Units (Hrs)"),
			"fieldname": "labour_sold_units",
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
			"label": _("Labour GP"),
			"fieldname": "labour_gross_profit",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Total Revenue"),
			"fieldname": "total_revenue",
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"label": _("Total GP"),
			"fieldname": "total_gross_profit",
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"label": _("Margin %"),
			"fieldname": "overall_gp_percent",
			"fieldtype": "Percent",
			"width": 100,
		},
	]


def get_executive_columns():
	return [
		{
			"label": _("Department / Category"),
			"fieldname": "category",
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"label": _("Performance Metric"),
			"fieldname": "metric",
			"fieldtype": "Data",
			"width": 240,
		},
		{
			"label": _("Period Actual"),
			"fieldname": "value",
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"label": _("Management Notes"),
			"fieldname": "notes",
			"fieldtype": "Data",
			"width": 220,
		},
	]


def get_executive_data(filters):
	summary = get_doc_summary(filters)
	fmt_curr = lambda val: frappe.format_value(val, {"fieldtype": "Currency"})

	return [
		# 1. Volume
		{
			"category": _("Workshop Volume"),
			"metric": _("Completed Service Orders"),
			"value": str(summary["volume"]["completed_orders"]),
			"notes": _("Quality inspection passed & ready for billing"),
		},
		{
			"category": _("Workshop Volume"),
			"metric": _("Average Turnaround Time"),
			"value": f"{summary['volume']['avg_turnaround_hours']} Hrs",
			"notes": _("Duration from intake/start to completion"),
		},
		# 2. Parts
		{
			"category": _("Parts Department"),
			"metric": _("Parts Net Sales Revenue"),
			"value": fmt_curr(summary["parts"]["revenue"]),
			"notes": _("Workshop repair orders & retail sales"),
		},
		{
			"category": _("Parts Department"),
			"metric": _("Cost of Goods Sold (COGS)"),
			"value": fmt_curr(summary["parts"]["cogs"]),
			"notes": _("Valuation cost from inventory ledger"),
		},
		{
			"category": _("Parts Department"),
			"metric": _("Parts Gross Profit"),
			"value": fmt_curr(summary["parts"]["gross_profit"]),
			"notes": f"{summary['parts']['gp_percent']}% " + _("gross margin"),
		},
		# 3. Labour
		{
			"category": _("Labour Department"),
			"metric": _("Labour Units Sold (Flat-Rate Hours)"),
			"value": f"{summary['labour']['sold_units']} Hrs",
			"notes": _("Billed customer standard hours"),
		},
		{
			"category": _("Labour Department"),
			"metric": _("Technician Clocked Actual Hours"),
			"value": f"{summary['labour']['actual_hours']} Hrs",
			"notes": _("Actual wrench time logged by mechanics"),
		},
		{
			"category": _("Labour Department"),
			"metric": _("Labour Sales Revenue"),
			"value": fmt_curr(summary["labour"]["revenue"]),
			"notes": _("Billed labour charges"),
		},
		{
			"category": _("Labour Department"),
			"metric": _("Internal Technician Labour Cost"),
			"value": fmt_curr(summary["labour"]["cost"]),
			"notes": _("Direct tech payroll cost burden"),
		},
		{
			"category": _("Labour Department"),
			"metric": _("Labour Gross Profit"),
			"value": fmt_curr(summary["labour"]["gross_profit"]),
			"notes": f"{summary['labour']['gp_percent']}% " + _("gross margin"),
		},
		# 4. Total
		{
			"category": _("Combined Workshop Total"),
			"metric": _("Total Department Revenue"),
			"value": fmt_curr(summary["department_total"]["total_revenue"]),
			"notes": _("Parts revenue + Labour revenue"),
		},
		{
			"category": _("Combined Workshop Total"),
			"metric": _("Total Gross Profit Margin"),
			"value": fmt_curr(summary["department_total"]["total_gross_profit"]),
			"notes": f"{summary['department_total']['overall_gp_percent']}% " + _("combined gross margin"),
		},
		# 5. WIP
		{
			"category": _("Balance Sheet WIP"),
			"metric": _("Active Work-in-Progress Orders"),
			"value": str(summary["wip_snapshot"]["total_orders"]),
			"notes": _("Repairs currently open in workshop"),
		},
		{
			"category": _("Balance Sheet WIP"),
			"metric": _("Total Work-in-Progress Valuation"),
			"value": fmt_curr(summary["wip_snapshot"]["total_wip"]),
			"notes": _("Parts consumed + Labour unbilled"),
		},
	]


def get_trend_chart(data):
	if not data:
		return None

	labels = [r["date"] for r in data]
	rev = [float(r.get("total_revenue", 0.0)) for r in data]
	gp = [float(r.get("total_gross_profit", 0.0)) for r in data]

	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": _("Total Revenue"), "values": rev},
				{"name": _("Total Gross Profit"), "values": gp},
			],
		},
		"type": "bar",
		"colors": ["#17a2b8", "#28a745"],
	}


def get_executive_chart(filters):
	summary = get_doc_summary(filters)
	return {
		"data": {
			"labels": [_("Parts Revenue"), _("Labour Revenue"), _("Parts GP"), _("Labour GP")],
			"datasets": [
				{
					"name": _("Department Breakdown"),
					"values": [
						summary["parts"]["revenue"],
						summary["labour"]["revenue"],
						summary["parts"]["gross_profit"],
						summary["labour"]["gross_profit"],
					],
				}
			],
		},
		"type": "bar",
		"colors": ["#007bff", "#6610f2", "#28a745", "#20c997"],
	}


def get_trend_summary_cards(data):
	if not data:
		return []

	total_rev = sum(float(r.get("total_revenue", 0.0)) for r in data)
	total_gp = sum(float(r.get("total_gross_profit", 0.0)) for r in data)
	total_orders = sum(int(r.get("orders_completed", 0)) for r in data)
	margin = round((total_gp / total_rev * 100.0), 1) if total_rev > 0 else 0.0

	return [
		{"value": round(total_rev, 2), "label": _("Total DOC Revenue"), "datatype": "Currency"},
		{"value": round(total_gp, 2), "label": _("Total Gross Profit"), "datatype": "Currency"},
		{"value": total_orders, "label": _("Total Completed Orders"), "datatype": "Int"},
		{"value": margin, "label": _("Overall Margin %"), "datatype": "Percent"},
	]


def get_executive_summary_cards(filters):
	summary = get_doc_summary(filters)
	return [
		{"value": summary["department_total"]["total_revenue"], "label": _("Period Total Revenue"), "datatype": "Currency"},
		{"value": summary["department_total"]["total_gross_profit"], "label": _("Period Gross Profit"), "datatype": "Currency"},
		{"value": summary["department_total"]["overall_gp_percent"], "label": _("Overall Gross Margin %"), "datatype": "Percent"},
		{"value": summary["wip_snapshot"]["total_wip"], "label": _("Current Active WIP Value"), "datatype": "Currency"},
	]
