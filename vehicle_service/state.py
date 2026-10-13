"""Pure status rules for Vehicle Service.

Nothing in this module touches the database, so every rule can be unit-tested in isolation.
See docs/design.md §3 for the state machines these functions implement.
"""

from collections.abc import Iterable
from typing import Any

# ---------------------------------------------------------------- Service Order
DRAFT = "Draft"
CHECKED_IN = "Checked In"
AWAITING_APPROVAL = "Awaiting Approval"
APPROVED = "Approved"
WAITING_FOR_PARTS = "Waiting for Parts"
READY_FOR_WORK = "Ready for Work"
IN_PROGRESS = "In Progress"
PAUSED = "Paused"
QC = "QC"
READY_FOR_BILLING = "Ready for Billing"
INVOICED = "Invoiced"
READY_FOR_COLLECTION = "Ready for Collection"
DELIVERED = "Delivered"
CANCELLED = "Cancelled"

ORDER_FLOW = [
	DRAFT,
	CHECKED_IN,
	IN_PROGRESS,
	PAUSED,
	AWAITING_APPROVAL,
	APPROVED,
	WAITING_FOR_PARTS,
	READY_FOR_WORK,
	QC,
	READY_FOR_BILLING,
	INVOICED,
	READY_FOR_COLLECTION,
	DELIVERED,
]

# States recalculated from jobs and parts rather than set explicitly.
OPERATIONAL = frozenset({APPROVED, WAITING_FOR_PARTS, READY_FOR_WORK, IN_PROGRESS, QC})
CLOSED = frozenset({DELIVERED, CANCELLED})
PRE_APPROVAL = frozenset({DRAFT, CHECKED_IN, IN_PROGRESS, PAUSED, AWAITING_APPROVAL})
# States in which estimates (first or additional) may be raised.
ESTIMATE_ALLOWED = frozenset({CHECKED_IN, IN_PROGRESS, PAUSED, AWAITING_APPROVAL}) | OPERATIONAL
# States in which parts may still be issued or returned (stock not yet consumed by invoice).
PARTS_MOVABLE = OPERATIONAL | {AWAITING_APPROVAL, PAUSED}

# ---------------------------------------------------------------- Service Job
JOB_PENDING = "Pending Approval"
JOB_APPROVED = "Approved"
JOB_ASSIGNED = "Assigned"
JOB_IN_PROGRESS = "In Progress"
JOB_PAUSED = "Paused"
JOB_COMPLETED = "Completed"
JOB_QC_FAILED = "QC Failed"
JOB_PASSED = "Passed"
JOB_DECLINED = "Declined"
JOB_CANCELLED = "Cancelled"

JOB_INACTIVE = frozenset({JOB_PENDING, JOB_DECLINED, JOB_CANCELLED})
JOB_DONE = frozenset({JOB_COMPLETED, JOB_PASSED})
JOB_STARTABLE = frozenset({JOB_ASSIGNED, JOB_QC_FAILED})
JOB_WORKING = frozenset({JOB_IN_PROGRESS, JOB_PAUSED})

# ---------------------------------------------------------------- Parts
PART_PENDING = "Pending Approval"
PART_REQUIRED = "Required"
PART_WAITING = "Waiting Stock"
PART_PARTIAL = "Partially Issued"
PART_ISSUED = "Issued"
PART_PARTIAL_RETURN = "Partially Returned"
PART_RETURNED = "Returned"
PART_SUBSTITUTED = "Substituted"
PART_DECLINED = "Declined"

# ---------------------------------------------------------------- Vehicle
V_OUTSIDE = "Outside Workshop"
V_ARRIVED = "Arrived"
V_CHECKED_IN = "Checked In"
V_WAITING = "Waiting"
V_IN_WORKSHOP = "In Workshop"
V_QC = "QC"
V_AWAITING_RELEASE = "Awaiting Release"
V_READY = "Ready for Collection"

_VEHICLE_STATUS = {
	DRAFT: V_ARRIVED,
	CHECKED_IN: V_CHECKED_IN,
	PAUSED: V_WAITING,
	AWAITING_APPROVAL: V_WAITING,
	APPROVED: V_WAITING,
	WAITING_FOR_PARTS: V_WAITING,
	READY_FOR_WORK: V_WAITING,
	IN_PROGRESS: V_IN_WORKSHOP,
	QC: V_QC,
	READY_FOR_BILLING: V_AWAITING_RELEASE,
	INVOICED: V_AWAITING_RELEASE,
	READY_FOR_COLLECTION: V_READY,
	DELIVERED: V_OUTSIDE,
	CANCELLED: V_OUTSIDE,
}


