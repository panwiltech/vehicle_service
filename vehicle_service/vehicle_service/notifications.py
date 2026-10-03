# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, format_datetime, now_datetime


def get_order_context(order_name):
	"""Gathers order, vehicle, customer, and advisor context."""
	order = frappe.get_doc("Service Order", order_name)
	veh = frappe.get_doc("Service Vehicle", order.vehicle) if order.vehicle else None

	customer_email = None
	customer_phone = order.driver_phone

	if order.customer:
		# Check contact for customer
		contacts = frappe.get_all(
			"Dynamic Link",
			filters={"link_doctype": "Customer", "link_name": order.customer, "parenttype": "Contact"},
			pluck="parent",
		)
		if contacts:
			contact = frappe.get_doc("Contact", contacts[0])
			customer_email = contact.email_id
			if not customer_phone:
				customer_phone = contact.mobile_no or contact.phone

	return {
		"order": order,
		"veh": veh,
		"customer_name": order.customer_name or order.customer,
		"customer_email": customer_email,
		"customer_phone": customer_phone,
		"company": order.company or "Workshop",
	}


def log_communication(order, subject, content, channel="Email", recipient=None):
	"""Logs a communication record attached to the Service Order."""
	comm = frappe.new_doc("Communication")
	comm.communication_type = "Communication"
	comm.communication_medium = channel
	comm.sent_or_received = "Sent"
	comm.subject = subject
	comm.content = content
	comm.reference_doctype = "Service Order"
	comm.reference_name = order.name
	comm.sender = frappe.session.user
	# Ensure email recipient is valid if medium is Email
	if channel == "Email":
		if not recipient or "@" not in str(recipient):
			recipient = frappe.db.get_value("User", frappe.session.user, "email") or "customer@example.com"

	comm.recipients = recipient
	comm.status = "Linked"
	comm.communication_date = now_datetime()
	comm.insert(ignore_permissions=True)

	# Optionally try sending email if configured and channel is Email
	if channel == "Email" and recipient and "@" in recipient:
		try:
			frappe.sendmail(
				recipients=[recipient],
				subject=subject,
				message=content,
				reference_doctype="Service Order",
				reference_name=order.name,
				now=True,
			)
		except Exception:
			# Never fail transaction if outbound mail transport is unconfigured
			frappe.log_error(title="Failed to dispatch customer email", message=frappe.get_traceback())

	return comm.name


def send_intake_confirmation(order_name, channel="Email"):
	"""Sends vehicle check-in / intake confirmation with reported complaints."""
	ctx = get_order_context(order_name)
	order = ctx["order"]
	veh = ctx["veh"]

	veh_desc = f"{veh.make} {veh.model}" if veh else (order.vehicle_description or "Vehicle")
	mileage_str = f"{order.odometer_in:,.0f}" if order.odometer_in else "Unrecorded"

	subject = f"Intake Confirmation: {veh_desc} ({order.vehicle}) - Ref {order.name}"

	content = f"""
	Dear {ctx['customer_name']},

	Your vehicle has been checked in at {ctx['company']}.

	Vehicle: {veh_desc} (Registration: {order.vehicle})
	Intake Odometer: {mileage_str} km
	Fuel Level: {order.fuel_level or 'Unrecorded'}
	Service Order Ref: {order.name}

	Reported Complaints / Scope:
	{order.customer_complaint or 'Routine Inspection & Service'}

	Service Advisor: {order.service_advisor or 'Workshop Team'}

	We will inspect your vehicle and provide an estimate before performing any non-routine work.
	Thank you for trusting {ctx['company']}.
	""".strip()

	recipient = ctx["customer_email"] or order.driver_phone
	return log_communication(order, subject, content, channel=channel, recipient=recipient)


def send_estimate_approval_request(order_name, quotation_name=None, channel="Email"):
	"""Sends itemized quotation / estimate for customer approval."""
	if isinstance(quotation_name, dict):
		quotation_name = quotation_name.get("quotation")

	ctx = get_order_context(order_name)
	order = ctx["order"]

	if not quotation_name:
		quotation_name = frappe.db.get_value("Quotation", {"vs_service_order": order.name}, "name")

	q_doc = frappe.get_doc("Quotation", quotation_name) if quotation_name else None
	total_str = fmt_money(q_doc.grand_total, currency=q_doc.currency) if q_doc else "Pending"

	# Build itemized list
	items_summary = []
	if q_doc:
		for itm in q_doc.items:
			category = itm.get("vs_category") or "Essential"
			items_summary.append(
				f"• [{category}] {itm.item_name} - {fmt_money(itm.amount, currency=q_doc.currency)}"
			)
	items_text = "\n".join(items_summary) if items_summary else "• Detailed repair estimate attached."

	subject = f"Service Estimate Approval Required: {order.vehicle} - {total_str}"

	content = f"""
	Dear {ctx['customer_name']},

	The technical inspection for your vehicle {order.vehicle} is complete.
	Quotation Reference: {quotation_name or 'Draft Estimate'}
	Total Estimated Amount: {total_str}

	Recommended Scope:
	{items_text}

	Please reply or contact your Service Advisor ({order.service_advisor or 'our office'}) to approve or adjust this scope of work.
	Work will commence upon your authorization.
	""".strip()

	recipient = ctx["customer_email"] or order.driver_phone
	return log_communication(order, subject, content, channel=channel, recipient=recipient)


def send_ready_for_collection(order_name, channel="Email"):
	"""Sends vehicle ready for collection notification with billing clearance summary."""
	ctx = get_order_context(order_name)
	order = ctx["order"]

	inv_ref = order.sales_invoice or "Cleared / Warranty"
	location_str = order.current_location or "Workshop Delivery Bay"

	subject = f"Ready for Collection: {order.vehicle} - Order {order.name}"

	content = f"""
	Dear {ctx['customer_name']},

	Good news! The service and quality control checks for your vehicle {order.vehicle} are now complete.
	Your vehicle is Ready for Collection at {ctx['company']}.

	Collection Location: {location_str}
	Invoice / Settlement Ref: {inv_ref}

	Please bring this confirmation to the service reception when collecting your vehicle.
	Our team is ready to hand over your keys and walk you through the completed work.

	Operating Hours: Monday - Friday 07:30 - 17:30, Saturday 08:00 - 13:00.
	""".strip()

	recipient = ctx["customer_email"] or order.driver_phone
	return log_communication(order, subject, content, channel=channel, recipient=recipient)
