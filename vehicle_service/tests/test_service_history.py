# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.job_control import add_job


class TestServiceHistorySchema(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Customer", "History Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "History Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Workshop Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

	def _create_vehicle(self, reg_no: str, vin: str):
		if frappe.db.exists("Service Vehicle", reg_no):
			return frappe.get_doc("Service Vehicle", reg_no)
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = reg_no
		v.vin = vin
		v.make = "Toyota"
		v.model = "Hilux"
		v.year = 2022
		v.customer = "History Test Customer"
		v.current_mileage = 15000
		v.insert(ignore_permissions=True)
		return v

	def test_vehicle_rename_tracks_previous_registrations_idempotently(self):
		old_reg = f"OLD-{frappe.generate_hash(length=5).upper()}"
		mid_reg = f"MID-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(old_reg, f"VIN-{old_reg}")

		frappe.rename_doc("Service Vehicle", old_reg, f" {mid_reg.lower()} ", force=True)
		doc = frappe.get_doc("Service Vehicle", mid_reg)
		self.assertEqual(doc.registration_no, mid_reg)
		self.assertEqual(doc.previous_registration_nos, old_reg)

		frappe.rename_doc("Service Vehicle", mid_reg, old_reg, force=True)
		frappe.rename_doc("Service Vehicle", old_reg, mid_reg, force=True)
		doc.reload()
		tokens = [t.strip() for t in (doc.previous_registration_nos or "").split(",") if t.strip()]
		self.assertEqual(sorted(tokens), sorted([old_reg]))
		self.assertNotIn(mid_reg, tokens)

	def test_vehicle_rename_allowed_without_force_and_preserves_multi_hop_history(self):
		p1 = f"P1-{frappe.generate_hash(length=5).upper()}"
		p2 = f"P2-{frappe.generate_hash(length=5).upper()}"
		p3 = f"P3-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(p1, f"VIN-{p1}")

		# allow_rename=1 permits renaming without force=True
		frappe.rename_doc("Service Vehicle", p1, p2)
		frappe.rename_doc("Service Vehicle", p2, f"  {p3.lower()}  ")
		doc = frappe.get_doc("Service Vehicle", p3)
		self.assertEqual(doc.registration_no, p3)
		self.assertEqual(doc.previous_registration_nos, f"{p1}, {p2}")

		# Cycling back to p1 removes p1 from previous_registration_nos
		frappe.rename_doc("Service Vehicle", p3, p1)
		doc = frappe.get_doc("Service Vehicle", p1)
		self.assertEqual(doc.previous_registration_nos, f"{p2}, {p3}")

		# Blank/whitespace-only plate is rejected
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc("Service Vehicle", p1, "   ")

	def test_follows_up_job_mirrors_between_service_job_and_order(self):
		reg = f"FUP-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(reg, f"VIN-{reg}")
		so1 = frappe.new_doc("Service Order")
		so1.vehicle = reg
		so1.customer = "History Test Customer"
		so1.insert(ignore_permissions=True)
		orig_job = add_job(so1.name, job_title="Replace Rear Brake Pads", category="Recommended")
		so1.reload()
		so1.status = "Delivered"
		so1.flags.ignore_job_lock = True
		so1.save(ignore_permissions=True)

		so2 = frappe.new_doc("Service Order")
		so2.vehicle = reg
		so2.customer = "History Test Customer"
		so2.insert(ignore_permissions=True)
		follow_job = add_job(
			so2.name,
			job_title="Replace Rear Brake Pads (Follow-Up)",
			follows_up_job=orig_job["job"],
		)

		sj2 = frappe.get_doc("Service Job", follow_job["job"])
		self.assertEqual(sj2.follows_up_job, orig_job["job"])
		so2.reload()
		matching_rows = [r for r in so2.jobs if r.service_job == sj2.name]
		self.assertEqual(len(matching_rows), 1)
		self.assertEqual(matching_rows[0].follows_up_job, orig_job["job"])

	def test_follows_up_job_syncs_bidirectionally_on_service_order_save(self):
		reg = f"SYN-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(reg, f"VIN-{reg}")
		so1 = frappe.new_doc("Service Order")
		so1.vehicle = reg
		so1.customer = "History Test Customer"
		so1.insert(ignore_permissions=True)
		rec_job_a = add_job(so1.name, job_title="Flush Brake Fluid", category="Recommended")
		rec_job_b = add_job(so1.name, job_title="Align Wheels", category="Recommended")
		so1.reload()
		so1.status = "Delivered"
		so1.flags.ignore_job_lock = True
		so1.save(ignore_permissions=True)

		so2 = frappe.new_doc("Service Order")
		so2.vehicle = reg
		so2.customer = "History Test Customer"
		so2.insert(ignore_permissions=True)

		# Direction 1: Service Job -> Service Order Job when standalone Service Job is created
		sj_standalone = frappe.new_doc("Service Job")
		sj_standalone.service_order = so2.name
		sj_standalone.vehicle = reg
		sj_standalone.job_title = "Standalone Follow-Up"
		sj_standalone.follows_up_job = rec_job_a["job"]
		sj_standalone.insert(ignore_permissions=True)

		so2.reload()
		so2.save(ignore_permissions=True)
		row_standalone = next(r for r in so2.jobs if r.service_job == sj_standalone.name)
		self.assertEqual(row_standalone.follows_up_job, rec_job_a["job"])

		# Direction 1b: Service Job -> Service Order Job when existing Service Job is updated directly
		sj_direct = frappe.new_doc("Service Job")
		sj_direct.service_order = so2.name
		sj_direct.vehicle = reg
		sj_direct.job_title = "Direct Update Follow-Up"
		sj_direct.insert(ignore_permissions=True)
		so2.reload()
		so2.save(ignore_permissions=True)

		sj_direct.reload()
		sj_direct.follows_up_job = rec_job_b["job"]
		sj_direct.save(ignore_permissions=True)
		so2.reload()
		so2.save(ignore_permissions=True)
		row_direct = next(r for r in so2.jobs if r.service_job == sj_direct.name)
		self.assertEqual(row_direct.follows_up_job, rec_job_b["job"])

		# Direction 2: Service Order Job -> Service Job when child row is updated on Service Order
		row_direct.follows_up_job = rec_job_a["job"]
		so2.save(ignore_permissions=True)
		sj_direct.reload()
		self.assertEqual(sj_direct.follows_up_job, rec_job_a["job"])


class TestServiceHistorySearch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Customer", "Search Test Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Search Test Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
		if not frappe.db.exists("Customer", "Other Search Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Other Search Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Workshop Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)
		self._ensure_vehicle("ABC 1234", "VIN1234567890ABCD", prev="XYZ 9001")
		self._ensure_vehicle("DEF 5678", "VIN1234567890ABCD")
		self._ensure_vehicle("KLM 4455", "VIN9999999999KLM0")

	def tearDown(self):
		frappe.set_user("Administrator")

	def _ensure_vehicle(
		self,
		reg_no: str,
		vin: str,
		prev: str | None = None,
		customer: str = "Search Test Customer",
	):
		if frappe.db.exists("Service Vehicle", reg_no):
			v = frappe.get_doc("Service Vehicle", reg_no)
		else:
			v = frappe.new_doc("Service Vehicle")
			v.registration_no = reg_no
			v.vin = vin
			v.make = "Ford"
			v.model = "Ranger"
			v.year = 2021
			v.customer = customer
			v.insert(ignore_permissions=True)
		if prev is not None and v.previous_registration_nos != prev:
			frappe.db.set_value("Service Vehicle", v.name, "previous_registration_nos", prev)
		return v

	def _ensure_test_user(self, email: str, roles: list[str]):
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.new_doc("User")
			user.email = email
			user.first_name = email.split("@")[0]
			user.last_name = "Tester"
			user.enabled = 1
			user.user_type = "System User"
		user.roles = []
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
		return user.name

	def test_search_vehicles_by_reg_vin_and_previous_plate(self):
		from vehicle_service.service_history import search_vehicles

		by_norm_reg = search_vehicles("  abc-1234 ")
		self.assertTrue(by_norm_reg)
		self.assertEqual(by_norm_reg[0]["name"], "ABC 1234")
		self.assertEqual(by_norm_reg[0]["match_source"], "Registration")

		by_prev_plate = search_vehicles("xyz9001")
		self.assertTrue(any(r["name"] == "ABC 1234" and r["match_source"] == "Previous Registration" for r in by_prev_plate))

		by_vin = search_vehicles("VIN1234567890ABCD")
		returned_names = {r["name"] for r in by_vin}
		self.assertEqual(returned_names, {"ABC 1234", "DEF 5678"})

	def test_search_vehicles_escapes_sql_wildcards_and_handles_no_match(self):
		from vehicle_service.service_history import search_vehicles

		self.assertEqual(search_vehicles("   "), [])
		self.assertEqual(search_vehicles("%_%"), [])
		self.assertEqual(search_vehicles("NONEXISTENT-PLATE-999"), [])

	def test_resolve_vehicle_cluster_merges_same_vin_records(self):
		from vehicle_service.service_history import resolve_vehicle_cluster

		primary, cluster_ids = resolve_vehicle_cluster("ABC 1234")
		self.assertEqual(primary.name, "ABC 1234")
		self.assertEqual(set(cluster_ids), {"ABC 1234", "DEF 5678"})

	def test_search_vehicles_historical_intake_invoice_ranking_and_limit(self):
		from vehicle_service.job_control import complete_service_order
		from vehicle_service.service_history import normalize_lookup_token, search_vehicles
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			create_sales_invoice_from_order,
		)

		self.assertEqual(normalize_lookup_token("  abc-1234  "), ("ABC-1234", "ABC1234"))
		self.assertEqual(normalize_lookup_token(None), ("", ""))

		# Historical Vehicle Intake snapshot (preserve snapshot fields against fetch_from)
		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = "KLM 4455"
		intake.customer = "Search Test Customer"
		intake.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Vehicle Intake",
			intake.name,
			{"license_plate": "OLD-INT 77", "vin": "HIST-VIN-INT-77"},
			update_modified=False,
		)

		by_intake = search_vehicles("oldint77")
		self.assertTrue(any(r["name"] == "KLM 4455" and r["match_source"] == "Historical Record" for r in by_intake))

		# Historical submitted Sales Invoice snapshot vs draft Sales Invoice (draft excluded)
		so = frappe.new_doc("Service Order")
		so.vehicle = "KLM 4455"
		so.customer = "Search Test Customer"
		so.insert(ignore_permissions=True)
		add_job(so.name, job_title="History Snapshot Check", estimated_hours=1.0)
		complete_service_order(so.name)
		inv_res = create_sales_invoice_from_order(so.name)
		inv = frappe.get_doc("Sales Invoice", inv_res["sales_invoice"])
		inv.vs_license_plate = "OLD-INV-88"
		inv.vs_chassis_no = "HIST-VIN-INV-88"
		inv.save(ignore_permissions=True)

		# Draft invoice must not appear as historical match
		self.assertEqual(search_vehicles("oldinv88"), [])

		inv.submit()
		by_inv = search_vehicles("oldinv88")
		self.assertTrue(any(r["name"] == "KLM 4455" and r["match_source"] == "Historical Record" for r in by_inv))
		by_inv_vin = search_vehicles("HISTVININV88")
		self.assertTrue(any(r["name"] == "KLM 4455" and r["match_source"] == "Historical Record" for r in by_inv_vin))

		# Ranking: exact/prefix registration beats substring VIN; limit respected
		self._ensure_vehicle("ABC 9999", "VIN-OTHER-ABC99")
		ranked = search_vehicles("ABC")
		self.assertIn(ranked[0]["name"], {"ABC 1234", "ABC 9999"})
		self.assertEqual(ranked[0]["match_source"], "Registration")
		# DEF 5678 only matches ABC inside VIN (substring, rank=3) so comes after prefix reg matches
		names_order = [r["name"] for r in ranked]
		self.assertGreater(names_order.index("DEF 5678"), names_order.index("ABC 1234"))
		self.assertEqual(len(search_vehicles("ABC", limit=1)), 1)

	def test_search_and_cluster_permissions_and_missing_vehicle(self):
		from vehicle_service.service_history import resolve_vehicle_cluster, search_vehicles

		# Missing vehicle raises DoesNotExistError
		with self.assertRaises(frappe.DoesNotExistError):
			resolve_vehicle_cluster("MISSING-VEH-999")

		# Guest is rejected
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			search_vehicles("ABC")
		with self.assertRaises(frappe.PermissionError):
			resolve_vehicle_cluster("ABC 1234")

		# Desk user without any HISTORY_VIEWER_ROLES is rejected
		frappe.set_user("Administrator")
		unauth_user = self._ensure_test_user("nohistory.test@example.com", ["Stock User"])
		frappe.set_user(unauth_user)
		with self.assertRaises(frappe.PermissionError):
			search_vehicles("ABC")
		with self.assertRaises(frappe.PermissionError):
			resolve_vehicle_cluster("ABC 1234")

		# Authorized viewers (Workshop Technician, Accounts Manager, System Manager) can search and resolve cluster
		frappe.set_user("Administrator")
		tech_user = self._ensure_test_user("histtech.test@example.com", ["Workshop Technician"])
		accounts_user = self._ensure_test_user("histacct.test@example.com", ["Accounts Manager"])
		sysmgr_user = self._ensure_test_user("histsys.test@example.com", ["System Manager"])
		other_veh = f"OTH-{frappe.generate_hash(length=5).upper()}"
		self._ensure_vehicle(other_veh, "VIN-OTHER-CUST-1", customer="Other Search Customer")

		for permitted_user in (tech_user, accounts_user, sysmgr_user):
			frappe.set_user(permitted_user)
			self.assertTrue(any(r["name"] == "ABC 1234" for r in search_vehicles("ABC 1234")))
			primary, cluster_ids = resolve_vehicle_cluster("ABC 1234")
			self.assertEqual(primary.name, "ABC 1234")
			self.assertEqual(set(cluster_ids), {"ABC 1234", "DEF 5678"})

		# User Permission restricting Customer hides non-permitted vehicles
		frappe.set_user("Administrator")
		up = frappe.new_doc("User Permission")
		up.user = tech_user
		up.allow = "Customer"
		up.for_value = "Other Search Customer"
		up.insert(ignore_permissions=True)

		frappe.set_user(tech_user)
		self.assertEqual(search_vehicles("ABC 1234"), [])
		self.assertTrue(any(r["name"] == other_veh for r in search_vehicles(other_veh)))
		with self.assertRaises(frappe.PermissionError):
			resolve_vehicle_cluster("ABC 1234")

	def test_search_vehicles_exact_match_with_many_substrings_and_multi_prev_plates(self):
		from vehicle_service.service_history import search_vehicles

		# Create >25 substring matches before the exact match so deterministic SQL ORDER BY is exercised.
		for idx in range(30):
			self._ensure_vehicle(f"SUB-{idx:02d}-AB12", f"VIN-SUB-{idx:02d}-0000")
		self._ensure_vehicle("AB 12", "VIN-EXACT-AB12", prev="OLD 1, XYZ 9001, PREV-88")

		exact_only = search_vehicles("AB12", limit=1)
		self.assertEqual(len(exact_only), 1)
		self.assertEqual(exact_only[0]["name"], "AB 12")
		self.assertEqual(exact_only[0]["match_source"], "Registration")

		for prev_token in ("old1", "xyz 9001", "prev-88"):
			prev_matches = search_vehicles(prev_token)
			self.assertTrue(
				any(r["name"] == "AB 12" and r["match_source"] == "Previous Registration" for r in prev_matches),
				f"Expected AB 12 via Previous Registration for token {prev_token!r}",
			)


