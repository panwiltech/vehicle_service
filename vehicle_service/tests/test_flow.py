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
	add_ad_hoc_job,
	add_manual_part,
	assign_job,
	check_in_vehicle,
	correct_intake,
	create_estimate,
	deliver_vehicle,
	issue_parts_to_workshop,
	make_service_quotation,
	record_customer_approval,
	request_part_substitution,
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

		if not frappe.db.exists("Item", "BRAKE-PAD-ALT"):
			it3 = frappe.new_doc("Item")
			it3.item_code = "BRAKE-PAD-ALT"
			it3.item_name = "Alternative Brake Pad"
			it3.item_group = "Products"
			it3.is_stock_item = 1
			it3.insert(ignore_permissions=True)

		# Setup settings
		settings = frappe.get_single("Vehicle Service Settings")
		settings.labour_item = "LABOUR-TEST"
		settings.labour_rate = 60.0
		settings.save(ignore_permissions=True)

		emp_name = frappe.db.get_value("Employee", {"first_name": "Test", "last_name": "Tech"})
		if not emp_name:
			company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.get_all("Company")[0].name
			e = frappe.new_doc("Employee")
			e.first_name = "Test"
			e.last_name = "Tech"
			e.gender = "Male"
			e.status = "Active"
			e.company = company
			e.date_of_birth = "1990-01-01"
			e.date_of_joining = "2020-01-01"
			e.insert(ignore_permissions=True)
			self.emp_name = e.name
		else:
			self.emp_name = emp_name

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

	def test_add_ad_hoc_job_workflow(self):
		reg_no = "TST-ADHOC-01"
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Toyota"
			veh.model = "Corolla"
			veh.vin = "VIN-TST-ADHOC"
			veh.customer = "Test Customer"
			veh.current_mileage = 60000
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = "Test Customer"
		order.service_advisor = "Administrator"
		order.insert(ignore_permissions=True)

		res = add_ad_hoc_job(
			service_order=order.name,
			job_title="Inspect Suspension Struts",
			category="Essential",
			estimated_hours=1.5,
			description="Check front suspension noise"
		)
		self.assertEqual(res["status"], "success")
		job_name = res["job"]
		self.assertTrue(frappe.db.exists("Service Job", job_name))

		job_doc = frappe.get_doc("Service Job", job_name)
		self.assertEqual(job_doc.job_title, "Inspect Suspension Struts")
		self.assertEqual(job_doc.category, "Essential")
		self.assertEqual(job_doc.estimated_hours, 1.5)
		self.assertIn(job_doc.source, ["Additional", "Manually Added"])

	def create_clean_order(self, reg_no="TST-DEC-01"):
		if not frappe.db.exists("Service Vehicle", reg_no):
			veh = frappe.new_doc("Service Vehicle")
			veh.registration_no = reg_no
			veh.make = "Toyota"
			veh.model = "Hilux"
			veh.vin = f"VIN-{reg_no}"
			veh.customer = "Test Customer"
			veh.current_mileage = 45000
			veh.insert(ignore_permissions=True)
		else:
			veh = frappe.get_doc("Service Vehicle", reg_no)

		order = frappe.new_doc("Service Order")
		order.vehicle = veh.name
		order.customer = "Test Customer"
		order.service_advisor = "Administrator"
		order.insert(ignore_permissions=True)
		return order

	def test_scenario_1_approved_quotation_auto_population(self):
		import json
		order = self.create_clean_order("TST-SCEN1-01")
		check_in_vehicle(order.name, odometer_in=45000, fuel_level="1/2", customer_complaint="Annual service")

		q = frappe.new_doc("Quotation")
		q.party_name = "Test Customer"
		q.vs_service_order = order.name
		q.append("items", {
			"item_code": "LABOUR-TEST",
			"item_name": "Major Service Labour",
			"qty": 2.0,
			"rate": 75.0,
			"vs_category": "Essential",
			"vs_approval": "Pending",
		})
		q.append("items", {
			"item_code": "BRAKE-PAD-TEST",
			"item_name": "Front Brake Pad",
			"qty": 1.0,
			"rate": 120.0,
			"vs_category": "Essential",
			"vs_approval": "Pending",
		})
		q.insert(ignore_permissions=True)
		q.submit()

		decisions = {it.name: "Approved" for it in q.items}
		res = record_customer_approval(
			order_name=order.name,
			quotation_name=q.name,
			approvals_json=json.dumps(decisions),
			approval_method="Signed",
		)
		self.assertEqual(res["status"], "success")
		self.assertTrue(res.get("sales_order"))

		order.reload()
		# Verify Service Job auto-populated
		jobs = frappe.get_all("Service Job", filters={"service_order": order.name}, fields=["name", "job_title", "status", "source"])
		self.assertEqual(len(jobs), 1)
		self.assertEqual(jobs[0].job_title, "Major Service Labour")
		self.assertEqual(jobs[0].status, "Approved")
		self.assertEqual(jobs[0].source, "From Quotation")

		# Verify Service Order Part auto-populated
		self.assertEqual(len(order.parts), 1)
		part = order.parts[0]
		self.assertEqual(part.item_code, "BRAKE-PAD-TEST")
		self.assertEqual(part.approval_status, "Approved")
		self.assertEqual(part.part_status, "Required")
		self.assertEqual(part.source, "From Quotation")

	def test_scenario_2_new_job_after_quotation_approval(self):
		import json
		order = self.create_clean_order("TST-SCEN2-01")
		check_in_vehicle(order.name, odometer_in=45000, fuel_level="1/2", customer_complaint="Brake service")

		q = frappe.new_doc("Quotation")
		q.party_name = "Test Customer"
		q.vs_service_order = order.name
		q.append("items", {
			"item_code": "LABOUR-TEST",
			"item_name": "Brake Replacement Labour",
			"qty": 2.0,
			"rate": 60.0,
			"vs_category": "Essential",
			"vs_approval": "Pending",
		})
		q.insert(ignore_permissions=True)
		q.submit()

		decisions = {it.name: "Approved" for it in q.items}
		record_customer_approval(
			order_name=order.name,
			quotation_name=q.name,
			approvals_json=json.dumps(decisions),
		)

		# Job Controller adds new job discovered after quotation approval
		job_res = add_ad_hoc_job(
			service_order=order.name,
			job_title="Inspect Steering Rack",
			category="Recommended",
			estimated_hours=1.0,
			priority="High",
			reason="Play noticed during test drive",
		)
		self.assertEqual(job_res["status"], "success")

		new_job = frappe.get_doc("Service Job", job_res["job"])
		self.assertEqual(new_job.job_title, "Inspect Steering Rack")
		self.assertEqual(new_job.source, "Additional Work")
		self.assertEqual(new_job.priority, "High")
		self.assertEqual(new_job.reason_for_adding, "Play noticed during test drive")

		# Ensure original quotation is preserved with 1 item
		q_fresh = frappe.get_doc("Quotation", q.name)
		self.assertEqual(len(q_fresh.items), 1)

	def test_scenario_3_new_part_after_quotation_approval(self):
		import json
		order = self.create_clean_order("TST-SCEN3-01")
		check_in_vehicle(order.name, odometer_in=45000, fuel_level="1/2", customer_complaint="Maintenance")

		q = frappe.new_doc("Quotation")
		q.party_name = "Test Customer"
		q.vs_service_order = order.name
		q.append("items", {
			"item_code": "LABOUR-TEST",
			"item_name": "General Check Labour",
			"qty": 1.0,
			"rate": 60.0,
			"vs_category": "Essential",
			"vs_approval": "Pending",
		})
		q.insert(ignore_permissions=True)
		q.submit()

		decisions = {it.name: "Approved" for it in q.items}
		record_customer_approval(order_name=order.name, quotation_name=q.name, approvals_json=json.dumps(decisions))

		# Parts Manager adds additional part discovered
		part_res = add_manual_part(
			service_order=order.name,
			item_code="BRAKE-PAD-TEST",
			qty_required=2.0,
			rate=110.0,
			reason="Extra pads required for rear axle",
		)
		self.assertEqual(part_res["status"], "success")

		order.reload()
		part = next(p for p in order.parts if p.name == part_res["part"])
		self.assertEqual(part.item_code, "BRAKE-PAD-TEST")
		self.assertEqual(part.qty_required, 2.0)
		self.assertEqual(part.source, "Additional Part")
		self.assertEqual(part.approval_status, "Approved")
		self.assertEqual(part.part_status, "Required")
		self.assertEqual(part.reason_for_adding, "Extra pads required for rear axle")

	def test_scenario_4_service_order_without_quotation_operational(self):
		# Service Order created without any quotation
		order = self.create_clean_order("TST-SCEN4-01")
		check_in_vehicle(order.name, odometer_in=45000, fuel_level="3/4", customer_complaint="Quick oil service")

		# Job Controller adds job and assigns technician
		job_res = add_ad_hoc_job(
			service_order=order.name,
			job_title="Oil and Filter Change",
			category="Essential",
			estimated_hours=0.8,
			reason="Immediate express service",
		)
		self.assertEqual(job_res["status"], "success")

		job_doc = frappe.get_doc("Service Job", job_res["job"])
		self.assertEqual(job_doc.source, "Manually Added")

		# Assign technician directly
		assign_res = assign_job(job_name=job_doc.name, technician=self.emp_name)
		self.assertEqual(assign_res["status"], "success")
		job_doc.reload()
		self.assertEqual(job_doc.status, "Assigned")

		# Parts Manager adds parts directly
		part_res = add_manual_part(
			service_order=order.name,
			item_code="BRAKE-PAD-TEST",
			qty_required=1.0,
			job=job_doc.name,
			reason="Replaced during express check",
		)
		self.assertEqual(part_res["status"], "success")

		order.reload()
		part = next(p for p in order.parts if p.name == part_res["part"])
		self.assertEqual(part.source, "Manually Added")
		self.assertEqual(part.approval_status, "Approved")
		self.assertEqual(part.part_status, "Required")

		# Verify no quotation document exists for this order
		quotations = frappe.get_all("Quotation", filters={"vs_service_order": order.name})
		self.assertEqual(len(quotations), 0)

	def test_scenario_5_additional_job_with_linked_parts(self):
		order = self.create_clean_order("TST-SCEN5-01")
		# Job Controller creates new job
		job_res = add_ad_hoc_job(
			service_order=order.name,
			job_title="Front Brake Overhaul",
			category="Essential",
			estimated_hours=2.0,
			priority="High",
		)
		job_name = job_res["job"]

		# Parts Manager creates part specifically linked to this job
		part_res = add_manual_part(
			service_order=order.name,
			item_code="BRAKE-PAD-TEST",
			qty_required=2.0,
			job=job_name,
			reason="Pads for front overhaul job",
		)

		order.reload()
		part = next(p for p in order.parts if p.name == part_res["part"])
		self.assertEqual(part.job, job_name)
		self.assertEqual(part.source, "Manually Added")

	def test_scenario_6_part_substitution_workflow(self):
		order = self.create_clean_order("TST-SCEN6-01")
		part_res = add_manual_part(
			service_order=order.name,
			item_code="BRAKE-PAD-TEST",
			qty_required=1.0,
			rate=100.0,
			reason="Initial requirement",
		)
		orig_row_name = part_res["part"]

		# Parts Manager requests substitution with BRAKE-PAD-ALT
		sub_res = request_part_substitution(
			service_order=order.name,
			part_row=orig_row_name,
			substitute_item="BRAKE-PAD-ALT",
			qty=1.0,
			reason="BRAKE-PAD-TEST out of stock, using alternate brand",
		)
		self.assertEqual(sub_res["status"], "success")

		order.reload()
		orig_row = next(p for p in order.parts if p.name == orig_row_name)
		self.assertEqual(orig_row.part_status, "Substituted")
		self.assertTrue(orig_row.substituted_by)

		sub_row = next(p for p in order.parts if p.name == sub_res["new_part_row"])
		self.assertEqual(sub_row.item_code, "BRAKE-PAD-ALT")
		self.assertEqual(sub_row.source, "Substitute Part")
		self.assertEqual(sub_row.approval_status, "Approved")
		self.assertEqual(sub_row.part_status, "Required")

	def test_scenario_7_duplicate_prevention_on_repeated_approval(self):
		import json
		order = self.create_clean_order("TST-SCEN7-01")
		check_in_vehicle(order.name, odometer_in=50000, fuel_level="1/2", customer_complaint="Service check")

		q = frappe.new_doc("Quotation")
		q.party_name = "Test Customer"
		q.vs_service_order = order.name
		q.append("items", {
			"item_code": "LABOUR-TEST",
			"item_name": "Single Labor Item",
			"qty": 1.0,
			"rate": 60.0,
			"vs_category": "Essential",
			"vs_approval": "Pending",
		})
		q.append("items", {
			"item_code": "BRAKE-PAD-TEST",
			"item_name": "Single Part Item",
			"qty": 1.0,
			"rate": 100.0,
			"vs_category": "Essential",
			"vs_approval": "Pending",
		})
		q.insert(ignore_permissions=True)
		q.submit()

		decisions = {it.name: "Approved" for it in q.items}

		# First approval trigger
		record_customer_approval(order_name=order.name, quotation_name=q.name, approvals_json=json.dumps(decisions))
		order.reload()
		initial_jobs_count = len(frappe.get_all("Service Job", filters={"service_order": order.name}))
		initial_parts_count = len(order.parts)

		self.assertEqual(initial_jobs_count, 1)
		self.assertEqual(initial_parts_count, 1)

		# Second approval trigger (re-running customer approval)
		record_customer_approval(order_name=order.name, quotation_name=q.name, approvals_json=json.dumps(decisions))
		order.reload()
		subsequent_jobs_count = len(frappe.get_all("Service Job", filters={"service_order": order.name}))
		subsequent_parts_count = len(order.parts)

		# Ensure no duplicates were spawned
		self.assertEqual(subsequent_jobs_count, initial_jobs_count)
		self.assertEqual(subsequent_parts_count, initial_parts_count)

	def test_issue_parts_to_workshop_workflow(self):
		import json
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
		order = self.create_clean_order("TST-ISSUE-01")
		settings = frappe.get_cached_doc("Vehicle Service Settings")

		# Ensure stock exists in stores warehouse before transfer
		make_stock_entry(
			item_code="BRAKE-PAD-TEST",
			to_warehouse=settings.parts_warehouse,
			qty=10.0,
			rate=50.0,
			purpose="Material Receipt",
			company=order.company,
		)

		# Add an approved part directly
		part_res = add_manual_part(
			service_order=order.name,
			item_code="BRAKE-PAD-TEST",
			qty_required=2.0,
			rate=100.0,
			reason="Direct issuance test",
		)
		self.assertEqual(part_res["status"], "success")

		# Issue parts to workshop WIP
		issue_res = issue_parts_to_workshop(
			order_name=order.name,
			items_json=json.dumps([{"part_row": part_res["part"], "qty": 2.0}]),
		)
		self.assertEqual(issue_res["status"], "success")
		self.assertTrue(issue_res.get("stock_entry"))

		order.reload()
		part = next(p for p in order.parts if p.name == part_res["part"])
		self.assertEqual(part.qty_issued, 2.0)
		self.assertEqual(part.part_status, "Issued")

	def test_direct_table_row_part_addition_and_issuance(self):
		import json
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
		order = self.create_clean_order("TST-GRID-ADD-01")
		settings = frappe.get_cached_doc("Vehicle Service Settings")

		# Ensure stock exists in stores warehouse
		make_stock_entry(
			item_code="BRAKE-PAD-TEST",
			to_warehouse=settings.parts_warehouse,
			qty=10.0,
			rate=50.0,
			purpose="Material Receipt",
			company=order.company,
		)

		# Simulate adding a row directly into the child table (like in Quotation)
		row = order.append("parts", {
			"item_code": "BRAKE-PAD-TEST",
			"qty_required": 3.0,
			"rate": 100.0,
		})
		order.save()

		order.reload()
		part = next(p for p in order.parts if p.item_code == "BRAKE-PAD-TEST")
		self.assertEqual(part.approval_status, "Approved")
		self.assertEqual(part.part_status, "Required")
		self.assertEqual(part.source, "Manually Added")
		self.assertGreater(part.rate, 0)

		# Issue the part via Stock Entry
		issue_res = issue_parts_to_workshop(
			order_name=order.name,
			items_json=json.dumps([{"part_row": part.name, "qty": 3.0}]),
		)
		self.assertEqual(issue_res["status"], "success")

		order.reload()
		part = next(p for p in order.parts if p.item_code == "BRAKE-PAD-TEST")
		self.assertEqual(part.qty_issued, 3.0)
		self.assertEqual(part.part_status, "Issued")

	def test_direct_table_row_job_addition_and_sync(self):
		order = self.create_clean_order("TST-GRID-JOB-01")

		# 1. Add job row directly to child table (Quotation-style grid row)
		jrow = order.append("jobs", {
			"job_title": "Direct Brake Check",
			"category": "Essential",
			"estimated_hours": 1.5,
		})
		order.save()

		order.reload()
		self.assertEqual(len(order.jobs), 1)
		jrow = order.jobs[0]
		self.assertEqual(jrow.job_title, "Direct Brake Check")
		self.assertEqual(jrow.source, "Manually Added")
		self.assertEqual(jrow.status, "Approved")
		self.assertTrue(jrow.service_job)

		# 2. Verify standalone Service Job doc exists and matches
		sj = frappe.get_doc("Service Job", jrow.service_job)
		self.assertEqual(sj.service_order, order.name)
		self.assertEqual(sj.job_title, "Direct Brake Check")
		self.assertEqual(sj.estimated_hours, 1.5)

		# 3. Update Service Job status to 'In Progress' and verify sync back to order.jobs
		sj.status = "In Progress"
		from frappe.utils import add_to_date, now_datetime
		t1 = now_datetime()
		t2 = add_to_date(t1, hours=1)
		sj.append("time_logs", {
			"from_time": t1,
			"to_time": t2,
			"hours": 1.0,
		})
		sj.save()

		order.sync_status_from_jobs_and_parts()
		order.reload()
		self.assertEqual(order.jobs[0].status, "In Progress")
		self.assertEqual(order.jobs[0].actual_hours, 1.0)









