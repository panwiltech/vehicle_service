# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

VEH = "TST-JB-01"
VEH2 = "TST-JB-02"


class TestJobBatchActions(FrappeTestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.sql("UPDATE `tabService Job Time Log` SET to_time = NOW() WHERE to_time IS NULL")
        for o in frappe.get_all("Service Order", filters={"vehicle": ["in", [VEH, VEH2]]}, pluck="name"):
            try:
                frappe.db.set_value("Service Order", o, "status", "Cancelled")
                frappe.delete_doc("Service Order", o, force=True, ignore_permissions=True)
            except Exception:
                frappe.db.delete("Service Order Job", {"parent": o})
                frappe.db.delete("Service Order", {"name": o})
        if not frappe.db.exists("Customer", "Test Customer"):
            c = frappe.new_doc("Customer")
            c.customer_name = "Test Customer"
            c.customer_type = "Individual"
            c.insert(ignore_permissions=True)
        if not frappe.db.exists("Item", "LABOUR"):
            it = frappe.new_doc("Item")
            it.item_code = "LABOUR"
            it.item_name = "Standard Labour"
            it.item_group = "Services"
            it.is_stock_item = 0
            it.insert(ignore_permissions=True)
        for veh in (VEH, VEH2):
            if not frappe.db.exists("Service Vehicle", veh):
                v = frappe.new_doc("Service Vehicle")
                v.registration_no = veh
                v.customer = "Test Customer"
                v.vin = "VIN-" + veh
                v.make = "Toyota"
                v.model = "Hilux"
                v.insert(ignore_permissions=True)

    # ------------------------------------------------------------ helpers
    def _tech(self, last):
        name = frappe.db.get_value("Employee", {"first_name": "Batch", "last_name": last})
        if name:
            return name
        company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company")[0].name
        emp = frappe.new_doc("Employee")
        emp.first_name = "Batch"
        emp.last_name = last
        emp.gender = "Male"
        emp.company = company
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = "2020-01-01"
        emp.status = "Active"
        emp.insert(ignore_permissions=True)
        return emp.name

    def _order(self, titles=("Job A", "Job B"), techs=("TechA", "TechB"), veh=VEH):
        """Order in Approved status with one assigned job per title."""
        from vehicle_service.job_control import add_job, assign_technician

        so = frappe.new_doc("Service Order")
        so.vehicle = veh
        so.customer = "Test Customer"
        so.insert(ignore_permissions=True)
        jobs = []
        for title, tech in zip(titles, techs):
            j = add_job(so.name, job_title=title, estimated_hours=1.0)["job"]
            if tech:
                assign_technician(j, self._tech(tech))
            jobs.append(j)
        frappe.db.set_value("Service Order", so.name, "status", "Approved")
        so.reload()
        so.sync_status_from_jobs_and_parts()
        so.reload()
        return so, jobs

    def _status(self, job):
        return frappe.db.get_value("Service Job", job, "status")

    # ------------------------------------------------------------ complete
    def test_complete_one_of_two_leaves_other_untouched(self):
        from vehicle_service.job_control import complete_jobs

        so, (a, b) = self._order()
        res = complete_jobs(so.name, [a])
        self.assertEqual(self._status(a), "Completed")
        self.assertEqual(self._status(b), "Assigned")
        so.reload()
        self.assertNotEqual(so.status, "Ready for Billing")
        self.assertNotEqual(res["order_status"], "Ready for Billing")

    def test_complete_last_job_sets_ready_for_billing(self):
        from vehicle_service.job_control import complete_jobs

        so, (a, b) = self._order()
        complete_jobs(so.name, [a])
        complete_jobs(so.name, [b])
        so.reload()
        self.assertEqual(so.status, "Ready for Billing")
        self.assertEqual(so.board_status, "Completed")

    def test_complete_accepts_json_string_and_multiple(self):
        import json

        from vehicle_service.job_control import complete_jobs

        so, (a, b) = self._order()
        complete_jobs(so.name, json.dumps([a, b]))
        so.reload()
        self.assertEqual(so.status, "Ready for Billing")

    def test_complete_twice_rejected_and_completed_on_stable(self):
        from vehicle_service.job_control import complete_jobs

        so, (a, b) = self._order()
        complete_jobs(so.name, [a])
        first = frappe.db.get_value("Service Job", a, "completed_on")
        self.assertRaises(frappe.ValidationError, complete_jobs, so.name, [a])
        self.assertEqual(frappe.db.get_value("Service Job", a, "completed_on"), first)

    def test_foreign_or_unknown_job_id_rejected_nothing_changed(self):
        from vehicle_service.job_control import complete_jobs

        so1, (a, b) = self._order()
        so2, (c,) = self._order(titles=("Job C",), techs=("TechA",), veh=VEH2)
        self.assertRaises(frappe.ValidationError, complete_jobs, so1.name, [a, c])
        self.assertRaises(frappe.ValidationError, complete_jobs, so1.name, [a, "NO-SUCH-JOB"])
        self.assertEqual(self._status(a), "Assigned")
        self.assertEqual(self._status(c), "Assigned")

    def test_empty_selection_rejected(self):
        from vehicle_service.job_control import complete_jobs, pause_jobs, start_jobs

        so, _ = self._order()
        for fn in (start_jobs, complete_jobs):
            self.assertRaises(frappe.ValidationError, fn, so.name, [])
        self.assertRaises(frappe.ValidationError, pause_jobs, so.name, [], "Other")

    def test_pending_approval_blocks_ready_for_billing(self):
        from vehicle_service.job_control import complete_jobs
        from vehicle_service.vehicle_service.doctype.service_job.service_job import report_additional_work

        so, (a,) = self._order(titles=("Job A",), techs=("TechA",))
        report_additional_work(so.name, "Extra", 1.0)
        complete_jobs(so.name, [a])
        so.reload()
        self.assertNotEqual(so.status, "Ready for Billing")

    def test_non_controller_cannot_complete(self):
        from vehicle_service.job_control import complete_jobs

        so, (a, b) = self._order()
        frappe.set_user("Guest")
        try:
            self.assertRaises(frappe.PermissionError, complete_jobs, so.name, [a])
        finally:
            frappe.set_user("Administrator")
        self.assertEqual(self._status(a), "Assigned")

    def test_service_job_complete_job_uses_same_guards(self):
        from vehicle_service.vehicle_service.doctype.service_job.service_job import complete_job

        so, (a, b) = self._order()
        complete_job(a)
        self.assertEqual(self._status(a), "Completed")
        self.assertRaises(frappe.ValidationError, complete_job, a)

    # ------------------------------------------------------------ start / pause
    def test_start_selected_only(self):
        from vehicle_service.job_control import start_jobs

        so, (a, b) = self._order()
        start_jobs(so.name, [a])
        self.assertEqual(self._status(a), "In Progress")
        self.assertEqual(self._status(b), "Assigned")

    def test_start_two_jobs_same_technician_rejected_atomically(self):
        from vehicle_service.job_control import start_jobs

        so, (a, b) = self._order(techs=("TechA", "TechA"))
        self.assertRaises(frappe.ValidationError, start_jobs, so.name, [a, b])
        self.assertEqual(self._status(a), "Assigned")
        self.assertEqual(self._status(b), "Assigned")

    def test_start_rejects_in_progress_job(self):
        from vehicle_service.job_control import start_jobs

        so, (a, b) = self._order()
        start_jobs(so.name, [a])
        self.assertRaises(frappe.ValidationError, start_jobs, so.name, [a])

    def test_pause_only_in_progress(self):
        from vehicle_service.job_control import pause_jobs, start_jobs

        so, (a, b) = self._order()
        start_jobs(so.name, [a])
        self.assertRaises(frappe.ValidationError, pause_jobs, so.name, [a, b], "Other")
        self.assertEqual(self._status(a), "In Progress")
        pause_jobs(so.name, [a], "Other")
        self.assertEqual(self._status(a), "Paused")
        self.assertRaises(frappe.ValidationError, pause_jobs, so.name, [a], "Other")

    def test_locked_order_rejects_all_actions(self):
        from vehicle_service.job_control import complete_jobs, pause_jobs, start_jobs

        so, (a, b) = self._order()
        frappe.db.set_value("Service Order", so.name, "status", "Ready for Billing")
        self.assertRaises(frappe.ValidationError, start_jobs, so.name, [a])
        self.assertRaises(frappe.ValidationError, pause_jobs, so.name, [a], "Other")
        self.assertRaises(frappe.ValidationError, complete_jobs, so.name, [a])

    # ------------------------------------------------------------ candidates
    def test_candidates_filter_by_action(self):
        from vehicle_service.job_control import complete_jobs, get_job_action_candidates, start_jobs

        so, (a, b) = self._order()
        start_jobs(so.name, [a])
        start = {c["name"]: c for c in get_job_action_candidates(so.name, "start")}
        self.assertNotIn(a, start)
        self.assertIsNone(start[b]["blocked_reason"])
        pause = [c["name"] for c in get_job_action_candidates(so.name, "pause")]
        self.assertEqual(pause, [a])
        complete_jobs(so.name, [a])
        self.assertEqual(get_job_action_candidates(so.name, "pause"), [])
        done = [c["name"] for c in get_job_action_candidates(so.name, "complete")]
        self.assertEqual(done, [b])

    def test_candidates_blocked_reason_for_unassigned(self):
        from vehicle_service.job_control import get_job_action_candidates

        so, (a,) = self._order(titles=("Job A",), techs=(None,))
        rows = get_job_action_candidates(so.name, "start")
        self.assertEqual(len(rows), 1)
        self.assertIn("technician", rows[0]["blocked_reason"].lower())

    def test_candidates_empty_state_returns_empty_list(self):
        from vehicle_service.job_control import get_job_action_candidates

        so = frappe.new_doc("Service Order")
        so.vehicle = VEH
        so.customer = "Test Customer"
        so.insert(ignore_permissions=True)
        for action in ("start", "pause", "complete"):
            self.assertEqual(get_job_action_candidates(so.name, action), [])