class TestServiceHistoryPermissionsSetup(FrappeTestCase):
	def test_setup_job_controller_permissions_preserves_custom_perms(self):
		from vehicle_service.install import setup_job_controller_permissions

		frappe.set_user("Administrator")
		original_rows = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": "Service Vehicle"},
			fields=["role", "read", "write", "create", "delete", "email", "export", "print", "report", "share"],
		)
		try:
			# Case 1: Lone legacy Job Controller Custom DocPerm is cleaned up
			frappe.db.delete("Custom DocPerm", {"parent": "Service Vehicle"})
			cdp = frappe.new_doc("Custom DocPerm")
			cdp.parent = "Service Vehicle"
			cdp.parenttype = "DocType"
			cdp.parentfield = "permissions"
			cdp.role = "Job Controller"
			cdp.read = 1
			cdp.insert(ignore_permissions=True)

			setup_job_controller_permissions()
			self.assertEqual(
				frappe.get_all("Custom DocPerm", filters={"parent": "Service Vehicle"}, pluck="role"),
				[],
			)

			# Case 2: Legitimate customizations with additional roles are preserved
			for role in ("Job Controller", "Service Advisor"):
				c = frappe.new_doc("Custom DocPerm")
				c.parent = "Service Vehicle"
				c.parenttype = "DocType"
				c.parentfield = "permissions"
				c.role = role
				c.read = 1
				c.insert(ignore_permissions=True)

			setup_job_controller_permissions()
			remaining_roles = set(
				frappe.get_all("Custom DocPerm", filters={"parent": "Service Vehicle"}, pluck="role")
			)
			self.assertEqual(remaining_roles, {"Job Controller", "Service Advisor"})
		finally:
			frappe.db.delete("Custom DocPerm", {"parent": "Service Vehicle"})
			for row in original_rows:
				c = frappe.new_doc("Custom DocPerm")
				c.parent = "Service Vehicle"
				c.parenttype = "DocType"
				c.parentfield = "permissions"
				for k, v in row.items():
					setattr(c, k, v)
				c.insert(ignore_permissions=True)
			frappe.clear_cache(doctype="Service Vehicle")
			frappe.db.commit()


