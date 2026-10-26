# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

"""Central Authoritative Analytics & Calculation Engine for Vehicle Service.

Implements consistent, reusable calculation rules for:
1. Completed Service Orders & Daily Throughput
2. Multi-Branch Work-In-Progress (WIP) Valuation (Parts Stock Cost + Labour Internal Cost)
3. Multi-Technician Labour Units Sold Attribution (Job-level isolation & time log allocation)
4. Parts Sales & Margins (Workshop vs OTC)
5. Daily Operating Control (DOC) Executive Performance Metrics
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional
import frappe
from frappe import _
from frappe.utils import (
	cint,
	date_diff,
	flt,
	getdate,
	now_datetime,
	nowdate,
	time_diff_in_hours,
)


def get_default_labour_cost_rate() -> float:
	"""Fetches the internal hourly labour cost rate from Vehicle Service Settings."""
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	return flt(getattr(settings, "default_labour_cost_rate", None)) or 40.0


def get_labour_cost_rate_subquery(technician_expr: str = "sj.technician") -> str:
	"""Safely constructs SQL expression for technician hourly cost rate, falling back to %(default_rate)s."""
	try:
		if frappe.db and frappe.db.has_column("Employee", "custom_hourly_cost_rate"):
			return f"COALESCE((SELECT custom_hourly_cost_rate FROM `tabEmployee` WHERE name = {technician_expr}), %(default_rate)s)"
	except Exception:
		pass
	return "%(default_rate)s"


def get_technician_hourly_cost(emp_id: Optional[str] = None) -> float:
	"""Safely fetches technician cost rate, falling back to default_labour_cost_rate."""
	default_rate = get_default_labour_cost_rate()
	if not emp_id:
		return default_rate
	try:
		if frappe.db and frappe.db.has_column("Employee", "custom_hourly_cost_rate"):
			val = frappe.db.get_value("Employee", emp_id, "custom_hourly_cost_rate")
			if val:
				return flt(val)
	except Exception:
		pass
	return default_rate


def resolve_branch_warehouses(branch: Optional[str] = None) -> Dict[str, Any]:
	"""Returns the stores and WIP warehouses mapped to a branch."""
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	default_stores = settings.parts_warehouse
	default_wip = settings.wip_warehouse

	if not branch:
		return {"stores_warehouse": default_stores, "wip_warehouse": default_wip, "cost_center": None}

	for mapping in getattr(settings, "branch_warehouses", []):
		if mapping.branch == branch:
			return {
				"stores_warehouse": mapping.stores_warehouse or default_stores,
				"wip_warehouse": mapping.wip_warehouse or default_wip,
				"cost_center": mapping.cost_center,
			}

	return {"stores_warehouse": default_stores, "wip_warehouse": default_wip, "cost_center": None}


def enforce_branch_permission(filters: Dict[str, Any]) -> Dict[str, Any]:
	"""Enforces server-side branch restriction if the user lacks company-wide managerial rights."""
	filters = filters or {}
	user = frappe.session.user
	if not user or user == "Administrator":
		return filters

	roles = set(frappe.get_roles(user))
	is_manager = bool(roles & {"System Manager", "Service Manager", "Accounts Manager"})

	if not is_manager:
		user_branch = frappe.defaults.get_user_default("branch")
		if user_branch:
			filters["branch"] = user_branch

	return filters


# ---------------------------------------------------------------- Completed Orders
def get_completed_orders(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
	"""Fetches completed service orders based on the authoritative work_completed_on timestamp."""
	filters = enforce_branch_permission(filters or {})
	conditions = ["so.status != 'Cancelled'"]
	values = {}

	if filters.get("from_date"):
		conditions.append("so.work_completed_on >= %(from_date)s")
		values["from_date"] = f"{filters.get('from_date')} 00:00:00"
	if filters.get("to_date"):
		conditions.append("so.work_completed_on <= %(to_date)s")
		values["to_date"] = f"{filters.get('to_date')} 23:59:59"
	if filters.get("branch"):
		conditions.append("so.branch = %(branch)s")
		values["branch"] = filters.get("branch")
	if filters.get("service_advisor"):
		conditions.append("so.service_advisor = %(service_advisor)s")
		values["service_advisor"] = filters.get("service_advisor")
	if filters.get("customer"):
		conditions.append("so.customer = %(customer)s")
		values["customer"] = filters.get("customer")

	cond_str = " AND ".join(conditions)

	query = f"""
		SELECT
			so.name AS service_order,
			so.vehicle,
			so.vehicle_description,
			so.customer,
			so.customer_name,
			so.branch,
			so.service_advisor,
			so.technicians,
			so.checked_in_on,
			so.work_started_on,
			so.work_completed_on,
			so.status,
			so.sales_invoice,
			so.order_type
		FROM `tabService Order` so
		WHERE {cond_str}
		ORDER BY so.work_completed_on DESC
	"""

	orders = frappe.db.sql(query, values, as_dict=True)

	for o in orders:
		start = o.work_started_on or o.checked_in_on
		if start and o.work_completed_on:
			o["turnaround_hours"] = round(time_diff_in_hours(o.work_completed_on, start), 2)
		else:
			o["turnaround_hours"] = 0.0

	return orders


# ---------------------------------------------------------------- Daily Throughput
def get_daily_throughput(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
	"""Calculates daily service order throughput: received, started, completed, awaiting billing, in-progress, and backlog."""
	filters = enforce_branch_permission(filters or {})
	from_date = filters.get("from_date") or nowdate()
	to_date = filters.get("to_date") or nowdate()
	branch = filters.get("branch")

	branch_cond = "AND branch = %(branch)s" if branch else ""
	params = {"from_date": from_date, "to_date": to_date, "branch": branch}

	# Generate day-by-day metrics
	query_completed = f"""
		SELECT DATE(work_completed_on) as date, COUNT(DISTINCT name) as count,
			   AVG(TIMESTAMPDIFF(SECOND, IFNULL(work_started_on, checked_in_on), work_completed_on) / 3600.0) as avg_turnaround
		FROM `tabService Order`
		WHERE status != 'Cancelled' AND work_completed_on IS NOT NULL
		  AND DATE(work_completed_on) BETWEEN %(from_date)s AND %(to_date)s
		  {branch_cond}
		GROUP BY DATE(work_completed_on)
	"""
	completed_by_date = {str(r.date): r for r in frappe.db.sql(query_completed, params, as_dict=True)}

	query_received = f"""
		SELECT DATE(IFNULL(checked_in_on, creation)) as date, COUNT(DISTINCT name) as count
		FROM `tabService Order`
		WHERE status != 'Cancelled'
		  AND DATE(IFNULL(checked_in_on, creation)) BETWEEN %(from_date)s AND %(to_date)s
		  {branch_cond}
		GROUP BY DATE(IFNULL(checked_in_on, creation))
	"""
	received_by_date = {str(r.date): r.count for r in frappe.db.sql(query_received, params, as_dict=True)}

	query_started = f"""
		SELECT DATE(work_started_on) as date, COUNT(DISTINCT name) as count
		FROM `tabService Order`
		WHERE status != 'Cancelled' AND work_started_on IS NOT NULL
		  AND DATE(work_started_on) BETWEEN %(from_date)s AND %(to_date)s
		  {branch_cond}
		GROUP BY DATE(work_started_on)
	"""
	started_by_date = {str(r.date): r.count for r in frappe.db.sql(query_started, params, as_dict=True)}

	# Iterate each date in range
	start_dt = getdate(from_date)
	end_dt = getdate(to_date)
	total_days = date_diff(end_dt, start_dt) + 1

	data = []
	for i in range(total_days):
		cur_date = frappe.utils.add_days(start_dt, i)
		cur_str = str(cur_date)

		comp_info = completed_by_date.get(cur_str, {})
		comp_count = cint(comp_info.get("count", 0))
		rec_count = cint(received_by_date.get(cur_str, 0))
		started_count = cint(started_by_date.get(cur_str, 0))
		avg_turn = round(flt(comp_info.get("avg_turnaround", 0.0)), 2)

		# Backlog at end of day cur_str: received on/before cur_date and (not completed or completed after cur_date 23:59:59)
		backlog_query = f"""
			SELECT COUNT(DISTINCT name) as backlog
			FROM `tabService Order`
			WHERE status != 'Cancelled'
			  AND DATE(IFNULL(checked_in_on, creation)) <= %(cur_date)s
			  AND (work_completed_on IS NULL OR work_completed_on > %(cur_end)s)
			  {branch_cond}
		"""
		backlog_params = {"cur_date": cur_str, "cur_end": f"{cur_str} 23:59:59", "branch": branch}
		backlog_res = frappe.db.sql(backlog_query, backlog_params, as_dict=True)
		backlog = cint(backlog_res[0].backlog) if backlog_res else 0

		data.append({
			"date": cur_str,
			"branch": branch or _("All Branches"),
			"orders_received": rec_count,
			"orders_started": started_count,
			"orders_completed": comp_count,
			"avg_turnaround_hours": avg_turn,
			"backlog": backlog,
		})

	return data


# ---------------------------------------------------------------- WIP Valuation
def get_wip_valuation(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
	"""Calculates active Work-in-Progress (WIP) valuation:
	- Parts WIP: Consumed parts valued at inventory stock cost (NOT selling price).
	- Labour WIP: Actual recorded hours valued at internal labour cost rate.
	- Sublet / direct costs.
	"""
	filters = enforce_branch_permission(filters or {})
	active_statuses = ("Approved", "Waiting for Parts", "Ready for Work", "In Progress", "Paused", "QC", "Ready for Billing")
	status_cond = "so.status IN %(statuses)s"

	conditions = [status_cond, "so.status != 'Cancelled'"]
	values = {"statuses": active_statuses}

	if filters.get("branch"):
		conditions.append("so.branch = %(branch)s")
		values["branch"] = filters.get("branch")

	cond_str = " AND ".join(conditions)

	order_query = f"""
		SELECT
			so.name, so.vehicle, so.customer, so.customer_name, so.branch, so.status,
			so.order_type, so.checked_in_on, so.work_started_on, so.company
		FROM `tabService Order` so
		WHERE {cond_str}
		ORDER BY so.creation ASC
	"""
	orders = frappe.db.sql(order_query, values, as_dict=True)
	default_cost_rate = get_default_labour_cost_rate()

	order_rows = []
	total_parts_wip = 0.0
	total_labour_wip = 0.0
	total_sublet_wip = 0.0
	branch_wip_summary = defaultdict(lambda: {"parts": 0.0, "labour": 0.0, "sublet": 0.0, "total": 0.0, "orders_count": 0})

	for o in orders:
		# 1. Parts WIP (actual consumed stock at valuation rate)
		parts = frappe.db.sql(
			"""
			SELECT sop.item_code, sop.qty_issued, sop.qty_returned, sop.qty_used,
				   COALESCE(
				       (SELECT incoming_rate FROM `tabStock Ledger Entry`
				        WHERE item_code = sop.item_code AND voucher_type = 'Stock Entry'
				        ORDER BY posting_datetime DESC, creation DESC LIMIT 1),
				       (SELECT valuation_rate FROM `tabItem` WHERE name = sop.item_code),
				       0.0
				   ) as valuation_rate
			FROM `tabService Order Part` sop
			WHERE sop.parent = %(order_name)s AND sop.approval_status = 'Approved'
		""",
			{"order_name": o.name},
			as_dict=True,
		)

		parts_cost = 0.0
		for p in parts:
			net_qty = max(0.0, flt(p.qty_issued) - flt(p.qty_returned)) if p.qty_issued else flt(p.qty_used)
			parts_cost += net_qty * flt(p.valuation_rate)

		# 2. Labour WIP (actual logged hours * internal labour cost rate)
		labour_rate_sql = get_labour_cost_rate_subquery("sj.technician")
		jobs = frappe.db.sql(
			f"""
			SELECT sj.name, sj.technician, sj.actual_hours, sj.estimated_hours, sj.supplier_cost,
			       {labour_rate_sql} as labour_cost_rate
			FROM `tabService Job` sj
			WHERE sj.service_order = %(order_name)s AND sj.status NOT IN ('Cancelled', 'Declined')
		""",
			{"order_name": o.name, "default_rate": default_cost_rate},
			as_dict=True,
		)

		labour_cost = 0.0
		sublet_cost = 0.0
		for j in jobs:
			# If actual hours logged, use actual; otherwise fall back to 0 (unworked)
			hrs = flt(j.actual_hours)
			labour_cost += hrs * flt(j.labour_cost_rate)
			sublet_cost += flt(j.supplier_cost)

		total_order_wip = parts_cost + labour_cost + sublet_cost
		days_in_wip = date_diff(nowdate(), getdate(o.work_started_on or o.checked_in_on)) if (o.work_started_on or o.checked_in_on) else 0

		br = o.branch or _("Unassigned")
		branch_wip_summary[br]["parts"] += parts_cost
		branch_wip_summary[br]["labour"] += labour_cost
		branch_wip_summary[br]["sublet"] += sublet_cost
		branch_wip_summary[br]["total"] += total_order_wip
		branch_wip_summary[br]["orders_count"] += 1

		total_parts_wip += parts_cost
		total_labour_wip += labour_cost
		total_sublet_wip += sublet_cost

		order_rows.append({
			"service_order": o.name,
			"vehicle": o.vehicle,
			"customer": o.customer_name or o.customer,
			"branch": br,
			"status": o.status,
			"days_in_wip": max(0, days_in_wip),
			"parts_wip_cost": round(parts_cost, 2),
			"labour_wip_cost": round(labour_cost, 2),
			"sublet_wip_cost": round(sublet_cost, 2),
			"total_wip_cost": round(total_order_wip, 2),
		})

	return {
		"orders": order_rows,
		"branch_summary": [
			{
				"branch": b,
				"orders_count": s["orders_count"],
				"parts_wip": round(s["parts"], 2),
				"labour_wip": round(s["labour"], 2),
				"sublet_wip": round(s["sublet"], 2),
				"total_wip": round(s["total"], 2),
			}
			for b, s in branch_wip_summary.items()
		],
		"summary": {
			"total_orders": len(order_rows),
			"total_parts_wip": round(total_parts_wip, 2),
			"total_labour_wip": round(total_labour_wip, 2),
			"total_sublet_wip": round(total_sublet_wip, 2),
			"total_wip": round(total_parts_wip + total_labour_wip + total_sublet_wip, 2),
		},
	}


def get_detailed_wip_data(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
	"""Returns comprehensive WIP breakdown:
	1. Order-level WIP with aging buckets (0-7, 8-14, 15-30, 30+ days).
	2. Parts-level itemized breakdown (qty issued, returned, net, unit valuation rate, cost).
	3. Labour-level itemized breakdown (technician, logged hours, cost rate, labour cost).
	4. Multi-Branch warehouse reconciliation (operational parts WIP vs ERPNext Stock Ledger balance in wip_warehouse).
	"""
	filters = enforce_branch_permission(filters or {})
	active_statuses = ("Approved", "Waiting for Parts", "Ready for Work", "In Progress", "Paused", "QC", "Ready for Billing")
	status_cond = "so.status IN %(statuses)s"

	conditions = [status_cond, "so.status != 'Cancelled'"]
	values = {"statuses": active_statuses}

	if filters.get("branch"):
		conditions.append("so.branch = %(branch)s")
		values["branch"] = filters.get("branch")

	if filters.get("status"):
		conditions.append("so.status = %(status)s")
		values["status"] = filters.get("status")

	cond_str = " AND ".join(conditions)

	order_query = f"""
		SELECT
			so.name, so.vehicle, so.vehicle_description, so.customer, so.customer_name,
			so.branch, so.status, so.order_type, so.checked_in_on, so.work_started_on, so.company
		FROM `tabService Order` so
		WHERE {cond_str}
		ORDER BY so.creation ASC
	"""
	orders = frappe.db.sql(order_query, values, as_dict=True)
	default_cost_rate = get_default_labour_cost_rate()

	order_rows = []
	parts_detail_rows = []
	labour_detail_rows = []
	branch_wip_summary = defaultdict(lambda: {"parts": 0.0, "labour": 0.0, "sublet": 0.0, "total": 0.0, "orders_count": 0})
	aging_summary = {"0-7 Days": 0, "8-14 Days": 0, "15-30 Days": 0, "30+ Days": 0}

	for o in orders:
		days_in_wip = date_diff(nowdate(), getdate(o.work_started_on or o.checked_in_on)) if (o.work_started_on or o.checked_in_on) else 0
		days_in_wip = max(0, days_in_wip)

		if days_in_wip <= 7:
			aging_bucket = "0-7 Days"
		elif days_in_wip <= 14:
			aging_bucket = "8-14 Days"
		elif days_in_wip <= 30:
			aging_bucket = "15-30 Days"
		else:
			aging_bucket = "30+ Days"

		aging_summary[aging_bucket] += 1

		# 1. Parts WIP
		parts = frappe.db.sql(
			"""
			SELECT sop.item_code, sop.item_name, sop.qty_issued, sop.qty_returned, sop.qty_used,
				   COALESCE(
				       (SELECT incoming_rate FROM `tabStock Ledger Entry`
				        WHERE item_code = sop.item_code AND voucher_type = 'Stock Entry'
				        ORDER BY posting_datetime DESC, creation DESC LIMIT 1),
				       (SELECT valuation_rate FROM `tabItem` WHERE name = sop.item_code),
				       0.0
				   ) as valuation_rate
			FROM `tabService Order Part` sop
			WHERE sop.parent = %(order_name)s AND sop.approval_status = 'Approved'
		""",
			{"order_name": o.name},
			as_dict=True,
		)

		parts_cost = 0.0
		for p in parts:
			net_qty = max(0.0, flt(p.qty_issued) - flt(p.qty_returned)) if p.qty_issued else flt(p.qty_used)
			p_cost = net_qty * flt(p.valuation_rate)
			parts_cost += p_cost

			if net_qty > 0 or p.qty_issued:
				parts_detail_rows.append({
					"service_order": o.name,
					"vehicle": o.vehicle,
					"branch": o.branch or _("Unassigned"),
					"item_code": p.item_code,
					"item_name": p.item_name,
					"qty_issued": flt(p.qty_issued),
					"qty_returned": flt(p.qty_returned),
					"net_consumed_qty": net_qty,
					"unit_valuation_rate": round(flt(p.valuation_rate), 2),
					"total_parts_cost": round(p_cost, 2),
				})

		# 2. Labour WIP
		labour_rate_sql = get_labour_cost_rate_subquery("sj.technician")
		jobs = frappe.db.sql(
			f"""
			SELECT sj.name, sj.job_title, sj.technician, sj.technician_name, sj.actual_hours,
			       sj.estimated_hours, sj.supplier_cost,
			       {labour_rate_sql} as labour_cost_rate
			FROM `tabService Job` sj
			WHERE sj.service_order = %(order_name)s AND sj.status NOT IN ('Cancelled', 'Declined')
		""",
			{"order_name": o.name, "default_rate": default_cost_rate},
			as_dict=True,
		)

		labour_cost = 0.0
		sublet_cost = 0.0
		for j in jobs:
			hrs = flt(j.actual_hours)
			cost_rate = flt(j.labour_cost_rate)
			j_labour_cost = hrs * cost_rate
			labour_cost += j_labour_cost
			sublet_cost += flt(j.supplier_cost)

			if hrs > 0:
				labour_detail_rows.append({
					"service_order": o.name,
					"vehicle": o.vehicle,
					"branch": o.branch or _("Unassigned"),
					"job_title": j.job_title,
					"technician": j.technician_name or j.technician or _("Unassigned"),
					"actual_hours": round(hrs, 2),
					"labour_cost_rate": round(cost_rate, 2),
					"total_labour_cost": round(j_labour_cost, 2),
				})

		total_order_wip = parts_cost + labour_cost + sublet_cost
		br = o.branch or _("Unassigned")
		branch_wip_summary[br]["parts"] += parts_cost
		branch_wip_summary[br]["labour"] += labour_cost
		branch_wip_summary[br]["sublet"] += sublet_cost
		branch_wip_summary[br]["total"] += total_order_wip
		branch_wip_summary[br]["orders_count"] += 1

		# Filter by aging_bucket if specified
		if filters.get("aging_bucket") and filters.get("aging_bucket") != aging_bucket:
			continue

		order_rows.append({
			"service_order": o.name,
			"vehicle": o.vehicle,
			"make_model": o.vehicle_description,
			"customer": o.customer_name or o.customer,
			"branch": br,
			"status": o.status,
			"days_in_wip": days_in_wip,
			"aging_bucket": aging_bucket,
			"parts_wip_cost": round(parts_cost, 2),
			"labour_wip_cost": round(labour_cost, 2),
			"sublet_wip_cost": round(sublet_cost, 2),
			"total_wip_cost": round(total_order_wip, 2),
		})

	# 3. Branch Warehouse Reconciliation
	reconciliation_rows = []
	for b, s in branch_wip_summary.items():
		wh_info = resolve_branch_warehouses(b if b != _("Unassigned") else None)
		wip_wh = wh_info.get("wip_warehouse")

		gl_wip_stock_value = 0.0
		if wip_wh:
			res = frappe.db.sql(
				"""
				SELECT SUM(stock_value_difference) as total_val
				FROM `tabStock Ledger Entry`
				WHERE warehouse = %(wip_warehouse)s AND is_cancelled = 0
			""",
				{"wip_warehouse": wip_wh},
				as_dict=True,
			)
			gl_wip_stock_value = flt(res[0].total_val) if res and res[0].total_val else 0.0

		variance = round(s["parts"] - gl_wip_stock_value, 2)
		reconciliation_rows.append({
			"branch": b,
			"wip_warehouse": wip_wh or _("Not Configured"),
			"operational_parts_wip": round(s["parts"], 2),
			"warehouse_stock_valuation": round(gl_wip_stock_value, 2),
			"variance": variance,
			"status": _("Reconciled") if abs(variance) < 0.01 else _("Variance Detected"),
		})

	total_parts = sum(r["parts_wip_cost"] for r in order_rows)
	total_labour = sum(r["labour_wip_cost"] for r in order_rows)
	total_sublet = sum(r["sublet_wip_cost"] for r in order_rows)

	return {
		"orders": order_rows,
		"parts_details": parts_detail_rows,
		"labour_details": labour_detail_rows,
		"branch_reconciliation": reconciliation_rows,
		"aging_summary": aging_summary,
		"summary": {
			"total_orders": len(order_rows),
			"total_parts_wip": round(total_parts, 2),
			"total_labour_wip": round(total_labour, 2),
			"total_sublet_wip": round(total_sublet, 2),
			"total_wip": round(total_parts + total_labour + total_sublet, 2),
		},
	}



# ---------------------------------------------------------------- Technician Labour Units Attribution
def get_technician_labour_units(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
	"""Calculates labour units sold per technician.
	- Distinguishes Service Order vs Service Job: Each job is attributed to its assigned technician.
	- Only if multiple technicians recorded time on the same individual job is that specific job's units apportioned.
	"""
	filters = enforce_branch_permission(filters or {})
	conditions = ["sj.status NOT IN ('Cancelled', 'Declined')"]
	values = {}

	if filters.get("from_date"):
		conditions.append("sj.completed_on >= %(from_date)s")
		values["from_date"] = f"{filters.get('from_date')} 00:00:00"
	if filters.get("to_date"):
		conditions.append("sj.completed_on <= %(to_date)s")
		values["to_date"] = f"{filters.get('to_date')} 23:59:59"
	if filters.get("technician"):
		conditions.append("(sj.technician = %(technician)s OR EXISTS (SELECT 1 FROM `tabService Job Time Log` WHERE parent = sj.name AND technician = %(technician)s))")
		values["technician"] = filters.get("technician")
	if filters.get("branch"):
		conditions.append("so.branch = %(branch)s")
		values["branch"] = filters.get("branch")

	cond_str = " AND ".join(conditions)

	# Fetch jobs and their assigned technician
	jobs_query = f"""
		SELECT
			sj.name AS job_name,
			sj.service_order,
			sj.job_title,
			sj.technician AS primary_technician,
			sj.technician_name,
			sj.estimated_hours AS billable_units,
			sj.rate AS selling_rate,
			sj.actual_hours,
			so.branch
		FROM `tabService Job` sj
		JOIN `tabService Order` so ON so.name = sj.service_order
		WHERE {cond_str}
	"""
	jobs = frappe.db.sql(jobs_query, values, as_dict=True)
	default_cost_rate = get_default_labour_cost_rate()

	# Technician aggregation map
	tech_stats = defaultdict(lambda: {
		"technician": "",
		"technician_name": "",
		"branch": "",
		"jobs_count": 0,
		"sold_units": 0.0,
		"labour_revenue": 0.0,
		"actual_hours": 0.0,
		"labour_cost": 0.0,
	})

	for j in jobs:
		billable_units = flt(j.billable_units) or 1.0
		selling_rate = flt(j.selling_rate) or 50.0
		job_rev = billable_units * selling_rate

		# Check if multiple technicians logged time on THIS specific job
		time_logs = frappe.db.sql(
			"""
			SELECT technician, SUM(hours) as logged_hours
			FROM `tabService Job Time Log`
			WHERE parent = %(job_name)s
			GROUP BY technician
		""",
			{"job_name": j.job_name},
			as_dict=True,
		)

		if time_logs and len(time_logs) > 1:
			total_logged = sum(flt(tl.logged_hours) for tl in time_logs) or 1.0
			for tl in time_logs:
				t_id = tl.technician
				share_ratio = flt(tl.logged_hours) / total_logged
				t_units = billable_units * share_ratio
				t_rev = job_rev * share_ratio
				t_cost_rate = get_technician_hourly_cost(t_id)

				st = tech_stats[t_id]
				st["technician"] = t_id
				st["technician_name"] = frappe.db.get_value("Employee", t_id, "employee_name") or t_id
				st["branch"] = j.branch
				st["jobs_count"] += 1
				st["sold_units"] += t_units
				st["labour_revenue"] += t_rev
				st["actual_hours"] += flt(tl.logged_hours)
				st["labour_cost"] += flt(tl.logged_hours) * t_cost_rate
		else:
			# Single technician attribution (standard case)
			t_id = j.primary_technician or (time_logs[0].technician if time_logs else None) or _("Unassigned")
			t_name = j.technician_name or frappe.db.get_value("Employee", t_id, "employee_name") or t_id
			t_cost_rate = get_technician_hourly_cost(t_id)
			act_hrs = flt(j.actual_hours) or (flt(time_logs[0].logged_hours) if time_logs else 0.0)

			st = tech_stats[t_id]
			st["technician"] = t_id
			st["technician_name"] = t_name
			st["branch"] = j.branch
			st["jobs_count"] += 1
			st["sold_units"] += billable_units
			st["labour_revenue"] += job_rev
			st["actual_hours"] += act_hrs
			st["labour_cost"] += act_hrs * t_cost_rate

	# Calculate profit and efficiency
	result = []
	for t_id, st in tech_stats.items():
		sold = st["sold_units"]
		act = st["actual_hours"]
		rev = st["labour_revenue"]
		cost = st["labour_cost"]
		gp = rev - cost
		eff = round((sold / act * 100.0), 1) if act > 0 else (100.0 if sold > 0 else 0.0)

		result.append({
			"technician": st["technician"],
			"technician_name": st["technician_name"],
			"branch": st["branch"],
			"jobs_completed": st["jobs_count"],
			"sold_units": round(sold, 2),
			"labour_revenue": round(rev, 2),
			"actual_hours": round(act, 2),
			"labour_cost": round(cost, 2),
			"gross_profit": round(gp, 2),
			"efficiency_rate": eff,
		})

	if filters.get("technician"):
		result = [r for r in result if r["technician"] == filters.get("technician")]

	return sorted(result, key=lambda x: x["sold_units"], reverse=True)


# ---------------------------------------------------------------- Parts Sales & Margins
def get_parts_sales(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
	"""Fetches parts sold via submitted Sales Invoices, distinguishing repair order parts from over-the-counter."""
	filters = enforce_branch_permission(filters or {})
	conditions = ["si.docstatus = 1", "sii.item_code IS NOT NULL"]
	values = {}

	if filters.get("from_date"):
		conditions.append("si.posting_date >= %(from_date)s")
		values["from_date"] = filters.get("from_date")
	if filters.get("to_date"):
		conditions.append("si.posting_date <= %(to_date)s")
		values["to_date"] = filters.get("to_date")
	if filters.get("branch"):
		conditions.append("COALESCE(so.branch, (SELECT bwm.branch FROM `tabBranch Warehouse Mapping` bwm WHERE bwm.stores_warehouse = sii.warehouse LIMIT 1)) = %(branch)s")
		values["branch"] = filters.get("branch")
	if filters.get("customer"):
		conditions.append("si.customer = %(customer)s")
		values["customer"] = filters.get("customer")
	if filters.get("item_code"):
		conditions.append("sii.item_code = %(item_code)s")
		values["item_code"] = filters.get("item_code")
	if filters.get("sale_type") == "Workshop Repair":
		conditions.append("si.vs_service_order IS NOT NULL AND si.vs_service_order != ''")
	elif filters.get("sale_type") == "Over-the-Counter":
		conditions.append("(si.vs_service_order IS NULL OR si.vs_service_order = '')")

	cond_str = " AND ".join(conditions)

	query = f"""
		SELECT
			si.name AS invoice_number,
			si.posting_date,
			si.customer,
			si.customer_name,
			COALESCE(so.branch, (SELECT bwm.branch FROM `tabBranch Warehouse Mapping` bwm WHERE bwm.stores_warehouse = sii.warehouse LIMIT 1)) AS branch,
			si.vs_service_order,
			sii.item_code,
			sii.item_name,
			sii.qty,
			sii.rate,
			sii.amount AS net_sales,
			sii.warehouse,
			COALESCE(
				(SELECT incoming_rate FROM `tabStock Ledger Entry`
				 WHERE voucher_type = 'Sales Invoice' AND voucher_no = si.name AND item_code = sii.item_code
				 LIMIT 1),
				(SELECT valuation_rate FROM `tabItem` WHERE name = sii.item_code),
				0.0
			) as cogs_rate
		FROM `tabSales Invoice` si
		LEFT JOIN `tabService Order` so ON so.name = si.vs_service_order
		JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		JOIN `tabItem` itm ON itm.name = sii.item_code
		WHERE {cond_str} AND itm.is_stock_item = 1
		ORDER BY si.posting_date DESC
	"""
	items = frappe.db.sql(query, values, as_dict=True)

	for itm in items:
		qty = flt(itm.qty)
		net = flt(itm.net_sales)
		cogs_rate = flt(itm.cogs_rate)
		cogs = qty * cogs_rate
		gp = net - cogs
		gp_pct = round((gp / net * 100.0), 1) if net > 0 else 0.0

		itm["unit_cost"] = round(cogs_rate, 2)
		itm["sale_type"] = _("Workshop Repair") if itm.vs_service_order else _("Over-the-Counter")
		itm["cogs"] = round(cogs, 2)
		itm["gross_profit"] = round(gp, 2)
		itm["gp_percent"] = gp_pct

	return items


# ---------------------------------------------------------------- Daily Operating Control (DOC)
def get_doc_summary(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
	"""Aggregates Daily Operating Control (DOC) executive overview:
	- Workshop volume (received, completed, in-progress)
	- Parts revenue, COGS, and GP
	- Labour units, revenue, cost, and GP
	- Total combined gross profit & margin %
	- Active WIP snapshot
	"""
	filters = enforce_branch_permission(filters or {})
	from_date = filters.get("from_date") or nowdate()
	to_date = filters.get("to_date") or nowdate()

	# 1. Orders throughput
	completed_orders = get_completed_orders(filters)
	total_completed = len(completed_orders)
	avg_turnaround = round(sum(o["turnaround_hours"] for o in completed_orders) / total_completed, 2) if total_completed else 0.0

	# 2. Parts sales & profit
	parts_sales = get_parts_sales(filters)
	parts_rev = sum(flt(p["net_sales"]) for p in parts_sales)
	parts_cogs = sum(flt(p["cogs"]) for p in parts_sales)
	parts_gp = parts_rev - parts_cogs
	parts_gp_pct = round((parts_gp / parts_rev * 100.0), 1) if parts_rev > 0 else 0.0

	# 3. Labour units sold & profit
	labour_stats = get_technician_labour_units(filters)
	labour_units = sum(flt(l["sold_units"]) for l in labour_stats)
	labour_rev = sum(flt(l["labour_revenue"]) for l in labour_stats)
	labour_cost = sum(flt(l["labour_cost"]) for l in labour_stats)
	labour_act_hrs = sum(flt(l["actual_hours"]) for l in labour_stats)
	labour_gp = labour_rev - labour_cost
	labour_gp_pct = round((labour_gp / labour_rev * 100.0), 1) if labour_rev > 0 else 0.0

	# 4. Department totals
	total_rev = parts_rev + labour_rev
	total_cogs_cost = parts_cogs + labour_cost
	total_gp = total_rev - total_cogs_cost
	overall_gp_pct = round((total_gp / total_rev * 100.0), 1) if total_rev > 0 else 0.0

	# 5. Open WIP snapshot
	wip_data = get_wip_valuation(filters)

	return {
		"reporting_period": f"{from_date} to {to_date}",
		"branch": filters.get("branch") or _("All Branches"),
		"volume": {
			"completed_orders": total_completed,
			"avg_turnaround_hours": avg_turnaround,
		},
		"parts": {
			"revenue": round(parts_rev, 2),
			"cogs": round(parts_cogs, 2),
			"gross_profit": round(parts_gp, 2),
			"gp_percent": parts_gp_pct,
		},
		"labour": {
			"sold_units": round(labour_units, 2),
			"actual_hours": round(labour_act_hrs, 2),
			"revenue": round(labour_rev, 2),
			"cost": round(labour_cost, 2),
			"gross_profit": round(labour_gp, 2),
			"gp_percent": labour_gp_pct,
		},
		"department_total": {
			"total_revenue": round(total_rev, 2),
			"total_cost": round(total_cogs_cost, 2),
			"total_gross_profit": round(total_gp, 2),
			"overall_gp_percent": overall_gp_pct,
		},
		"wip_snapshot": wip_data["summary"],
	}


def get_doc_daily_breakdown(filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
	"""Calculates daily operational and commercial metrics for the DOC report."""
	filters = enforce_branch_permission(filters or {})
	from_date = filters.get("from_date") or frappe.utils.add_months(nowdate(), -1)
	to_date = filters.get("to_date") or nowdate()
	branch = filters.get("branch")

	# 1. Daily Orders Completed
	orders = get_completed_orders(filters)
	orders_by_date = defaultdict(lambda: {"count": 0, "turnaround": []})
	for o in orders:
		if o.get("work_completed_on"):
			dt_str = str(getdate(o["work_completed_on"]))
			orders_by_date[dt_str]["count"] += 1
			orders_by_date[dt_str]["turnaround"].append(flt(o.get("turnaround_hours", 0.0)))

	# 2. Daily Parts Sales
	parts = get_parts_sales(filters)
	parts_by_date = defaultdict(lambda: {"revenue": 0.0, "cogs": 0.0, "gp": 0.0})
	for p in parts:
		dt_str = str(getdate(p.get("posting_date")))
		parts_by_date[dt_str]["revenue"] += flt(p.get("net_sales", 0.0))
		parts_by_date[dt_str]["cogs"] += flt(p.get("cogs", 0.0))
		parts_by_date[dt_str]["gp"] += flt(p.get("gross_profit", 0.0))

	# 3. Daily Labour Performance (from Service Jobs)
	branch_cond = "AND so.branch = %(branch)s" if branch else ""
	labour_rate_sql = get_labour_cost_rate_subquery("sj.technician")
	job_query = f"""
		SELECT
			DATE(sj.completed_on) as date,
			SUM(sj.estimated_hours) as sold_units,
			SUM(sj.estimated_hours * sj.rate) as labour_rev,
			SUM(sj.actual_hours) as actual_hours,
			SUM(sj.actual_hours * {labour_rate_sql}) as labour_cost
		FROM `tabService Job` sj
		JOIN `tabService Order` so ON so.name = sj.service_order
		WHERE sj.status NOT IN ('Cancelled', 'Declined')
		  AND sj.completed_on IS NOT NULL
		  AND DATE(sj.completed_on) BETWEEN %(from_date)s AND %(to_date)s
		  {branch_cond}
		GROUP BY DATE(sj.completed_on)
	"""
	default_cost_rate = get_default_labour_cost_rate()
	job_params = {"from_date": from_date, "to_date": to_date, "branch": branch, "default_rate": default_cost_rate}
	jobs_res = frappe.db.sql(job_query, job_params, as_dict=True)
	labour_by_date = {str(r.date): r for r in jobs_res}

	start_dt = getdate(from_date)
	end_dt = getdate(to_date)
	total_days = date_diff(end_dt, start_dt) + 1

	daily_rows = []
	for i in range(total_days):
		cur_date = frappe.utils.add_days(start_dt, i)
		cur_str = str(cur_date)

		ord_info = orders_by_date.get(cur_str, {"count": 0, "turnaround": []})
		comp_count = ord_info["count"]
		avg_turn = round(sum(ord_info["turnaround"]) / comp_count, 1) if comp_count else 0.0

		p_info = parts_by_date.get(cur_str, {"revenue": 0.0, "cogs": 0.0, "gp": 0.0})
		p_rev = round(p_info["revenue"], 2)
		p_gp = round(p_info["gp"], 2)

		l_info = labour_by_date.get(cur_str, {})
		l_sold = round(flt(l_info.get("sold_units", 0.0)), 2)
		l_rev = round(flt(l_info.get("labour_rev", 0.0)), 2)
		l_cost = round(flt(l_info.get("labour_cost", 0.0)), 2)
		l_act = round(flt(l_info.get("actual_hours", 0.0)), 2)
		l_gp = round(l_rev - l_cost, 2)

		tot_rev = round(p_rev + l_rev, 2)
		tot_gp = round(p_gp + l_gp, 2)
		gp_pct = round((tot_gp / tot_rev * 100.0), 1) if tot_rev > 0 else 0.0

		daily_rows.append({
			"date": cur_str,
			"branch": branch or _("All Branches"),
			"orders_completed": comp_count,
			"avg_turnaround_hours": avg_turn,
			"parts_revenue": p_rev,
			"parts_gross_profit": p_gp,
			"labour_sold_units": l_sold,
			"labour_actual_hours": l_act,
			"labour_revenue": l_rev,
			"labour_gross_profit": l_gp,
			"total_revenue": tot_rev,
			"total_gross_profit": tot_gp,
			"overall_gp_percent": gp_pct,
		})

	return daily_rows

