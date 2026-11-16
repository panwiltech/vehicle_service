# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import base64
import copy
import os
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	cint,
	date_diff,
	flt,
	format_datetime,
	get_datetime,
	get_fullname,
	getdate,
	now_datetime,
	nowdate,
)

HISTORY_VIEWER_ROLES: set[str] = {
	"System Manager",
	"Service Manager",
	"Service Advisor",
	"Service Receptionist",
	"Workshop Supervisor",
	"Job Controller",
	"Workshop Technician",
	"QC Inspector",
	"Parts Controller",
	"Parts Manager",
	"Service Accounts",
	"Accounts User",
	"Accounts Manager",
}

FINANCIAL_ROLES: set[str] = {
	"System Manager",
	"Service Manager",
	"Service Advisor",
	"Workshop Supervisor",
	"Job Controller",
	"Service Accounts",
	"Accounts User",
	"Accounts Manager",
}

CROSS_BRANCH_ROLES: set[str] = {
	"System Manager",
	"Service Manager",
	"Accounts Manager",
}

_SOURCE_PRIORITY: dict[str, int] = {
	"Registration": 0,
	"VIN": 1,
	"Previous Registration": 2,
	"Historical Record": 3,
}

_VEHICLE_SELECT_COLS = """
	sv.name,
	sv.registration_no,
	sv.previous_registration_nos,
	sv.vin,
	sv.make,
	sv.model,
	sv.year,
	sv.customer,
	sv.customer_name,
	sv.current_mileage,
	sv.vehicle_status
"""


