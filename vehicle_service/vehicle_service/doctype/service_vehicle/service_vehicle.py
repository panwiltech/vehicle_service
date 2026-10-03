# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, getdate, now_datetime, nowdate


class ServiceVehicle(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		colour: DF.Data | None
		current_location: DF.Link | None
		current_mileage: DF.Int
		current_service_order: DF.Link | None
		custodian: DF.Link | None
		customer: DF.Link
		customer_name: DF.Data | None
		driver_name: DF.Data | None
		driver_phone: DF.Data | None
		engine_no: DF.Data | None
		fuel_type: DF.Literal["", "Petrol", "Diesel", "Hybrid", "Electric", "LPG", "Other"]
		image: DF.AttachImage | None
		last_service_date: DF.Date | None
		last_service_mileage: DF.Int
		make: DF.Data
		model: DF.Data
		next_service_date: DF.Date | None
		next_service_mileage: DF.Int
		notes: DF.TextEditor | None
		registration_no: DF.Data
		service_interval_km: DF.Int
		service_interval_months: DF.Int
		transmission: DF.Literal["", "Manual", "Automatic"]
		vehicle_status: DF.Literal["Outside Workshop", "Arrived", "Checked In", "Waiting", "In Workshop", "QC", "Awaiting Release", "Ready for Collection"]
		vin: DF.Data
		year: DF.Int
	# end: auto-generated types

	def validate(self):
		if self.registration_no:
			self.registration_no = self.registration_no.strip().upper()

		if self.vin:
			self.vin = self.vin.strip().upper()

		self.validate_mileage()
		self.calculate_next_service()

	def validate_mileage(self):
		if not self.is_new() and self.current_mileage:
			old_mileage = frappe.db.get_value("Service Vehicle", self.name, "current_mileage") or 0
			if old_mileage and self.current_mileage < old_mileage:
				if not frappe.flags.in_correction:
					frappe.throw(
						_("Current mileage ({0} km) cannot be lower than previously recorded mileage ({1} km)").format(
							self.current_mileage, old_mileage
						)
					)

	def calculate_next_service(self):
		settings = frappe.get_cached_doc("Vehicle Service Settings")
		interval_km = self.service_interval_km or settings.default_service_interval_km or 5000
		interval_months = self.service_interval_months or settings.default_service_interval_months or 6

		base_mileage = self.last_service_mileage or self.current_mileage or 0
		if base_mileage:
			self.next_service_mileage = base_mileage + interval_km

		base_date = self.last_service_date or (getdate(self.creation) if self.creation else getdate(nowdate()))
		if base_date:
			self.next_service_date = add_months(base_date, interval_months)

	def move_location(self, to_location: str, reason: str | None = None, service_order: str | None = None):
		if not to_location:
			frappe.throw(_("Destination location is required"))

		from_loc = self.current_location
		if from_loc == to_location:
			return

		self.current_location = to_location
		self.save(ignore_permissions=True)

		movement = frappe.new_doc("Vehicle Movement")
		movement.vehicle = self.name
		movement.service_order = service_order or self.current_service_order
		movement.from_location = from_loc
		movement.to_location = to_location
		movement.moved_on = now_datetime()
		movement.moved_by = frappe.session.user
		movement.reason = reason or _("Location updated")
		movement.insert(ignore_permissions=True)


@frappe.whitelist()
def move_vehicle(vehicle: str, to_location: str, reason: str | None = None):
	doc = frappe.get_doc("Service Vehicle", vehicle)
	doc.check_permission("write")
	doc.move_location(to_location, reason)
	return {"status": "success", "current_location": doc.current_location}


@frappe.whitelist()
def get_vehicle_summary(vehicle: str):
	if not frappe.db.exists("Service Vehicle", vehicle):
		return None

	doc = frappe.get_doc("Service Vehicle", vehicle)
	active_order = None
	if doc.current_service_order:
		active_order = frappe.db.get_value(
			"Service Order",
			doc.current_service_order,
			["name", "status", "service_advisor", "expected_completion"],
			as_dict=True,
		)

	# Fetch recent 5 service orders
	recent_orders = frappe.get_all(
		"Service Order",
		filters={"vehicle": vehicle, "status": ["!=", "Draft"]},
		fields=["name", "creation", "status", "odometer_in", "sales_invoice"],
		order_by="creation desc",
		limit=5,
	)

	return {
		"name": doc.name,
		"registration_no": doc.registration_no,
		"make": doc.make,
		"model": doc.model,
		"year": doc.year,
		"customer": doc.customer,
		"customer_name": doc.customer_name,
		"driver_name": doc.driver_name,
		"driver_phone": doc.driver_phone,
		"current_mileage": doc.current_mileage,
		"vehicle_status": doc.vehicle_status,
		"current_location": doc.current_location,
		"active_order": active_order,
		"recent_orders": recent_orders,
		"last_service_date": doc.last_service_date,
		"next_service_date": doc.next_service_date,
		"next_service_mileage": doc.next_service_mileage,
	}
