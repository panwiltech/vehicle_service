# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime, add_to_date
from vehicle_service.vehicle_service.doctype.service_order.service_order import (
	check_in_vehicle,
	record_customer_approval,
)
from vehicle_service.vehicle_service.doctype.service_job.service_job import (
	start_job,
	pause_job,
)
from vehicle_service.vehicle_service.page.workshop_control.workshop_control import (
	get_workshop_live_board,
	quick_assign_technician_bay,
	quick_move_bay,
	quick_start_job,
	quick_pause_job,
)
from vehicle_service.vehicle_service.page.parts_control.parts_control import (
	get_parts_control_board,
	create_shortage_material_request,
)


class TestWorkshopControlPages(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_locations_and_vehicle()

	def setup_locations_and_vehicle(self):
		# Create workshop locations / bays
		bays = [
			{"location_name": "Bay 1 - Lift", "location_type": "Bay"},
			{"location_name": "Bay 2 - Alignment", "location_type": "Bay"},
			{"location_name": "Bay 3 - Diagnostics", "location_type": "Bay"},
		]
		for b in bays:
			if not frappe.db.exists("Workshop Location", b["location_name"]):
				loc = frappe.new_doc("Workshop Location")
				loc.location_name = b["location_name"]
				loc.location_type = b["location_type"]
				loc.is_active = 1
				loc.insert(ignore_permissions=True)

		# Create customer
		if not frappe.db.exists("Customer", "Live Board Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Live Board Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create test item
		if not frappe.db.exists("Item", "BRAKE-PAD-TEST"):
			it = frappe.new_doc("Item")
			it.item_code = "BRAKE-PAD-TEST"
			it.item_name = "Front Brake Pad"
			it.item_group = "Products"
			it.is_stock_item = 1
			it.stock_uom = "Nos"
			it.insert(ignore_permissions=True)

		# Create technician employee
		company = frappe.get_all("Company")[0].name
		if not frappe.db.exists("Employee", {"first_name": "TestAdmin", "last_name": "Tech"}):
			emp = frappe.new_doc("Employee")
			emp.first_name = "TestAdmin"
			emp.last_name = "Tech"
			emp.company = company
			emp.gender = "Male"
			emp.date_of_birth = "1990-01-01"
			emp.date_of_joining = "2020-01-01"
			emp.insert(ignore_permissions=True)
			self.emp = emp
		else:
			self.emp = frappe.get_doc("Employee", {"first_name": "TestAdmin", "last_name": "Tech"})

		# Create vehicle
		reg_no = "BOARD 101"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Ford"
			veh.model = "Ranger"
			veh.vin = "VIN-BOARD-101"
			veh.year = 2023
			veh.customer = "Live Board Customer"
			veh.current_mileage = 45000
			veh.current_location = "Bay 1 - Lift"
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)
			veh.current_location = "Bay 1 - Lift"
			veh.save(ignore_permissions=True)

	def test_workshop_live_board_data(self):
		# Create Service Order with Job
		veh = frappe.get_doc("Service Vehicle", "BOARD 101")
		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = veh.customer
		order.priority = "Urgent"
		order.current_location = "Bay 1 - Lift"
		order.insert(ignore_permissions=True)

		job = frappe.new_doc("Service Job")
		job.service_order = order.name
		job.job_title = "Suspension Overhaul"
		job.technician = self.emp.name
		job.bay = "Bay 1 - Lift"
		job.status = "Assigned"
		job.estimated_hours = 3.0
		job.category = "Essential"
		job.insert(ignore_permissions=True)

		check_in_vehicle(
			order_name=order.name,
			odometer_in=45000,
			fuel_level="1/2",
		)
		order.reload()
		order.status = "In Progress"
		order.save(ignore_permissions=True)

		board = get_workshop_live_board(filters={})
		self.assertIn("kpis", board)
		self.assertIn("bays", board)
		self.assertIn("unallocated_orders", board)

		# KPI assertions
		self.assertGreaterEqual(board["kpis"]["total_on_site"], 1)
		self.assertGreaterEqual(board["kpis"]["total_bays"], 3)

		# Check bay list contains Bay 1 (occupied) and Bay 2 (available)
		occupied_bays = [b for b in board["bays"] if b.get("is_occupied")]
		empty_bays = [b for b in board["bays"] if not b.get("is_occupied")]

		self.assertTrue(any(b["location_name"] == "Bay 1 - Lift" for b in occupied_bays))
		self.assertTrue(any(b["location_name"] == "Bay 2 - Alignment" for b in empty_bays))

		# Test quick actions
		job = frappe.get_all("Service Job", filters={"service_order": order.name}, limit=1)[0]
		quick_start_job(job.name)
		job_doc = frappe.get_doc("Service Job", job.name)
		self.assertEqual(job_doc.status, "In Progress")

		quick_pause_job(job.name, reason="Testing Pause")
		job_doc = frappe.get_doc("Service Job", job.name)
		self.assertEqual(job_doc.status, "Paused")

		quick_move_bay(order.name, "Bay 2 - Alignment")
		order.reload()
		self.assertEqual(order.current_location, "Bay 2 - Alignment")

	def test_parts_control_board_data(self):
		# Create dedicated vehicle
		reg_no = "PARTS 202"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Toyota"
			veh.model = "Corolla"
			veh.vin = "VIN-PARTS-202"
			veh.year = 2023
			veh.customer = "Live Board Customer"
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = veh.customer
		order.priority = "Normal"
		order.insert(ignore_permissions=True)

		job = frappe.new_doc("Service Job")
		job.service_order = order.name
		job.job_title = "Front Brake Replacement"
		job.status = "Assigned"
		job.insert(ignore_permissions=True)

		order.append("parts", {
			"item_code": "BRAKE-PAD-TEST",
			"item_name": "Front Brake Pad",
			"job": job.name,
			"qty_required": 2.0,
			"qty_issued": 0.0,
			"part_status": "Draft",
			"approval_status": "Approved",
		})
		order.status = "Approved"
		order.save(ignore_permissions=True)

		# Fetch parts board
		board = get_parts_control_board(filters={})
		self.assertIn("kpis", board)
		self.assertIn("to_issue", board)
		self.assertIn("in_wip", board)
		self.assertIn("shortages", board)

		self.assertGreaterEqual(board["kpis"]["lines_to_pick"], 1)

		# Test shortage material request creation
		mr_name = create_shortage_material_request("BRAKE-PAD-TEST", 5.0)
		self.assertTrue(frappe.db.exists("Material Request", mr_name))
		mr = frappe.get_doc("Material Request", mr_name)
		self.assertEqual(mr.items[0].item_code, "BRAKE-PAD-TEST")
		self.assertEqual(mr.items[0].qty, 5.0)
