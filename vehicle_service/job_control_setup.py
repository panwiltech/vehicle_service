# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe


def create_test_user(email="jobcontroller.test@example.com", password=None):
	"""Idempotently creates or updates the dedicated test Job Controller user."""
	password = password or "JobController123!"

	# Ensure Job Controller role exists
	if not frappe.db.exists("Role", "Job Controller"):
		r = frappe.new_doc("Role")
		r.role_name = "Job Controller"
		r.desk_access = 1
		r.insert(ignore_permissions=True)

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
		# Restrict roles strictly to Job Controller
		user.roles = []
		user.append("roles", {"role": "Job Controller"})
		user.new_password = password
		user.default_workspace = "Job Control Board"
		user.save(ignore_permissions=True)

	frappe.db.commit()
	return {"email": email, "password": password}


def sync_job_control_workspace():
	"""Ensures the Job Control Board workspace is reloaded from disk with valid title and number cards."""
	frappe.reload_doc("vehicle_service", "workspace", "job_control_board", force=True)
	frappe.db.commit()
	return True
