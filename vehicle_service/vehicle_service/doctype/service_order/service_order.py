# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	cint,
	flt,
	get_link_to_form,
	now_datetime,
	nowdate,
)
from vehicle_service.state import (
	AWAITING_APPROVAL,
	CANCELLED,
	CHECKED_IN,
	DELIVERED,
	DRAFT,
	INVOICED,
	JOB_DONE,
	JOB_INACTIVE,
	OPERATIONAL,
	ORDER_FLOW,
	PART_REQUIRED,
	PART_WAITING,
	QC,
	READY_FOR_BILLING,
	READY_FOR_COLLECTION,
	billable_labour_hours,
	compute_operational_status,
	compute_part_status,
	qty_on_vehicle,
	stepper_position,
	vehicle_status_for,
)


class ServiceOrder(Document):
	def validate(self):
		self.validate_open_orders()
		self.fetch_vehicle_and_company_defaults()
		self.validate_intake_frozen()
		self.recalculate_parts_summary()

	def validate_open_orders(self):
		if self.is_new() or self.has_value_changed("vehicle"):
			settings = frappe.get_cached_doc("Vehicle Service Settings")
			if not settings.allow_multiple_open_orders and self.vehicle:
				existing = frappe.db.get_value(
					"Service Order",
					{"vehicle": self.vehicle, "status": ["not in", [DELIVERED, CANCELLED]], "name": ["!=", self.name or ""]},
					"name",
				)
				if existing:
					frappe.throw(
						_("Vehicle {0} already has an active Service Order ({1}). Only one active order is allowed at a time.").format(
							self.vehicle, get_link_to_form("Service Order", existing)
						)
					)

	def fetch_vehicle_and_company_defaults(self):
		if self.vehicle:
			v = frappe.get_cached_doc("Service Vehicle", self.vehicle)
			self.vehicle_description = f"{v.make or ''} {v.model or ''} ({v.year or ''})".strip()
			if not self.customer:
				self.customer = v.customer
			if not self.driver_name and v.driver_name:
				self.driver_name = v.driver_name
			if not self.driver_phone and v.driver_phone:
				self.driver_phone = v.driver_phone
			if not self.odometer_in and v.current_mileage:
				self.odometer_in = v.current_mileage
			if not self.current_location and v.current_location:
				self.current_location = v.current_location

		if not self.company:
			settings = frappe.get_cached_doc("Vehicle Service Settings")
			self.company = settings.company or frappe.defaults.get_user_default("Company")

		if not self.service_advisor:
			self.service_advisor = frappe.session.user

	def validate_intake_frozen(self):
		if not self.is_new() and not frappe.flags.in_correction:
			prev = self.get_doc_before_save()
			was_frozen = prev.intake_frozen if prev else 0
			if was_frozen:
				for field in [
					"odometer_in",
					"fuel_level",
					"customer_complaint",
					"existing_damage",
					"vehicle_contents",
					"intake_confirmed",
				]:
					if self.has_value_changed(field):
						frappe.throw(
							_("Intake details are frozen after check-in. Use the 'Correct Intake' action to update '{0}' with an audit reason.").format(
								self.meta.get_label(field)
							)
						)

	def recalculate_parts_summary(self):
		for row in self.get("parts", []):
			row.qty_used = round(flt(row.qty_issued or 0) - flt(row.qty_returned or 0), 2)
			row.part_status = compute_part_status(row)

	def sync_status_from_jobs_and_parts(self):
		"""Derives operational status when order is in active workshop stages."""
		if self.status in (DRAFT, CHECKED_IN, AWAITING_APPROVAL, READY_FOR_BILLING, INVOICED, READY_FOR_COLLECTION, DELIVERED, CANCELLED):
			return

		jobs = frappe.get_all("Service Job", filters={"service_order": self.name}, fields=["status"])
		new_status = compute_operational_status(jobs, self.parts)

		if self.status != new_status:
			self.status = new_status
			self.save(ignore_permissions=True)

		# Update vehicle status
		if self.vehicle:
			v_status = vehicle_status_for(self.status)
			frappe.db.set_value("Service Vehicle", self.vehicle, "vehicle_status", v_status)

	def on_update(self):
		prev = self.get_doc_before_save()
		prev_status = prev.status if prev else None
		if self.status == READY_FOR_COLLECTION and prev_status != READY_FOR_COLLECTION:
			try:
				from vehicle_service.vehicle_service.notifications import send_ready_for_collection
				send_ready_for_collection(self.name)
			except Exception:
				frappe.log_error(title="Failed to auto-send collection notification", message=frappe.get_traceback())

	def on_trash(self):
		if self.status not in (DRAFT, CANCELLED):
			frappe.throw(_("Cannot delete Service Order in status '{0}'. Cancel it first.").format(self.status))


