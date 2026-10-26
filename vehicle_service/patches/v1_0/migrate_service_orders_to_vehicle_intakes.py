import frappe


def execute():
	frappe.reload_doc("vehicle_service", "doctype", "vehicle_intake")
	frappe.reload_doc("vehicle_service", "doctype", "service_order")

	orders = frappe.get_all(
		"Service Order",
		filters={"vehicle_intake": ["in", ["", None]]},
		fields=[
			"name",
			"vehicle",
			"customer",
			"service_advisor",
			"company",
			"odometer_in",
			"fuel_level",
			"customer_complaint",
			"existing_damage",
			"vehicle_contents",
			"customer_signature",
			"intake_confirmed",
			"checked_in_on",
			"checked_in_by",
			"creation",
		],
	)

	for o in orders:
		# If an intake already points to this order, just link it
		existing_intake = frappe.db.get_value("Vehicle Intake", {"service_order": o.name}, "name")
		if existing_intake:
			frappe.db.set_value("Service Order", o.name, "vehicle_intake", existing_intake, update_modified=False)
			continue

		if not o.odometer_in and not o.customer_signature:
			continue

		intake = frappe.new_doc("Vehicle Intake")
		intake.vehicle = o.vehicle
		intake.customer = o.customer
		intake.service_advisor = o.service_advisor
		intake.company = o.company
		intake.odometer_in = o.odometer_in or 0
		intake.fuel_level = o.fuel_level or "1/2"
		intake.customer_complaint = o.customer_complaint
		intake.existing_damage = o.existing_damage
		intake.vehicle_contents = o.vehicle_contents
		intake.customer_signature = o.customer_signature
		intake.intake_confirmed = o.intake_confirmed or 1
		intake.checked_in_on = o.checked_in_on or o.creation
		intake.checked_in_by = o.checked_in_by
		intake.service_order = o.name
		intake.status = "Checked In"
		intake.intake_frozen = 1
		intake.flags.ignore_permissions = True
		intake.flags.ignore_mandatory = True
		intake.insert()

		frappe.db.set_value("Service Order", o.name, "vehicle_intake", intake.name, update_modified=False)
