# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime, time_diff_in_seconds
from vehicle_service.state import compute_operational_status
from vehicle_service.vehicle_service.doctype.service_job.service_job import (
	start_job,
	pause_job,
)


@frappe.whitelist()
def get_workshop_live_board(filters=None):
	"""Returns real-time operational workshop board data including:
	- Service bays (both occupied and available)
	- Unallocated or staging orders
	- Real-time KPIs
	- Dynamic job clock durations
	"""
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except Exception:
			filters = {}
	filters = filters or {}

	# 1. Fetch active service bays
	locations = frappe.get_all(
		"Workshop Location",
		filters={"location_type": "Bay", "is_active": 1},
		fields=["name", "location_name"],
		order_by="location_name asc",
	)

	# 2. Fetch active orders
	order_filters = {"status": ["not in", ["Delivered", "Cancelled"]]}
	if filters.get("status") and filters.get("status") != "All":
		order_filters["status"] = filters.get("status")
	if filters.get("priority") and filters.get("priority") != "All":
		order_filters["priority"] = filters.get("priority")

	orders = frappe.get_all(
		"Service Order",
		filters=order_filters,
		fields=[
			"name",
			"vehicle",
			"customer",
			"status",
			"priority",
			"current_location",
			"checked_in_on",
			"expected_completion",
			"creation",
			"modified",
		],
		order_by="priority desc, modified desc",
	)

	# 3. Fetch linked vehicles
	veh_names = [o.vehicle for o in orders if o.vehicle]
	vehicles = {}
	if veh_names:
		veh_docs = frappe.get_all(
			"Service Vehicle",
			filters={"name": ["in", veh_names]},
			fields=["name", "registration_no", "make", "model", "current_location", "vehicle_status"],
		)
		vehicles = {v.name: v for v in veh_docs}

	# 4. Fetch linked jobs
	order_names = [o.name for o in orders]
	jobs = []
	if order_names:
		jobs = frappe.get_all(
			"Service Job",
			filters={"service_order": ["in", order_names], "status": ["not in", ["Cancelled"]]},
			fields=[
				"name",
				"service_order",
				"job_title",
				"technician",
				"bay",
				"status",
				"estimated_hours",
				"actual_hours",
			],
		)

	# Group jobs by order
	order_jobs = {}
	active_job_ids = []
	for j in jobs:
		order_jobs.setdefault(j.service_order, []).append(j)
		if j.status == "In Progress":
			active_job_ids.append(j.name)

	# Fetch open time logs for dynamic duration
	open_logs = {}
	if active_job_ids:
		logs = frappe.db.sql(
			"""
			SELECT parent, from_time, technician
			FROM `tabService Job Time Log`
			WHERE parent IN %s AND (to_time IS NULL OR to_time = '')
			""",
			(tuple(active_job_ids),),
			as_dict=True,
		)
		for log in logs:
			open_logs[log.parent] = frappe._dict({
				"service_job": log.parent,
				"start_time": log.from_time,
				"from_time": log.from_time,
				"technician": log.technician,
			})

	# 5. Fetch parts for orders
	parts = []
	if order_names:
		parts = frappe.get_all(
			"Service Order Part",
			filters={"parent": ["in", order_names]},
			fields=["name", "parent", "item_code", "item_name", "qty_required", "qty_issued", "qty_used", "part_status", "approval_status"],
		)
	order_parts = {}
	for p in parts:
		order_parts.setdefault(p.parent, []).append(p)

	# Build enhanced order map
	now = now_datetime()
	enhanced_orders = {}
	for o in orders:
		v = vehicles.get(o.vehicle) or {}
		o_jobs = order_jobs.get(o.name, [])
		o_parts = order_parts.get(o.name, [])

		# Find current primary job
		primary_job = None
		# Look for In Progress first, then Ready/Assigned, then Paused, then Completed
		for st in ["In Progress", "Paused", "Ready", "Assigned", "Pending"]:
			matches = [j for j in o_jobs if j.status == st]
			if matches:
				primary_job = matches[0]
				break
		if not primary_job and o_jobs:
			primary_job = o_jobs[0]

		# Compute elapsed clock & total actual hours
		total_est = sum(j.estimated_hours or 0.0 for j in o_jobs)
		total_act = sum(j.actual_hours or 0.0 for j in o_jobs)
		elapsed_str = ""

		if primary_job and primary_job.name in open_logs:
			log = open_logs[primary_job.name]
			secs = time_diff_in_seconds(now, log.start_time)
			running_hours = secs / 3600.0
			total_act += running_hours
			mins = int((secs % 3600) // 60)
			hrs = int(secs // 3600)
			elapsed_str = f"{hrs}h {mins}m"
		elif primary_job and primary_job.status == "Paused":
			elapsed_str = "Paused"

		# Compute parts status
		parts_status = "None"
		if o_parts:
			all_issued = all((p.qty_issued or 0) >= (p.qty_required or 0) for p in o_parts)
			any_pending = any(p.approval_status in ["Pending", "Draft"] for p in o_parts)
			any_shortage = any((p.qty_required or 0) > (p.qty_issued or 0) for p in o_parts)

			if any_pending:
				parts_status = "Pending Approval"
			elif any_shortage:
				parts_status = "Shortage"
			elif all_issued:
				parts_status = "Issued"

		# Determine next action
		next_action = "View Order"
		if o.status == "Draft":
			next_action = "View Intake / Order"
		elif o.status == "Waiting for Parts":
			next_action = "Issue Parts"
		elif o.status == "Ready for Work":
			next_action = "Start Job"
		elif o.status == "In Progress":
			next_action = "View / Pause"
		elif o.status == "QC":
			next_action = "QC Inspection"
		elif o.status in ["Ready for Collection", "Invoiced"]:
			next_action = "Deliver"

		enhanced = {
			"name": o.name,
			"customer": o.customer,
			"priority": o.priority,
			"status": o.status,
			"operational_status": compute_operational_status(o_jobs, o_parts),
			"assigned_bay": o.current_location or (v.get("current_location") if v else None),
			"vehicle_reg": v.get("registration_no", ""),
			"vehicle_model": f"{v.get('make', '')} {v.get('model', '')}".strip(),
			"vehicle_location": v.get("current_location", ""),
			"active_job": primary_job.job_title if primary_job else "—",
			"active_job_name": primary_job.name if primary_job else "",
			"technician": primary_job.technician if primary_job else "—",
			"job_status": primary_job.status if primary_job else "—",
			"estimated_hours": round(total_est, 1),
			"actual_hours": round(total_act, 1),
			"elapsed_str": elapsed_str,
			"parts_status": parts_status,
			"next_action": next_action,
		}

		# Apply filters for technician, bay, search
		match = True
		if filters.get("technician") and filters.get("technician") != "All":
			if enhanced["technician"] != filters.get("technician"):
				match = False
		if filters.get("bay") and filters.get("bay") != "All":
			if enhanced["assigned_bay"] != filters.get("bay"):
				match = False
		if filters.get("search"):
			query = filters.get("search").lower()
			if (
				query not in enhanced["name"].lower()
				and query not in enhanced["customer"].lower()
				and query not in enhanced["vehicle_reg"].lower()
				and query not in enhanced["vehicle_model"].lower()
			):
				match = False

		if match:
			enhanced_orders[o.name] = enhanced

	# 6. Map bays
	bays = []
	allocated_order_names = set()

	for loc in locations:
		bay_data = {
			"location_name": loc.location_name,
			"is_occupied": False,
			"order": None,
		}

		# Find order in this bay
		for o_name, o_info in enhanced_orders.items():
			if o_name not in allocated_order_names and o_info.get("assigned_bay") == loc.location_name:
				bay_data["is_occupied"] = True
				bay_data["order"] = o_info
				allocated_order_names.add(o_name)
				break

		# Bay filter check: if bay filter is applied, only return matching bay
		if filters.get("bay") and filters.get("bay") != "All":
			if loc.location_name == filters.get("bay"):
				bays.append(bay_data)
		else:
			bays.append(bay_data)

	# 7. Unallocated orders (orders without a bay or in non-bay locations)
	unallocated = []
	for o_name, o_info in enhanced_orders.items():
		if o_name not in allocated_order_names:
			unallocated.append(o_info)

	# 8. Compute Workshop KPIs
	total_on_site = len(orders)
	in_progress_count = sum(1 for o in orders if o.status == "In Progress")
	awaiting_approval_count = sum(1 for o in orders if o.status == "Draft")
	waiting_parts_count = sum(1 for o in orders if o.status == "Waiting for Parts")
	in_qc_count = sum(1 for o in orders if o.status == "QC")
	ready_collection_count = sum(1 for o in orders if o.status in ["Ready for Collection", "Invoiced"])
	occupied_bays_count = sum(1 for b in bays if b.get("is_occupied"))
	total_bays_count = len(locations)
	bay_util = (
		round((occupied_bays_count / total_bays_count) * 100.0, 1)
		if total_bays_count > 0
		else 0.0
	)

	return {
		"kpis": {
			"total_on_site": total_on_site,
			"in_progress": in_progress_count,
			"awaiting_approval": awaiting_approval_count,
			"waiting_parts": waiting_parts_count,
			"in_qc": in_qc_count,
			"ready_for_collection": ready_collection_count,
			"total_bays": total_bays_count,
			"occupied_bays": occupied_bays_count,
			"bay_utilisation": bay_util,
		},
		"bays": bays,
		"unallocated_orders": unallocated,
	}


@frappe.whitelist()
def quick_assign_technician_bay(job_name, technician=None, bay_location=None):
	"""Quick supervisor action to assign/reassign technician and bay location."""
	job = frappe.get_doc("Service Job", job_name)
	if technician:
		job.technician = technician
	if bay_location:
		job.bay = bay_location
	job.save()

	if bay_location and job.service_order:
		quick_move_bay(job.service_order, bay_location)

	return {"success": True, "message": _("Assigned successfully")}


@frappe.whitelist()
def quick_move_bay(order_name, new_location, reason=None):
	"""Move service order and vehicle to a new bay location with movement log."""
	order = frappe.get_doc("Service Order", order_name)
	old_location = order.current_location

	order.current_location = new_location
	order.save()

	# Also update Vehicle location and create movement record
	if order.vehicle:
		veh = frappe.get_doc("Service Vehicle", order.vehicle)
		from_loc = veh.current_location or old_location
		veh.current_location = new_location
		veh.save()

		# Create Vehicle Movement log
		vm = frappe.new_doc("Vehicle Movement")
		vm.vehicle = veh.name
		vm.service_order = order.name
		vm.from_location = from_loc
		vm.to_location = new_location
		vm.moved_on = now_datetime()
		vm.moved_by = frappe.session.user
		vm.reason = reason or "Moved via Workshop Control"
		vm.insert(ignore_permissions=True)

	return {"success": True, "message": _("Vehicle moved to {0}").format(new_location)}


@frappe.whitelist()
def quick_start_job(job_name):
	"""Supervisor quick start job."""
	return start_job(job_name)


@frappe.whitelist()
def quick_pause_job(job_name, reason="Supervisor Override"):
	"""Supervisor quick pause job."""
	return pause_job(job_name, reason)
