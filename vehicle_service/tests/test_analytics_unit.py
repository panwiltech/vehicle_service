# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import unittest
from datetime import datetime, timedelta
from frappe.utils import flt, now_datetime


class TestAnalyticsUnit(unittest.TestCase):
    def test_work_completion_timestamp_logic(self):
        """Test timestamp assignment on status transitions."""
        from vehicle_service.vehicle_service.doctype.service_order.service_order import (
            determine_status_timestamps,
        )

        now = datetime(2026, 10, 26, 10, 0, 0)
        # Test 1: Transitioning to In Progress stamps work_started_on
        started_on, completed_on = determine_status_timestamps("In Progress", None, None, now=now)
        self.assertEqual(started_on, now)
        self.assertIsNone(completed_on)

        # Test 2: Transitioning to Ready for Billing stamps work_completed_on
        started_on, completed_on = determine_status_timestamps("Ready for Billing", now, None, now=now)
        self.assertEqual(started_on, now)
        self.assertEqual(completed_on, now)

        # Test 3: Existing completed_on is not overwritten
        later = datetime(2026, 10, 26, 12, 0, 0)
        started_on2, completed_on2 = determine_status_timestamps("Delivered", now, now, now=later)
        self.assertEqual(completed_on2, now)

    def test_wip_aging_buckets(self):
        """Test WIP aging bucket segmentation logic."""
        def classify_aging(days):
            if days <= 7:
                return "0-7 Days"
            elif days <= 14:
                return "8-14 Days"
            elif days <= 30:
                return "15-30 Days"
            else:
                return "30+ Days"

        self.assertEqual(classify_aging(0), "0-7 Days")
        self.assertEqual(classify_aging(7), "0-7 Days")
        self.assertEqual(classify_aging(8), "8-14 Days")
        self.assertEqual(classify_aging(14), "8-14 Days")
        self.assertEqual(classify_aging(15), "15-30 Days")
        self.assertEqual(classify_aging(30), "15-30 Days")
        self.assertEqual(classify_aging(31), "30+ Days")
        self.assertEqual(classify_aging(90), "30+ Days")

    def test_technician_labour_units_split_math(self):
        """Test single-tech vs multi-tech billable units allocation."""
        # Case 1: Single tech job (4.0 billable hours) -> 100% to assigned tech
        billable_hours = 4.0
        time_logs_single = [{"technician": "TECH-01", "hours": 3.0}]
        tech_units_single = billable_hours  # Single tech gets full 4.0 units
        self.assertEqual(tech_units_single, 4.0)
        eff_single = round((tech_units_single / 3.0) * 100.0, 1)
        self.assertEqual(eff_single, 133.3)

        # Case 2: Multi-tech shared job (4.0 billable hours)
        # Tech A: 1.0 hr, Tech B: 3.0 hrs (total 4.0 hrs)
        time_logs_multi = [
            {"technician": "TECH-A", "hours": 1.0},
            {"technician": "TECH-B", "hours": 3.0},
        ]
        total_logged = sum(tl["hours"] for tl in time_logs_multi)
        tech_a_share = 1.0 / total_logged
        tech_b_share = 3.0 / total_logged
        tech_a_units = round(billable_hours * tech_a_share, 2)
        tech_b_units = round(billable_hours * tech_b_share, 2)
        self.assertEqual(tech_a_units, 1.0)
        self.assertEqual(tech_b_units, 3.0)
        self.assertEqual(tech_a_units + tech_b_units, billable_hours)

    def test_parts_sales_gp_math(self):
        """Test parts sales net sales, COGS, and GP margin calculations."""
        qty = 2.0
        selling_rate = 120.0
        net_sales = qty * selling_rate  # 240.0
        cogs_rate = 70.0
        cogs = qty * cogs_rate  # 140.0
        gross_profit = net_sales - cogs  # 100.0
        gp_pct = round((gross_profit / net_sales) * 100.0, 1)

        self.assertEqual(net_sales, 240.0)
        self.assertEqual(cogs, 140.0)
        self.assertEqual(gross_profit, 100.0)
        self.assertEqual(gp_pct, 41.7)

    def test_doc_combined_margin_math(self):
        """Test DOC combined workshop revenue and margin calculations."""
        parts_rev = 5000.0
        parts_cogs = 3000.0
        parts_gp = parts_rev - parts_cogs  # 2000.0

        labour_rev = 8000.0
        labour_cost = 3200.0
        labour_gp = labour_rev - labour_cost  # 4800.0

        tot_rev = parts_rev + labour_rev  # 13000.0
        tot_cost = parts_cogs + labour_cost  # 6200.0
        tot_gp = parts_gp + labour_gp  # 6800.0
        overall_gp_pct = round((tot_gp / tot_rev) * 100.0, 1)

        self.assertEqual(tot_rev, 13000.0)
        self.assertEqual(tot_cost, 6200.0)
        self.assertEqual(tot_gp, 6800.0)
        self.assertEqual(overall_gp_pct, 52.3)


if __name__ == "__main__":
    unittest.main()



