# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class PartsSubstitution(Document):
	def validate(self):
		if self.service_order and self.part_row:
			order = frappe.get_doc("Service Order", self.service_order)
			matching_row = None
			for p in order.parts:
				if p.name == self.part_row:
					matching_row = p
					break

			if matching_row:
				self.original_item = matching_row.item_code
				self.original_qty = matching_row.qty_required

				# Price check comparison
				orig_price = frappe.db.get_value("Item Price", {"item_code": self.original_item, "price_list": "Standard Selling"}, "price_list_rate") or 0
				sub_price = frappe.db.get_value("Item Price", {"item_code": self.substitute_item, "price_list": "Standard Selling"}, "price_list_rate") or 0
				if flt(sub_price) > flt(orig_price):
					self.needs_customer_approval = 1


@frappe.whitelist()
def approve_substitution(sub_name: str, review_notes: str | None = None):
	sub = frappe.get_doc("Parts Substitution", sub_name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if not (roles & {"Parts Controller", "Service Manager", "System Manager"}):
		frappe.throw(_("Only Parts Controllers or Service Managers can approve substitutions."))

	if sub.status != "Requested":
		frappe.throw(_("Substitution is already {0}").format(sub.status))

	order = frappe.get_doc("Service Order", sub.service_order)
	orig_row = None
	for r in order.parts:
		if r.name == sub.part_row:
			orig_row = r
			break

	if not orig_row:
		frappe.throw(_("Original part row not found on Service Order."))

	if orig_row.qty_issued and orig_row.qty_issued > (orig_row.qty_returned or 0):
		frappe.throw(_("Parts have already been issued for this row. Please return them first before substituting."))

	# Create new line
	new_approval = "Pending" if sub.needs_customer_approval else orig_row.approval_status
	new_part_status = "Pending Approval" if sub.needs_customer_approval else "Required"

	new_row = order.append(
		"parts",
		{
			"item_code": sub.substitute_item,
			"job": orig_row.job,
			"category": orig_row.category,
			"qty_required": sub.qty,
			"approval_status": new_approval,
			"part_status": new_part_status,
			"source": "Substitute Part",
		},
	)

	orig_row.substituted_by = new_row.name or "New"
	orig_row.part_status = "Substituted"

	order.save(ignore_permissions=True)

	sub.status = "Approved"
	sub.reviewed_by = user
	sub.reviewed_on = now_datetime()
	sub.review_notes = review_notes
	sub.new_part_row = new_row.name
	sub.save(ignore_permissions=True)

	order.sync_status_from_jobs_and_parts()

	return {"status": "success", "substitution_status": "Approved"}


@frappe.whitelist()
def reject_substitution(sub_name: str, reason: str):
	sub = frappe.get_doc("Parts Substitution", sub_name)
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if not (roles & {"Parts Controller", "Service Manager", "System Manager"}):
		frappe.throw(_("Only Parts Controllers or Service Managers can reject substitutions."))

	sub.status = "Rejected"
	sub.reviewed_by = user
	sub.reviewed_on = now_datetime()
	sub.review_notes = reason
	sub.save(ignore_permissions=True)

	return {"status": "success", "substitution_status": "Rejected"}
