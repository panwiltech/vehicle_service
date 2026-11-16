# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import unittest
from datetime import datetime, timedelta
from frappe.utils import flt, now_datetime


class TestAnalyticsUnit(unittest.TestCase):
    def test_work_completion_timestamp_logic(self):
        """Test timestamp assignment on status transitions."""
        from vehicle_service.doctype.service_order.service_order import determine_status_timestamps

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


if __name__ == "__main__":
    unittest.main()