class TestServiceHistoryAggregationAndSecurity(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		from vehicle_service.job_control_setup import create_all_test_users

		self.all_test_users = create_all_test_users()
		settings = frappe.get_single("Vehicle Service Settings")
		self.company = settings.company or frappe.get_all("Company", pluck="name")[0]
		self.parts_warehouse = settings.parts_warehouse
		self.wip_warehouse = settings.wip_warehouse

		self.customer = self._ensure_customer("History Aggregation Customer")
		self.stock_item = self._ensure_stock_item("HIST-BRAKE-PAD", "History Test Brake Pad")
		self._ensure_labour_item("LABOUR")
		self.branch_a = self._ensure_branch("Hist Branch A")
		self.branch_b = self._ensure_branch("Hist Branch B")
		self.emp = self._ensure_employee("Hist", "Tech One")
		self.emp_2 = self._ensure_employee("Hist", "Tech Two")

		self.tech_user = self._ensure_test_user("hist.agg.tech@example.com", ["Workshop Technician"])
		self.branch_advisor_user = self._ensure_test_user("hist.agg.branch.advisor@example.com", ["Service Advisor"])
		self.manager_user = self._ensure_test_user("hist.agg.manager@example.com", ["Service Manager"])
		self.no_role_user = self._ensure_test_user("hist.agg.norole@example.com", ["Stock User"])

		frappe.db.delete("User Permission", {"user": self.branch_advisor_user})
		frappe.db.delete("User Permission", {"user": self.manager_user})
		frappe.cache.hdel("user_permissions", self.branch_advisor_user)
		frappe.cache.hdel("user_permissions", self.manager_user)
		frappe.defaults.set_user_default("branch", self.branch_a, user=self.branch_advisor_user)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _ensure_customer(self, name: str) -> str:
		if not frappe.db.exists("Customer", name):
			c = frappe.new_doc("Customer")
			c.customer_name = name
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)
		return name

	def _ensure_labour_item(self, item_code: str) -> str:
		if not frappe.db.exists("Item", item_code):
			it = frappe.new_doc("Item")
			it.item_code = item_code
			it.item_name = "Workshop Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)
		return item_code

	def _ensure_stock_item(self, item_code: str, item_name: str) -> str:
		if not frappe.db.exists("Item", item_code):
			it = frappe.new_doc("Item")
			it.item_code = item_code
			it.item_name = item_name
			it.item_group = "Products"
			it.is_stock_item = 1
			it.stock_uom = "Nos"
			it.valuation_rate = 40.0
			it.insert(ignore_permissions=True)
		return item_code

	def _ensure_branch(self, branch_name: str) -> str:
		if not frappe.db.exists("Branch", branch_name):
			b = frappe.new_doc("Branch")
			b.branch = branch_name
			b.insert(ignore_permissions=True)
		return branch_name

	def _ensure_employee(self, first_name: str, last_name: str):
		existing = frappe.db.get_value("Employee", {"first_name": first_name, "last_name": last_name}, "name")
		if existing:
			return frappe.get_doc("Employee", existing)
		emp = frappe.new_doc("Employee")
		emp.first_name = first_name
		emp.last_name = last_name
		emp.company = self.company
		emp.gender = "Male"
		emp.date_of_birth = "1991-03-10"
		emp.date_of_joining = "2020-02-01"
		emp.insert(ignore_permissions=True)
		return emp

	def _ensure_test_user(self, email: str, roles: list[str]) -> str:
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.new_doc("User")
			user.email = email
			user.first_name = email.split("@")[0]
			user.last_name = "Tester"
			user.enabled = 1
			user.user_type = "System User"
		user.roles = []
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)
		return user.name

	def _create_vehicle(self, reg_no: str, vin: str, mileage: int = 45000, **kwargs):
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = reg_no
		v.vin = vin
		v.make = "Toyota"
		v.model = "Hilux"
		v.year = 2022
		v.customer = self.customer
		v.current_mileage = mileage
		for k, val in kwargs.items():
			setattr(v, k, val)
		v.insert(ignore_permissions=True)
		return v

	def _create_order(
		self,
		vehicle: str,
		*,
		status: str = "In Progress",
		order_type: str = "Customer",
		branch: str | None = None,
		service_advisor: str | None = None,
		checked_in_on: str | None = None,
		order_date: str | None = None,
		odometer_in: int = 45000,
		odometer_out: int = 0,
		delivery_notes: str | None = None,
	):
		so = frappe.new_doc("Service Order")
		so.vehicle = vehicle
		so.customer = self.customer
		so.company = self.company
		so.branch = branch or self.branch_a
		so.order_type = order_type
		so.status = status
		so.service_advisor = service_advisor or "Administrator"
		so.odometer_in = odometer_in
		if odometer_out:
			so.odometer_out = odometer_out
		if checked_in_on:
			so.checked_in_on = checked_in_on
		if order_date:
			so.order_date = order_date
		if delivery_notes:
			so.delivery_notes = delivery_notes
		so.flags.ignore_open_order_validation = True
		so.insert(ignore_permissions=True)
		return so

	def _issue_and_use_part(self, order, item_code: str, qty: float = 1.0, rate: float = 65.0):
		import json
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
		from vehicle_service.vehicle_service.doctype.service_order.service_order import issue_parts_to_workshop

		make_stock_entry(
			item_code=item_code,
			to_warehouse=self.parts_warehouse,
			qty=qty + 2.0,
			rate=40.0,
			purpose="Material Receipt",
			company=self.company,
		)
		order.reload()
		part_row = order.append(
			"parts",
			{
				"item_code": item_code,
				"qty_required": qty,
				"rate": rate,
				"approval_status": "Approved",
			},
		)
		order.flags.ignore_open_order_validation = True
		order.save(ignore_permissions=True)
		issue_parts_to_workshop(
			order_name=order.name,
			items_json=json.dumps([{"part_row": part_row.name, "qty": qty}]),
		)
		order.reload()
		p = next(row for row in order.parts if row.name == part_row.name)
		p.qty_used = qty
		order.flags.ignore_open_order_validation = True
		order.save(ignore_permissions=True)
		return p

	def _pay_invoice(self, si):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
		from frappe.utils import nowdate

		pe = get_payment_entry("Sales Invoice", si.name)
		cash_acc = frappe.db.get_value("Company", self.company, "default_cash_account")
		if cash_acc:
			pe.paid_to = cash_acc
		pe.reference_no = f"PAY-{si.name}"
		pe.reference_date = nowdate()
		pe.insert(ignore_permissions=True)
		pe.submit()
		return pe

	def test_overview_stats_excludes_draft_cancelled_and_deducts_credit_notes(self):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc
		from frappe.utils import nowdate
		from vehicle_service.job_control import complete_service_order
		from vehicle_service.service_history import get_vehicle_service_history
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			create_sales_invoice_from_order,
			deliver_vehicle,
		)

		self.vehicle_reg = f"STAT-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(self.vehicle_reg, f"VIN-{self.vehicle_reg}", mileage=45000)

		# 1. Delivered + Paid order with Labour, Stock Part, and QC
		paid_order = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			order_type="Warranty",
			branch=self.branch_a,
			checked_in_on="2026-10-05 09:00:00",
			order_date="2026-10-05",
			odometer_in=45000,
		)
		add_job(paid_order.name, job_title="Brake Service", technician=self.emp.name, estimated_hours=2.0)
		frappe.db.set_value("Service Job", {"service_order": paid_order.name}, "rate", 100.0)
		self._issue_and_use_part(paid_order, self.stock_item, qty=1.0, rate=65.0)
		complete_service_order(paid_order.name)

		qc = frappe.new_doc("Service QC")
		qc.service_order = paid_order.name
		qc.vehicle = self.vehicle_reg
		qc.inspector = "Administrator"
		qc.inspected_on = "2026-10-05 14:00:00"
		qc.result = "Pass"
		qc.road_test_done = 1
		qc.road_test_km = 4.5
		qc.findings = "Brakes tested cleanly."
		qc.append("checklist", {"check_item": "Brake fluid level", "passed": 1, "remarks": "Full"})
		qc.insert(ignore_permissions=True)

		inv_res_1 = create_sales_invoice_from_order(paid_order.name)
		self.si_paid = frappe.get_doc("Sales Invoice", inv_res_1["sales_invoice"])
		self.si_paid.submit()
		self._pay_invoice(self.si_paid)
		deliver_vehicle(paid_order.name, odometer_out=45120, collected_by="Owner", delivery_notes="All good.")

		# 2. Delivered order whose Sales Invoice was reversed by a Credit Note (vs_service_order cleared)
		self.credited_order = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			order_type="Customer",
			branch=self.branch_b,
			checked_in_on="2026-10-02 09:00:00",
			order_date="2026-10-02",
			odometer_in=44800,
		)
		add_job(self.credited_order.name, job_title="Diagnostic Scan", technician=self.emp.name, estimated_hours=1.0)
		complete_service_order(self.credited_order.name)
		inv_res_2 = create_sales_invoice_from_order(self.credited_order.name)
		si_2 = frappe.get_doc("Sales Invoice", inv_res_2["sales_invoice"])
		si_2.submit()

		cn_2 = make_return_doc("Sales Invoice", si_2.name)
		cn_2.posting_date = nowdate()
		cn_2.vs_service_order = None  # Verify fallback capture via return_against
		cn_2.insert(ignore_permissions=True)
		cn_2.submit()

		frappe.db.set_value(
			"Service Order",
			self.credited_order.name,
			{"status": "Delivered", "delivered_on": "2026-10-02 16:00:00", "odometer_out": 44810},
		)

		# 3. Active In Progress order (Not Invoiced)
		in_prog = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			order_type="Customer",
			branch=self.branch_a,
			checked_in_on="2026-10-10 08:30:00",
			order_date="2026-10-10",
			odometer_in=45100,
		)
		add_job(in_prog.name, job_title="Wheel Alignment", technician=self.emp.name, estimated_hours=1.5)

		# 4. Cancelled order (excluded from overview stats and default timeline)
		cancelled = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			branch=self.branch_a,
			checked_in_on="2026-09-20 10:00:00",
			order_date="2026-09-20",
			odometer_in=44500,
		)
		add_job(cancelled.name, job_title="Cancelled Job", estimated_hours=2.0)
		frappe.db.set_value("Service Order", cancelled.name, "status", "Cancelled")

		# 5. Draft order (always excluded)
		self._create_order(
			self.vehicle_reg,
			status="Draft",
			branch=self.branch_a,
			checked_in_on="2026-10-11 10:00:00",
			order_date="2026-10-11",
			odometer_in=45110,
		)

		data = get_vehicle_service_history(self.vehicle_reg)
		stats = data["overview_stats"]
		self.assertEqual(stats["total_service_orders"], 3)
		self.assertEqual(stats["total_visits"], 3)
		self.assertEqual(stats["outstanding_service_orders"], 1)
		self.assertEqual(stats["completed_orders_count"], 2)
		self.assertEqual(stats["total_completed_repairs"], 2)
		self.assertEqual(stats["last_recorded_mileage"], 45120)
		self.assertAlmostEqual(stats["total_historical_service_value"], float(self.si_paid.grand_total), places=2)

		credited_visit = next(v for v in data["timeline"] if v["service_order"] == self.credited_order.name)
		self.assertEqual(credited_visit["financials"]["payment_status"], "Credited")
		self.assertAlmostEqual(credited_visit["financials"]["total_invoice_value"], 0.0, places=2)
		self.assertIn(cn_2.name, credited_visit["financials"]["credit_notes"])

		paid_visit = next(v for v in data["timeline"] if v["service_order"] == paid_order.name)
		self.assertEqual(paid_visit["financials"]["payment_status"], "Paid")
		self.assertGreater(paid_visit["financials"]["labour_charges"], 0)
		self.assertGreater(paid_visit["financials"]["parts_charges"], 0)
		self.assertEqual(len(paid_visit["financials"]["payments"]), 1)

		# Standalone Checked In Vehicle Intake increases total_visits without increasing total_service_orders
		standalone_intake = frappe.new_doc("Vehicle Intake")
		standalone_intake.vehicle = self.vehicle_reg
		standalone_intake.customer = self.customer
		standalone_intake.company = self.company
		standalone_intake.status = "Checked In"
		standalone_intake.odometer_in = 45200
		standalone_intake.checked_in_on = "2026-10-12 08:00:00"
		standalone_intake.insert(ignore_permissions=True)

		with_intake = get_vehicle_service_history(self.vehicle_reg)
		self.assertEqual(with_intake["overview_stats"]["total_service_orders"], 3)
		self.assertEqual(with_intake["overview_stats"]["total_visits"], 4)
		self.assertEqual(with_intake["overview_stats"]["last_recorded_mileage"], 45200)
		self.assertTrue(any(v["visit_type"] == "Vehicle Intake" for v in with_intake["timeline"]))

	def test_recommendations_completion_requires_linked_completed_job(self):
		from frappe.utils import add_days, nowdate
		from vehicle_service.service_history import get_vehicle_service_history

		self.vehicle_reg = f"REC-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(self.vehicle_reg, f"VIN-{self.vehicle_reg}", mileage=50000)
		frappe.db.set_value(
			"Service Vehicle",
			self.vehicle_reg,
			{"next_service_date": add_days(nowdate(), -5), "next_service_mileage": 50500},
			update_modified=False,
		)

		order_1 = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			checked_in_on="2026-09-10 09:00:00",
			order_date="2026-09-10",
			delivery_notes="Monitor rear shock absorbers.",
		)
		rec_res = add_job(order_1.name, job_title="Replace Rear Shock Absorbers", category="Recommended")
		self.rec_job = frappe.get_doc("Service Job", rec_res["job"])
		self.rec_job.status = "Declined"
		self.rec_job.save(ignore_permissions=True)

		# Standalone declined recommended part (not linked to rec_job)
		order_1.reload()
		rec_part = order_1.append(
			"parts",
			{
				"item_code": self.stock_item,
				"qty_required": 2.0,
				"rate": 55.0,
				"category": "Recommended",
				"approval_status": "Declined",
			},
		)
		order_1.status = "Delivered"
		order_1.flags.ignore_open_order_validation = True
		order_1.flags.ignore_job_lock = True
		order_1.save(ignore_permissions=True)

		qc_1 = frappe.new_doc("Service QC")
		qc_1.service_order = order_1.name
		qc_1.vehicle = self.vehicle_reg
		qc_1.inspector = "Administrator"
		qc_1.inspected_on = "2026-09-10 15:00:00"
		qc_1.result = "Pass"
		qc_1.findings = "Minor oil seep at timing cover."
		qc_1.insert(ignore_permissions=True)

		# Cancelled order with completed follow-up must NEVER mark rec_job completed
		cancelled_order = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			checked_in_on="2026-09-25 09:00:00",
			order_date="2026-09-25",
		)
		cancelled_follow = add_job(
			cancelled_order.name,
			job_title="Cancelled Follow-up",
			follows_up_job=self.rec_job.name,
		)
		frappe.db.set_value("Service Job", cancelled_follow["job"], "status", "Completed")
		frappe.db.set_value("Service Order", cancelled_order.name, "status", "Cancelled")

		self.order_2 = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			checked_in_on="2026-10-15 09:00:00",
			order_date="2026-10-15",
		)
		follow_res = add_job(
			self.order_2.name,
			job_title="Replace Rear Shock Absorbers (Follow-Up)",
			follows_up_job=self.rec_job.name,
		)
		self.follow_job = frappe.get_doc("Service Job", follow_res["job"])
		frappe.db.set_value("Service Job", self.follow_job.name, "status", "Pending Approval")

		before = get_vehicle_service_history(self.vehicle_reg)
		self.assertTrue(any(r["source_id"] == self.rec_job.name for r in before["recommendations"]["outstanding"]))
		self.assertFalse(any(r["source_id"] == self.rec_job.name for r in before["recommendations"]["completed"]))
		self.assertTrue(any(r["source_id"] == rec_part.name for r in before["recommendations"]["outstanding"]))

		# Uncompleted active follow-up job ("In Progress") still leaves recommendation Outstanding
		frappe.db.set_value("Service Job", self.follow_job.name, "status", "In Progress")
		in_progress_check = get_vehicle_service_history(self.vehicle_reg)
		self.assertTrue(
			any(r["source_id"] == self.rec_job.name for r in in_progress_check["recommendations"]["outstanding"])
		)
		self.assertFalse(
			any(r["source_id"] == self.rec_job.name for r in in_progress_check["recommendations"]["completed"])
		)

		# Completing linked follow-up job moves recommendation to Completed with attribution
		frappe.db.set_value("Service Job", self.follow_job.name, "status", "Completed")
		after = get_vehicle_service_history(self.vehicle_reg)
		self.assertFalse(any(r["source_id"] == self.rec_job.name for r in after["recommendations"]["outstanding"]))
		comp = next(r for r in after["recommendations"]["completed"] if r["source_id"] == self.rec_job.name)
		self.assertEqual(comp["linked_completion_job"], self.follow_job.name)
		self.assertEqual(comp["linked_completion_order"], self.order_2.name)

		# Advisory notes & scheduled maintenance evaluated accurately
		advisory_texts = [a["note"] for a in after["recommendations"]["advisory_notes"]]
		self.assertIn("Monitor rear shock absorbers.", advisory_texts)
		self.assertIn("Minor oil seep at timing cover.", advisory_texts)
		self.assertTrue(any(s["status"] == "Overdue" for s in after["recommendations"]["scheduled"]))
		self.assertTrue(any(s["status"] == "Due" for s in after["recommendations"]["scheduled"]))
		self.assertTrue(any(r["source_id"] == rec_part.name for r in after["recommendations"]["outstanding"]))

		# Part recommendation becomes Completed only when qty_used > 0 on a completed order
		frappe.db.set_value("Service Order Part", rec_part.name, "qty_used", 2.0)
		part_done = get_vehicle_service_history(self.vehicle_reg)
		self.assertFalse(any(r["source_id"] == rec_part.name for r in part_done["recommendations"]["outstanding"]))
		self.assertTrue(any(r["source_id"] == rec_part.name for r in part_done["recommendations"]["completed"]))

	def test_timeline_ordering_details_and_filters(self):
		from vehicle_service.job_control import complete_service_order
		from vehicle_service.service_history import get_vehicle_service_history
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			create_sales_invoice_from_order,
			deliver_vehicle,
		)

		shared_vin = f"VIN-CLST-{frappe.generate_hash(length=6).upper()}"
		self.vehicle_reg = f"TL1-{frappe.generate_hash(length=5).upper()}"
		other_reg = f"TL2-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(self.vehicle_reg, shared_vin, mileage=60000)
		self._create_vehicle(other_reg, shared_vin, mileage=62000)

		# Order 1 on first plate: Warranty, Paid, emp, Service Advisor
		o1 = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			order_type="Warranty",
			branch=self.branch_a,
			service_advisor=self.branch_advisor_user,
			checked_in_on="2026-09-01 09:00:00",
			order_date="2026-09-01",
			odometer_in=60000,
		)
		frappe.db.set_value(
			"Service Order",
			o1.name,
			{"existing_damage": "Scratch on left fender", "vehicle_contents": "Spare wheel & jack"},
		)
		if o1.vehicle_intake:
			intake_doc = frappe.get_doc("Vehicle Intake", o1.vehicle_intake)
			intake_doc.existing_damage = "Scratch on left fender"
			intake_doc.vehicle_contents = "Spare wheel & jack"
			intake_doc.append(
				"intake_photos",
				{"photo": "/files/test-intake-photo.jpg", "description": "Left fender scratch"},
			)
			intake_doc.save(ignore_permissions=True)

		add_job(o1.name, job_title="Warranty Alternator Replace", technician=self.emp.name, estimated_hours=2.0)
		self._issue_and_use_part(o1, self.stock_item, qty=1.0, rate=75.0)
		complete_service_order(o1.name)

		qc1 = frappe.new_doc("Service QC")
		qc1.service_order = o1.name
		qc1.vehicle = self.vehicle_reg
		qc1.inspector = "Administrator"
		qc1.inspected_on = "2026-09-01 16:00:00"
		qc1.result = "Pass"
		qc1.road_test_done = 1
		qc1.road_test_km = 6.0
		qc1.findings = "Charging voltage normal."
		qc1.append("checklist", {"check_item": "Alternator output", "passed": 1, "remarks": "14.2V"})
		qc1.insert(ignore_permissions=True)

		inv1_res = create_sales_invoice_from_order(o1.name)
		si1 = frappe.get_doc("Sales Invoice", inv1_res["sales_invoice"])
		si1.submit()
		self._pay_invoice(si1)
		deliver_vehicle(o1.name, odometer_out=60010, collected_by="Driver One")

		# Order 2 on second plate sharing VIN: Customer, Not Invoiced, emp_2
		o2 = self._create_order(
			other_reg,
			status="In Progress",
			order_type="Customer",
			branch=self.branch_a,
			service_advisor="Administrator",
			checked_in_on="2026-10-15 10:00:00",
			order_date="2026-10-15",
			odometer_in=62000,
		)
		add_job(o2.name, job_title="Customer Oil Change", technician=self.emp_2.name, estimated_hours=1.0)

		desc_data = get_vehicle_service_history(self.vehicle_reg)
		self.assertEqual(set(desc_data["vehicle_ids"]), {self.vehicle_reg, other_reg})
		self.assertEqual(len(desc_data["timeline"]), 2)
		dates_desc = [v["visit_date"] for v in desc_data["timeline"]]
		self.assertEqual(dates_desc, sorted(dates_desc, reverse=True))

		paid_visit = next(v for v in desc_data["timeline"] if v["service_order"] == o1.name)
		self.assertIn("jobs", paid_visit)
		self.assertIn("parts", paid_visit)
		self.assertIn("qc", paid_visit)
		self.assertEqual(paid_visit["existing_damage"], "Scratch on left fender")
		self.assertEqual(paid_visit["vehicle_contents"], "Spare wheel & jack")
		self.assertEqual(len(paid_visit["intake_photos"]), 1)
		self.assertEqual(paid_visit["qc"]["result"], "Pass")
		self.assertEqual(len(paid_visit["qc"]["checklist"]), 1)
		self.assertEqual(paid_visit["parts"][0]["qty_used"], 1.0)

		asc_data = get_vehicle_service_history(self.vehicle_reg, filters={"sort_order": "asc"})
		self.assertEqual([v["visit_date"] for v in asc_data["timeline"]], list(reversed(dates_desc)))

		filtered = get_vehicle_service_history(
			self.vehicle_reg,
			filters={"order_type": "Warranty", "technician": self.emp.name, "invoice_status": "Paid"},
		)
		self.assertEqual(len(filtered["timeline"]), 1)
		self.assertEqual(filtered["timeline"][0]["service_order"], o1.name)
		self.assertTrue(all(v["order_type"] == "Warranty" for v in filtered["timeline"]))

		date_filtered = get_vehicle_service_history(
			self.vehicle_reg,
			filters={"from_date": "2026-10-01", "to_date": "2026-10-31", "service_advisor": "Administrator"},
		)
		self.assertEqual([v["service_order"] for v in date_filtered["timeline"]], [o2.name])

	def test_role_financial_redaction_and_branch_isolation(self):
		from vehicle_service.job_control import complete_service_order
		from vehicle_service.service_history import get_vehicle_service_history
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			create_sales_invoice_from_order,
			deliver_vehicle,
		)

		self.vehicle_reg = f"SEC-{frappe.generate_hash(length=5).upper()}"
		self._create_vehicle(self.vehicle_reg, f"VIN-{self.vehicle_reg}", mileage=30000)

		# Branch A order (Paid, with Sublet cost fields + Part rate)
		order_a = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			branch=self.branch_a,
			checked_in_on="2026-10-01 09:00:00",
			order_date="2026-10-01",
			odometer_in=30000,
		)
		job_a = add_job(order_a.name, job_title="Branch A Service", technician=self.emp.name, estimated_hours=1.5)
		frappe.db.set_value(
			"Service Job",
			job_a["job"],
			{"rate": 120.0, "amount": 180.0, "supplier_cost": 80.0, "supplier_invoice_ref": "SUP-INV-01"},
		)
		self._issue_and_use_part(order_a, self.stock_item, qty=1.0, rate=95.0)
		complete_service_order(order_a.name)
		inv_a = frappe.get_doc("Sales Invoice", create_sales_invoice_from_order(order_a.name)["sales_invoice"])
		inv_a.submit()
		self._pay_invoice(inv_a)
		deliver_vehicle(order_a.name, odometer_out=30050, collected_by="Branch A Driver")

		# Branch B order
		order_b = self._create_order(
			self.vehicle_reg,
			status="In Progress",
			branch=self.branch_b,
			checked_in_on="2026-10-05 10:00:00",
			order_date="2026-10-05",
			odometer_in=30060,
		)
		add_job(order_b.name, job_title="Branch B Inspection", technician=self.emp_2.name, estimated_hours=1.0)

		# 1. Workshop Technician: financial redaction enforced
		frappe.set_user(self.tech_user)
		tech_data = get_vehicle_service_history(self.vehicle_reg, filters={"invoice_status": "Paid"})
		self.assertFalse(tech_data["permissions"]["can_view_financials"])
		self.assertIsNone(tech_data["overview_stats"]["total_historical_service_value"])
		self.assertEqual(tech_data["filter_options"]["invoice_statuses"], [])
		self.assertEqual(len(tech_data["timeline"]), 2)
		for v in tech_data["timeline"]:
			self.assertIsNone(v["financials"])
			for j in v["jobs"]:
				self.assertNotIn("rate", j)
				self.assertNotIn("amount", j)
				self.assertNotIn("supplier_cost", j)
				self.assertNotIn("supplier_invoice_ref", j)
			for p in v["parts"]:
				self.assertNotIn("rate", p)
				self.assertNotIn("amount", p)

		# 2. Branch-scoped Service Advisor: sees only Branch A
		frappe.set_user(self.branch_advisor_user)
		branch_data = get_vehicle_service_history(self.vehicle_reg)
		self.assertTrue(branch_data["permissions"]["can_view_financials"])
		self.assertFalse(branch_data["permissions"]["is_cross_branch"])
		self.assertEqual(branch_data["permissions"]["allowed_branches"], [self.branch_a])
		self.assertEqual(len(branch_data["timeline"]), 1)
		self.assertTrue(all(v["branch"] == self.branch_a for v in branch_data["timeline"]))
		self.assertEqual(branch_data["overview_stats"]["total_service_orders"], 1)

		# 3. Cross-branch Service Manager sees all branches unless restricted by User Permission
		frappe.set_user(self.manager_user)
		mgr_data = get_vehicle_service_history(self.vehicle_reg)
		self.assertTrue(mgr_data["permissions"]["is_cross_branch"])
		self.assertIsNone(mgr_data["permissions"]["allowed_branches"])
		self.assertEqual({v["branch"] for v in mgr_data["timeline"]}, {self.branch_a, self.branch_b})

		frappe.set_user("Administrator")
		up = frappe.new_doc("User Permission")
		up.user = self.manager_user
		up.allow = "Branch"
		up.for_value = self.branch_b
		up.insert(ignore_permissions=True)

		frappe.set_user(self.manager_user)
		restricted_mgr_data = get_vehicle_service_history(self.vehicle_reg)
		self.assertEqual(restricted_mgr_data["permissions"]["allowed_branches"], [self.branch_b])
		self.assertEqual([v["branch"] for v in restricted_mgr_data["timeline"]], [self.branch_b])

		# 4. Unauthorized Desk user without any HISTORY_VIEWER_ROLES is rejected
		frappe.set_user(self.no_role_user)
		with self.assertRaises(frappe.PermissionError):
			get_vehicle_service_history(self.vehicle_reg)


