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
