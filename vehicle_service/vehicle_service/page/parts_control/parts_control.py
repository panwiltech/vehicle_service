# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate, add_days
from vehicle_service.vehicle_service.doctype.service_order.service_order import (
	issue_parts_to_workshop,
	return_parts_from_workshop,
)


@frappe.whitelist()
def get_parts_control_board(filters=None):
	"""Returns real-time Parts Control board data across 4 tabs:
	1. To Issue (Approved orders needing parts picking)
	2. In Workshop / WIP (Parts currently in workshop bays)
	3. Substitutions Pending (Requested part substitutions)
	4. Stock Shortages (Parts with insufficient stock in stores)
	"""
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except Exception:
			filters = {}
	filters = filters or {}

	settings = frappe.get_cached_doc("Vehicle Service Settings")
	stores_wh = settings.parts_warehouse
	wip_wh = settings.wip_warehouse

	# 1. Fetch active orders
	orders = {
		o.name: o
		for o in frappe.get_all(
			"Service Order",
			filters={"status": ["not in", ["Delivered", "Cancelled"]]},
			fields=["name", "vehicle", "customer", "status", "priority", "current_location", "creation", "modified"],
		)
	}

	order_names = list(orders.keys())
	parts = []
	jobs = {}
	if order_names:
		parts = frappe.get_all(
			"Service Order Part",
			filters={"parent": ["in", order_names]},
			fields=[
				"name",
				"parent",
				"item_code",
				"item_name",
				"job",
				"category",
				"qty_required",
				"qty_issued",
				"qty_returned",
				"qty_used",
				"part_status",
				"approval_status",
				"rate",
				"material_request",
			],
		)
		job_docs = frappe.get_all(
			"Service Job",
			filters={"service_order": ["in", order_names]},
			fields=["name", "job_title", "technician", "status", "bay"],
		)
		jobs = {j.name: j for j in job_docs}

	# Stock balance lookup from Bin
	unique_items = list({p.item_code for p in parts if p.item_code})
	stock_map = {}
	if unique_items:
		bin_filters = {"item_code": ["in", unique_items]}
		if stores_wh:
			bin_filters["warehouse"] = stores_wh
		bins = frappe.get_all("Bin", filters=bin_filters, fields=["item_code", "actual_qty"])
		for b in bins:
			stock_map[b.item_code] = stock_map.get(b.item_code, 0.0) + flt(b.actual_qty)

	# Tab 1: To Issue
	to_issue = []
	for p in parts:
		o = orders.get(p.parent)
		if not o:
			continue
		# Only orders approved or in work
		if o.status in ["Draft", "Cancelled", "Delivered"]:
			continue

		needed = flt(p.qty_required) - (flt(p.qty_issued) - flt(p.qty_returned))
		if needed > 0:
			available = stock_map.get(p.item_code, 0.0)
			j = jobs.get(p.job)
			to_issue.append({
				"order": o.name,
				"customer": o.customer,
				"priority": o.priority,
				"part_row": p.name,
				"item_code": p.item_code,
				"item_name": p.item_name,
				"job_title": j.job_title if j else "—",
				"technician": j.technician if j else "—",
				"qty_required": flt(p.qty_required),
				"qty_issued": flt(p.qty_issued),
				"qty_remaining": needed,
				"stock_available": available,
				"is_shortage": available < needed,
			})

	# Tab 2: In Workshop (WIP)
	in_wip = []
	for p in parts:
		o = orders.get(p.parent)
		if not o:
			continue
		qty_wip = flt(p.qty_issued) - (flt(p.qty_returned) + flt(p.qty_used))
		if qty_wip > 0:
			j = jobs.get(p.job)
			in_wip.append({
				"order": o.name,
				"customer": o.customer,
				"bay": o.current_location or (j.bay if j else "—"),
				"part_row": p.name,
				"item_code": p.item_code,
				"item_name": p.item_name,
				"job_title": j.job_title if j else "—",
				"technician": j.technician if j else "—",
				"qty_issued": flt(p.qty_issued),
				"qty_returned": flt(p.qty_returned),
				"qty_used": flt(p.qty_used),
				"qty_in_wip": qty_wip,
			})

	# Tab 3: Substitutions Pending
	subs_docs = frappe.get_all(
		"Parts Substitution",
		filters={"status": "Requested"},
		fields=[
			"name",
			"service_order",
			"part_row",
			"original_item",
			"original_qty",
			"substitute_item",
			"qty",
			"reason",
			"requested_by",
			"creation",
		],
		order_by="creation desc",
	)
	substitutions = []
	for s in subs_docs:
		substitutions.append({
			"name": s.name,
			"service_order": s.service_order,
			"part_row": s.part_row,
			"original_item": s.original_item,
			"original_qty": flt(s.original_qty),
			"substitute_item": s.substitute_item,
			"qty": flt(s.qty),
			"reason": s.reason,
			"requested_by": s.requested_by,
			"stock_original": stock_map.get(s.original_item, 0.0),
			"stock_substitute": stock_map.get(s.substitute_item, 0.0),
		})

	# Tab 4: Stock Shortages (Aggregated by item across all orders)
	unfulfilled_by_item = {}
	for item in to_issue:
		code = item["item_code"]
		if code not in unfulfilled_by_item:
			unfulfilled_by_item[code] = {
				"item_code": code,
				"item_name": item["item_name"],
				"total_needed": 0.0,
				"orders": set(),
			}
		unfulfilled_by_item[code]["total_needed"] += item["qty_remaining"]
		unfulfilled_by_item[code]["orders"].add(item["order"])

	shortages = []
	for code, data in unfulfilled_by_item.items():
		avail = stock_map.get(code, 0.0)
		if avail < data["total_needed"]:
			shortages.append({
				"item_code": code,
				"item_name": data["item_name"],
				"total_required": data["total_needed"],
				"stock_available": avail,
				"shortfall": data["total_needed"] - avail,
				"orders_affected": list(data["orders"]),
			})

	# Summary KPIs
	kpis = {
		"lines_to_pick": len(to_issue),
		"lines_in_wip": len(in_wip),
		"pending_substitutions": len(substitutions),
		"critical_shortages": len(shortages),
		"total_stock_items": len(unique_items),
	}

	return {
		"kpis": kpis,
		"to_issue": to_issue,
		"in_wip": in_wip,
		"substitutions": substitutions,
		"shortages": shortages,
	}


