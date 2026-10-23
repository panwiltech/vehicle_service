# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import unittest

from vehicle_service.state import job_action_block_reason

ALL_STATUSES = [
    "Pending Approval", "Approved", "Assigned", "In Progress", "Paused",
    "Completed", "QC Failed", "Passed", "Declined", "Cancelled",
]


def job(status, technician="EMP-1"):
    return {"status": status, "technician": technician}


def allowed(action, status, **kw):
    kw.setdefault("order_status", "Approved")
    kw.setdefault("on_hold", False)
    tech = kw.pop("technician", "EMP-1")
    return job_action_block_reason(action, job(status, tech), **kw) is None


class TestJobActionRules(unittest.TestCase):
    def test_start_rules(self):
        ok = {"Approved", "Assigned", "Paused", "QC Failed"}
        for s in ALL_STATUSES:
            self.assertEqual(allowed("start", s), s in ok, s)
        self.assertIn("technician", job_action_block_reason("start", job("Assigned", None), "Approved", False).lower())
        self.assertIn("hold", job_action_block_reason("start", job("Assigned"), "Approved", True).lower())

    def test_pause_rules(self):
        for s in ALL_STATUSES:
            self.assertEqual(allowed("pause", s), s == "In Progress", s)

    def test_complete_rules(self):
        ok = {"Approved", "Assigned", "In Progress", "Paused", "QC Failed"}
        for s in ALL_STATUSES:
            self.assertEqual(allowed("complete", s), s in ok, s)

    def test_locked_order_blocks_all(self):
        for order_status in ("Ready for Billing", "Invoiced", "Ready for Collection", "Delivered", "Cancelled"):
            for action in ("start", "pause", "complete"):
                self.assertFalse(allowed(action, "In Progress", order_status=order_status), (action, order_status))

    def test_pending_and_cancelled_never_actionable(self):
        for s in ("Pending Approval", "Cancelled", "Declined", "Passed", "Completed"):
            for action in ("start", "pause", "complete"):
                self.assertFalse(allowed(action, s), (action, s))