class TestServiceHistoryPrintExport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
		from vehicle_service.job_control import complete_service_order
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			create_sales_invoice_from_order,
			issue_parts_to_workshop,
		)

		settings = frappe.get_single("Vehicle Service Settings")
		self.company = settings.company or frappe.get_all("Company", pluck="name")[0]
		self.parts_warehouse = settings.parts_warehouse
		self.wip_warehouse = settings.wip_warehouse

		self.customer = "Print Export Customer"
		if not frappe.db.exists("Customer", self.customer):
			c = frappe.new_doc("Customer")
			c.customer_name = self.customer
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		if not frappe.db.exists("Item", "LABOUR"):
			it = frappe.new_doc("Item")
			it.item_code = "LABOUR"
			it.item_name = "Workshop Labour"
			it.item_group = "Services"
			it.is_stock_item = 0
			it.insert(ignore_permissions=True)

		self.stock_item = "HIST-PRINT-FILTER"
		if not frappe.db.exists("Item", self.stock_item):
			it = frappe.new_doc("Item")
			it.item_code = self.stock_item
			it.item_name = "Print Test Oil Filter"
			it.item_group = "Products"
			it.is_stock_item = 1
			it.stock_uom = "Nos"
			it.valuation_rate = 30.0
			it.insert(ignore_permissions=True)

		self.declined_item = "HIST-PRINT-WIPER"
		if not frappe.db.exists("Item", self.declined_item):
			it = frappe.new_doc("Item")
			it.item_code = self.declined_item
			it.item_name = "Declined Wiper Blade"
			it.item_group = "Products"
			it.is_stock_item = 1
			it.stock_uom = "Nos"
			it.valuation_rate = 20.0
			it.insert(ignore_permissions=True)

		self.branch = "Print Export Branch"
		if not frappe.db.exists("Branch", self.branch):
			b = frappe.new_doc("Branch")
			b.branch = self.branch
			b.insert(ignore_permissions=True)

		emp_name = frappe.db.get_value(
			"Employee",
			{"first_name": "PrintTech", "last_name": "Specialist"},
			"name",
		)
		if emp_name:
			self.emp = frappe.get_doc("Employee", emp_name)
		else:
			self.emp = frappe.new_doc("Employee")
			self.emp.first_name = "PrintTech"
			self.emp.last_name = "Specialist"
			self.emp.company = self.company
			self.emp.gender = "Male"
			self.emp.date_of_birth = "1992-05-14"
			self.emp.date_of_joining = "2021-01-10"
			self.emp.insert(ignore_permissions=True)
		self.tech_name = self.emp.employee_name or "PrintTech Specialist"

		self.tech_user = "hist.print.tech@example.com"
		self._ensure_user(self.tech_user, ["Workshop Technician"])
		self.no_role_user = "hist.print.norole@example.com"
		self._ensure_user(self.no_role_user, ["Stock User"])
		frappe.db.delete("User Permission", {"user": self.tech_user})
		frappe.defaults.clear_default("branch", parent=self.tech_user)
		frappe.cache.hdel("user_permissions", self.tech_user)

		self.vehicle_reg = f"PRT-{frappe.generate_hash(length=5).upper()}"
		v = frappe.new_doc("Service Vehicle")
		v.registration_no = self.vehicle_reg
		v.vin = f"VIN-{self.vehicle_reg}"
		v.make = "Toyota"
		v.model = "Fortuner"
		v.year = 2023
		v.customer = self.customer
		v.current_mileage = 25000
		v.insert(ignore_permissions=True)

		order = frappe.new_doc("Service Order")
		order.vehicle = self.vehicle_reg
		order.customer = self.customer
		order.company = self.company
		order.branch = self.branch
		order.order_type = "Customer"
		order.status = "In Progress"
		order.service_advisor = "Administrator"
		order.odometer_in = 25000
		order.checked_in_on = "2026-10-15 09:00:00"
		order.order_date = "2026-10-15"
		order.customer_complaint = "Engine rattle at idle"
		order.hold_reason = "INTERNAL_HOLD_SECRET"
		order.dispute_notes = "INTERNAL_DISPUTE_SECRET"
		order.pause_reason = "Technical Consultation"
		order.delivery_notes = "Check coolant level at next visit."
		order.flags.ignore_open_order_validation = True
		order.insert(ignore_permissions=True)
		self.order = order

		if order.vehicle_intake:
			frappe.db.set_value(
				"Vehicle Intake",
				order.vehicle_intake,
				"reception_notes",
				"INTERNAL_RECEPTION_SECRET",
				update_modified=False,
			)

		completed_job = add_job(
			order.name,
			job_title="Completed Oil Service",
			description="Full synthetic oil and filter replacement",
			technician=self.emp.name,
			estimated_hours=1.5,
			rate=100.0,
			reason="INTERNAL_ADD_REASON",
		)
		frappe.db.set_value(
			"Service Job",
			completed_job["job"],
			{
				"qc_fail_reason": "INTERNAL_QC_FAIL_REASON",
				"pause_reason": "INTERNAL_PAUSE_SECRET",
			},
			update_modified=False,
		)

		declined_job = add_job(
			order.name,
			job_title="Declined Extra Job",
			technician=self.emp.name,
			estimated_hours=1.0,
			category="Recommended",
			reason="INTERNAL_DECLINED_REASON",
		)
		frappe.db.set_value("Service Job", declined_job["job"], "status", "Declined", update_modified=False)
		frappe.db.set_value(
			"Service Order Job",
			{"parent": order.name, "service_job": declined_job["job"]},
			"status",
			"Declined",
			update_modified=False,
		)

		import json

		make_stock_entry(
			item_code=self.stock_item,
			to_warehouse=self.parts_warehouse,
			qty=3.0,
			rate=30.0,
			purpose="Material Receipt",
			company=self.company,
		)
		order.reload()
		approved_part = order.append(
			"parts",
			{
				"item_code": self.stock_item,
				"qty_required": 1.0,
				"rate": 55.0,
				"approval_status": "Approved",
			},
		)
		declined_part = order.append(
			"parts",
			{
				"item_code": self.declined_item,
				"qty_required": 1.0,
				"rate": 40.0,
				"approval_status": "Declined",
				"part_status": "Declined",
				"reason_for_adding": "INTERNAL_PART_REASON",
			},
		)
		order.flags.ignore_open_order_validation = True
		order.save(ignore_permissions=True)
		issue_parts_to_workshop(
			order_name=order.name,
			items_json=json.dumps([{"part_row": approved_part.name, "qty": 1.0}]),
		)
		order.reload()
		for row in order.parts:
			if row.name == approved_part.name:
				row.qty_used = 1.0
			elif row.name == declined_part.name:
				row.approval_status = "Declined"
				row.part_status = "Declined"
		order.flags.ignore_open_order_validation = True
		order.save(ignore_permissions=True)

		complete_service_order(order.name)
		frappe.db.set_value(
			"Service Order",
			order.name,
			"pause_reason",
			"Technical Consultation",
			update_modified=False,
		)

		qc_fail = frappe.new_doc("Service QC")
		qc_fail.service_order = order.name
		qc_fail.vehicle = self.vehicle_reg
		qc_fail.inspector = "Administrator"
		qc_fail.inspected_on = "2026-10-15 13:00:00"
		qc_fail.result = "Fail"
		qc_fail.fail_reason = "INTERNAL_QC_REWORK_SECRET"
		qc_fail.findings = "Initial oil filter gasket weeping."
		qc_fail.append("failed_jobs", {"job": completed_job["job"]})
		qc_fail.insert(ignore_permissions=True)

		qc_pass = frappe.new_doc("Service QC")
		qc_pass.service_order = order.name
		qc_pass.vehicle = self.vehicle_reg
		qc_pass.inspector = "Administrator"
		qc_pass.inspected_on = "2026-10-15 15:00:00"
		qc_pass.result = "Pass"
		qc_pass.road_test_done = 1
		qc_pass.road_test_km = 5.0
		qc_pass.findings = "Road test completed cleanly."
		qc_pass.append("checklist", {"check_item": "Oil pressure & leak check", "passed": 1, "remarks": "Dry"})
		qc_pass.insert(ignore_permissions=True)

		inv_res = create_sales_invoice_from_order(order.name)
		si = frappe.get_doc("Sales Invoice", inv_res["sales_invoice"])
		si.submit()
		self.invoice_name = si.name

		# Cancelled order to ensure customer mode strips cancelled visits even if requested via filter
		cancelled_order = frappe.new_doc("Service Order")
		cancelled_order.vehicle = self.vehicle_reg
		cancelled_order.customer = self.customer
		cancelled_order.company = self.company
		cancelled_order.branch = self.branch
		cancelled_order.order_type = "Customer"
		cancelled_order.status = "In Progress"
		cancelled_order.odometer_in = 24900
		cancelled_order.checked_in_on = "2026-10-01 08:00:00"
		cancelled_order.order_date = "2026-10-01"
		cancelled_order.flags.ignore_open_order_validation = True
		cancelled_order.insert(ignore_permissions=True)
		add_job(cancelled_order.name, job_title="CANCELLED_ORDER_JOB", technician=self.emp.name, estimated_hours=1.0)
		frappe.db.set_value("Service Order", cancelled_order.name, "status", "Cancelled", update_modified=False)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _ensure_user(self, email: str, roles: list[str]):
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.new_doc("User")
			user.email = email
			user.first_name = email.split("@")[0]
			user.last_name = "Tester"
			user.enabled = 1
			user.user_type = "System User"
		user.roles = []
		for role in roles:
			user.append("roles", {"role": role})
		user.save(ignore_permissions=True)

	def test_print_internal_vs_customer_sanitization(self):
		from vehicle_service.service_history import render_vehicle_service_history_print

		internal_html = render_vehicle_service_history_print(
			self.vehicle_reg,
			mode="internal",
			include_financials=1,
			filters={"include_cancelled": 1},
		)
		self.assertIn(self.vehicle_reg, internal_html)
		self.assertIn("INTERNAL_HOLD_SECRET", internal_html)
		self.assertIn("INTERNAL_RECEPTION_SECRET", internal_html)
		self.assertIn("INTERNAL_DISPUTE_SECRET", internal_html)
		self.assertIn("INTERNAL_PAUSE_SECRET", internal_html)
		self.assertIn("Technical Consultation", internal_html)
		self.assertIn("INTERNAL_QC_FAIL_REASON", internal_html)
		self.assertIn("INTERNAL_QC_REWORK_SECRET", internal_html)
		self.assertIn("INTERNAL_ADD_REASON", internal_html)
		self.assertIn("INTERNAL_DECLINED_REASON", internal_html)
		self.assertIn("INTERNAL_PART_REASON", internal_html)
		self.assertIn("Declined Extra Job", internal_html)
		self.assertIn("Declined Wiper Blade", internal_html)
		self.assertIn("CANCELLED_ORDER_JOB", internal_html)
		self.assertIn(self.tech_name, internal_html)
		self.assertIn(self.invoice_name, internal_html)
		self.assertIn("/assets/vehicle_service/images/vehicle-service-logo.svg", internal_html)

		customer_html = render_vehicle_service_history_print(
			self.vehicle_reg,
			mode="customer",
			include_financials=1,
			filters={"include_cancelled": 1},
		)
		self.assertIn(self.vehicle_reg, customer_html)
		self.assertIn("Completed Oil Service", customer_html)
		self.assertIn("Print Test Oil Filter", customer_html)
		self.assertIn("Road test completed cleanly.", customer_html)
		self.assertNotIn("INTERNAL_HOLD_SECRET", customer_html)
		self.assertNotIn("INTERNAL_RECEPTION_SECRET", customer_html)
		self.assertNotIn("INTERNAL_DISPUTE_SECRET", customer_html)
		self.assertNotIn("INTERNAL_PAUSE_SECRET", customer_html)
		self.assertNotIn("Technical Consultation", customer_html)
		self.assertNotIn("INTERNAL_QC_FAIL_REASON", customer_html)
		self.assertNotIn("INTERNAL_QC_REWORK_SECRET", customer_html)
		self.assertNotIn("INTERNAL_ADD_REASON", customer_html)
		self.assertNotIn("INTERNAL_DECLINED_REASON", customer_html)
		self.assertNotIn("INTERNAL_PART_REASON", customer_html)
		self.assertNotIn("Declined Extra Job", customer_html)
		self.assertNotIn("Declined Wiper Blade", customer_html)
		self.assertNotIn("CANCELLED_ORDER_JOB", customer_html)
		self.assertNotIn(self.tech_name, customer_html)
		self.assertNotIn(self.emp.name, customer_html)
		self.assertIn(self.invoice_name, customer_html)

	def test_sanitize_visit_for_customer_helper(self):
		from vehicle_service.service_history import _sanitize_visit_for_customer

		self.assertEqual(_sanitize_visit_for_customer({"status": "Cancelled"}), {})

		sample = {
			"status": "Delivered",
			"reception_notes": "sec1",
			"hold_reason": "sec2",
			"dispute_notes": "sec3",
			"pause_reason": "sec4",
			"service_advisor": "adv@example.com",
			"service_advisor_name": "Advisor One",
			"intake": {"reception_notes": "sec5", "checked_in_by": "staff@example.com", "fuel_level": "1/2"},
			"jobs": [
				{
					"name": "J1",
					"job_title": "Good Job",
					"status": "Completed",
					"technician": "EMP-1",
					"technician_name": "Tech A",
					"reason_for_adding": "sec6",
					"qc_fail_reason": "sec7",
				},
				{"name": "J2", "job_title": "Declined Job", "status": "Declined"},
			],
			"parts": [
				{"item_code": "P1", "part_status": "Issued", "approval_status": "Approved", "reason_for_adding": "sec8"},
				{"item_code": "P2", "part_status": "Issued", "approval_status": "Approved", "job": "J2"},
				{"item_code": "P3", "part_status": "Declined", "approval_status": "Declined"},
			],
			"qc_inspections": [
				{"name": "QC-2", "result": "Pass", "inspector": "qc@example.com", "findings": "OK"},
				{"name": "QC-1", "result": "Fail", "fail_reason": "sec9", "inspector": "qc@example.com"},
			],
		}
		sanitized = _sanitize_visit_for_customer(sample)
		self.assertNotIn("reception_notes", sanitized)
		self.assertNotIn("hold_reason", sanitized)
		self.assertNotIn("dispute_notes", sanitized)
		self.assertNotIn("pause_reason", sanitized)
		self.assertNotIn("service_advisor", sanitized)
		self.assertEqual(sanitized["service_advisor_name"], "Advisor One")
		self.assertNotIn("reception_notes", sanitized["intake"])
		self.assertEqual([j["job_title"] for j in sanitized["jobs"]], ["Good Job"])
		self.assertNotIn("technician", sanitized["jobs"][0])
		self.assertNotIn("technician_name", sanitized["jobs"][0])
		self.assertNotIn("reason_for_adding", sanitized["jobs"][0])
		self.assertNotIn("qc_fail_reason", sanitized["jobs"][0])
		self.assertEqual([p["item_code"] for p in sanitized["parts"]], ["P1"])
		self.assertNotIn("reason_for_adding", sanitized["parts"][0])
		self.assertEqual(len(sanitized["qc_inspections"]), 1)
		self.assertEqual(sanitized["qc_inspections"][0]["name"], "QC-2")
		self.assertNotIn("inspector", sanitized["qc_inspections"][0])
		self.assertEqual(sanitized["qc"]["name"], "QC-2")
		# Input dict must not be mutated
		self.assertEqual(len(sample["jobs"]), 2)
		self.assertIn("reception_notes", sample)

	def test_print_financial_toggle_and_technician_bypass_blocked(self):
		from vehicle_service.service_history import render_vehicle_service_history_print

		customer_no_fin = render_vehicle_service_history_print(self.vehicle_reg, mode="customer", include_financials=0)
		self.assertNotIn("Total Invoice Value", customer_no_fin)
		self.assertNotIn("Total Historical Service Value", customer_no_fin)
		self.assertNotIn(self.invoice_name, customer_no_fin)

		customer_str_false = render_vehicle_service_history_print(
			self.vehicle_reg, mode="customer", include_financials="0"
		)
		self.assertNotIn("Total Invoice Value", customer_str_false)
		self.assertNotIn(self.invoice_name, customer_str_false)

		frappe.set_user(self.tech_user)
		tech_html = render_vehicle_service_history_print(self.vehicle_reg, mode="customer", include_financials=1)
		self.assertNotIn("Total Invoice Value", tech_html)
		self.assertNotIn("Total Historical Service Value", tech_html)
		self.assertNotIn(self.invoice_name, tech_html)

		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			render_vehicle_service_history_print(self.vehicle_reg, mode="invalid_mode")

		frappe.set_user(self.no_role_user)
		with self.assertRaises(frappe.PermissionError):
			render_vehicle_service_history_print(self.vehicle_reg, mode="customer")

	def test_download_pdf_generates_valid_pdf_bytes(self):
		from vehicle_service.service_history import download_vehicle_service_history_pdf

		download_vehicle_service_history_pdf(self.vehicle_reg, mode="customer", include_financials=1)
		self.assertEqual(frappe.local.response.get("type"), "pdf")
		self.assertTrue((frappe.local.response.get("filename") or "").endswith("-customer.pdf"))
		pdf_bytes = frappe.local.response.get("filecontent") or b""
		self.assertTrue(pdf_bytes.startswith(b"%PDF"))

		download_vehicle_service_history_pdf(self.vehicle_reg, mode="internal", include_financials=1)
		self.assertEqual(frappe.local.response.get("type"), "pdf")
		self.assertTrue((frappe.local.response.get("filename") or "").endswith("-internal.pdf"))
		internal_pdf_bytes = frappe.local.response.get("filecontent") or b""
		self.assertTrue(internal_pdf_bytes.startswith(b"%PDF"))

	def test_print_escapes_html_injection_payloads(self):
		from vehicle_service.service_history import render_vehicle_service_history_print

		xss_payload = '<script>window.__xss=1</script><img src=x onerror="alert(1)">'
		frappe.db.set_value(
			"Service Order",
			self.order.name,
			"customer_complaint",
			xss_payload,
			update_modified=False,
		)
		html = render_vehicle_service_history_print(self.vehicle_reg, mode="customer", include_financials=0)
		self.assertNotIn("<script>window.__xss=1</script>", html)
		self.assertNotIn('<img src=x onerror="alert(1)">', html)
		self.assertIn("&lt;script&gt;window.__xss=1&lt;/script&gt;", html)
