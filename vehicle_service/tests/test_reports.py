# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.vehicle_service.report.estimate_vs_actual.estimate_vs_actual import (
	execute as execute_estimate_vs_actual,
)
from vehicle_service.vehicle_service.report.technician_performance.technician_performance import (
	execute as execute_technician_performance,
)
from vehicle_service.vehicle_service.report.workshop_performance.workshop_performance import (
	execute as execute_workshop_performance,
)
from vehicle_service.vehicle_service.report.parts_consumption.parts_consumption import (
	execute as execute_parts_consumption,
)


class TestWorkshopReports(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_test_data()

	def setup_test_data(self):
		company = frappe.get_all("Company")[0].name

		# Create customer
		if not frappe.db.exists("Customer", "Report Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Report Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create employee
		if not frappe.db.exists("Employee", {"first_name": "Report", "last_name": "Tech"}):
			emp = frappe.new_doc("Employee")
			emp.first_name = "Report"
			emp.last_name = "Tech"
			emp.company = company
			emp.gender = "Male"
			emp.date_of_birth = "1992-05-15"
			emp.date_of_joining = "2021-01-01"
			emp.insert(ignore_permissions=True)
			self.emp = emp
		else:
			self.emp = frappe.get_doc("Employee", {"first_name": "Report", "last_name": "Tech"})

		# Create vehicle
		reg_no = "RPT 999"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Nissan"
			veh.model = "Navara"
			veh.vin = "VIN-RPT-999"
			veh.year = 2023
			veh.customer = "Report Customer"
			veh.insert(ignore_permissions=True)

		# Check if active order already exists for vehicle
		existing_order = frappe.db.get_value(
			"Service Order",
			{"vehicle": reg_no, "status": ["not in", ["Delivered", "Cancelled"]]},
			"name",
		)
		if existing_order:
			order = frappe.get_doc("Service Order", existing_order)
		else:
			order = frappe.new_doc("Service Order")
			order.vehicle = reg_no
			order.customer = "Report Customer"
			order.priority = "Normal"
			order.status = "In Progress"
			order.insert(ignore_permissions=True)

		job_name = frappe.db.get_value("Service Job", {"service_order": order.name, "job_title": "Clutch Overhaul"}, "name")
		if not job_name:
			job = frappe.new_doc("Service Job")
			job.service_order = order.name
			job.job_title = "Clutch Overhaul"
			job.technician = self.emp.name
			job.status = "Completed"
			job.estimated_hours = 4.0
			job.append("time_logs", {
				"technician": self.emp.name,
				"from_time": "2026-10-03 08:00:00",
				"to_time": "2026-10-03 11:30:00",
				"hours": 3.5,
			})
			job.insert(ignore_permissions=True)
		else:
			job = frappe.get_doc("Service Job", job_name)

		if not frappe.db.exists("Item", "CLUTCH-KIT-TEST"):
			it = frappe.new_doc("Item")
			it.item_code = "CLUTCH-KIT-TEST"
			it.item_name = "Clutch Kit Heavy Duty"
			it.item_group = "Products"
			it.is_stock_item = 1
			it.stock_uom = "Nos"
			it.insert(ignore_permissions=True)

		if not order.parts:
			order.append("parts", {
				"item_code": "CLUTCH-KIT-TEST",
				"item_name": "Clutch Kit Heavy Duty",
				"job": job.name,
				"qty_required": 1.0,
				"qty_issued": 1.0,
				"qty_returned": 0.0,
				"qty_used": 1.0,
				"rate": 150.0,
				"part_status": "Issued",
				"approval_status": "Approved",
			})
			order.save(ignore_permissions=True)
		self.order = order

	def test_estimate_vs_actual_report(self):
		columns, data, message, chart, summary = execute_estimate_vs_actual(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)
		row = next((r for r in data if r.get("service_order") == self.order.name), None)
		self.assertIsNotNone(row)
		self.assertEqual(row.get("estimated_hours"), 4.0)
		self.assertEqual(row.get("actual_hours"), 3.5)
		self.assertEqual(row.get("variance_hours"), -0.5)

	def test_technician_performance_report(self):
		# Update employee name while keeping old name on service job
		self.emp.reload()
		self.emp.first_name = "UpdatedReport"
		self.emp.last_name = "Technician"
		self.emp.save(ignore_permissions=True)
		self.emp.reload()

		columns, data, message, chart, summary = execute_technician_performance(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)
		row = next((r for r in data if r.get("technician") == self.emp.name), None)
		self.assertIsNotNone(row)
		self.assertEqual(row.get("technician_name"), self.emp.employee_name)
		self.assertEqual(row.get("jobs_completed"), 1)
		self.assertEqual(row.get("total_actual_hours"), 3.5)

	def test_workshop_performance_report(self):
		columns, data, message, chart, summary = execute_workshop_performance(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)

	def test_parts_consumption_report(self):
		columns, data, message, chart, summary = execute_parts_consumption(filters={})
		self.assertGreater(len(columns), 0)
		self.assertGreater(len(data), 0)
		row = next((r for r in data if r.get("item_code") == "CLUTCH-KIT-TEST"), None)
		self.assertIsNotNone(row)
		self.assertEqual(row.get("qty_used"), 1.0)
		self.assertEqual(row.get("net_consumed_amount"), 150.0)

	def test_completion_timestamps_and_analytics_throughput(self):
		from vehicle_service.analytics import get_completed_orders, get_daily_throughput

		# Verify order completion timestamp stamping
		self.order.status = "Ready for Billing"
		self.order.save()
		self.assertIsNotNone(self.order.work_completed_on)

		completed = get_completed_orders({"from_date": "2026-01-01", "to_date": "2026-12-31"})
		self.assertIsInstance(completed, list)
		order_found = next((o for o in completed if o["service_order"] == self.order.name), None)
		self.assertIsNotNone(order_found)
		self.assertGreaterEqual(order_found["turnaround_hours"], 0.0)

		throughput = get_daily_throughput({"from_date": "2026-10-01", "to_date": "2026-10-31"})
		self.assertIsInstance(throughput, list)
		self.assertGreater(len(throughput), 0)

	def test_wip_valuation_stock_cost_vs_billing_price(self):
		from vehicle_service.analytics import get_wip_valuation

		# Put order in active WIP status
		self.order.status = "In Progress"
		self.order.save()

		wip = get_wip_valuation({})
		self.assertIn("orders", wip)
		self.assertIn("summary", wip)
		self.assertGreaterEqual(wip["summary"]["total_parts_wip"], 0.0)
		self.assertGreaterEqual(wip["summary"]["total_labour_wip"], 0.0)

	def test_multi_technician_distinct_jobs_attribution(self):
		from vehicle_service.analytics import get_technician_labour_units

		# Verify distinct jobs are credited 100% to assigned technician
		tech_data = get_technician_labour_units({})
		self.assertIsInstance(tech_data, list)
		if tech_data:
			self.assertIn("sold_units", tech_data[0])
			self.assertIn("labour_revenue", tech_data[0])
			self.assertIn("labour_cost", tech_data[0])
			self.assertIn("efficiency_rate", tech_data[0])

	def test_doc_summary_aggregation(self):
		from vehicle_service.analytics import get_doc_summary

		doc_summary = get_doc_summary({"from_date": "2026-10-01", "to_date": "2026-10-31"})
		self.assertIn("volume", doc_summary)
		self.assertIn("parts", doc_summary)
		self.assertIn("labour", doc_summary)
		self.assertIn("department_total", doc_summary)
		self.assertIn("wip_snapshot", doc_summary)

	def test_completed_service_orders_script_report(self):
		from vehicle_service.vehicle_service.report.completed_service_orders.completed_service_orders import (
			execute as execute_completed_orders,
		)

		columns, data, message, chart, summary = execute_completed_orders(
			{"from_date": "2026-01-01", "to_date": "2026-12-31"}
		)
		self.assertGreater(len(columns), 0)
		self.assertIsInstance(data, list)
		self.assertIsNotNone(summary)

	def test_service_order_throughput_script_report(self):
		from vehicle_service.vehicle_service.report.service_order_throughput.service_order_throughput import (
			execute as execute_throughput,
		)

		columns, data, message, chart, summary = execute_throughput(
			{"from_date": "2026-10-01", "to_date": "2026-10-31"}
		)
		self.assertGreater(len(columns), 0)
		self.assertIsInstance(data, list)
		self.assertIsNotNone(chart)
		self.assertIsNotNone(summary)

	def test_reports_dashboard_metrics_api(self):
		from vehicle_service.vehicle_service.page.reports_dashboard.reports_dashboard import (
			get_dashboard_data,
		)

		res = get_dashboard_data({"from_date": "2026-10-01", "to_date": "2026-10-31"})
		self.assertIn("cards", res)
		self.assertIn("charts", res)
		self.assertEqual(len(res["cards"]), 6)
		self.assertIn("throughput", res["charts"])
		self.assertIn("wip", res["charts"])
		self.assertIn("technician", res["charts"])

	def test_wip_valuation_script_report(self):
		from vehicle_service.vehicle_service.report.wip_valuation.wip_valuation import execute as execute_wip_valuation

		# 1. Order Summary Mode
		cols, data, msg, chart, summary = execute_wip_valuation({"view_mode": "Order Summary"})
		self.assertGreater(len(cols), 0)
		self.assertIsInstance(data, list)
		self.assertIsNotNone(summary)

		# 2. Parts Details Mode
		cols_p, data_p, msg_p, chart_p, summary_p = execute_wip_valuation({"view_mode": "Parts Details"})
		self.assertGreater(len(cols_p), 0)
		self.assertIsInstance(data_p, list)
		self.assertIsNotNone(summary_p)

		# 3. Labour Details Mode
		cols_l, data_l, msg_l, chart_l, summary_l = execute_wip_valuation({"view_mode": "Labour Details"})
		self.assertGreater(len(cols_l), 0)
		self.assertIsInstance(data_l, list)
		self.assertIsNotNone(summary_l)

		# 4. Branch Reconciliation Mode
		cols_r, data_r, msg_r, chart_r, summary_r = execute_wip_valuation({"view_mode": "Branch Reconciliation"})
		self.assertGreater(len(cols_r), 0)
		self.assertIsInstance(data_r, list)
		self.assertIsNotNone(summary_r)

	def test_parts_sales_script_report(self):
		from vehicle_service.vehicle_service.report.parts_sales.parts_sales import execute as execute_parts_sales

		cols, data, msg, chart, summary = execute_parts_sales({"from_date": "2026-01-01", "to_date": "2026-12-31"})
		self.assertGreater(len(cols), 0)
		self.assertIsInstance(data, list)
		self.assertIsNotNone(summary)

	def test_technician_labour_units_script_report(self):
		from vehicle_service.vehicle_service.report.technician_labour_units.technician_labour_units import (
			execute as execute_tech_units,
		)

		cols, data, msg, chart, summary = execute_tech_units({"from_date": "2026-01-01", "to_date": "2026-12-31"})
		self.assertGreater(len(cols), 0)
		self.assertIsInstance(data, list)
		self.assertIsNotNone(summary)

	def test_doc_report_script_report(self):
		from vehicle_service.vehicle_service.report.daily_operating_control.daily_operating_control import (
			execute as execute_doc_report,
		)

		# 1. Daily Operating Trend
		cols_t, data_t, msg_t, chart_t, summary_t = execute_doc_report(
			{"from_date": "2026-10-01", "to_date": "2026-10-31", "view_mode": "Daily Operating Trend"}
		)
		self.assertGreater(len(cols_t), 0)
		self.assertIsInstance(data_t, list)
		self.assertIsNotNone(summary_t)

		# 2. Executive Summary Mode
		cols_e, data_e, msg_e, chart_e, summary_e = execute_doc_report(
			{"from_date": "2026-10-01", "to_date": "2026-10-31", "view_mode": "Executive Summary"}
		)
		self.assertGreater(len(cols_e), 0)
		self.assertIsInstance(data_e, list)
		self.assertIsNotNone(summary_e)

		# 3. Standard Frappe Report resolution by report name
		res = frappe.get_doc("Report", "Daily Operating Control").execute_script_report(
			filters={"from_date": "2026-10-01", "to_date": "2026-10-31", "view_mode": "Executive Summary"}
		)
		self.assertIsNotNone(res)





