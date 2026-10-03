# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from vehicle_service.state import JOB_PASSED, JOB_QC_FAILED


class ServiceQC(Document):
	def validate(self):
		if self.docstatus == 1 or self.result:
			if not self.result:
				frappe.throw(_("QC Result (Pass/Fail) is required."))

			if self.result == "Pass":
				for item in self.get("checklist", []):
					if not item.passed:
						frappe.throw(
							_("All inspection checklist items must be passed. Item '{0}' is not checked.").format(
								item.check_item
							)
						)
			elif self.result == "Fail":
				if not self.fail_reason:
					frappe.throw(_("Failure Reason is mandatory when QC fails."))
				if not self.get("failed_jobs"):
					frappe.throw(_("Please select at least one job to return to workshop for rework."))

	def on_submit(self):
		order = frappe.get_doc("Service Order", self.service_order)
		order.last_qc = self.name
		order.qc_result = self.result

		settings = frappe.get_cached_doc("Vehicle Service Settings")

		if self.result == "Pass":
			# Mark all completed jobs as Passed
			completed_jobs = frappe.get_all(
				"Service Job",
				filters={"service_order": self.service_order, "status": "Completed"},
				pluck="name",
			)
			for jname in completed_jobs:
				frappe.db.set_value("Service Job", jname, "status", JOB_PASSED)

			order.status = "Ready for Billing"
			order.save(ignore_permissions=True)

			# Move vehicle to Parking / Finished area
			if settings.parking_location:
				vehicle = frappe.get_doc("Service Vehicle", order.vehicle)
				vehicle.move_location(settings.parking_location, _("QC Passed. Vehicle moved to parking."), order.name)

		elif self.result == "Fail":
			# Mark failed jobs as QC Failed
			for fj in self.get("failed_jobs", []):
				frappe.db.set_value(
					"Service Job",
					fj.job,
					{
						"status": JOB_QC_FAILED,
						"qc_fail_reason": self.fail_reason,
					},
				)

			# Order status returns to In Progress
			order.sync_status_from_jobs_and_parts()

			vehicle = frappe.get_doc("Service Vehicle", order.vehicle)
			target_bay = None
			if self.failed_jobs:
				first_job = frappe.db.get_value("Service Job", self.failed_jobs[0].job, "bay")
				if first_job:
					target_bay = first_job
			if target_bay:
				vehicle.move_location(target_bay, _("QC Failed. Returned to workshop bay."), order.name)


@frappe.whitelist()
def create_qc_inspection(service_order: str, template: str | None = None):
	order = frappe.get_doc("Service Order", service_order)
	if order.status != "QC":
		frappe.throw(_("Service Order {0} is in status '{1}'. QC inspection can only be started when status is 'QC'.").format(order.name, order.status))

	qc = frappe.new_doc("Service QC")
	qc.service_order = order.name
	qc.vehicle = order.vehicle
	qc.inspector = frappe.session.user

	settings = frappe.get_cached_doc("Vehicle Service Settings")
	template_to_use = template or settings.default_qc_template
	if template_to_use and frappe.db.exists("QC Template", template_to_use):
		qc.qc_template = template_to_use
		tmpl = frappe.get_doc("QC Template", template_to_use)
		for itm in tmpl.items:
			qc.append("checklist", {"check_item": itm.check_item, "passed": 0})

	qc.insert(ignore_permissions=True)
	return {"status": "success", "qc_name": qc.name}