# ---------------------------------------------------------------- Whitelisted Actions


@frappe.whitelist()
def check_in_vehicle(
	order_name: str,
	odometer_in: int,
	fuel_level: str | None = None,
	customer_complaint: str | None = None,
	existing_damage: str | None = None,
	vehicle_contents: str | None = None,
	intake_confirmed: int = 1,
	customer_signature: str | None = None,
):
	order = frappe.get_doc("Service Order", order_name)
	if order.status != DRAFT:
		frappe.throw(_("Vehicle is already checked in (Status: {0}).").format(order.status))

	vehicle = frappe.get_doc("Service Vehicle", order.vehicle)

	# Validate odometer
	if odometer_in and vehicle.current_mileage and int(odometer_in) < int(vehicle.current_mileage):
		frappe.throw(
			_("Odometer reading ({0} km) cannot be lower than current vehicle mileage ({1} km).").format(
				odometer_in, vehicle.current_mileage
			)
		)

	order.odometer_in = int(odometer_in) if odometer_in else vehicle.current_mileage
	order.fuel_level = fuel_level
	order.customer_complaint = customer_complaint or order.customer_complaint
	order.existing_damage = existing_damage
	order.vehicle_contents = vehicle_contents
	order.intake_confirmed = intake_confirmed
	order.customer_signature = customer_signature
	order.intake_frozen = 1
	order.checked_in_on = now_datetime()
	order.checked_in_by = frappe.session.user
	order.status = CHECKED_IN
	order.save(ignore_permissions=True)

	# Update vehicle status and mileage
	vehicle.current_mileage = order.odometer_in
	vehicle.current_service_order = order.name
	vehicle.vehicle_status = "Checked In"

	settings = frappe.get_cached_doc("Vehicle Service Settings")
	if settings.reception_location:
		vehicle.move_location(settings.reception_location, _("Vehicle checked in"), order.name)
	vehicle.save(ignore_permissions=True)

	# If service package attached, apply it now
	if order.service_package:
		apply_service_package(order.name, order.service_package)

	try:
		from vehicle_service.vehicle_service.notifications import send_intake_confirmation
		send_intake_confirmation(order.name)
	except Exception:
		frappe.log_error(title="Failed to auto-send intake confirmation", message=frappe.get_traceback())

	return {"status": "success", "order_status": order.status}