@frappe.whitelist()
def quick_issue_part(order_name, part_row, qty):
	"""Issues part row to workshop WIP via Stock Entry."""
	return issue_parts_to_workshop(order_name, [{"part_row": part_row, "qty": flt(qty)}])


@frappe.whitelist()
def quick_return_part(order_name, part_row, qty):
	"""Returns part row from workshop WIP to Stores via Stock Entry."""
	return return_parts_from_workshop(order_name, [{"part_row": part_row, "qty": flt(qty)}])


@frappe.whitelist()
def approve_substitution(substitution_name, review_notes=None):
	"""Approves a substitution request and swaps item on Service Order."""
	sub = frappe.get_doc("Parts Substitution", substitution_name)
	if sub.status != "Requested":
		frappe.throw(_("Substitution is already {0}").format(sub.status))

	sub.status = "Approved"
	sub.reviewed_by = frappe.session.user
	sub.reviewed_on = now_datetime()
	sub.review_notes = review_notes or "Approved via Parts Control"
	sub.save()

	# Update Service Order part line
	order = frappe.get_doc("Service Order", sub.service_order)
	for p in order.parts:
		if p.name == sub.part_row:
			p.item_code = sub.substitute_item
			p.item_name = frappe.db.get_value("Item", sub.substitute_item, "item_name") or sub.substitute_item
			p.qty_required = sub.qty
			break
	order.save()

	return {"success": True, "message": _("Substitution approved successfully")}


@frappe.whitelist()
def create_shortage_material_request(item_code, qty, schedule_date=None):
	"""Creates a Material Request for purchase of shorted parts."""
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company")[0].name
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	stores_wh = settings.parts_warehouse or frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")

	uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
	required_date = schedule_date or add_days(nowdate(), 2)

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Purchase"
	mr.company = company
	mr.schedule_date = required_date
	mr.append(
		"items",
		{
			"item_code": item_code,
			"qty": flt(qty),
			"uom": uom,
			"warehouse": stores_wh,
			"schedule_date": required_date,
		},
	)
	mr.insert(ignore_permissions=True)

	return mr.name
