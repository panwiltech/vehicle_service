# Copyright (c) 2026, Azazel and contributors
# For license information, please see license.txt

import frappe


def handle_stock_entry_change(doc, method=None):
	if getattr(doc, "vs_service_order", None):
		from vehicle_service.vehicle_service.doctype.service_order.service_order import (
			recalculate_order_parts_from_stock,
		)

		recalculate_order_parts_from_stock(doc.vs_service_order)
