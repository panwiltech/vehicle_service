# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe


def _ensure_role(role_name: str):
	if not frappe.db.exists("Role", role_name):
		r = frappe.new_doc("Role")
		r.role_name = role_name
		r.desk_access = 1
		r.insert(ignore_permissions=True)


def create_test_user(email="jobcontroller.test@example.com", password=None):
	"""Idempotently creates or updates the dedicated test Job Controller user."""
	password = password or "JobController123!"
	_ensure_role("Job Controller")

	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "Job Controller"
		user.last_name = "Tester"
		user.enabled = 1
		user.user_type = "System User"
		user.roles = []
		user.append("roles", {"role": "Job Controller"})
		user.new_password = password
		user.default_workspace = "Job Control Board"
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)
		user.enabled = 1
		user.roles = []
		user.append("roles", {"role": "Job Controller"})
		user.new_password = password
		user.default_workspace = "Job Control Board"
		user.save(ignore_permissions=True)

	frappe.db.commit()
	return {"email": email, "password": password}


def create_test_service_advisor_user(email="serviceadvisor.test@example.com", password=None):
	"""Idempotently creates or updates the dedicated test Service Advisor user."""
	password = password or "ServiceAdvisor123!"
	_ensure_role("Service Advisor")

	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "Service Advisor"
		user.last_name = "Tester"
		user.enabled = 1
		user.user_type = "System User"
		user.roles = []
		user.append("roles", {"role": "Service Advisor"})
		user.new_password = password
		user.default_workspace = "Service Advisor"
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)
		user.enabled = 1
		user.roles = []
		user.append("roles", {"role": "Service Advisor"})
		user.new_password = password
		user.default_workspace = "Service Advisor"
		user.save(ignore_permissions=True)

	frappe.db.commit()
	return {"email": email, "password": password}


def create_test_parts_controller_user(email="partscontroller.test@example.com", password=None):
	"""Idempotently creates or updates the dedicated test Parts Controller / Consultant user."""
	password = password or "PartsController123!"
	_ensure_role("Parts Controller")

	if not frappe.db.exists("User", email):
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "Parts Controller"
		user.last_name = "Tester"
		user.enabled = 1
		user.user_type = "System User"
		user.roles = []
		user.append("roles", {"role": "Parts Controller"})
		user.new_password = password
		user.default_workspace = "Parts Store"
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)
		user.enabled = 1
		user.roles = []
		user.append("roles", {"role": "Parts Controller"})
		user.new_password = password
		user.default_workspace = "Parts Store"
		user.save(ignore_permissions=True)

	frappe.db.commit()
	return {"email": email, "password": password}


def create_all_test_users():
	"""Helper to initialize or sync all operational test users."""
	jc = create_test_user()
	sa = create_test_service_advisor_user()
	pc = create_test_parts_controller_user()
	return {"job_controller": jc, "service_advisor": sa, "parts_controller": pc}


def sync_job_control_workspace():
	"""Ensures the Job Control Board workspace is reloaded from disk with valid title and number cards."""
	frappe.reload_doc("vehicle_service", "workspace", "job_control_board", force=True)
	frappe.db.commit()
	return True
