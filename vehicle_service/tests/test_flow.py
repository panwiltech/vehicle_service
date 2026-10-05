# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.state import (
	compute_operational_status,
	compute_part_status,
	vehicle_status_for,
)
from vehicle_service.vehicle_service.doctype.service_booking.service_booking import (
	check_in_booking,
)
from vehicle_service.vehicle_service.doctype.service_job.service_job import (
	complete_job,
	pause_job,
	start_job,
)
from vehicle_service.vehicle_service.doctype.service_order.service_order import (
	check_in_vehicle,
	correct_intake,
	create_estimate,
	deliver_vehicle,
	make_service_quotation,
	record_customer_approval,
)
from vehicle_service.vehicle_service.doctype.service_qc.service_qc import (
	create_qc_inspection,
)


class TestVehicleServiceFlow(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.setup_master_data()

	def setup_master_data(self):
		# Create test customer
		if not frappe.db.exists("Customer", "Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		# Create test items
		if not frappe.db.exists("Item", "LABOUR-TEST"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR-TEST"
			it.item_name = "Standard Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "BRAKE-PAD-TEST"):
			it2 = frappe.new_doc("Item")
			it2.item_code = "BRAKE-PAD-TEST"
			it2.item_name = "Front Brake Pad"
			it2.item_group = "Products"
			it2.is_stock_item = 1
			it2.insert(ignore_permissions=True)

		# Setup settings
		settings = frappe.get_single("Vehicle Service Settings")
		settings.labour_item = "LABOUR-TEST"
		settings.labour_rate = 60.0
		settings.save(ignore_permissions=True)

	def test_pure_state_rules(self):
		from vehicle_service.state import PAUSED, ORDER_FLOW, stepper_position
		self.assertEqual(PAUSED, "Paused")
		self.assertIn(PAUSED, ORDER_FLOW)
		self.assertEqual(vehicle_status_for("Paused"), "Waiting")
		self.assertTrue(stepper_position("Paused") >= 0)

		# Test vehicle status mapping
		self.assertEqual(vehicle_status_for("Draft"), "Arrived")
		self.assertEqual(vehicle_status_for("In Progress"), "In Workshop")
		self.assertEqual(vehicle_status_for("QC"), "QC")
		self.assertEqual(vehicle_status_for("Delivered"), "Outside Workshop")

		# Test operational status computation
		jobs = [{"status": "Assigned"}]
		parts = []
		self.assertEqual(compute_operational_status(jobs, parts), "Ready for Work")

		jobs = [{"status": "In Progress"}]
		self.assertEqual(compute_operational_status(jobs, parts), "In Progress")

		jobs = [{"status": "Completed"}]
		self.assertEqual(compute_operational_status(jobs, parts), "QC")

	def test_end_to_end_workshop_flow(self):
		# 1. Create Vehicle
		reg_no = "TST 9999"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Toyota"
			veh.model = "Hilux"
			veh.vin = "VIN-TST-9999"
			veh.year = 2022
			veh.customer = "Test Customer"
			veh.current_mileage = 50000
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		# 2. Create Service Order
		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = veh.customer
		order.customer_complaint = "Squeaking sound when braking"
		order.insert(ignore_permissions=True)
		self.assertEqual(order.status, "Draft")

		# 3. Check-in
		check_in_vehicle(
			order_name=order.name,
			odometer_in=50100,
			fuel_level="1/2",
			customer_complaint="Squeaking sound when braking",
			existing_damage="Minor scratch on rear bumper",
			vehicle_contents="Spare wheel and jack present",
			intake_confirmed=1,
		)
		order.reload()
		self.assertEqual(order.status, "In Progress")
		self.assertEqual(order.intake_frozen, 1)

		# Verify vehicle mileage updated
		veh.reload()
		self.assertEqual(veh.current_mileage, 50100)
		self.assertEqual(veh.vehicle_status, "In Workshop")

		# 4. Correct Intake Audit Test
		correct_intake(order.name, "existing_damage", "Minor scratch on rear bumper + left wing dent", "Customer noticed additional dent")
		order.reload()
		self.assertEqual(len(order.corrections), 1)
		self.assertEqual(order.existing_damage, "Minor scratch on rear bumper + left wing dent")

		# 5. Add Jobs and Parts
		job1 = frappe.new_doc("Service Job")
		job1.service_order = order.name
		job1.job_title = "Brake Inspection & Cleaning"
		job1.estimated_hours = 1.0
		job1.category = "Essential"
		job1.insert(ignore_permissions=True)

		order.append(
			"parts",
			{
				"item_code": "BRAKE-PAD-TEST",
				"job": job1.name,
				"category": "Essential",
				"qty_required": 1.0,
				"approval_status": "Pending",
				"part_status": "Pending Approval",
			},
		)
		order.save(ignore_permissions=True)

		# 6. Create Estimate
		est_res = create_estimate(order.name)
		q_name = est_res["quotation"]
		order.reload()
		self.assertEqual(order.status, "In Progress")

		# 7. Customer Approval
		quotation = frappe.get_doc("Quotation", q_name)
		decisions = {item.name: "Approved" for item in quotation.items}
		app_res = record_customer_approval(
			order_name=order.name,
			quotation_name=q_name,
			approvals_json=decisions,
			approval_method="Phone",
			approved_by_customer="Mr. Tester",
		)
		order.reload()
		job1.reload()
		self.assertEqual(job1.status, "Approved")
		self.assertTrue(order.status in ("Approved", "Ready for Work"))

		# 8. Start & Complete Job
		job1.status = "Assigned"
		job1.save(ignore_permissions=True)

		start_job(job1.name)
		job1.reload()
		self.assertEqual(job1.status, "In Progress")

		complete_job(job1.name)
		job1.reload()
		self.assertEqual(job1.status, "Completed")

		order.reload()
		self.assertEqual(order.status, "QC")

		# 9. QC Inspection
		qc_res = create_qc_inspection(order.name)
		qc_doc = frappe.get_doc("Service QC", qc_res["qc_name"])
		for item in qc_doc.checklist:
			item.passed = 1
		qc_doc.result = "Pass"
		qc_doc.submit()

		order.reload()
		self.assertEqual(order.status, "Ready for Billing")

		# 10. Deliver
		order.status = "Ready for Collection"
		order.save(ignore_permissions=True)

		deliver_vehicle(
			order_name=order.name,
			odometer_out=50105,
			collected_by="Mr. Tester",
			delivery_notes="All work explained and accepted.",
		)
		order.reload()
		self.assertEqual(order.status, "Delivered")

		veh.reload()
		self.assertEqual(veh.vehicle_status, "Outside Workshop")
		self.assertEqual(veh.current_mileage, 50105)
		self.assertTrue(veh.next_service_mileage > 50105)

	def test_service_order_vehicle_autofill(self):
		reg_no = "TST-AUTOFILL"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Ford"
			veh.model = "Ranger"
			veh.vin = "VIN-TST-AUTOFILL"
			veh.year = 2023
			veh.customer = "Test Customer"
			veh.driver_name = "John Driver"
			veh.driver_phone = "+26377123456"
			veh.current_mileage = 45000
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		# Create order with only vehicle specified
		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.insert(ignore_permissions=True)

		self.assertEqual(order.customer, "Test Customer")
		self.assertIn("Ford Ranger", order.vehicle_description)
		self.assertEqual(order.driver_name, "John Driver")
		self.assertEqual(order.driver_phone, "+26377123456")
		self.assertEqual(order.odometer_in, 45000)

	def test_quotation_custom_fields(self):
		meta = frappe.get_meta("Quotation")
		self.assertTrue(meta.has_field("vs_service_order"))
		self.assertTrue(meta.has_field("vs_vehicle"))
		self.assertTrue(meta.has_field("vs_service_advisor"))

	def test_make_service_quotation(self):
		reg_no = "TST-Q-MAKE"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Toyota"
			veh.model = "Corolla"
			veh.vin = "VIN-TST-Q-MAKE"
			veh.customer = "Test Customer"
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = "Test Customer"
		order.service_advisor = "Administrator"
		order.insert(ignore_permissions=True)

		# Call make_service_quotation with no pre-existing jobs or parts
		res = make_service_quotation(order.name)
		self.assertEqual(res["status"], "success")
		self.assertFalse(res["existing"])
		qtn_name = res["quotation"]

		qtn = frappe.get_doc("Quotation", qtn_name)
		self.assertEqual(qtn.party_name, "Test Customer")
		self.assertEqual(qtn.vs_service_order, order.name)
		self.assertEqual(qtn.vs_vehicle, veh.name)
		self.assertEqual(qtn.vs_service_advisor, "Administrator")

		# Calling it again returns the same existing draft quotation
		res2 = make_service_quotation(order.name)
		self.assertEqual(res2["quotation"], qtn_name)
		self.assertTrue(res2["existing"])

	def test_quotation_sync_to_service_order(self):
		reg_no = "TST-Q-SYNC"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Nissan"
			veh.model = "Navara"
			veh.vin = "VIN-TST-Q-SYNC"
			veh.customer = "Test Customer"
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = "Test Customer"
		order.service_advisor = "Administrator"
		order.insert(ignore_permissions=True)

		# 1. Create quotation via make_service_quotation
		res = make_service_quotation(order.name)
		qtn = frappe.get_doc("Quotation", res["quotation"])

		# 2. Add stock part directly on quotation
		qtn.append(
			"items",
			{
				"item_code": "BRAKE-PAD-TEST",
				"item_name": "Front Brake Pad",
				"qty": 2.0,
				"rate": 85.0,
				"vs_category": "Essential",
			},
		)

		# 3. Add labour service directly on quotation
		qtn.append(
			"items",
			{
				"item_code": "LABOUR-TEST",
				"item_name": "Standard Labour",
				"qty": 2.0,
				"rate": 60.0,
				"vs_category": "Recommended",
			},
		)

		# Save quotation, which fires on_update hook sync
		qtn.save(ignore_permissions=True)

		# 4. Verify Service Order parts updated
		order.reload()
		self.assertEqual(len(order.parts), 1)
		part = order.parts[0]
		self.assertEqual(part.item_code, "BRAKE-PAD-TEST")
		self.assertEqual(part.qty_required, 2.0)
		self.assertEqual(part.rate, 85.0)
		self.assertEqual(part.quotation, qtn.name)

		# 5. Verify Service Job created
		jobs = frappe.get_all(
			"Service Job",
			filters={"service_order": order.name, "quotation": qtn.name},
			fields=["name", "job_title", "estimated_hours"],
		)
		self.assertEqual(len(jobs), 1)
		self.assertEqual(jobs[0].job_title, "Standard Labour")
		self.assertEqual(jobs[0].estimated_hours, 2.0)

	def test_workflow_intake_to_submitted_approval(self):
		reg_no = "TST-SUBMIT-APP"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Toyota"
			veh.model = "Prado"
			veh.vin = "VIN-TST-SUBMIT-APP"
			veh.customer = "Test Customer"
			veh.current_mileage = 120000
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = "Test Customer"
		order.service_advisor = "Administrator"
		order.insert(ignore_permissions=True)

		# 1. Check in vehicle -> should move to In Progress
		check_in_vehicle(
			order_name=order.name,
			odometer_in=120000,
			fuel_level="Full",
			customer_complaint="Engine noise",
			intake_confirmed=1,
		)
		order.reload()
		self.assertEqual(order.status, "In Progress")

		# Add job
		job = frappe.new_doc("Service Job")
		job.service_order = order.name
		job.job_title = "Engine Diagnostic Scan"
		job.estimated_hours = 2.0
		job.insert(ignore_permissions=True)

		# 2. Make Service Quotation -> order remains In Progress
		q_res = make_service_quotation(order.name)
		q_name = q_res["quotation"]
		order.reload()
		self.assertEqual(order.status, "In Progress")

		# 3. Submit Quotation -> order becomes Paused (Awaiting Approval)
		qtn = frappe.get_doc("Quotation", q_name)
		qtn.submit()
		order.reload()
		self.assertEqual(order.status, "Paused")
		self.assertEqual(order.pause_reason, "Awaiting Approval")

		# 4. Record Customer Approval on submitted quotation -> order resumes to In Progress
		decisions = {item.name: "Approved" for item in qtn.items}
		app_res = record_customer_approval(
			order_name=order.name,
			quotation_name=q_name,
			approvals_json=decisions,
			approval_method="Phone",
			approved_by_customer="Customer Test",
		)
		order.reload()
		self.assertTrue(order.status in ("Approved", "Ready for Work", "In Progress"))
		self.assertFalse(order.pause_reason)
		self.assertTrue(app_res.get("sales_order"))





