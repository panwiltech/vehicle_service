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

	if booking.service_order:
		return {"status": "success", "service_order": booking.service_order}

	order = frappe.new_doc("Service Order")
	order.vehicle = booking.vehicle
	order.customer = booking.customer
	order.booking = booking.name
	order.service_advisor = booking.service_advisor or frappe.session.user
	order.customer_complaint = booking.requested_service
	order.service_package = booking.service_package
	order.insert(ignore_permissions=True)

	booking.status = "Arrived"
	booking.service_order = order.name
	booking.save(ignore_permissions=True)

	return {"status": "success", "service_order": order.name}


@frappe.whitelist()
def cancel_booking(booking_name: str, reason: str):
	booking = frappe.get_doc("Service Booking", booking_name)
	booking.status = "Cancelled"
	booking.close_reason = reason
	booking.save(ignore_permissions=True)
	return {"status": "success"}