# States where workshop jobs are completed and order is in billing/delivery stages
COMPLETED_STATES = frozenset({READY_FOR_BILLING, INVOICED, READY_FOR_COLLECTION, DELIVERED})

_BOARD_STATUS = {
	DRAFT: "Open",
	CHECKED_IN: "Open",
	AWAITING_APPROVAL: "Open",
	APPROVED: "Open",
	WAITING_FOR_PARTS: "Open",
	READY_FOR_WORK: "Open",
	IN_PROGRESS: "In Progress",
	QC: "In Progress",
	PAUSED: "Paused",
	READY_FOR_BILLING: "Completed",
	INVOICED: "Completed",
	READY_FOR_COLLECTION: "Completed",
	DELIVERED: "Completed",
}


def board_status_for(status: str | None) -> str | None:
	"""Derives the 4-state board status (Open, In Progress, Paused, Completed) for Job Control Board."""
	if not status:
		return None
	return _BOARD_STATUS.get(status)


def _get(row: Any, key: str, default=None):
	if isinstance(row, dict):
		return row.get(key, default)
	return getattr(row, key, default)


def vehicle_status_for(order_status: str | None) -> str:
	"""Vehicle status implied by its open Service Order (or none)."""
	if not order_status:
		return V_OUTSIDE
	return _VEHICLE_STATUS.get(order_status, V_OUTSIDE)


def compute_operational_status(jobs: Iterable[Any], parts: Iterable[Any]) -> str:
	"""Derive the Service Order status while work is authorised (design §3.1).

	Priority order:
	1. every approved job done (and nothing awaiting approval) -> Ready for Billing (QC removed)
	2. any job being worked, paused, or returned from QC -> In Progress
	3. an approved part is waiting for stock -> Waiting for Parts
	4. any approved job has a technician -> Ready for Work
	5. otherwise -> Approved
	"""
	jobs = list(jobs)
	parts = list(parts)
	active = [j for j in jobs if _get(j, "status") not in JOB_INACTIVE]
	pending = any(_get(j, "status") == JOB_PENDING for j in jobs)

	if active and all(_get(j, "status") in JOB_DONE for j in active):
		return IN_PROGRESS if pending else READY_FOR_BILLING
	if any(_get(j, "status") in JOB_WORKING | {JOB_QC_FAILED} for j in active):
		return IN_PROGRESS
	if any(
		_get(p, "approval_status") == "Approved" and _get(p, "part_status") == PART_WAITING for p in parts
	):
		return WAITING_FOR_PARTS
	if any(_get(j, "status") == JOB_ASSIGNED for j in active):
		return READY_FOR_WORK
	return APPROVED


def compute_part_status(row: Any) -> str:
	"""Derive a part line's status from approval and quantities (design §3.3)."""
	if _get(row, "substituted_by"):
		return PART_SUBSTITUTED
	approval = _get(row, "approval_status") or "Pending"
	if approval == "Declined":
		return PART_DECLINED
	if approval != "Approved":
		return PART_PENDING

	required = float(_get(row, "qty_required") or 0)
	issued = float(_get(row, "qty_issued") or 0)
	returned = float(_get(row, "qty_returned") or 0)

	if issued <= 0:
		return PART_WAITING if _get(row, "material_request") else PART_REQUIRED
	if returned > 0:
		return PART_RETURNED if returned >= issued else PART_PARTIAL_RETURN
	if issued < required:
		return PART_PARTIAL
	return PART_ISSUED


def qty_on_vehicle(row: Any) -> float:
	"""Quantity currently sitting with the vehicle (issued minus returned)."""
	return float(_get(row, "qty_issued") or 0) - float(_get(row, "qty_returned") or 0)


def qty_issuable(row: Any) -> float:
	"""How much more may be issued against an approved line without exceeding authorisation."""
	if _get(row, "approval_status") != "Approved" or _get(row, "substituted_by"):
		return 0.0
	return max(float(_get(row, "qty_required") or 0) - qty_on_vehicle(row), 0.0)


def billable_labour_hours(approved_hours: float, actual_hours: float, basis: str | None) -> float:
	"""Labour hours to invoice. Never exceeds what the customer authorised."""
	approved = float(approved_hours or 0)
	if basis and basis.startswith("Actual"):
		return min(float(actual_hours or 0), approved)
	return approved


def stepper_position(status: str) -> int:
	"""Index of a status on the visual stepper (operational sub-states collapse onto 'Approved')."""
	collapsed = {
		WAITING_FOR_PARTS: APPROVED,
		READY_FOR_WORK: APPROVED,
	}.get(status, status)
	steps = [s for s in ORDER_FLOW if s not in (WAITING_FOR_PARTS, READY_FOR_WORK)]
	return steps.index(collapsed) if collapsed in steps else -1