@frappe.whitelist()
def correct_intake(order_name: str, fieldname: str, new_value: str, reason: str):
	order = frappe.get_doc("Service Order", order_name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if not (roles & {"Service Advisor", "Service Manager", "System Manager"}):
		frappe.throw(_("Only Service Advisors or Managers can correct intake information."))

	if not reason:
		frappe.throw(_("A valid reason is required for intake corrections."))

	old_val = str(order.get(fieldname) or "")
	label = order.meta.get_label(fieldname)

	order.append(
		"corrections",
		{
			"field_label": label,
			"fieldname": fieldname,
			"old_value": old_val,
			"new_value": str(new_value),
			"reason": reason,
			"corrected_by": user,
			"corrected_on": now_datetime(),
		},
	)

	frappe.flags.in_correction = True
	if fieldname == "odometer_in":
		order.odometer_in = int(new_value)
		if order.vehicle:
			v = frappe.get_doc("Service Vehicle", order.vehicle)
			v.current_mileage = order.odometer_in
			v.save(ignore_permissions=True)
	else:
		order.set(fieldname, new_value)

	order.save(ignore_permissions=True)
	frappe.flags.in_correction = False

	return {"status": "success"}


@frappe.whitelist()
def apply_service_package(order_name: str, package_name: str):
	order = frappe.get_doc("Service Order", order_name)
	pkg = frappe.get_doc("Service Package", package_name)

	created_jobs = {}
	# Create jobs
	for j in pkg.jobs:
		job = frappe.new_doc("Service Job")
		job.service_order = order.name
		job.job_title = j.job_title
		job.category = j.category or "Essential"
		job.estimated_hours = j.estimated_hours or 1.0
		job.description = j.description
		job.status = "Pending Approval"
		job.source = "Package"
		job.insert(ignore_permissions=True)
		created_jobs[j.job_title] = job.name

	# Add parts
	for p in pkg.parts:
		linked_job = created_jobs.get(p.job_title) if p.job_title else None
		order.append(
			"parts",
			{
				"item_code": p.item_code,
				"job": linked_job,
				"category": p.category or "Essential",
				"qty_required": p.qty or 1.0,
				"approval_status": "Pending",
				"part_status": "Pending Approval",
				"source": "Package",
			},
		)

	order.save(ignore_permissions=True)
	return {"status": "success", "jobs_count": len(pkg.jobs), "parts_count": len(pkg.parts)}


@frappe.whitelist()
def make_service_quotation(order_name: str):
	order = frappe.get_doc("Service Order", order_name)
	settings = frappe.get_cached_doc("Vehicle Service Settings")

	existing = frappe.db.get_value(
		"Quotation",
		{"vs_service_order": order.name, "docstatus": 0},
		"name",
	)
	if existing:
		return {"status": "success", "quotation": existing, "existing": True}

	quotation = frappe.new_doc("Quotation")
	quotation.quotation_to = "Customer"
	quotation.party_name = order.customer
	quotation.company = order.company
	quotation.transaction_date = nowdate()
	quotation.vs_service_order = order.name
	quotation.vs_vehicle = order.vehicle
	quotation.vs_service_advisor = order.service_advisor or frappe.session.user

	jobs = frappe.get_all(
		"Service Job",
		filters={"service_order": order.name, "quotation": ["in", ["", None]], "status": "Pending Approval"},
		fields=["name", "job_title", "category", "estimated_hours"],
	)
	parts = [p for p in order.parts if not p.quotation and p.approval_status == "Pending"]

	labour_item = settings.labour_item
	labour_rate = flt(settings.labour_rate) or 50.0

	for j in jobs:
		quotation.append(
			"items",
			{
				"item_code": labour_item or "Labour",
				"item_name": j.job_title,
				"description": f"Labour for job: {j.job_title}",
				"qty": flt(j.estimated_hours) or 1.0,
				"rate": labour_rate,
				"vs_job": j.name,
				"vs_category": j.category or "Maintenance",
				"vs_approval": "Pending",
			},
		)

	for p in parts:
		rate = frappe.db.get_value("Item Price", {"item_code": p.item_code, "price_list": "Standard Selling"}, "price_list_rate") or 0.0
		quotation.append(
			"items",
			{
				"item_code": p.item_code,
				"qty": flt(p.qty_required) or 1.0,
				"rate": flt(rate),
				"vs_part_row": p.name,
				"vs_category": p.category or "Maintenance",
				"vs_approval": "Pending",
			},
		)

	quotation.order_type = "Sales"
	if not quotation.items:
		quotation.total = 0.0
		quotation.base_total = 0.0
		quotation.net_total = 0.0
		quotation.base_net_total = 0.0
		quotation.grand_total = 0.0
		quotation.base_grand_total = 0.0
		quotation.rounded_total = 0.0
		quotation.base_rounded_total = 0.0
		quotation.insert(ignore_permissions=True, ignore_mandatory=True)
	else:
		quotation.insert(ignore_permissions=True)

	for q_item in quotation.items:
		if q_item.vs_job:
			frappe.db.set_value("Service Job", q_item.vs_job, {"quotation": quotation.name, "quotation_item": q_item.name})
		elif q_item.vs_part_row:
			for p in order.parts:
				if p.name == q_item.vs_part_row:
					p.quotation = quotation.name
					p.quotation_item = q_item.name
					p.rate = q_item.rate

	if order.status in [DRAFT, CHECKED_IN]:
		order.status = AWAITING_APPROVAL
		order.save(ignore_permissions=True)

	return {"status": "success", "quotation": quotation.name, "existing": False}


@frappe.whitelist()
def create_estimate(order_name: str):
	order = frappe.get_doc("Service Order", order_name)
	settings = frappe.get_cached_doc("Vehicle Service Settings")

	jobs = frappe.get_all(
		"Service Job",
		filters={"service_order": order.name, "quotation": ["in", ["", None]], "status": "Pending Approval"},
		fields=["name", "job_title", "category", "estimated_hours"],
	)

	parts = [p for p in order.parts if not p.quotation and p.approval_status == "Pending"]

	if not jobs and not parts:
		frappe.throw(_("No un-estimated jobs or parts found on this order."))

	labour_item = settings.labour_item
	labour_rate = flt(settings.labour_rate) or 50.0

	quotation = frappe.new_doc("Quotation")
	quotation.quotation_to = "Customer"
	quotation.party_name = order.customer
	quotation.company = order.company
	quotation.transaction_date = nowdate()
	quotation.vs_service_order = order.name
	quotation.vs_vehicle = order.vehicle
	quotation.vs_service_advisor = order.service_advisor or frappe.session.user

	# Add labour lines
	for j in jobs:
		quotation.append(
			"items",
			{
				"item_code": labour_item or "Labour",
				"item_name": j.job_title,
				"description": f"Labour for job: {j.job_title}",
				"qty": flt(j.estimated_hours) or 1.0,
				"rate": labour_rate,
				"vs_job": j.name,
				"vs_category": j.category,
				"vs_approval": "Pending",
			},
		)

	# Add parts lines
	for p in parts:
		rate = frappe.db.get_value("Item Price", {"item_code": p.item_code, "price_list": "Standard Selling"}, "price_list_rate") or 0.0
		quotation.append(
			"items",
			{
				"item_code": p.item_code,
				"qty": flt(p.qty_required) or 1.0,
				"rate": flt(rate),
				"vs_part_row": p.name,
				"vs_category": p.category,
				"vs_approval": "Pending",
			},
		)

	quotation.insert(ignore_permissions=True)

	# Back-link quotation
	for q_item in quotation.items:
		if q_item.vs_job:
			frappe.db.set_value("Service Job", q_item.vs_job, {"quotation": quotation.name, "quotation_item": q_item.name})
		elif q_item.vs_part_row:
			for p in order.parts:
				if p.name == q_item.vs_part_row:
					p.quotation = quotation.name
					p.quotation_item = q_item.name
					p.rate = q_item.rate

	order.status = AWAITING_APPROVAL
	order.save(ignore_permissions=True)

	try:
		from vehicle_service.vehicle_service.notifications import send_estimate_approval_request
		send_estimate_approval_request(order.name, quotation.name)
	except Exception:
		frappe.log_error(title="Failed to auto-send estimate approval request", message=frappe.get_traceback())

	return {"status": "success", "quotation": quotation.name}


@frappe.whitelist()
def record_customer_approval(
	order_name: str,
	quotation_name: str,
	approvals_json: str | dict,
	approval_method: str = "Phone",
	approved_by_customer: str | None = None,
	notes: str | None = None,
):
	"""Approvals format: { quotation_item_name: 'Approved' | 'Declined' }"""
	order = frappe.get_doc("Service Order", order_name)
	quotation = frappe.get_doc("Quotation", quotation_name)
	decisions = json.loads(approvals_json) if isinstance(approvals_json, str) else approvals_json

	total_approved = 0.0
	total_declined = 0.0
	approved_items = []

	for item in quotation.items:
		status = decisions.get(item.name, "Approved")
		item.vs_approval = status
		if status == "Approved":
			total_approved += flt(item.amount)
			approved_items.append(item.name)
		else:
			total_declined += flt(item.amount)

	quotation.save(ignore_permissions=True)
	quotation.submit()

	sales_order_name = None
	# If any item was approved, generate Sales Order for approved items only
	if approved_items:
		from erpnext.selling.doctype.quotation.quotation import _make_sales_order

		frappe.flags.args = {"selected_items": [{"name": i} for i in approved_items]}
		so = _make_sales_order(quotation.name, ignore_permissions=True)
		so.vs_service_order = order.name
		delivery_date = order.expected_completion or add_days(nowdate(), 1)
		so.delivery_date = delivery_date
		def_wh = frappe.db.get_value("Warehouse", {"company": so.company, "is_group": 0}, "name")
		for itm in so.items:
			if not itm.delivery_date:
				itm.delivery_date = delivery_date
			if not itm.warehouse and frappe.db.get_value("Item", itm.item_code, "is_stock_item"):
				itm.warehouse = (
					frappe.db.get_value("Item Default", {"parent": itm.item_code, "company": so.company}, "default_warehouse")
					or def_wh
				)
		so.insert(ignore_permissions=True)
		so.submit()
		sales_order_name = so.name

		# Map SO detail back to jobs and parts
		for so_item in so.items:
			q_item = next((qi for qi in quotation.items if qi.name == so_item.quotation_item), None)
			if q_item:
				if q_item.vs_job:
					frappe.db.set_value(
						"Service Job",
						q_item.vs_job,
						{
							"sales_order": so.name,
							"so_detail": so_item.name,
							"status": "Approved",
						},
					)
				elif q_item.vs_part_row:
					for p in order.parts:
						if p.name == q_item.vs_part_row:
							p.sales_order = so.name
							p.so_detail = so_item.name
							p.approval_status = "Approved"
							p.part_status = PART_REQUIRED
							p.rate = so_item.rate

	# Mark declined items
	for item in quotation.items:
		if item.vs_approval == "Declined":
			if item.vs_job:
				frappe.db.set_value("Service Job", item.vs_job, "status", "Declined")
			elif item.vs_part_row:
				for p in order.parts:
					if p.name == item.vs_part_row:
						p.approval_status = "Declined"
						p.part_status = "Declined"

	# Append Approval Log Row
	round_no = len(order.approvals) + 1
	order.append(
		"approvals",
		{
			"round": round_no,
			"quotation": quotation.name,
			"sales_order": sales_order_name,
			"approval_method": approval_method,
			"approved_by_customer": approved_by_customer or order.driver_name,
			"approved_amount": total_approved,
			"declined_amount": total_declined,
			"recorded_by": frappe.session.user,
			"approved_on": now_datetime(),
			"notes": notes,
		},
	)

	if approved_items:
		order.status = "Approved"
	else:
		order.status = "Cancelled"
		order.cancellation_reason = _("All estimate items declined by customer.")

	order.save(ignore_permissions=True)
	order.sync_status_from_jobs_and_parts()

	return {
		"status": "success",
		"sales_order": sales_order_name,
		"order_status": order.status,
	}


@frappe.whitelist()
def assign_job(job_name: str, technician: str, bay: str | None = None):
	job = frappe.get_doc("Service Job", job_name)
	emp = frappe.get_doc("Employee", technician)

	job.technician = emp.name
	job.technician_user = emp.user_id
	if bay:
		job.bay = bay
	job.status = "Assigned"
	job.save(ignore_permissions=True)

	order = frappe.get_doc("Service Order", job.service_order)
	if bay:
		vehicle = frappe.get_doc("Service Vehicle", order.vehicle)
		vehicle.move_location(bay, _("Assigned to bay {0}").format(bay), order.name)
		if not vehicle.custodian and emp.user_id:
			vehicle.custodian = emp.user_id
			vehicle.save(ignore_permissions=True)

	order.sync_status_from_jobs_and_parts()

	return {"status": "success", "job_status": job.status, "order_status": order.status}


@frappe.whitelist()
def issue_parts_to_workshop(order_name: str, items_json: str | list):
	"""Issues approved parts from Parts Store Warehouse to Workshop WIP Warehouse via Stock Entry."""
	order = frappe.get_doc("Service Order", order_name)
	settings = frappe.get_cached_doc("Vehicle Service Settings")

	stores_wh = settings.parts_warehouse
	wip_wh = settings.wip_warehouse

	if not stores_wh or not wip_wh:
		frappe.throw(_("Please configure Parts Store and Workshop WIP Warehouses in Vehicle Service Settings."))

	items = json.loads(items_json) if isinstance(items_json, str) else items_json

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.company = order.company
	se.vs_service_order = order.name
	se.from_warehouse = stores_wh
	se.to_warehouse = wip_wh

	for itm in items:
		part_row_name = itm.get("part_row")
		qty = flt(itm.get("qty"))
		part_row = next((p for p in order.parts if p.name == part_row_name), None)
		if not part_row:
			continue

		issuable = flt(part_row.qty_required) - qty_on_vehicle(part_row)
		if qty > issuable:
			frappe.throw(_("Cannot issue {0} units for {1}. Max issuable is {2}.").format(qty, part_row.item_code, issuable))

		se.append(
			"items",
			{
				"item_code": part_row.item_code,
				"qty": qty,
				"s_warehouse": stores_wh,
				"t_warehouse": wip_wh,
				"vs_part_row": part_row.name,
			},
		)

	se.insert(ignore_permissions=True)
	se.submit()

	# Recalculate quantities on order parts
	recalculate_order_parts_from_stock(order.name)

	return {"status": "success", "stock_entry": se.name}


@frappe.whitelist()
def return_parts_from_workshop(order_name: str, items_json: str | list):
	"""Returns unconsumed parts from Workshop WIP Warehouse back to Parts Store Warehouse."""
	order = frappe.get_doc("Service Order", order_name)
	settings = frappe.get_cached_doc("Vehicle Service Settings")

	stores_wh = settings.parts_warehouse
	wip_wh = settings.wip_warehouse

	items = json.loads(items_json) if isinstance(items_json, str) else items_json

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.company = order.company
	se.vs_service_order = order.name
	se.from_warehouse = wip_wh
	se.to_warehouse = stores_wh

	for itm in items:
		part_row_name = itm.get("part_row")
		qty = flt(itm.get("qty"))
		part_row = next((p for p in order.parts if p.name == part_row_name), None)
		if not part_row:
			continue

		current_on_vehicle = qty_on_vehicle(part_row)
		if qty > current_on_vehicle:
			frappe.throw(_("Cannot return {0} units of {1}. Current issued on vehicle is only {2}.").format(qty, part_row.item_code, current_on_vehicle))

		se.append(
			"items",
			{
				"item_code": part_row.item_code,
				"qty": qty,
				"s_warehouse": wip_wh,
				"t_warehouse": stores_wh,
				"vs_part_row": part_row.name,
			},
		)

	se.insert(ignore_permissions=True)
	se.submit()

	recalculate_order_parts_from_stock(order.name)

	return {"status": "success", "stock_entry": se.name}


def recalculate_order_parts_from_stock(order_name: str):
	order = frappe.get_doc("Service Order", order_name)
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	wip_wh = settings.wip_warehouse

	# Fetch sum of issued and returned for each part row from submitted Stock Entries
	entries = frappe.db.sql(
		"""
		SELECT sed.vs_part_row, sed.t_warehouse, sed.s_warehouse, SUM(sed.qty) as total_qty
		FROM `tabStock Entry Detail` sed
		JOIN `tabStock Entry` se ON se.name = sed.parent
		WHERE se.vs_service_order = %s AND se.docstatus = 1 AND sed.vs_part_row IS NOT NULL
		GROUP BY sed.vs_part_row, sed.t_warehouse, sed.s_warehouse
	""",
		(order.name,),
		as_dict=True,
	)

	issued_map = {}
	returned_map = {}
	for e in entries:
		if e.t_warehouse == wip_wh:
			issued_map[e.vs_part_row] = issued_map.get(e.vs_part_row, 0.0) + flt(e.total_qty)
		elif e.s_warehouse == wip_wh:
			returned_map[e.vs_part_row] = returned_map.get(e.vs_part_row, 0.0) + flt(e.total_qty)

	for p in order.parts:
		p.qty_issued = issued_map.get(p.name, 0.0)
		p.qty_returned = returned_map.get(p.name, 0.0)
		p.qty_used = round(p.qty_issued - p.qty_returned, 2)
		p.part_status = compute_part_status(p)

	order.save(ignore_permissions=True)
	order.sync_status_from_jobs_and_parts()


@frappe.whitelist()
def create_sales_invoice_from_order(order_name: str):
	order = frappe.get_doc("Service Order", order_name)
	if order.status != READY_FOR_BILLING:
		frappe.throw(_("Sales Invoice can only be created when Service Order is in 'Ready for Billing' status (Current: {0}).").format(order.status))

	if order.sales_invoice and frappe.db.exists("Sales Invoice", order.sales_invoice):
		return {"status": "success", "sales_invoice": order.sales_invoice}

	settings = frappe.get_cached_doc("Vehicle Service Settings")
	wip_wh = settings.wip_warehouse
	labour_item = settings.labour_item or "Labour"
	labour_rate = flt(settings.labour_rate) or 50.0

	si = frappe.new_doc("Sales Invoice")
	si.customer = order.customer
	si.company = order.company
	si.posting_date = nowdate()
	si.vs_service_order = order.name
	si.update_stock = 1

	# Jobs Labour billing
	jobs = frappe.get_all(
		"Service Job",
		filters={"service_order": order.name, "status": ["in", [JOB_DONE, "Completed", "Passed"]]},
		fields=["name", "job_title", "sales_order", "so_detail", "estimated_hours", "actual_hours"],
	)

	for j in jobs:
		billable_hours = billable_labour_hours(j.estimated_hours, j.actual_hours, settings.labour_billing_basis)
		if billable_hours > 0:
			si.append(
				"items",
				{
					"item_code": labour_item,
					"item_name": j.job_title,
					"description": f"Labour for job: {j.job_title} ({billable_hours} hrs)",
					"qty": billable_hours,
					"rate": labour_rate,
					"sales_order": j.sales_order,
					"so_detail": j.so_detail,
					"vs_job": j.name,
				},
			)

	# Parts billing (only parts actually consumed/used)
	for p in order.parts:
		if p.approval_status == "Approved" and p.qty_used > 0:
			si.append(
				"items",
				{
					"item_code": p.item_code,
					"qty": p.qty_used,
					"rate": flt(p.rate),
					"warehouse": wip_wh,
					"sales_order": p.sales_order,
					"so_detail": p.so_detail,
					"vs_part_row": p.name,
				},
			)

	si.insert(ignore_permissions=True)

	order.sales_invoice = si.name
	order.save(ignore_permissions=True)

	return {"status": "success", "sales_invoice": si.name}


@frappe.whitelist()
def release_on_credit(order_name: str, reason: str):
	order = frappe.get_doc("Service Order", order_name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if not (roles & {"Service Accounts", "Service Manager", "System Manager"}):
		frappe.throw(_("Only Accounts or Service Managers can authorise release on credit."))

	order.credit_released = 1
	order.credit_release_reason = reason
	order.status = READY_FOR_COLLECTION
	order.save(ignore_permissions=True)

	# Update vehicle status
	frappe.db.set_value("Service Vehicle", order.vehicle, "vehicle_status", "Ready for Collection")

	return {"status": "success", "order_status": order.status}


@frappe.whitelist()
def deliver_vehicle(
	order_name: str,
	odometer_out: int,
	collected_by: str,
	delivery_notes: str | None = None,
	delivery_signature: str | None = None,
):
	order = frappe.get_doc("Service Order", order_name)
	if order.status != READY_FOR_COLLECTION:
		frappe.throw(_("Vehicle can only be delivered when in 'Ready for Collection' status (Current: {0}).").format(order.status))

	odometer = int(odometer_out)
	if order.odometer_in and odometer < order.odometer_in:
		frappe.throw(_("Odometer out ({0} km) cannot be less than intake odometer ({1} km).").format(odometer, order.odometer_in))

	order.odometer_out = odometer
	order.collected_by = collected_by
	order.delivery_notes = delivery_notes
	order.delivery_signature = delivery_signature
	order.delivered_on = now_datetime()
	order.status = DELIVERED
	order.save(ignore_permissions=True)

	# Update Vehicle lifetime history
	vehicle = frappe.get_doc("Service Vehicle", order.vehicle)
	vehicle.current_mileage = odometer
	vehicle.last_service_date = nowdate()
	vehicle.last_service_mileage = odometer
	vehicle.vehicle_status = "Outside Workshop"
	vehicle.current_service_order = None
	vehicle.current_location = None
	vehicle.custodian = None
	vehicle.save(ignore_permissions=True)

	# Schedule satisfaction follow-up ToDo for Service Advisor (+3 days)
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	followup_days = settings.satisfaction_followup_days or 3
	followup_date = add_days(nowdate(), followup_days)

	if order.service_advisor:
		todo = frappe.new_doc("ToDo")
		todo.allocated_to = order.service_advisor
		todo.date = followup_date
		todo.description = _("Customer Satisfaction Follow-up: Vehicle {0} ({1}), Customer: {2} ({3})").format(
			vehicle.registration_no, vehicle.make or "", order.customer_name or "", order.driver_phone or ""
		)
		todo.reference_type = "Service Order"
		todo.reference_name = order.name
		todo.insert(ignore_permissions=True)

	return {"status": "success", "order_status": order.status}


@frappe.whitelist()
def cancel_order(order_name: str, reason: str):
	order = frappe.get_doc("Service Order", order_name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))

	# Guard: cannot cancel if parts are still issued
	for p in order.parts:
		if qty_on_vehicle(p) > 0:
			frappe.throw(_("Cannot cancel order: part '{0}' has {1} units issued in workshop. Return parts first.").format(p.item_code, qty_on_vehicle(p)))

	if order.status not in (DRAFT, CHECKED_IN, AWAITING_APPROVAL):
		if not (roles & {"Service Manager", "System Manager"}):
			frappe.throw(_("Only Service Managers can cancel an order that has already been approved."))

	order.status = CANCELLED
	order.cancellation_reason = reason
	order.save(ignore_permissions=True)

	# Cancel pending / assigned jobs
	jobs = frappe.get_all("Service Job", filters={"service_order": order.name, "status": ["not in", ["Cancelled", "Passed"]]}, pluck="name")
	for j in jobs:
		frappe.db.set_value("Service Job", j, "status", "Cancelled")

	if order.vehicle:
		vehicle = frappe.get_doc("Service Vehicle", order.vehicle)
		if vehicle.current_service_order == order.name:
			vehicle.current_service_order = None
			vehicle.vehicle_status = "Outside Workshop"
			vehicle.save(ignore_permissions=True)

	return {"status": "success", "order_status": order.status}
