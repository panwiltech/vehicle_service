# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

DRAFT = "Draft"
CHECKED_IN = "Checked In"
CANCELLED = "Cancelled"


class VehicleIntake(Document):
	def validate(self):
		if self.vehicle:
			v = frappe.get_doc("Service Vehicle", self.vehicle)
			if not self.customer:
				self.customer = v.customer
			if not self.vehicle_description:
				desc = f"{v.make or ''} {v.model or ''} {v.year or ''}".strip()
				self.vehicle_description = desc or v.registration_no
			if not self.license_plate:
				self.license_plate = v.registration_no
			if not self.vin:
				self.vin = v.vin

		self.validate_frozen_fields()

	def validate_frozen_fields(self):
		if getattr(frappe.flags, "in_correction", False):
			return

		if self.intake_frozen:
			prev = self.get_doc_before_save()
			if prev and prev.intake_frozen:
				for f in ("odometer_in", "fuel_level", "customer_signature", "intake_confirmed"):
					if self.get(f) != prev.get(f):
						label = self.meta.get_label(f) or f
						frappe.throw(
							_("Field '{0}' is frozen at check-in. Use Correct Intake to amend it.").format(label)
						)


@frappe.whitelist()
def complete_check_in(intake_name: str, customer_signature: str | None = None):
	intake = frappe.get_doc("Vehicle Intake", intake_name)
	if intake.status != DRAFT:
		frappe.throw(_("Vehicle Intake is already {0}.").format(intake.status))

	if customer_signature:
		intake.customer_signature = customer_signature

	vehicle = frappe.get_doc("Service Vehicle", intake.vehicle)

	if not intake.odometer_in and vehicle.current_mileage:
		intake.odometer_in = vehicle.current_mileage

	if intake.odometer_in and vehicle.current_mileage and int(intake.odometer_in) < int(vehicle.current_mileage):
		frappe.throw(
			_("Odometer reading ({0} km) cannot be lower than current vehicle mileage ({1} km).").format(
				intake.odometer_in, vehicle.current_mileage
			)
		)

	intake.status = CHECKED_IN
	intake.intake_frozen = 1
	intake.checked_in_on = now_datetime()
	intake.checked_in_by = frappe.session.user
	intake.save(ignore_permissions=True)

	# Update Service Vehicle mileage and workshop status
	vehicle.current_mileage = intake.odometer_in
	vehicle.vehicle_status = "In Workshop"

	try:
		settings = frappe.get_cached_doc("Vehicle Service Settings")
		if settings.reception_location:
			vehicle.move_location(settings.reception_location, _("Vehicle intake check-in"), intake.name)
	except Exception:
		pass

	vehicle.save(ignore_permissions=True)

	return {"status": "success", "intake_status": intake.status}


@frappe.whitelist()
def correct_intake(intake_name: str, fieldname: str, new_value: str, reason: str):
	intake = frappe.get_doc("Vehicle Intake", intake_name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if not (roles & {"Service Advisor", "Service Manager", "System Manager"}):
		frappe.throw(_("Only Service Advisors or Managers can correct intake information."))

	if not reason:
		frappe.throw(_("A valid reason is required for intake corrections."))

	old_val = str(intake.get(fieldname) or "")
	label = intake.meta.get_label(fieldname) or fieldname

	intake.append(
		"corrections",
		{
			"field_label": label,
			"fieldname": fieldname,
			"old_value": old_val,
			"new_value": str(new_value),
			"reason": reason,
			"corrected_by": user,
			"corrected_on": now_datetime(),
		},
	)

	frappe.flags.in_correction = True
	if fieldname == "odometer_in":
		intake.odometer_in = int(new_value)
		if intake.vehicle:
			v = frappe.get_doc("Service Vehicle", intake.vehicle)
			v.current_mileage = intake.odometer_in
			v.save(ignore_permissions=True)
		if intake.service_order and frappe.db.exists("Service Order", intake.service_order):
			frappe.db.set_value("Service Order", intake.service_order, "odometer_in", intake.odometer_in)
	else:
		intake.set(fieldname, new_value)
		if intake.service_order and frappe.db.exists("Service Order", intake.service_order):
			if hasattr(frappe.get_meta("Service Order"), fieldname):
				frappe.db.set_value("Service Order", intake.service_order, fieldname, new_value)

	intake.save(ignore_permissions=True)
	frappe.flags.in_correction = False

	return {"status": "success"}


@frappe.whitelist()
def create_service_order_from_intake(intake_name: str) -> dict:
	intake = frappe.get_doc("Vehicle Intake", intake_name)
	if intake.status != CHECKED_IN:
		frappe.throw(_("Vehicle Intake must be Checked In before creating a Service Order."))

	if intake.service_order and frappe.db.exists("Service Order", intake.service_order):
		return {"status": "success", "service_order": intake.service_order}

	order = frappe.new_doc("Service Order")
	order.vehicle_intake = intake.name
	order.vehicle = intake.vehicle
	order.customer = intake.customer
	order.service_advisor = intake.service_advisor or frappe.session.user
	order.booking = intake.booking
	order.company = intake.company
	order.customer_complaint = intake.customer_complaint
	order.odometer_in = intake.odometer_in
	order.fuel_level = intake.fuel_level
	order.existing_damage = intake.existing_damage
	order.vehicle_contents = intake.vehicle_contents
	order.intake_confirmed = intake.intake_confirmed
	order.customer_signature = intake.customer_signature
	order.intake_frozen = 1
	order.checked_in_on = intake.checked_in_on
	order.checked_in_by = intake.checked_in_by
	order.flags.ignore_permissions = True
	order.insert()

	intake.service_order = order.name
	intake.save(ignore_permissions=True)

	if intake.booking and frappe.db.exists("Service Booking", intake.booking):
		frappe.db.set_value(
			"Service Booking",
			intake.booking,
			{"status": "Arrived", "service_order": order.name},
			update_modified=False,
		)

	return {"status": "success", "service_order": order.name}
