# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt
from vehicle_service.state import (
	board_status_for,
	compute_operational_status,
	COMPLETED_STATES,
)


class TestJobControl(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		test_vehs = ["TST-BOARD-01", "TST-BOARD-02", "TST-JC-01", "TST-INV-01"]
		# Clean up any open time logs from prior test runs
		frappe.db.sql("UPDATE `tabService Job Time Log` SET to_time = NOW() WHERE to_time IS NULL")
		orders = frappe.get_all("Service Order", filters={"vehicle": ["in", test_vehs]}, pluck="name")
		for o in orders:
			try:
				frappe.db.set_value("Service Order", o, "status", "Cancelled")
				frappe.delete_doc("Service Order", o, force=True, ignore_permissions=True)
			except Exception:
				frappe.db.delete("Service Order Part", {"parent": o})
				frappe.db.delete("Service Order Job", {"parent": o})
				frappe.db.delete("Service Order", {"name": o})
		frappe.db.commit()

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

		from vehicle_service.job_control_setup import create_test_user
		create_test_user()

	def test_board_status_for(self):
		self.assertEqual(board_status_for("Draft"), "Open")
		self.assertEqual(board_status_for("Checked In"), "Open")
		self.assertEqual(board_status_for("Awaiting Approval"), "Open")
		self.assertEqual(board_status_for("Approved"), "Open")
		self.assertEqual(board_status_for("Waiting for Parts"), "Open")
		self.assertEqual(board_status_for("Ready for Work"), "Open")
		self.assertEqual(board_status_for("In Progress"), "In Progress")
		self.assertEqual(board_status_for("QC"), "In Progress")
		self.assertEqual(board_status_for("Paused"), "Paused")
		self.assertEqual(board_status_for("Ready for Billing"), "Completed")
		self.assertEqual(board_status_for("Invoiced"), "Completed")
		self.assertEqual(board_status_for("Ready for Collection"), "Completed")
		self.assertEqual(board_status_for("Delivered"), "Completed")
		self.assertIsNone(board_status_for("Cancelled"))

	def test_compute_operational_status_paused_and_pending(self):
		# Case 1: Job 1 paused for parts, Job 2 pending approval -> Waiting for Parts
		jobs = [
			{"status": "Paused", "pause_reason": "Waiting for Parts"},
			{"status": "Pending Approval"},
		]
		self.assertEqual(compute_operational_status(jobs, []), "Waiting for Parts")

		# Case 2: Job 1 paused with part waiting stock -> Waiting for Parts
		jobs = [
			{"status": "Paused", "pause_reason": "On hold"},
			{"status": "Pending Approval"},
		]
		parts = [{"approval_status": "Approved", "part_status": "Waiting Stock"}]
		self.assertEqual(compute_operational_status(jobs, parts), "Waiting for Parts")

		# Case 3: Job 1 paused (general reason), Job 2 pending approval -> Paused
		jobs = [
			{"status": "Paused", "pause_reason": "Technician on break"},
			{"status": "Pending Approval"},
		]
		self.assertEqual(compute_operational_status(jobs, []), "Paused")

		# Case 4: Job 1 In Progress, Job 2 Paused -> In Progress (active wrench turning)
		jobs = [
			{"status": "In Progress"},
			{"status": "Paused", "pause_reason": "Waiting for Parts"},
		]
		self.assertEqual(compute_operational_status(jobs, []), "In Progress")

		# Case 5: Job 1 Completed, Job 2 Pending Approval -> Awaiting Approval
		jobs = [
			{"status": "Completed"},
			{"status": "Pending Approval"},
		]
		self.assertEqual(compute_operational_status(jobs, []), "Awaiting Approval")

		# Case 6: All jobs Pending Approval -> Awaiting Approval
		jobs = [
			{"status": "Pending Approval"},
			{"status": "Pending Approval"},
		]
		self.assertEqual(compute_operational_status(jobs, []), "Awaiting Approval")

		# Case 7: Job paused for Awaiting Approval -> Awaiting Approval
		jobs = [
			{"status": "Paused", "pause_reason": "Awaiting Approval"},
		]
		self.assertEqual(compute_operational_status(jobs, []), "Awaiting Approval")

		# Case 8: Job 1 paused for parts, Job 2 paused for approval -> Waiting for Parts
		jobs = [
			{"status": "Paused", "pause_reason": "Waiting for Parts"},
			{"status": "Paused", "pause_reason": "Awaiting Approval"},
		]
		self.assertEqual(compute_operational_status(jobs, []), "Waiting for Parts")

	def test_board_fields_and_completed_order_lock(self):
		# Setup vehicle
		veh_id = "TST-BOARD-01"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-BOARD-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.append("jobs", {
			"job_title": "Oil Change",
			"estimated_hours": 1.5,
			"rate": 50.0,
			"technician_name": "John Doe",
		})
		so.insert(ignore_permissions=True)

		self.assertEqual(so.board_status, "Open")
		self.assertEqual(so.job_count, 1)
		self.assertIn("John Doe", so.technicians)
		self.assertIsNotNone(so.order_date)

		# Transition to Ready for Billing (Completed)
		so.status = "Ready for Billing"
		so.save(ignore_permissions=True)
		self.assertEqual(so.board_status, "Completed")

		# Modifying jobs on completed order directly should fail
		so.jobs[0].job_title = "Modified Title"
		self.assertRaises(frappe.ValidationError, so.save)

		# Reload so doc status clean
		so.reload()
		# Direct Service Job edit on completed order should also fail
		sj_name = so.jobs[0].service_job
		sj = frappe.get_doc("Service Job", sj_name)
		sj.job_title = "Modified Title directly"
		self.assertRaises(frappe.ValidationError, sj.save)

	def test_job_control_actions_workflow(self):
		from vehicle_service.job_control import (
			add_job,
			assign_technician,
			start_clock,
			pause_clock,
			complete_service_order,
			order_has_permission,
		)

		veh_id = "TST-JC-01"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-JC-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		# Ensure test employee exists
		emp_name = frappe.db.get_value("Employee", {"first_name": "Alex", "last_name": "Tech"})
		if not emp_name:
			company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company")[0].name
			emp = frappe.new_doc("Employee")
			emp.first_name = "Alex"
			emp.last_name = "Tech"
			emp.gender = "Male"
			emp.company = company
			emp.date_of_birth = "1990-01-01"
			emp.date_of_joining = "2020-01-01"
			emp.status = "Active"
			emp.insert(ignore_permissions=True)
			emp_id = emp.name
		else:
			emp_id = emp_name

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.insert(ignore_permissions=True)

		# 1. Add Job
		res_add = add_job(so.name, job_title="Brake Service", estimated_hours=2.0)
		job_name = res_add["job"]
		job = frappe.get_doc("Service Job", job_name)
		self.assertEqual(job.status, "Approved")
		so.reload()
		self.assertEqual(len(so.jobs), 1)

		# 2. Start Clock without technician should fail
		self.assertRaises(frappe.ValidationError, start_clock, job_name)

		# 3. Assign Technician
		assign_technician(job_name, emp_id)
		job.reload()
		self.assertEqual(job.technician, emp_id)
		self.assertEqual(job.status, "Assigned")

		# 4. Start Clock
		start_clock(job_name)
		job.reload()
		self.assertEqual(job.status, "In Progress")
		self.assertEqual(len(job.time_logs), 1)
		self.assertIsNone(job.time_logs[0].to_time)

		# 5. Starting a second clock for same technician on another job must fail
		res_add2 = add_job(so.name, job_title="Tyre Rotation", technician=emp_id)
		self.assertRaises(frappe.ValidationError, start_clock, res_add2["job"])

		# 6. Pause Clock
		pause_clock(job_name, reason="Lunch break")
		job.reload()
		self.assertEqual(job.status, "Paused")
		self.assertIsNotNone(job.time_logs[0].to_time)

		# 7. Resume Clock
		start_clock(job_name)
		job.reload()
		self.assertEqual(job.status, "In Progress")
		self.assertEqual(len(job.time_logs), 2)

		# 8. Complete Service Order
		complete_service_order(so.name)
		so.reload()
		job.reload()
		self.assertEqual(so.status, "Ready for Billing")
		self.assertEqual(so.board_status, "Completed")
		self.assertEqual(job.status, "Completed")
		self.assertIsNotNone(job.time_logs[1].to_time)

		# 9. Actions on completed order should be rejected
		self.assertRaises(frappe.ValidationError, add_job, so.name, "New Job")
		self.assertRaises(frappe.ValidationError, start_clock, job_name)

		# 10. Permission hook check
		jc_user = "jobcontroller.test@example.com"
		# Job Controller can read completed order but cannot write
		self.assertTrue(order_has_permission(so, ptype="read", user=jc_user))
		self.assertFalse(order_has_permission(so, ptype="write", user=jc_user))
		# Administrator can read and write
		self.assertTrue(order_has_permission(so, ptype="read", user="Administrator"))
		self.assertTrue(order_has_permission(so, ptype="write", user="Administrator"))

		# Job Controller can both read and write an open / in-progress order
		open_so = frappe.new_doc("Service Order")
		open_so.vehicle = veh_id
		open_so.customer = "Test Customer"
		open_so.status = "In Progress"
		self.assertTrue(order_has_permission(open_so, ptype="read", user=jc_user))
		self.assertTrue(order_has_permission(open_so, ptype="write", user=jc_user))

	def test_sales_invoice_labour_hours_sync(self):
		from vehicle_service.job_control import add_job, complete_service_order
		from vehicle_service.vehicle_service.doctype.service_order.service_order import create_sales_invoice_from_order

		veh_id = "TST-INV-01"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-INV-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.insert(ignore_permissions=True)

		res_add = add_job(so.name, job_title="Engine Diagnostics", estimated_hours=1.0)
		job_name = res_add["job"]

		# Complete order to ready for billing
		complete_service_order(so.name)

		# Create Sales Invoice
		res_inv = create_sales_invoice_from_order(so.name)
		inv = frappe.get_doc("Sales Invoice", res_inv["sales_invoice"])

		# Service advisor modifies labour quantity from 1.0 to 2.5 hours on the invoice
		found_job_item = False
		for item in inv.items:
			if getattr(item, "vs_job", None) == job_name:
				item.qty = 2.5
				found_job_item = True
		self.assertTrue(found_job_item)

		inv.save(ignore_permissions=True)
		inv.submit()

		# Verify that the Service Job estimated_hours and row on order updated to 2.5
		job = frappe.get_doc("Service Job", job_name)
		self.assertEqual(flt(job.estimated_hours), 2.5)

		so.reload()
		for row in so.jobs:
			if row.service_job == job_name:
				self.assertEqual(flt(row.estimated_hours), 2.5)

	def test_role_and_test_user_setup(self):
		from vehicle_service.job_control_setup import create_all_test_users
		create_all_test_users()

		self.assertTrue(frappe.db.exists("Role", "Job Controller"))
		self.assertTrue(frappe.db.exists("Role", "Service Advisor"))
		self.assertTrue(frappe.db.exists("Role", "Parts Controller"))
		self.assertTrue(frappe.db.exists("Role", "Parts Manager"))

		self.assertTrue(frappe.db.exists("Workspace", "Job Control Board"))
		self.assertTrue(frappe.db.exists("User", "jobcontroller.test@example.com"))
		self.assertTrue(frappe.db.exists("User", "serviceadvisor.test@example.com"))
		self.assertTrue(frappe.db.exists("User", "partscontroller.test@example.com"))

		ws = frappe.get_doc("Workspace", "Job Control Board")
		self.assertEqual(ws.title, "Job Control Board")

		jc_roles = frappe.get_roles("jobcontroller.test@example.com")
		self.assertIn("Job Controller", jc_roles)
		self.assertNotIn("System Manager", jc_roles)

		sa_roles = frappe.get_roles("serviceadvisor.test@example.com")
		self.assertIn("Service Advisor", sa_roles)

		pc_roles = frappe.get_roles("partscontroller.test@example.com")
		self.assertIn("Parts Controller", pc_roles)

	def test_draft_invoice_creation_with_incomplete_jobs_and_sync(self):
		from vehicle_service.job_control import add_job, complete_service_order
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			create_sales_invoice_from_order,
			add_manual_part,
		)

		veh_id = "TST-INV-DRAFT-01"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-INV-DRAFT-01"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		part_item = frappe.db.get_value("Item", {"is_stock_item": 1}, "name")
		if not part_item:
			p = frappe.new_doc("Item")
			p.item_code = "TST-DRAFT-PART"
			p.item_name = "Test Draft Part"
			p.item_group = "Raw Material"
			p.is_stock_item = 1
			p.valuation_rate = 80.0
			p.insert(ignore_permissions=True)
			part_item = p.name

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.status = "In Progress"
		so.flags.ignore_open_order_validation = True
		so.insert(ignore_permissions=True)

		res_add = add_job(so.name, job_title="Brake Inspection", estimated_hours=2.0)
		job_name = res_add["job"]

		# 1. Create draft invoice while order is In Progress and job is NOT completed
		res_inv = create_sales_invoice_from_order(so.name)
		self.assertEqual(res_inv["status"], "success")
		inv_name = res_inv["sales_invoice"]
		inv = frappe.get_doc("Sales Invoice", inv_name)
		self.assertEqual(inv.docstatus, 0)

		# Labour line must be present with estimated hours
		job_items = [it for it in inv.items if getattr(it, "vs_job", None) == job_name]
		self.assertEqual(len(job_items), 1)
		self.assertEqual(flt(job_items[0].qty), 2.0)

		# 2. Submitting Sales Invoice while job is still In Progress must fail
		self.assertRaises(frappe.ValidationError, inv.submit)

		# 3. Add part to Service Order after invoice was already created in draft
		settings = frappe.get_cached_doc("Vehicle Service Settings")
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
		make_stock_entry(
			item_code=part_item,
			to_warehouse=settings.wip_warehouse,
			qty=5.0,
			rate=80.0,
			purpose="Material Receipt",
			company=so.company,
		)

		res_part = add_manual_part(
			service_order=so.name,
			item_code=part_item,
			qty_required=1.0,
			rate=100.0,
		)
		so.reload()
		part_row = so.parts[-1]
		part_row.approval_status = "Approved"
		part_row.qty_issued = 1.0
		part_row.qty_used = 1.0
		so.flags.ignore_invoice_lock = True
		so.flags.ignore_job_lock = True
		so.save(ignore_permissions=True)

		# Calling create_sales_invoice_from_order or auto-sync updates draft invoice
		create_sales_invoice_from_order(so.name)
		inv.reload()
		part_items = [it for it in inv.items if getattr(it, "vs_part_row", None) == part_row.name]
		self.assertEqual(len(part_items), 1)
		self.assertEqual(flt(part_items[0].qty), 1.0)
		self.assertEqual(flt(part_items[0].rate), 100.0)

		# 4. Now complete the workshop jobs
		complete_service_order(so.name)
		so.reload()
		self.assertEqual(so.status, "Ready for Billing")

		# 5. Now submitting the Sales Invoice must succeed
		inv.reload()
		inv.submit()
		self.assertEqual(inv.docstatus, 1)

		so.reload()
		self.assertIn(so.status, ["Invoiced", "Ready for Collection"])

	def test_get_board_orders_multi_clock(self):
		from vehicle_service.job_board import get_board_orders
		from vehicle_service.job_control import add_job, assign_technician, start_clock

		veh_id = "TST-BOARD-02"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = veh_id
			v.customer = "Test Customer"
			v.vin = "VIN-TST-BOARD-02"
			v.make = "Ford"
			v.model = "Ranger"
			v.insert(ignore_permissions=True)

		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company")[0].name
		emp1 = frappe.db.get_value("Employee", {"first_name": "Alex", "last_name": "Tech"})
		if not emp1:
			e1 = frappe.new_doc("Employee")
			e1.first_name = "Alex"
			e1.last_name = "Tech"
			e1.gender = "Male"
			e1.company = company
			e1.date_of_birth = "1990-01-01"
			e1.date_of_joining = "2020-01-01"
			e1.status = "Active"
			e1.insert(ignore_permissions=True)
			emp1 = e1.name

		emp2 = frappe.db.get_value("Employee", {"first_name": "Sam", "last_name": "Tech"})
		if not emp2:
			e2 = frappe.new_doc("Employee")
			e2.first_name = "Sam"
			e2.last_name = "Tech"
			e2.gender = "Female"
			e2.company = company
			e2.date_of_birth = "1992-02-02"
			e2.date_of_joining = "2021-01-01"
			e2.status = "Active"
			e2.insert(ignore_permissions=True)
			emp2 = e2.name

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.insert(ignore_permissions=True)

		j1 = add_job(so.name, job_title="Front Brake Pads", estimated_hours=1.5)["job"]
		j2 = add_job(so.name, job_title="Oil & Filter Change", estimated_hours=1.0)["job"]

		assign_technician(j1, emp1)
		assign_technician(j2, emp2)

		start_clock(j1)
		start_clock(j2)

		cards = get_board_orders("In Progress")
		order_card = next((c for c in cards if c["name"] == so.name), None)
		self.assertIsNotNone(order_card, f"Service Order {so.name} must appear on In Progress tab")

		self.assertEqual(order_card["clock_count"], 2)
		self.assertTrue(order_card["has_running_clock"])
		self.assertEqual(len(order_card["active_clocks"]), 2)
		self.assertEqual(len(order_card["jobs"]), 2)

		active_techs = {c["technician"] for c in order_card["active_clocks"]}
		self.assertEqual(active_techs, {emp1, emp2})

	def test_multi_technician_running_and_paused_clocks_on_board(self):
		from vehicle_service.job_control import add_job, assign_technician, start_clock, pause_clock
		from vehicle_service.job_board import get_board_orders
		from frappe.utils import now_datetime

		veh_id = "TST-BOARD-02"
		if not frappe.db.exists("Service Vehicle", veh_id):
			v = frappe.new_doc("Service Vehicle")
			v.license_plate = veh_id
			v.customer = "Test Customer"
			v.make = "Toyota"
			v.model = "Hilux"
			v.insert(ignore_permissions=True)

		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company", pluck="name")[0]
		emp1 = frappe.db.get_value("Employee", {"first_name": "Alex", "last_name": "Tech"})
		emp2 = frappe.db.get_value("Employee", {"first_name": "Sam", "last_name": "Tech"})

		so = frappe.new_doc("Service Order")
		so.vehicle = veh_id
		so.customer = "Test Customer"
		so.insert(ignore_permissions=True)

		j1 = add_job(so.name, job_title="Engine Diagnosis", estimated_hours=2.0)["job"]
		j2 = add_job(so.name, job_title="Brake Replacement", estimated_hours=1.5)["job"]

		assign_technician(j1, emp1)
		assign_technician(j2, emp2)

		start_clock(j1)
		start_clock(j2)

		# Pause j1 with Waiting for Parts, leaving j2 running
		pause_clock(j1, reason="Waiting for Parts")

		cards = get_board_orders("In Progress")
		order_card = next((c for c in cards if c["name"] == so.name), None)
		self.assertIsNotNone(order_card, f"Service Order {so.name} must appear on In Progress tab")

		self.assertTrue(order_card["has_running_clock"])
		self.assertEqual(len(order_card["active_clocks"]), 1)
		self.assertEqual(order_card["active_clocks"][0]["technician"], emp2)

		self.assertIn("paused_clocks", order_card)
		self.assertEqual(len(order_card["paused_clocks"]), 1)
		paused_info = order_card["paused_clocks"][0]
		self.assertEqual(paused_info["job"], j1)
		self.assertEqual(paused_info["technician"], emp1)
		self.assertEqual(paused_info["pause_reason"], "Waiting for Parts")


