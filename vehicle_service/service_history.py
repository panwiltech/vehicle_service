# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

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