def _require_history_viewer() -> tuple[str, set[str]]:
	"""Verify the session user is signed in and holds a Vehicle Service History viewer role."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(
			_("Access denied: please sign in to view Vehicle Service History."),
			frappe.PermissionError,
		)

	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not (roles & HISTORY_VIEWER_ROLES):
		frappe.throw(
			_("Access denied: you do not have permission to view Vehicle Service History."),
			frappe.PermissionError,
		)
	return user, roles


def normalize_lookup_token(query: str) -> tuple[str, str]:
	"""Return `(clean_query, stripped_query)` uppercased with spaces/hyphens removed."""
	raw = "" if query is None else str(query)
	clean_query = raw.strip().upper()
	stripped_query = re.sub(r"[\s\-]+", "", clean_query)
	return clean_query, stripped_query


def _normalize_stripped(value: str | None) -> str:
	return normalize_lookup_token(value or "")[1]


def _escape_like(val: str) -> str:
	"""Escape backslash and LIKE wildcards (`%`, `_`) for MariaDB `ESCAPE '\\\\'`."""
	return (val or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _norm_sql(column_expr: str) -> str:
	# Only pass static trusted column identifiers into this helper.
	return f"REPLACE(REPLACE(UPPER(IFNULL({column_expr}, '')), ' ', ''), '-', '')"


def _best_score(scores: list[tuple[int, int, str]]) -> tuple[int, int, str] | None:
	return min(scores) if scores else None


def _score_vehicle_row(row: dict, stripped_query: str) -> tuple[int, int, str] | None:
	scores: list[tuple[int, int, str]] = []

	norm_reg = _normalize_stripped(row.get("registration_no"))
	if norm_reg:
		if norm_reg == stripped_query:
			scores.append((0, _SOURCE_PRIORITY["Registration"], "Registration"))
		elif norm_reg.startswith(stripped_query):
			scores.append((1, _SOURCE_PRIORITY["Registration"], "Registration"))
		elif stripped_query in norm_reg:
			scores.append((3, _SOURCE_PRIORITY["Registration"], "Registration"))

	norm_vin = _normalize_stripped(row.get("vin"))
	if norm_vin:
		if norm_vin == stripped_query:
			scores.append((0, _SOURCE_PRIORITY["VIN"], "VIN"))
		elif norm_vin.startswith(stripped_query):
			scores.append((1, _SOURCE_PRIORITY["VIN"], "VIN"))
		elif stripped_query in norm_vin:
			scores.append((3, _SOURCE_PRIORITY["VIN"], "VIN"))

	prev_raw = row.get("previous_registration_nos") or ""
	if prev_raw:
		prev_tokens = [_normalize_stripped(part) for part in prev_raw.split(",") if _normalize_stripped(part)]
		if any(tok == stripped_query for tok in prev_tokens):
			scores.append((2, _SOURCE_PRIORITY["Previous Registration"], "Previous Registration"))
		elif any(stripped_query in tok for tok in prev_tokens) or stripped_query in _normalize_stripped(prev_raw):
			scores.append((3, _SOURCE_PRIORITY["Previous Registration"], "Previous Registration"))

	return _best_score(scores)


def _score_historical_row(row: dict, stripped_query: str) -> tuple[int, int, str] | None:
	hist_plate = _normalize_stripped(row.get("hist_plate"))
	hist_vin = _normalize_stripped(row.get("hist_vin"))

	if (hist_plate and hist_plate == stripped_query) or (hist_vin and hist_vin == stripped_query):
		return (2, _SOURCE_PRIORITY["Historical Record"], "Historical Record")
	if (hist_plate and stripped_query in hist_plate) or (hist_vin and stripped_query in hist_vin):
		return (3, _SOURCE_PRIORITY["Historical Record"], "Historical Record")
	return None


def _register_candidate(
	candidates: dict[str, tuple[tuple[int, int, str], dict]],
	row: dict,
	score: tuple[int, int, str] | None,
) -> None:
	if not score:
		return
	name = row["name"]
	existing = candidates.get(name)
	if existing is None or score[:2] < existing[0][:2]:
		candidates[name] = (score, row)


def _to_search_result(row: dict, match_source: str) -> dict:
	return {
		"name": row["name"],
		"registration_no": row["registration_no"],
		"previous_registration_nos": row["previous_registration_nos"],
		"vin": row["vin"],
		"make": row["make"],
		"model": row["model"],
		"year": row["year"],
		"customer": row["customer"],
		"customer_name": row["customer_name"],
		"current_mileage": row["current_mileage"],
		"vehicle_status": row["vehicle_status"],
		"match_source": match_source,
	}


@frappe.whitelist()
def search_vehicles(query: str, limit: int = 10) -> list[dict]:
	"""Search permitted Service Vehicle records by normalised registration, VIN, previous plate, or historical snapshot."""
	_require_history_viewer()

	clean_query, stripped_query = normalize_lookup_token(query)
	if not stripped_query:
		return []

	effective_limit = cint(limit)
	if effective_limit <= 0:
		effective_limit = 10
	effective_limit = min(effective_limit, 100)
	sql_limit = max(effective_limit * 10, 200)

	escaped_stripped = _escape_like(stripped_query)
	escaped_clean = _escape_like(clean_query)
	params = {
		"stripped_query": stripped_query,
		"stripped_prefix": f"{escaped_stripped}%",
		"stripped_like": f"%{escaped_stripped}%",
		"prev_exact_like": f"%,{escaped_stripped},%",
		"clean_like": f"%{escaped_clean}%",
		"sql_limit": sql_limit,
	}

	reg_expr = _norm_sql("sv.registration_no")
	vin_expr = _norm_sql("sv.vin")
	prev_expr = _norm_sql("sv.previous_registration_nos")

	direct_rows = frappe.db.sql(
		f"""
		SELECT {_VEHICLE_SELECT_COLS}
		FROM `tabService Vehicle` sv
		WHERE
			{reg_expr} LIKE %(stripped_like)s ESCAPE '\\\\'
			OR {vin_expr} LIKE %(stripped_like)s ESCAPE '\\\\'
			OR UPPER(IFNULL(sv.previous_registration_nos, '')) LIKE %(clean_like)s ESCAPE '\\\\'
			OR {prev_expr} LIKE %(stripped_like)s ESCAPE '\\\\'
		ORDER BY
			CASE
				WHEN {reg_expr} = %(stripped_query)s OR {vin_expr} = %(stripped_query)s THEN 0
				WHEN {reg_expr} LIKE %(stripped_prefix)s ESCAPE '\\\\'
				  OR {vin_expr} LIKE %(stripped_prefix)s ESCAPE '\\\\' THEN 1
				WHEN CONCAT(',', {prev_expr}, ',') LIKE %(prev_exact_like)s ESCAPE '\\\\' THEN 2
				ELSE 3
			END,
			sv.registration_no ASC
		LIMIT %(sql_limit)s
		""",
		params,
		as_dict=True,
	)

	vi_plate_expr = _norm_sql("vi.license_plate")
	vi_vin_expr = _norm_sql("vi.vin")
	intake_rows = frappe.db.sql(
		f"""
		SELECT {_VEHICLE_SELECT_COLS},
			vi.license_plate AS hist_plate,
			vi.vin AS hist_vin
		FROM `tabVehicle Intake` vi
		INNER JOIN `tabService Vehicle` sv ON sv.name = vi.vehicle
		WHERE IFNULL(vi.vehicle, '') != ''
			AND IFNULL(vi.status, '') != 'Cancelled'
			AND (
				{vi_plate_expr} LIKE %(stripped_like)s ESCAPE '\\\\'
				OR {vi_vin_expr} LIKE %(stripped_like)s ESCAPE '\\\\'
			)
		ORDER BY
			CASE
				WHEN {vi_plate_expr} = %(stripped_query)s OR {vi_vin_expr} = %(stripped_query)s THEN 0
				ELSE 1
			END,
			vi.modified DESC,
			sv.registration_no ASC
		LIMIT %(sql_limit)s
		""",
		params,
		as_dict=True,
	)

	si_plate_expr = _norm_sql("si.vs_license_plate")
	si_vin_expr = _norm_sql("si.vs_chassis_no")
	invoice_rows = frappe.db.sql(
		f"""
		SELECT {_VEHICLE_SELECT_COLS},
			si.vs_license_plate AS hist_plate,
			si.vs_chassis_no AS hist_vin
		FROM `tabSales Invoice` si
		INNER JOIN `tabService Order` so ON so.name = si.vs_service_order
		INNER JOIN `tabService Vehicle` sv ON sv.name = so.vehicle
		WHERE si.docstatus = 1
			AND IFNULL(si.vs_service_order, '') != ''
			AND IFNULL(so.vehicle, '') != ''
			AND IFNULL(so.status, '') != 'Cancelled'
			AND (
				{si_plate_expr} LIKE %(stripped_like)s ESCAPE '\\\\'
				OR {si_vin_expr} LIKE %(stripped_like)s ESCAPE '\\\\'
			)
		ORDER BY
			CASE
				WHEN {si_plate_expr} = %(stripped_query)s OR {si_vin_expr} = %(stripped_query)s THEN 0
				ELSE 1
			END,
			si.posting_date DESC,
			si.modified DESC,
			sv.registration_no ASC
		LIMIT %(sql_limit)s
		""",
		params,
		as_dict=True,
	)

	candidates: dict[str, tuple[tuple[int, int, str], dict]] = {}
	for row in direct_rows:
		_register_candidate(candidates, row, _score_vehicle_row(row, stripped_query))

	for row in intake_rows + invoice_rows:
		# Also evaluate current Service Vehicle fields so Registration/VIN/Previous Plate keep higher precedence.
		best = _best_score(
			[
				score
				for score in (_score_vehicle_row(row, stripped_query), _score_historical_row(row, stripped_query))
				if score is not None
			]
		)
		_register_candidate(candidates, row, best)

	ordered = sorted(
		candidates.values(),
		key=lambda item: (item[0][0], item[0][1], (item[1].get("registration_no") or item[1]["name"] or "")),
	)

	results: list[dict] = []
	for score, row in ordered:
		if not frappe.has_permission("Service Vehicle", "read", doc=row["name"]):
			continue
		results.append(_to_search_result(row, score[2]))
		if len(results) >= effective_limit:
			break

	return results


def resolve_vehicle_cluster(vehicle_name: str) -> tuple[Document, list[str]]:
	"""Load a Service Vehicle and collect all permitted Service Vehicle names sharing its normalised VIN."""
	_require_history_viewer()

	if not vehicle_name or not frappe.db.exists("Service Vehicle", vehicle_name):
		frappe.throw(
			_("Service Vehicle {0} not found.").format(vehicle_name or ""),
			frappe.DoesNotExistError,
		)

	vehicle_doc = frappe.get_doc("Service Vehicle", vehicle_name)
	if not frappe.has_permission("Service Vehicle", "read", doc=vehicle_doc):
		frappe.throw(
			_("Access denied: you do not have permission to view Service Vehicle {0}.").format(vehicle_doc.name),
			frappe.PermissionError,
		)

	norm_vin = _normalize_stripped(vehicle_doc.vin)
	if not norm_vin:
		return vehicle_doc, [vehicle_doc.name]

	vin_expr = _norm_sql("vin")
	matched_names = frappe.db.sql(
		f"""
		SELECT name
		FROM `tabService Vehicle`
		WHERE {vin_expr} = %(norm_vin)s
		ORDER BY creation ASC, name ASC
		""",
		{"norm_vin": norm_vin},
		pluck=True,
	)

	cluster_ids = [vehicle_doc.name]
	seen = {vehicle_doc.name}
	for name in matched_names:
		if name not in seen and frappe.has_permission("Service Vehicle", "read", doc=name):
			seen.add(name)
			cluster_ids.append(name)

	return vehicle_doc, cluster_ids


_COMPLETED_JOB_STATUSES = {"Completed", "Passed"}
_COMPLETED_ORDER_STATUSES = {"Ready for Billing", "Invoiced", "Ready for Collection", "Delivered"}
_RECOMMENDED_CATEGORIES = {"Recommended", "Optional"}
_ADDITIONAL_SOURCES = {"Additional", "Additional Work"}
_RECOMMENDED_STATUSES = {"Declined", "Pending Approval"}
_REDACTED_JOB_FIELDS = ("rate", "amount", "supplier_cost", "supplier_invoice_ref")
_REDACTED_PART_FIELDS = ("rate", "amount")


def _to_date_str(value) -> str | None:
	return str(getdate(value)) if value else None


def _to_dt_str(value) -> str | None:
	return str(value) if value else None


def _get_user_scope(user: str, roles: set[str]) -> dict:
	"""Compute financial visibility and branch/company scope restrictions for a viewer."""
	is_admin = user == "Administrator"
	is_system_manager = is_admin or ("System Manager" in roles)
	can_view_financials = is_admin or bool(roles & FINANCIAL_ROLES)
	is_cross_branch = is_admin or bool(roles & CROSS_BRANCH_ROLES)

	allowed_branches: list[str] | None = None
	allowed_companies: list[str] | None = None
	intake_allowed_companies: list[str] | None = None

	if not is_system_manager:
		user_perms = frappe.permissions.get_user_permissions(user) or {}

		branch_perms = [
			p["doc"]
			for p in (user_perms.get("Branch") or [])
			if p.get("doc") and (not p.get("applicable_for") or p.get("applicable_for") == "Service Order")
		]
		if branch_perms:
			allowed_branches = sorted(set(branch_perms))
		elif not is_cross_branch:
			user_defaults = frappe.defaults.get_defaults_for(user) or {}
			default_branch = frappe.defaults.get_user_default("branch", user) or user_defaults.get("Branch")
			if isinstance(default_branch, list | tuple):
				default_branch = default_branch[0] if default_branch else None
			if default_branch:
				allowed_branches = [default_branch]

		company_rows = user_perms.get("Company") or []
		order_company_perms = [
			p["doc"]
			for p in company_rows
			if p.get("doc") and (not p.get("applicable_for") or p.get("applicable_for") == "Service Order")
		]
		intake_company_perms = [
			p["doc"]
			for p in company_rows
			if p.get("doc") and (not p.get("applicable_for") or p.get("applicable_for") == "Vehicle Intake")
		]
		if order_company_perms:
			allowed_companies = sorted(set(order_company_perms))
		if intake_company_perms:
			intake_allowed_companies = sorted(set(intake_company_perms))

	return {
		"can_view_financials": can_view_financials,
		"is_cross_branch": is_cross_branch,
		"allowed_branches": allowed_branches,
		"allowed_companies": allowed_companies,
		"intake_allowed_companies": intake_allowed_companies,
	}


def _serialize_vehicle_profile(vehicle_doc: Document) -> dict:
	return {
		"name": vehicle_doc.name,
		"registration_no": vehicle_doc.registration_no,
		"previous_registration_nos": vehicle_doc.previous_registration_nos,
		"vin": vehicle_doc.vin,
		"make": vehicle_doc.make,
		"model": vehicle_doc.model,
		"year": vehicle_doc.year,
		"colour": vehicle_doc.colour,
		"fuel_type": vehicle_doc.fuel_type,
		"transmission": vehicle_doc.transmission,
		"engine_no": vehicle_doc.engine_no,
		"customer": vehicle_doc.customer,
		"customer_name": vehicle_doc.customer_name,
		"driver_name": vehicle_doc.driver_name,
		"driver_phone": vehicle_doc.driver_phone,
		"vehicle_status": vehicle_doc.vehicle_status,
		"current_service_order": vehicle_doc.current_service_order,
		"current_location": vehicle_doc.current_location,
		"current_mileage": cint(vehicle_doc.current_mileage or 0),
		"last_service_date": _to_date_str(vehicle_doc.last_service_date),
		"last_service_mileage": cint(vehicle_doc.last_service_mileage or 0),
		"next_service_date": _to_date_str(vehicle_doc.next_service_date),
		"next_service_mileage": cint(vehicle_doc.next_service_mileage or 0),
	}


def _fetch_customer_profile(customer_id: str | None) -> dict:
	if not customer_id:
		return {}
	row = frappe.db.get_value(
		"Customer",
		customer_id,
		["name", "customer_name", "customer_group", "territory", "mobile_no", "email_id"],
		as_dict=True,
	)
	return dict(row) if row else {"name": customer_id}


def _fetch_orders_and_standalone_intakes(vehicle_ids: list[str], scope: dict) -> tuple[list[dict], list[dict]]:
	if not vehicle_ids:
		return [], []

	order_conditions = [
		"so.vehicle IN %(vehicle_ids)s",
		"IFNULL(so.status, '') != 'Draft'",
	]
	order_params: dict = {"vehicle_ids": tuple(vehicle_ids)}

	allowed_branches = scope.get("allowed_branches")
	if allowed_branches is not None:
		if allowed_branches:
			order_conditions.append("so.branch IN %(allowed_branches)s")
			order_params["allowed_branches"] = tuple(allowed_branches)
		else:
			order_conditions.append("1 = 0")

	allowed_companies = scope.get("allowed_companies")
	if allowed_companies is not None:
		if allowed_companies:
			order_conditions.append("so.company IN %(allowed_companies)s")
			order_params["allowed_companies"] = tuple(allowed_companies)
		else:
			order_conditions.append("1 = 0")

	orders = frappe.db.sql(
		f"""
		SELECT
			so.name, so.vehicle, so.vehicle_description, so.customer, so.customer_name,
			so.customer_po_no, so.driver_name, so.driver_phone, so.status, so.board_status,
			so.pause_reason, so.order_type, so.order_date, so.priority, so.service_advisor,
			so.expected_completion, so.current_location, so.company, so.branch, so.booking,
			so.warranty_of, so.vehicle_intake, so.odometer_in, so.odometer_out, so.fuel_level,
			so.service_package, so.customer_complaint, so.checked_in_on, so.checked_in_by,
			so.work_started_on, so.work_completed_on, so.on_hold, so.hold_reason,
			so.disputed, so.dispute_notes, so.sales_invoice, so.credit_released,
			so.credit_release_reason, so.last_qc, so.qc_result, so.delivered_on,
			so.collected_by, so.delivery_signature, so.delivery_notes, so.cancellation_reason,
			so.existing_damage, so.vehicle_contents, so.intake_confirmed, so.customer_signature,
			so.creation
		FROM `tabService Order` so
		WHERE {" AND ".join(order_conditions)}
		ORDER BY COALESCE(so.checked_in_on, so.order_date, so.creation) DESC, so.creation DESC
		""",
		order_params,
		as_dict=True,
	)

	intake_conditions = [
		"vi.vehicle IN %(vehicle_ids)s",
		"vi.status = 'Checked In'",
		"IFNULL(vi.service_order, '') = ''",
	]
	intake_params: dict = {"vehicle_ids": tuple(vehicle_ids)}

	intake_companies = scope.get("intake_allowed_companies")
	if intake_companies is not None:
		if intake_companies:
			intake_conditions.append("vi.company IN %(intake_companies)s")
			intake_params["intake_companies"] = tuple(intake_companies)
		else:
			intake_conditions.append("1 = 0")

	standalone_intakes = frappe.db.sql(
		f"""
		SELECT
			vi.name, vi.vehicle, vi.vehicle_description, vi.license_plate, vi.vin,
			vi.odometer_in, vi.customer, vi.customer_name, vi.driver_name, vi.driver_phone,
			vi.company, vi.service_advisor, vi.booking, vi.fuel_level, vi.customer_complaint,
			vi.reception_notes, vi.existing_damage, vi.vehicle_contents, vi.intake_confirmed,
			vi.customer_signature, vi.status, vi.service_order, vi.checked_in_on,
			vi.checked_in_by, vi.intake_frozen, vi.creation
		FROM `tabVehicle Intake` vi
		WHERE {" AND ".join(intake_conditions)}
		ORDER BY COALESCE(vi.checked_in_on, vi.creation) DESC, vi.creation DESC
		""",
		intake_params,
		as_dict=True,
	)

	return orders, standalone_intakes


def _fetch_intakes_and_photos(
	orders: list[dict], standalone_intakes: list[dict]
) -> tuple[dict[str, dict], dict[str, dict], dict[str, list[dict]]]:
	intakes_by_name: dict[str, dict] = {row["name"]: dict(row) for row in standalone_intakes}
	intakes_by_order: dict[str, dict] = {}
	photos_by_intake: dict[str, list[dict]] = {}

	order_names = [o["name"] for o in orders]
	linked_intake_names = [o["vehicle_intake"] for o in orders if o.get("vehicle_intake")]

	if order_names or linked_intake_names:
		clauses = []
		params: dict = {}
		if linked_intake_names:
			clauses.append("vi.name IN %(intake_names)s")
			params["intake_names"] = tuple(set(linked_intake_names))
		if order_names:
			clauses.append("vi.service_order IN %(order_names)s")
			params["order_names"] = tuple(order_names)

		rows = frappe.db.sql(
			f"""
			SELECT
				vi.name, vi.vehicle, vi.vehicle_description, vi.license_plate, vi.vin,
				vi.odometer_in, vi.customer, vi.customer_name, vi.driver_name, vi.driver_phone,
				vi.company, vi.service_advisor, vi.booking, vi.fuel_level, vi.customer_complaint,
				vi.reception_notes, vi.existing_damage, vi.vehicle_contents, vi.intake_confirmed,
				vi.customer_signature, vi.status, vi.service_order, vi.checked_in_on,
				vi.checked_in_by, vi.intake_frozen, vi.creation
			FROM `tabVehicle Intake` vi
			WHERE {" OR ".join(clauses)}
			""",
			params,
			as_dict=True,
		)
		for row in rows:
			item = dict(row)
			intakes_by_name[item["name"]] = item
			if item.get("service_order"):
				intakes_by_order[item["service_order"]] = item

	all_intake_names = list(intakes_by_name.keys())
	if all_intake_names:
		photo_rows = frappe.db.sql(
			"""
			SELECT name, parent, photo, description, taken_on
			FROM `tabVehicle Intake Photo`
			WHERE parent IN %(intake_names)s
			ORDER BY parent ASC, idx ASC
			""",
			{"intake_names": tuple(all_intake_names)},
			as_dict=True,
		)
		for p in photo_rows:
			photos_by_intake.setdefault(p["parent"], []).append(
				{
					"name": p["name"],
					"photo": p["photo"],
					"description": p["description"],
					"taken_on": _to_dt_str(p["taken_on"]),
				}
			)

	return intakes_by_name, intakes_by_order, photos_by_intake


def _merge_job_record(sj: dict | None, soj: dict | None, order_name: str) -> dict:
	primary = sj or soj or {}
	fallback = soj or sj or {}
	rate = flt(primary.get("rate")) or flt(fallback.get("rate"))
	amount = flt(primary.get("amount")) or flt(fallback.get("amount"))
	supplier_cost = flt(primary.get("supplier_cost")) or flt(fallback.get("supplier_cost"))
	return {
		"name": sj["name"] if sj else soj["name"],
		"service_job": sj["name"] if sj else (soj.get("service_job") if soj else None),
		"order_job_row": soj["name"] if soj else None,
		"service_order": order_name,
		"job_title": primary.get("job_title") or fallback.get("job_title"),
		"category": primary.get("category") or fallback.get("category"),
		"priority": primary.get("priority") or fallback.get("priority"),
		"status": primary.get("status") or fallback.get("status"),
		"technician": primary.get("technician") or fallback.get("technician"),
		"technician_name": primary.get("technician_name") or fallback.get("technician_name"),
		"bay": primary.get("bay") or fallback.get("bay"),
		"source": primary.get("source") or fallback.get("source"),
		"raised_by": sj.get("raised_by") if sj else None,
		"estimated_hours": flt(primary.get("estimated_hours") if primary.get("estimated_hours") is not None else fallback.get("estimated_hours")),
		"actual_hours": flt(primary.get("actual_hours") if primary.get("actual_hours") is not None else fallback.get("actual_hours")),
		"variance_hours": flt(sj.get("variance_hours")) if sj else 0.0,
		"service_item": primary.get("service_item") or fallback.get("service_item"),
		"description": sj.get("description") if sj else None,
		"customer_complaint": sj.get("customer_complaint") if sj else None,
		"reason_for_adding": primary.get("reason_for_adding") or fallback.get("reason_for_adding"),
		"pause_reason": sj.get("pause_reason") if sj else None,
		"qc_fail_reason": sj.get("qc_fail_reason") if sj else None,
		"follows_up_job": (sj.get("follows_up_job") if sj else None) or (soj.get("follows_up_job") if soj else None),
		"started_on": _to_dt_str(sj.get("started_on")) if sj else None,
		"completed_on": _to_dt_str(sj.get("completed_on")) if sj else None,
		"supplier": primary.get("supplier") or fallback.get("supplier"),
		"rate": rate,
		"amount": amount,
		"supplier_cost": supplier_cost,
		"supplier_invoice_ref": primary.get("supplier_invoice_ref") or fallback.get("supplier_invoice_ref"),
	}


def _fetch_jobs_by_order(order_names: list[str]) -> dict[str, list[dict]]:
	jobs_by_order: dict[str, list[dict]] = {}
	if not order_names:
		return jobs_by_order

	service_jobs = frappe.db.sql(
		"""
		SELECT
			name, service_order, vehicle, job_title, category, estimated_hours, status,
			priority, technician, technician_name, technician_user, bay, source, raised_by,
			actual_hours, variance_hours, customer_complaint, description, reason_for_adding,
			follows_up_job, started_on, completed_on, pause_reason, qc_fail_reason,
			service_item, rate, amount, supplier, supplier_cost, supplier_invoice_ref, creation
		FROM `tabService Job`
		WHERE service_order IN %(order_names)s
		ORDER BY creation ASC, name ASC
		""",
		{"order_names": tuple(order_names)},
		as_dict=True,
	)

	order_job_rows = frappe.db.sql(
		"""
		SELECT
			name, parent, idx, service_item, job_title, estimated_hours, rate, amount,
			actual_hours, status, technician, technician_name, bay, category, priority,
			source, service_job, follows_up_job, reason_for_adding, supplier,
			supplier_cost, supplier_invoice_ref
		FROM `tabService Order Job`
		WHERE parent IN %(order_names)s
		ORDER BY parent ASC, idx ASC
		""",
		{"order_names": tuple(order_names)},
		as_dict=True,
	)

	sj_by_name: dict[str, dict] = {sj["name"]: sj for sj in service_jobs}
	sjs_by_order: dict[str, list[dict]] = {}
	for sj in service_jobs:
		sjs_by_order.setdefault(sj["service_order"], []).append(sj)

	sojs_by_order: dict[str, list[dict]] = {}
	for row in order_job_rows:
		sojs_by_order.setdefault(row["parent"], []).append(row)

	for order_name in order_names:
		merged: list[dict] = []
		seen_sj: set[str] = set()
		for row in sojs_by_order.get(order_name, []):
			sj_name = row.get("service_job")
			sj_doc = sj_by_name.get(sj_name) if sj_name else None
			if sj_doc:
				seen_sj.add(sj_doc["name"])
			merged.append(_merge_job_record(sj_doc, row, order_name))

		for sj_doc in sjs_by_order.get(order_name, []):
			if sj_doc["name"] not in seen_sj:
				merged.append(_merge_job_record(sj_doc, None, order_name))

		jobs_by_order[order_name] = merged

	return jobs_by_order


def _fetch_parts_by_order(order_names: list[str]) -> dict[str, list[dict]]:
	parts_by_order: dict[str, list[dict]] = {}
	if not order_names:
		return parts_by_order

	part_rows = frappe.db.sql(
		"""
		SELECT
			name, parent, item_code, item_name, job, category, qty_required,
			qty_issued, qty_returned, qty_used, rate, part_status, approval_status,
			source, reason_for_adding, substituted_by, expected_date
		FROM `tabService Order Part`
		WHERE parent IN %(order_names)s
		ORDER BY parent ASC, idx ASC
		""",
		{"order_names": tuple(order_names)},
		as_dict=True,
	)
	for p in part_rows:
		parts_by_order.setdefault(p["parent"], []).append(
			{
				"name": p["name"],
				"service_order": p["parent"],
				"item_code": p["item_code"],
				"item_name": p["item_name"],
				"job": p["job"],
				"category": p["category"],
				"qty_required": flt(p["qty_required"]),
				"qty_issued": flt(p["qty_issued"]),
				"qty_returned": flt(p["qty_returned"]),
				"qty_used": flt(p["qty_used"]),
				"rate": flt(p["rate"]),
				"part_status": p["part_status"],
				"approval_status": p["approval_status"],
				"source": p["source"],
				"reason_for_adding": p["reason_for_adding"],
				"substituted_by": p["substituted_by"],
				"expected_date": _to_date_str(p["expected_date"]),
			}
		)
	return parts_by_order


def _fetch_qcs_by_order(order_names: list[str]) -> dict[str, list[dict]]:
	qcs_by_order: dict[str, list[dict]] = {}
	if not order_names:
		return qcs_by_order

	qc_rows = frappe.db.sql(
		"""
		SELECT
			name, service_order, vehicle, qc_template, inspector, inspected_on,
			result, road_test_done, road_test_km, findings, fail_reason, docstatus, creation
		FROM `tabService QC`
		WHERE service_order IN %(order_names)s
		  AND docstatus != 2
		ORDER BY inspected_on DESC, creation DESC
		""",
		{"order_names": tuple(order_names)},
		as_dict=True,
	)
	if not qc_rows:
		return qcs_by_order

	qc_names = [q["name"] for q in qc_rows]
	qc_items = frappe.db.sql(
		"""
		SELECT parent, check_item, passed, remarks
		FROM `tabService QC Item`
		WHERE parent IN %(qc_names)s
		ORDER BY parent ASC, idx ASC
		""",
		{"qc_names": tuple(qc_names)},
		as_dict=True,
	)
	items_by_qc: dict[str, list[dict]] = {}
	for item in qc_items:
		items_by_qc.setdefault(item["parent"], []).append(
			{
				"check_item": item["check_item"],
				"passed": cint(item["passed"]),
				"remarks": item["remarks"],
			}
		)

	for qc in qc_rows:
		qcs_by_order.setdefault(qc["service_order"], []).append(
			{
				"name": qc["name"],
				"service_order": qc["service_order"],
				"qc_template": qc["qc_template"],
				"inspector": qc["inspector"],
				"inspected_on": _to_dt_str(qc["inspected_on"]),
				"result": qc["result"],
				"road_test_done": cint(qc["road_test_done"]),
				"road_test_km": flt(qc["road_test_km"]),
				"findings": qc["findings"],
				"fail_reason": qc["fail_reason"],
				"docstatus": cint(qc["docstatus"]),
				"checklist": items_by_qc.get(qc["name"], []),
			}
		)

	return qcs_by_order


def _fetch_financials_bundle(orders: list[dict]) -> tuple[
	dict[str, list[dict]],
	dict[str, list[dict]],
	dict[str, list[dict]],
	dict[str, int],
]:
	invoices_by_order: dict[str, list[dict]] = {}
	items_by_invoice: dict[str, list[dict]] = {}
	payments_by_invoice: dict[str, list[dict]] = {}
	stock_item_map: dict[str, int] = {}

	if not orders:
		return invoices_by_order, items_by_invoice, payments_by_invoice, stock_item_map

	order_names = [o["name"] for o in orders]
	order_by_linked_inv = {o["sales_invoice"]: o["name"] for o in orders if o.get("sales_invoice")}

	inv_clauses = ["vs_service_order IN %(order_names)s"]
	inv_params: dict = {"order_names": tuple(order_names)}
	if order_by_linked_inv:
		inv_clauses.append("name IN %(linked_inv_names)s")
		inv_params["linked_inv_names"] = tuple(order_by_linked_inv.keys())

	inv_select = """
		name, vs_service_order, is_return, return_against, posting_date, due_date,
		grand_total, rounded_total, net_total, total, total_taxes_and_charges,
		discount_amount, outstanding_amount, paid_amount, total_advance, status, currency, creation
	"""
	primary_invoices = frappe.db.sql(
		f"""
		SELECT {inv_select}
		FROM `tabSales Invoice`
		WHERE docstatus = 1
		  AND ({" OR ".join(inv_clauses)})
		ORDER BY posting_date ASC, creation ASC
		""",
		inv_params,
		as_dict=True,
	)

	inv_by_name: dict[str, dict] = {}
	inv_to_order: dict[str, str] = {}
	for inv in primary_invoices:
		order_name = inv.get("vs_service_order") or order_by_linked_inv.get(inv["name"])
		if order_name:
			inv_by_name[inv["name"]] = dict(inv)
			inv_to_order[inv["name"]] = order_name

	primary_inv_names = list(inv_by_name.keys())
	if primary_inv_names:
		return_invoices = frappe.db.sql(
			f"""
			SELECT {inv_select}
			FROM `tabSales Invoice`
			WHERE docstatus = 1
			  AND is_return = 1
			  AND return_against IN %(primary_inv_names)s
			ORDER BY posting_date ASC, creation ASC
			""",
			{"primary_inv_names": tuple(primary_inv_names)},
			as_dict=True,
		)
		for ret in return_invoices:
			if ret["name"] not in inv_by_name:
				order_name = ret.get("vs_service_order") or inv_to_order.get(ret.get("return_against") or "")
				if order_name:
					inv_by_name[ret["name"]] = dict(ret)
					inv_to_order[ret["name"]] = order_name

	for inv in sorted(
		inv_by_name.values(),
		key=lambda row: (str(row.get("posting_date") or ""), str(row.get("creation") or ""), row["name"]),
	):
		order_name = inv_to_order[inv["name"]]
		invoices_by_order.setdefault(order_name, []).append(inv)

	all_inv_names = list(inv_by_name.keys())
	if all_inv_names:
		inv_items = frappe.db.sql(
			"""
			SELECT name, parent, item_code, item_name, qty, rate, amount, net_amount,
			       discount_amount, vs_job, vs_part_row
			FROM `tabSales Invoice Item`
			WHERE parent IN %(inv_names)s
			ORDER BY parent ASC, idx ASC
			""",
			{"inv_names": tuple(all_inv_names)},
			as_dict=True,
		)
		unclassified_items: set[str] = set()
		for it in inv_items:
			items_by_invoice.setdefault(it["parent"], []).append(dict(it))
			if not it.get("vs_job") and not it.get("vs_part_row") and it.get("item_code"):
				unclassified_items.add(it["item_code"])

		if unclassified_items:
			item_rows = frappe.get_all(
				"Item",
				filters={"name": ["in", list(unclassified_items)]},
				fields=["name", "is_stock_item"],
			)
			stock_item_map = {r["name"]: cint(r["is_stock_item"]) for r in item_rows}

		payment_rows = frappe.db.sql(
			"""
			SELECT per.reference_name AS invoice_name,
			       per.allocated_amount,
			       pe.name AS payment_entry,
			       pe.posting_date,
			       pe.payment_type,
			       pe.mode_of_payment,
			       pe.paid_amount,
			       pe.reference_no,
			       pe.reference_date
			FROM `tabPayment Entry Reference` per
			INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
			WHERE pe.docstatus = 1
			  AND per.reference_doctype = 'Sales Invoice'
			  AND per.reference_name IN %(inv_names)s
			ORDER BY pe.posting_date ASC, pe.creation ASC
			""",
			{"inv_names": tuple(all_inv_names)},
			as_dict=True,
		)
		for pay in payment_rows:
			payments_by_invoice.setdefault(pay["invoice_name"], []).append(
				{
					"payment_entry": pay["payment_entry"],
					"invoice_name": pay["invoice_name"],
					"posting_date": _to_date_str(pay["posting_date"]),
					"payment_type": pay["payment_type"],
					"mode_of_payment": pay["mode_of_payment"],
					"allocated_amount": flt(pay["allocated_amount"]),
					"reference_no": pay["reference_no"],
					"reference_date": _to_date_str(pay["reference_date"]),
				}
			)

	return invoices_by_order, items_by_invoice, payments_by_invoice, stock_item_map


def _empty_financials() -> dict:
	return {
		"labour_charges": 0.0,
		"parts_charges": 0.0,
		"additional_charges": 0.0,
		"discounts": 0.0,
		"total_invoice_value": 0.0,
		"outstanding_amount": 0.0,
		"paid_amount": 0.0,
		"invoice_number": None,
		"payment_status": "Not Invoiced",
		"credit_notes": [],
		"invoices": [],
		"payments": [],
	}


def _compute_order_financials(
	order_invoices: list[dict],
	items_by_invoice: dict[str, list[dict]],
	payments_by_invoice: dict[str, list[dict]],
	stock_item_map: dict[str, int],
	labour_item: str,
	jobs: list[dict],
	parts: list[dict],
) -> dict:
	if not order_invoices:
		labour_est = 0.0
		for j in jobs:
			if j.get("status") not in ("Cancelled", "Declined"):
				line_amt = flt(j.get("amount"))
				if not line_amt:
					line_amt = flt(j.get("estimated_hours")) * flt(j.get("rate"))
				labour_est += line_amt

		parts_est = 0.0
		for p in parts:
			if p.get("approval_status") == "Approved" and p.get("part_status") not in (
				"Declined",
				"Cancelled",
				"Substituted",
				"Returned",
			):
				if flt(p.get("qty_used")) > 0:
					billable_qty = flt(p["qty_used"])
				elif flt(p.get("qty_issued")) > 0:
					billable_qty = max(flt(p["qty_issued"]) - flt(p.get("qty_returned")), 0.0)
				else:
					billable_qty = flt(p.get("qty_required"))
				parts_est += billable_qty * flt(p.get("rate"))

		res = _empty_financials()
		res["labour_charges"] = round(labour_est, 2)
		res["parts_charges"] = round(parts_est, 2)
		return res

	labour_charges = 0.0
	parts_charges = 0.0
	additional_charges = 0.0
	discounts = 0.0
	order_payments: list[dict] = []
	invoice_summaries: list[dict] = []

	for inv in order_invoices:
		inv_name = inv["name"]
		discounts += flt(inv.get("discount_amount"))
		additional_charges += flt(inv.get("total_taxes_and_charges"))

		for it in items_by_invoice.get(inv_name, []):
			net_amt = flt(it.get("net_amount"))
			discounts += flt(it.get("discount_amount")) * flt(it.get("qty"))

			if it.get("vs_job"):
				labour_charges += net_amt
			elif it.get("vs_part_row"):
				parts_charges += net_amt
			elif it.get("item_code") in {labour_item, "LABOUR"}:
				labour_charges += net_amt
			elif stock_item_map.get(it.get("item_code") or ""):
				parts_charges += net_amt
			else:
				additional_charges += net_amt

		order_payments.extend(payments_by_invoice.get(inv_name, []))
		invoice_summaries.append(
			{
				"name": inv_name,
				"is_return": cint(inv.get("is_return")),
				"return_against": inv.get("return_against"),
				"posting_date": _to_date_str(inv.get("posting_date")),
				"due_date": _to_date_str(inv.get("due_date")),
				"grand_total": round(flt(inv.get("grand_total")), 2),
				"outstanding_amount": round(flt(inv.get("outstanding_amount")), 2),
				"status": inv.get("status"),
			}
		)

	total_invoice_value = round(sum(flt(inv.get("grand_total")) for inv in order_invoices), 2)
	net_outstanding = round(sum(flt(inv.get("outstanding_amount")) for inv in order_invoices), 2)
	non_return_invoices = [inv for inv in order_invoices if not cint(inv.get("is_return"))]
	return_invoices = [inv for inv in order_invoices if cint(inv.get("is_return"))]
	total_allocated_payments = round(sum(flt(p.get("allocated_amount")) for p in order_payments), 2)
	today_date = getdate(nowdate())

	if non_return_invoices and return_invoices and total_invoice_value <= 0:
		payment_status = "Credited"
	elif net_outstanding <= 0:
		payment_status = "Paid"
	elif (
		(0 < net_outstanding < total_invoice_value)
		or total_allocated_payments > 0
		or any(flt(inv.get("paid_amount")) > 0 or flt(inv.get("total_advance")) > 0 for inv in non_return_invoices)
	):
		payment_status = "Partly Paid"
	elif any(
		inv.get("due_date") and getdate(inv["due_date"]) < today_date and flt(inv.get("outstanding_amount")) > 0
		for inv in non_return_invoices
	):
		payment_status = "Overdue"
	else:
		payment_status = "Unpaid"

	primary_inv = non_return_invoices[-1] if non_return_invoices else order_invoices[-1]
	paid_amount = round(max(total_invoice_value - net_outstanding, 0.0), 2) if total_invoice_value > 0 else 0.0

	return {
		"labour_charges": round(labour_charges, 2),
		"parts_charges": round(parts_charges, 2),
		"additional_charges": round(additional_charges, 2),
		"discounts": round(discounts, 2),
		"total_invoice_value": total_invoice_value,
		"outstanding_amount": net_outstanding,
		"paid_amount": paid_amount,
		"invoice_number": primary_inv["name"],
		"payment_status": payment_status,
		"credit_notes": [inv["name"] for inv in return_invoices],
		"invoices": invoice_summaries,
		"payments": order_payments,
	}


def build_recommendations(
	vehicle_doc,
	orders: list[dict],
	jobs_by_order: dict,
	parts_by_order: dict,
	qcs_by_order: dict,
	last_recorded_mileage: int,
) -> dict:
	"""Build outstanding, completed, advisory, and scheduled maintenance recommendations."""
	non_cancelled_orders = [o for o in orders if o.get("status") not in ("Cancelled", "Draft")]

	followups_by_target: dict[str, list[dict]] = {}
	for order in non_cancelled_orders:
		for job in jobs_by_order.get(order["name"], []):
			target_id = job.get("follows_up_job")
			if target_id:
				followups_by_target.setdefault(target_id, []).append(job)

	outstanding: list[dict] = []
	completed: list[dict] = []
	advisory_notes: list[dict] = []
	listed_recommended_job_ids: set[str] = set()

	for order in non_cancelled_orders:
		order_name = order["name"]
		recommended_on = _to_date_str(order.get("checked_in_on") or order.get("order_date") or order.get("creation"))

		for job in jobs_by_order.get(order_name, []):
			is_recommended = (
				job.get("category") in _RECOMMENDED_CATEGORIES
				or job.get("source") in _ADDITIONAL_SOURCES
				or job.get("status") in _RECOMMENDED_STATUSES
			)
			if not is_recommended:
				continue

			job_id = job.get("service_job") or job.get("name")
			if job_id:
				listed_recommended_job_ids.add(job_id)
			if job.get("name"):
				listed_recommended_job_ids.add(job["name"])

			linked_completion_order = None
			linked_completion_job = None
			completed_on = None

			if job.get("status") in _COMPLETED_JOB_STATUSES:
				linked_completion_order = order_name
				linked_completion_job = job_id
				completed_on = job.get("completed_on") or _to_dt_str(order.get("work_completed_on"))
			else:
				for follow in followups_by_target.get(job_id or "", []):
					if follow.get("status") in _COMPLETED_JOB_STATUSES:
						linked_completion_order = follow.get("service_order")
						linked_completion_job = follow.get("service_job") or follow.get("name")
						completed_on = follow.get("completed_on")
						break

			entry = {
				"source_type": "Job",
				"source_id": job_id,
				"title": job.get("job_title"),
				"description": job.get("description") or job.get("reason_for_adding"),
				"category": job.get("category"),
				"source": job.get("source"),
				"original_status": job.get("status"),
				"status": "Completed" if linked_completion_job else "Outstanding",
				"recommended_on": recommended_on,
				"origin_order": order_name,
				"origin_vehicle": order.get("vehicle"),
				"linked_completion_order": linked_completion_order,
				"linked_completion_job": linked_completion_job,
				"completed_on": completed_on,
			}
			if linked_completion_job:
				completed.append(entry)
			else:
				outstanding.append(entry)

		for part in parts_by_order.get(order_name, []):
			if part.get("job") and part["job"] in listed_recommended_job_ids:
				continue
			is_recommended_part = (
				part.get("category") in _RECOMMENDED_CATEGORIES or part.get("approval_status") == "Declined"
			)
			if not is_recommended_part:
				continue

			is_completed_part = flt(part.get("qty_used")) > 0 and order.get("status") in _COMPLETED_ORDER_STATUSES
			orig_status = (
				"Declined"
				if part.get("approval_status") == "Declined"
				else (part.get("part_status") or part.get("category"))
			)
			part_entry = {
				"source_type": "Part",
				"source_id": part.get("name"),
				"title": part.get("item_name") or part.get("item_code"),
				"description": part.get("reason_for_adding"),
				"category": part.get("category"),
				"source": part.get("source"),
				"original_status": orig_status,
				"status": "Completed" if is_completed_part else "Outstanding",
				"recommended_on": recommended_on,
				"origin_order": order_name,
				"origin_vehicle": order.get("vehicle"),
				"linked_completion_order": order_name if is_completed_part else None,
				"linked_completion_job": part.get("job") if is_completed_part else None,
				"completed_on": _to_dt_str(order.get("work_completed_on")) if is_completed_part else None,
			}
			if is_completed_part:
				completed.append(part_entry)
			else:
				outstanding.append(part_entry)

		delivery_notes = (order.get("delivery_notes") or "").strip()
		if delivery_notes:
			advisory_notes.append(
				{
					"source_type": "Advisory Note",
					"source_doctype": "Service Order",
					"source_id": order_name,
					"origin_order": order_name,
					"title": _("Delivery Notes"),
					"note": delivery_notes,
					"recorded_on": _to_date_str(
						order.get("delivered_on")
						or order.get("work_completed_on")
						or order.get("order_date")
						or order.get("creation")
					),
					"status": "Advisory Logged",
				}
			)

		for qc in qcs_by_order.get(order_name, []):
			findings = (qc.get("findings") or "").strip()
			if findings:
				advisory_notes.append(
					{
						"source_type": "Advisory Note",
						"source_doctype": "Service QC",
						"source_id": qc["name"],
						"origin_order": order_name,
						"title": _("QC Inspection Findings ({0})").format(qc.get("result") or "QC"),
						"note": findings,
						"recorded_on": _to_date_str(
							qc.get("inspected_on") or order.get("order_date") or order.get("creation")
						),
						"status": "Advisory Logged",
					}
				)

	advisory_notes.sort(key=lambda item: (item.get("recorded_on") or "", item.get("source_id") or ""), reverse=True)

	scheduled: list[dict] = []
	settings = frappe.get_cached_doc("Vehicle Service Settings")
	reminder_days = cint(getattr(settings, "next_service_reminder_days", None) or 7)
	today = getdate(nowdate())

	if getattr(vehicle_doc, "next_service_date", None):
		next_date = getdate(vehicle_doc.next_service_date)
		days_remaining = date_diff(next_date, today)
		if days_remaining < 0:
			date_status = "Overdue"
		elif days_remaining <= reminder_days:
			date_status = "Due"
		else:
			date_status = "Upcoming"
		scheduled.append(
			{
				"source_type": "Scheduled Maintenance",
				"metric": "Date",
				"title": _("Next Scheduled Service Date"),
				"due_date": str(next_date),
				"days_remaining": days_remaining,
				"status": date_status,
			}
		)

	target_mileage = cint(getattr(vehicle_doc, "next_service_mileage", None) or 0)
	if target_mileage > 0:
		current_km = cint(last_recorded_mileage or 0)
		km_remaining = target_mileage - current_km
		if km_remaining < 0:
			km_status = "Overdue"
		elif km_remaining <= 500:
			km_status = "Due"
		else:
			km_status = "Upcoming"
		scheduled.append(
			{
				"source_type": "Scheduled Maintenance",
				"metric": "Mileage",
				"title": _("Next Scheduled Service Mileage"),
				"target_mileage": target_mileage,
				"current_mileage": current_km,
				"km_remaining": km_remaining,
				"status": km_status,
			}
		)

	return {
		"outstanding": outstanding,
		"completed": completed,
		"advisory_notes": advisory_notes,
		"scheduled": scheduled,
	}


def _compute_overview_stats(
	vehicle_doc: Document,
	orders: list[dict],
	standalone_intakes: list[dict],
	intakes_by_order: dict[str, dict],
	jobs_by_order: dict[str, list[dict]],
	financials_by_order: dict[str, dict],
	can_view_financials: bool,
) -> dict:
	non_cancelled = [o for o in orders if o.get("status") != "Cancelled"]

	completed_repairs = 0
	completed_orders_count = 0
	outstanding_orders = 0
	service_dates = []
	mileages = [cint(vehicle_doc.current_mileage or 0)]
	total_value = 0.0

	for order in non_cancelled:
		order_name = order["name"]
		status = order.get("status")
		if status != "Delivered":
			outstanding_orders += 1
		if status in _COMPLETED_ORDER_STATUSES:
			completed_orders_count += 1
			for dt_val in (order.get("delivered_on"), order.get("work_completed_on")):
				if dt_val:
					service_dates.append(getdate(dt_val))

		for job in jobs_by_order.get(order_name, []):
			if job.get("status") in _COMPLETED_JOB_STATUSES:
				completed_repairs += 1

		mileages.append(cint(order.get("odometer_out") or 0))
		mileages.append(cint(order.get("odometer_in") or 0))
		linked_intake = intakes_by_order.get(order_name)
		if linked_intake:
			mileages.append(cint(linked_intake.get("odometer_in") or 0))

		if can_view_financials:
			total_value += flt(financials_by_order.get(order_name, {}).get("total_invoice_value"))

	for intake in standalone_intakes:
		mileages.append(cint(intake.get("odometer_in") or 0))

	positive_mileages = [m for m in mileages if m > 0]
	last_recorded_mileage = max(positive_mileages) if positive_mileages else 0

	if service_dates:
		last_service_date = str(max(service_dates))
	elif vehicle_doc.last_service_date:
		last_service_date = str(getdate(vehicle_doc.last_service_date))
	else:
		last_service_date = None

	return {
		"total_visits": len(non_cancelled) + len(standalone_intakes),
		"total_service_orders": len(non_cancelled),
		"total_completed_repairs": completed_repairs,
		"completed_orders_count": completed_orders_count,
		"last_service_date": last_service_date,
		"last_recorded_mileage": last_recorded_mileage,
		"total_historical_service_value": round(total_value, 2) if can_view_financials else None,
		"outstanding_service_orders": outstanding_orders,
	}


def _fetch_user_full_names(user_ids: set[str]) -> dict[str, str]:
	clean_ids = [u for u in user_ids if u]
	if not clean_ids:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", clean_ids]}, fields=["name", "full_name"])
	return {r["name"]: (r.get("full_name") or r["name"]) for r in rows}


def _build_intake_summary(intake: dict | None, photos: list[dict]) -> dict | None:
	if not intake:
		return None
	return {
		"name": intake["name"],
		"status": intake.get("status"),
		"checked_in_on": _to_dt_str(intake.get("checked_in_on")),
		"checked_in_by": intake.get("checked_in_by"),
		"odometer_in": cint(intake.get("odometer_in") or 0),
		"fuel_level": intake.get("fuel_level"),
		"customer_complaint": intake.get("customer_complaint"),
		"existing_damage": intake.get("existing_damage"),
		"vehicle_contents": intake.get("vehicle_contents"),
		"reception_notes": intake.get("reception_notes"),
		"intake_confirmed": cint(intake.get("intake_confirmed") or 0),
		"photos": photos,
	}


def _assemble_visit_from_order(
	order: dict,
	intake: dict | None,
	photos: list[dict],
	jobs: list[dict],
	parts: list[dict],
	qcs: list[dict],
	financials: dict,
	user_names: dict[str, str],
) -> dict:
	visit_ts = order.get("checked_in_on") or (intake.get("checked_in_on") if intake else None) or order.get("order_date") or order.get("creation")
	advisor = order.get("service_advisor")
	return {
		"visit_type": "Service Order",
		"service_order": order["name"],
		"vehicle": order.get("vehicle"),
		"vehicle_intake": intake["name"] if intake else order.get("vehicle_intake"),
		"status": order.get("status"),
		"board_status": order.get("board_status"),
		"order_type": order.get("order_type"),
		"priority": order.get("priority"),
		"branch": order.get("branch"),
		"company": order.get("company"),
		"service_advisor": advisor,
		"service_advisor_name": user_names.get(advisor or "", advisor),
		"visit_date": _to_date_str(visit_ts),
		"visit_timestamp": _to_dt_str(visit_ts),
		"order_date": _to_date_str(order.get("order_date")),
		"checked_in_on": _to_dt_str(order.get("checked_in_on") or (intake.get("checked_in_on") if intake else None)),
		"work_started_on": _to_dt_str(order.get("work_started_on")),
		"work_completed_on": _to_dt_str(order.get("work_completed_on")),
		"delivered_on": _to_dt_str(order.get("delivered_on")),
		"odometer_in": cint(order.get("odometer_in") or (intake.get("odometer_in") if intake else 0)),
		"odometer_out": cint(order.get("odometer_out") or 0),
		"fuel_level": order.get("fuel_level") or (intake.get("fuel_level") if intake else None),
		"customer_complaint": order.get("customer_complaint") or (intake.get("customer_complaint") if intake else None),
		"existing_damage": order.get("existing_damage") or (intake.get("existing_damage") if intake else None),
		"vehicle_contents": order.get("vehicle_contents") or (intake.get("vehicle_contents") if intake else None),
		"reception_notes": intake.get("reception_notes") if intake else None,
		"hold_reason": order.get("hold_reason"),
		"dispute_notes": order.get("dispute_notes"),
		"pause_reason": order.get("pause_reason"),
		"cancellation_reason": order.get("cancellation_reason"),
		"delivery_notes": order.get("delivery_notes"),
		"collected_by": order.get("collected_by"),
		"current_location": order.get("current_location"),
		"intake_photos": photos,
		"intake": _build_intake_summary(intake, photos),
		"jobs": jobs,
		"parts": parts,
		"qc": qcs[0] if qcs else None,
		"qc_inspections": qcs,
		"financials": financials,
		"_sort_key": (get_datetime(visit_ts), get_datetime(order.get("creation")), order["name"]),
	}


def _assemble_visit_from_intake(
	intake: dict,
	photos: list[dict],
	user_names: dict[str, str],
) -> dict:
	visit_ts = intake.get("checked_in_on") or intake.get("creation")
	advisor = intake.get("service_advisor")
	return {
		"visit_type": "Vehicle Intake",
		"service_order": None,
		"vehicle": intake.get("vehicle"),
		"vehicle_intake": intake["name"],
		"status": intake.get("status"),
		"board_status": None,
		"order_type": None,
		"priority": None,
		"branch": None,
		"company": intake.get("company"),
		"service_advisor": advisor,
		"service_advisor_name": user_names.get(advisor or "", advisor),
		"visit_date": _to_date_str(visit_ts),
		"visit_timestamp": _to_dt_str(visit_ts),
		"order_date": None,
		"checked_in_on": _to_dt_str(intake.get("checked_in_on")),
		"work_started_on": None,
		"work_completed_on": None,
		"delivered_on": None,
		"odometer_in": cint(intake.get("odometer_in") or 0),
		"odometer_out": 0,
		"fuel_level": intake.get("fuel_level"),
		"customer_complaint": intake.get("customer_complaint"),
		"existing_damage": intake.get("existing_damage"),
		"vehicle_contents": intake.get("vehicle_contents"),
		"reception_notes": intake.get("reception_notes"),
		"hold_reason": None,
		"dispute_notes": None,
		"pause_reason": None,
		"cancellation_reason": None,
		"delivery_notes": None,
		"collected_by": None,
		"current_location": None,
		"intake_photos": photos,
		"intake": _build_intake_summary(intake, photos),
		"jobs": [],
		"parts": [],
		"qc": None,
		"qc_inspections": [],
		"financials": _empty_financials(),
		"_sort_key": (get_datetime(visit_ts), get_datetime(intake.get("creation")), intake["name"]),
	}


def _collect_filter_options(visits: list[dict], can_view_financials: bool) -> dict:
	statuses: set[str] = set()
	order_types: set[str] = set()
	technicians: dict[str, str] = {}
	advisors: dict[str, str] = {}
	invoice_statuses: set[str] = set()

	for v in visits:
		if v.get("status"):
			statuses.add(v["status"])
		if v.get("order_type"):
			order_types.add(v["order_type"])
		if v.get("service_advisor"):
			advisors[v["service_advisor"]] = v.get("service_advisor_name") or v["service_advisor"]
		for job in v.get("jobs", []):
			if job.get("technician"):
				technicians[job["technician"]] = job.get("technician_name") or job["technician"]
		if can_view_financials and v.get("financials") and v["financials"].get("payment_status"):
			invoice_statuses.add(v["financials"]["payment_status"])

	return {
		"statuses": sorted(statuses),
		"order_types": sorted(order_types),
		"technicians": [
			{"value": emp_id, "label": label}
			for emp_id, label in sorted(technicians.items(), key=lambda item: (item[1].lower(), item[0]))
		],
		"service_advisors": [
			{"value": user_id, "label": label}
			for user_id, label in sorted(advisors.items(), key=lambda item: (item[1].lower(), item[0]))
		],
		"invoice_statuses": sorted(invoice_statuses) if can_view_financials else [],
	}


def _filter_and_sort_visits(visits: list[dict], filters: dict, can_view_financials: bool) -> list[dict]:
	include_cancelled = (filters.get("status") == "Cancelled") or bool(cint(filters.get("include_cancelled")))
	from_date = getdate(filters["from_date"]) if filters.get("from_date") else None
	to_date = getdate(filters["to_date"]) if filters.get("to_date") else None
	status_filter = filters.get("status") or None
	order_type_filter = filters.get("order_type") or None
	technician_filter = filters.get("technician") or None
	advisor_filter = filters.get("service_advisor") or None
	invoice_status_filter = (filters.get("invoice_status") or None) if can_view_financials else None
	sort_order = str(filters.get("sort_order") or "desc").strip().lower()
	if sort_order not in ("asc", "desc"):
		sort_order = "desc"

	matched: list[dict] = []
	for visit in visits:
		if not include_cancelled and visit.get("status") == "Cancelled":
			continue
		if status_filter and visit.get("status") != status_filter:
			continue
		if order_type_filter and visit.get("order_type") != order_type_filter:
			continue
		if advisor_filter and visit.get("service_advisor") != advisor_filter:
			continue
		if technician_filter and not any(j.get("technician") == technician_filter for j in visit.get("jobs", [])):
			continue
		if invoice_status_filter:
			fin_status = (visit.get("financials") or {}).get("payment_status")
			if fin_status != invoice_status_filter:
				continue
		if from_date or to_date:
			if not visit.get("visit_date"):
				continue
			v_date = getdate(visit["visit_date"])
			if from_date and v_date < from_date:
				continue
			if to_date and v_date > to_date:
				continue
		matched.append(visit)

	matched.sort(key=lambda item: item["_sort_key"], reverse=(sort_order != "asc"))
	return matched


def _redact_visit_financials(visit: dict) -> dict:
	visit["financials"] = None
	for job in visit.get("jobs", []):
		for field in _REDACTED_JOB_FIELDS:
			job.pop(field, None)
	for part in visit.get("parts", []):
		for field in _REDACTED_PART_FIELDS:
			part.pop(field, None)
	return visit


def _parse_filters(filters: dict | str | None) -> dict:
	if not filters:
		return {}
	if isinstance(filters, str):
		parsed = frappe.parse_json(filters)
		return parsed if isinstance(parsed, dict) else {}
	return dict(filters) if isinstance(filters, dict) else {}


@frappe.whitelist()
def get_vehicle_service_history(vehicle: str, filters: dict | str | None = None) -> dict:
	"""Return unified, permission-scoped Vehicle Service History for a Service Vehicle cluster."""
	user, roles = _require_history_viewer()
	vehicle_doc, vehicle_ids = resolve_vehicle_cluster(vehicle)
	scope = _get_user_scope(user, roles)
	parsed_filters = _parse_filters(filters)

	customer_profile = _fetch_customer_profile(vehicle_doc.customer)
	orders, standalone_intakes = _fetch_orders_and_standalone_intakes(vehicle_ids, scope)
	order_names = [o["name"] for o in orders]

	intakes_by_name, intakes_by_order, photos_by_intake = _fetch_intakes_and_photos(orders, standalone_intakes)
	jobs_by_order = _fetch_jobs_by_order(order_names)
	parts_by_order = _fetch_parts_by_order(order_names)
	qcs_by_order = _fetch_qcs_by_order(order_names)
	invoices_by_order, items_by_invoice, payments_by_invoice, stock_item_map = _fetch_financials_bundle(orders)

	settings = frappe.get_cached_doc("Vehicle Service Settings")
	labour_item = getattr(settings, "labour_item", None) or "LABOUR"

	financials_by_order: dict[str, dict] = {}
	for order in orders:
		order_name = order["name"]
		financials_by_order[order_name] = _compute_order_financials(
			invoices_by_order.get(order_name, []),
			items_by_invoice,
			payments_by_invoice,
			stock_item_map,
			labour_item,
			jobs_by_order.get(order_name, []),
			parts_by_order.get(order_name, []),
		)

	can_view_financials = scope["can_view_financials"]
	overview_stats = _compute_overview_stats(
		vehicle_doc,
		orders,
		standalone_intakes,
		intakes_by_order,
		jobs_by_order,
		financials_by_order,
		can_view_financials,
	)

	recommendations = build_recommendations(
		vehicle_doc,
		orders,
		jobs_by_order,
		parts_by_order,
		qcs_by_order,
		overview_stats["last_recorded_mileage"],
	)

	user_ids = {o.get("service_advisor") for o in orders if o.get("service_advisor")}
	user_ids.update(i.get("service_advisor") for i in standalone_intakes if i.get("service_advisor"))
	user_names = _fetch_user_full_names(user_ids)

	all_visits: list[dict] = []
	for order in orders:
		order_name = order["name"]
		intake = intakes_by_order.get(order_name) or (
			intakes_by_name.get(order["vehicle_intake"]) if order.get("vehicle_intake") else None
		)
		photos = photos_by_intake.get(intake["name"], []) if intake else []
		all_visits.append(
			_assemble_visit_from_order(
				order,
				intake,
				photos,
				jobs_by_order.get(order_name, []),
				parts_by_order.get(order_name, []),
				qcs_by_order.get(order_name, []),
				financials_by_order[order_name],
				user_names,
			)
		)

	for intake in standalone_intakes:
		photos = photos_by_intake.get(intake["name"], [])
		all_visits.append(_assemble_visit_from_intake(intake, photos, user_names))

	filter_options = _collect_filter_options(all_visits, can_view_financials)
	timeline = _filter_and_sort_visits(all_visits, parsed_filters, can_view_financials)

	for visit in timeline:
		visit.pop("_sort_key", None)
		if not can_view_financials:
			_redact_visit_financials(visit)

	return {
		"vehicle": _serialize_vehicle_profile(vehicle_doc),
		"customer": customer_profile,
		"vehicle_ids": vehicle_ids,
		"permissions": {
			"can_view_financials": can_view_financials,
			"is_cross_branch": scope["is_cross_branch"],
			"allowed_branches": scope["allowed_branches"],
			"allowed_companies": scope["allowed_companies"],
		},
		"overview_stats": overview_stats,
		"recommendations": recommendations,
		"timeline": timeline,
		"filter_options": filter_options,
	}


_PRINT_TEMPLATE_PATH = "vehicle_service/templates/print_formats/vehicle_service_history_report.html"
_LOGO_ASSET_URL = "/assets/vehicle_service/images/vehicle-service-logo.svg"
_INTERNAL_VISIT_FIELDS = (
	"reception_notes",
	"hold_reason",
	"dispute_notes",
	"pause_reason",
	"cancellation_reason",
	"board_status",
	"current_location",
)
_INTERNAL_INTAKE_FIELDS = ("reception_notes", "checked_in_by")
_INTERNAL_JOB_FIELDS = (
	"technician",
	"technician_name",
	"technician_user",
	"raised_by",
	"bay",
	"reason_for_adding",
	"pause_reason",
	"qc_fail_reason",
	"variance_hours",
	"supplier",
	"supplier_cost",
	"supplier_invoice_ref",
)
_INTERNAL_PART_FIELDS = ("reason_for_adding",)
_INTERNAL_QC_FIELDS = ("fail_reason", "inspector")
_CUSTOMER_EXCLUDED_STATUSES = {"Declined", "Cancelled"}


def _parse_include_financials(value) -> bool:
	if value is None:
		return True
	if isinstance(value, bool):
		return value
	if isinstance(value, int | float):
		return bool(cint(value))
	text = str(value).strip().lower()
	if text in ("1", "true", "yes", "on"):
		return True
	if text in ("0", "false", "no", "off", ""):
		return False
	return bool(cint(value))


def _sanitize_visit_for_customer(visit: dict) -> dict:
	"""Return a customer-safe deep copy of a visit, or `{}` for cancelled visits."""
	if not visit or visit.get("status") == "Cancelled":
		return {}

	sanitized = copy.deepcopy(visit)
	for field in _INTERNAL_VISIT_FIELDS:
		sanitized.pop(field, None)
	sanitized.pop("service_advisor", None)

	if isinstance(sanitized.get("intake"), dict):
		for field in _INTERNAL_INTAKE_FIELDS:
			sanitized["intake"].pop(field, None)

	removed_job_ids: set[str] = set()
	kept_jobs: list[dict] = []
	for job in sanitized.get("jobs") or []:
		if job.get("status") in _CUSTOMER_EXCLUDED_STATUSES:
			for key in ("name", "service_job", "order_job_row"):
				if job.get(key):
					removed_job_ids.add(job[key])
			continue
		for field in _INTERNAL_JOB_FIELDS:
			job.pop(field, None)
		kept_jobs.append(job)
	sanitized["jobs"] = kept_jobs

	kept_parts: list[dict] = []
	for part in sanitized.get("parts") or []:
		if (
			part.get("part_status") in _CUSTOMER_EXCLUDED_STATUSES
			or part.get("approval_status") in _CUSTOMER_EXCLUDED_STATUSES
			or (part.get("job") and part.get("job") in removed_job_ids)
		):
			continue
		for field in _INTERNAL_PART_FIELDS:
			part.pop(field, None)
		kept_parts.append(part)
	sanitized["parts"] = kept_parts

	raw_qcs = sanitized.get("qc_inspections")
	if raw_qcs is None and isinstance(sanitized.get("qc"), dict):
		raw_qcs = [sanitized["qc"]]

	kept_qcs: list[dict] = []
	for qc in raw_qcs or []:
		if qc.get("result") == "Fail":
			continue
		for field in _INTERNAL_QC_FIELDS:
			qc.pop(field, None)
		kept_qcs.append(qc)

	sanitized["qc_inspections"] = kept_qcs
	sanitized["qc"] = kept_qcs[0] if kept_qcs else None

	return sanitized


def _sanitize_recommendations_for_customer(recommendations: dict, raw_timeline: list[dict]) -> dict:
	"""Filter declined/cancelled items, failed QC advisories, and internal reasons from recommendations."""
	sanitized = copy.deepcopy(recommendations or {})

	job_has_desc: dict[str, bool] = {}
	qc_result_map: dict[str, str | None] = {}
	for visit in raw_timeline:
		for job in visit.get("jobs") or []:
			has_desc = bool((job.get("description") or "").strip())
			for key in (job.get("service_job"), job.get("name")):
				if key:
					job_has_desc[key] = has_desc
		for qc in visit.get("qc_inspections") or []:
			if qc.get("name"):
				qc_result_map[qc["name"]] = qc.get("result")

	missing_job_ids = {
		item.get("source_id")
		for bucket in ("outstanding", "completed")
		for item in (sanitized.get(bucket) or [])
		if item.get("source_type") == "Job"
		and item.get("source_id")
		and item.get("source_id") not in job_has_desc
		and item.get("original_status") not in _CUSTOMER_EXCLUDED_STATUSES
	}
	if missing_job_ids:
		rows = frappe.get_all(
			"Service Job",
			filters={"name": ["in", list(missing_job_ids)]},
			fields=["name", "description"],
		)
		for row in rows:
			job_has_desc[row["name"]] = bool((row.get("description") or "").strip())

	for bucket in ("outstanding", "completed"):
		filtered: list[dict] = []
		for item in sanitized.get(bucket) or []:
			if item.get("original_status") in _CUSTOMER_EXCLUDED_STATUSES:
				continue
			if item.get("source_type") == "Part":
				item["description"] = None
			elif item.get("source_type") == "Job" and not job_has_desc.get(item.get("source_id") or "", False):
				item["description"] = None
			filtered.append(item)
		sanitized[bucket] = filtered

	missing_qc_ids = {
		adv.get("source_id")
		for adv in (sanitized.get("advisory_notes") or [])
		if adv.get("source_doctype") == "Service QC"
		and adv.get("source_id")
		and adv.get("source_id") not in qc_result_map
	}
	if missing_qc_ids:
		qc_rows = frappe.get_all(
			"Service QC",
			filters={"name": ["in", list(missing_qc_ids)]},
			fields=["name", "result"],
		)
		for row in qc_rows:
			qc_result_map[row["name"]] = row.get("result")

	sanitized["advisory_notes"] = [
		adv
		for adv in (sanitized.get("advisory_notes") or [])
		if not (
			adv.get("source_doctype") == "Service QC"
			and qc_result_map.get(adv.get("source_id") or "") == "Fail"
		)
	]

	return sanitized


def _get_print_company_info(visits: list[dict]) -> dict:
	company_name = next((v.get("company") for v in visits if v.get("company")), None)
	if not company_name:
		company_name = (
			frappe.db.get_single_value("Vehicle Service Settings", "company")
			or frappe.db.get_default("company")
			or "Vehicle Service Workshop"
		)

	info = {
		"company": company_name,
		"company_name": company_name,
		"tax_id": None,
		"phone_no": None,
		"email": None,
		"website": None,
		"default_currency": frappe.db.get_default("currency") or "ZMW",
	}
	if company_name and frappe.db.exists("Company", company_name):
		row = frappe.db.get_value(
			"Company",
			company_name,
			["company_name", "tax_id", "phone_no", "email", "website", "default_currency"],
			as_dict=True,
		)
		if row:
			info.update({k: v for k, v in row.items() if v is not None})
	return info


def _format_applied_filters(filters: dict, is_customer_mode: bool, include_financials: bool) -> str:
	parts: list[str] = []
	if filters.get("from_date"):
		parts.append(f"From {filters['from_date']}")
	if filters.get("to_date"):
		parts.append(f"To {filters['to_date']}")
	if filters.get("status"):
		parts.append(f"Status: {filters['status']}")
	if filters.get("order_type"):
		parts.append(f"Type: {filters['order_type']}")
	if not is_customer_mode and filters.get("technician"):
		parts.append(f"Technician: {filters['technician']}")
	if filters.get("service_advisor"):
		advisor_label = (
			(get_fullname(filters["service_advisor"]) or filters["service_advisor"])
			if is_customer_mode
			else filters["service_advisor"]
		)
		parts.append(f"Advisor: {advisor_label}")
	if include_financials and filters.get("invoice_status"):
		parts.append(f"Invoice: {filters['invoice_status']}")
	return ", ".join(parts)


def _inline_logo_for_pdf(html: str) -> str:
	"""Embed the local SVG logo as a data URI so wkhtmltopdf needs no HTTP round-trip."""
	logo_path = frappe.get_app_path("vehicle_service", "public", "images", "vehicle-service-logo.svg")
	if not os.path.exists(logo_path):
		return html
	with open(logo_path, "rb") as logo_file:
		encoded = base64.b64encode(logo_file.read()).decode("ascii")
	data_uri = f"data:image/svg+xml;base64,{encoded}"
	return html.replace(f'src="{_LOGO_ASSET_URL}"', f'src="{data_uri}"', 1)


@frappe.whitelist()
def render_vehicle_service_history_print(
	vehicle: str,
	mode: str = "internal",
	include_financials: int = 1,
	filters: dict | str | None = None,
) -> str:
	"""Render print-ready Vehicle Service History HTML for internal or customer mode."""
	if mode not in ("internal", "customer"):
		frappe.throw(_("Invalid print mode '{0}'. Expected 'internal' or 'customer'.").format(mode))

	parsed_filters = _parse_filters(filters)
	payload = get_vehicle_service_history(vehicle=vehicle, filters=parsed_filters)

	effective_include_financials = _parse_include_financials(include_financials) and bool(
		payload["permissions"]["can_view_financials"]
	)

	if not effective_include_financials:
		payload["overview_stats"]["total_historical_service_value"] = None
		for visit in payload["timeline"]:
			_redact_visit_financials(visit)

	is_customer_mode = mode == "customer"
	if is_customer_mode:
		raw_timeline = payload["timeline"]
		payload["timeline"] = [
			sanitized
			for visit in raw_timeline
			if (sanitized := _sanitize_visit_for_customer(visit))
		]
		payload["recommendations"] = _sanitize_recommendations_for_customer(
			payload["recommendations"],
			raw_timeline,
		)
		payload["vehicle"].pop("current_location", None)
		payload["vehicle"].pop("current_service_order", None)

	company_info = _get_print_company_info(payload["timeline"])
	report_title = _("Customer Service History") if is_customer_mode else _("Complete Service History")

	context = {
		"mode": mode,
		"is_customer_mode": is_customer_mode,
		"report_title": report_title,
		"include_financials": effective_include_financials,
		"logo_src": _LOGO_ASSET_URL,
		"company_info": company_info,
		"currency": company_info.get("default_currency") or "ZMW",
		"generated_on": format_datetime(now_datetime(), "dd-MMM-yyyy HH:mm"),
		"generated_by": get_fullname(frappe.session.user) or frappe.session.user,
		"applied_filters": _format_applied_filters(
			parsed_filters,
			is_customer_mode=is_customer_mode,
			include_financials=effective_include_financials,
		),
		"vehicle": payload["vehicle"],
		"customer": payload["customer"],
		"overview_stats": payload["overview_stats"],
		"recommendations": payload["recommendations"],
		"timeline": payload["timeline"],
	}
	return frappe.render_template(_PRINT_TEMPLATE_PATH, context)


@frappe.whitelist()
def download_vehicle_service_history_pdf(
	vehicle: str,
	mode: str = "internal",
	include_financials: int = 1,
	filters: dict | str | None = None,
) -> None:
	"""Generate Vehicle Service History PDF and write it to `frappe.local.response`."""
	from frappe.utils.pdf import get_pdf

	html = render_vehicle_service_history_print(
		vehicle=vehicle,
		mode=mode,
		include_financials=include_financials,
		filters=filters,
	)
	pdf_html = _inline_logo_for_pdf(html)
	pdf_bytes = get_pdf(pdf_html)

	reg_no = frappe.db.get_value("Service Vehicle", vehicle, "registration_no") or vehicle or "vehicle"
	safe_reg = re.sub(r"[^A-Za-z0-9._-]+", "-", str(reg_no).strip()).strip("-") or "vehicle"

	frappe.local.response.filename = f"Service-History-{safe_reg}-{mode}.pdf"
	frappe.local.response.filecontent = pdf_bytes
	frappe.local.response.type = "pdf"
