# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ServiceBooking(Document):
	def validate(self):
		if self.vehicle and not self.customer:
			self.customer = frappe.db.get_value("Service Vehicle", self.vehicle, "customer")


@frappe.whitelist()
def check_in_booking(booking_name: str):
	booking = frappe.get_doc("Service Booking", booking_name)
	if booking.status in ("Arrived", "Cancelled", "No Show"):
		frappe.throw(_("Booking {0} is already {1}").format(booking.name, booking.status))

	if getattr(booking, "vehicle_intake", None) and frappe.db.exists("Vehicle Intake", booking.vehicle_intake):
		return {"status": "success", "vehicle_intake": booking.vehicle_intake}

	if booking.service_order:
		return {"status": "success", "service_order": booking.service_order}

	intake = frappe.new_doc("Vehicle Intake")
	intake.vehicle = booking.vehicle
	intake.customer = booking.customer
	intake.booking = booking.name
	intake.service_advisor = booking.service_advisor or frappe.session.user
	intake.customer_complaint = booking.requested_service
	intake.flags.ignore_permissions = True
	intake.insert()

	if hasattr(booking, "vehicle_intake"):
		booking.vehicle_intake = intake.name
		booking.save(ignore_permissions=True)

	return {"status": "success", "vehicle_intake": intake.name}


@frappe.whitelist()
def cancel_booking(booking_name: str, reason: str):
	booking = frappe.get_doc("Service Booking", booking_name)
	booking.status = "Cancelled"
	booking.close_reason = reason
	booking.save(ignore_permissions=True)
	return {"status": "success"}
