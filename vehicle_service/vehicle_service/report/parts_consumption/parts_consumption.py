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
			"label": _("Qty Required"),
			"fieldname": "qty_required",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Qty Issued"),
			"fieldname": "qty_issued",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Qty Returned"),
			"fieldname": "qty_returned",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Qty Consumed"),
			"fieldname": "qty_used",
			"fieldtype": "Float",
			"width": 110,
		},
		{
			"label": _("Return Rate %"),
			"fieldname": "return_rate_pct",
			"fieldtype": "Percent",
			"width": 120,
		},
		{
			"label": _("Unit Rate ($)"),
			"fieldname": "rate",
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"label": _("Net Consumed ($)"),
			"fieldname": "net_consumed_amount",
			"fieldtype": "Currency",
			"width": 130,
		},
	]


def get_data(filters):
	part_filters = {}
	if filters.get("item_code"):
		part_filters["item_code"] = filters.get("item_code")
	if filters.get("from_date") and filters.get("to_date"):
		part_filters["creation"] = ["between", [filters.get("from_date"), filters.get("to_date") + " 23:59:59"]]

	parts = frappe.get_all(
		"Service Order Part",
		filters=part_filters,
		fields=[
			"item_code",
			"item_name",
			"qty_required",
			"qty_issued",
			"qty_returned",
			"qty_used",
			"rate",
		],
	)

	if not parts:
		return []

	# Group by item_code
	by_item = {}
	for p in parts:
		code = p.item_code
		if not code:
			continue
		if code not in by_item:
			by_item[code] = {
				"item_code": code,
				"item_name": p.item_name or code,
				"qty_required": 0.0,
				"qty_issued": 0.0,
				"qty_returned": 0.0,
				"qty_used": 0.0,
				"rate": flt(p.rate),
			}
		by_item[code]["qty_required"] += flt(p.qty_required)
		by_item[code]["qty_issued"] += flt(p.qty_issued)
		by_item[code]["qty_returned"] += flt(p.qty_returned)
		by_item[code]["qty_used"] += flt(p.qty_used)
		if flt(p.rate) > 0:
			by_item[code]["rate"] = flt(p.rate)

	data = []
	for code, d in by_item.items():
		issued = d["qty_issued"]
		returned = d["qty_returned"]
		used = d["qty_used"]
		rate = d["rate"]
		ret_pct = round((returned / issued * 100.0), 1) if issued > 0 else 0.0
		net_amount = round(used * rate, 2)

		data.append({
			"item_code": code,
			"item_name": d["item_name"],
			"qty_required": round(d["qty_required"], 2),
			"qty_issued": round(issued, 2),
			"qty_returned": round(returned, 2),
			"qty_used": round(used, 2),
			"return_rate_pct": ret_pct,
			"rate": rate,
			"net_consumed_amount": net_amount,
		})

	data.sort(key=lambda x: x["net_consumed_amount"], reverse=True)
	return data


def get_chart(data):
	if not data:
		return None

	top = data[:5]
	labels = [d["item_code"] for d in top]
	values = [d["net_consumed_amount"] for d in top]

	return {
		"data": {
			"labels": labels,
			"datasets": [{"name": _("Net Consumed ($)"), "values": values}],
		},
		"type": "bar",
	}


def get_summary(data):
	if not data:
		return []

	total_items = len(data)
	total_issued = sum(d["qty_issued"] for d in data)
	total_consumed = sum(d["qty_used"] for d in data)
	total_consumed_value = round(sum(d["net_consumed_amount"] for d in data), 2)

	return [
		{"value": total_items, "label": _("Distinct Parts Used"), "datatype": "Int"},
		{"value": total_issued, "label": _("Total Units Issued"), "datatype": "Float"},
		{"value": total_consumed, "label": _("Total Units Consumed"), "datatype": "Float"},
		{"value": total_consumed_value, "label": _("Net Consumed Value"), "datatype": "Currency"},
	]
