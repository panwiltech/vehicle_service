import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROLES = [
	"Service Receptionist",
	"Service Advisor",
	"Workshop Supervisor",
	"Workshop Technician",
	"Parts Controller",
	"QC Inspector",
	"Service Accounts",
	"Service Manager",
	"Job Controller",
]

DEFAULT_LOCATIONS = [
	{"location_name": "Reception", "location_type": "Reception"},
	{"location_name": "Reception Yard", "location_type": "Yard"},
	{"location_name": "Bay 1", "location_type": "Bay"},
	{"location_name": "Bay 2", "location_type": "Bay"},
	{"location_name": "Bay 3", "location_type": "Bay"},
	{"location_name": "Bay 4", "location_type": "Bay"},
	{"location_name": "Parts Waiting Area", "location_type": "Parts Waiting"},
	{"location_name": "QC Area", "location_type": "QC"},
	{"location_name": "Road Test", "location_type": "Road Test"},
	{"location_name": "Parking", "location_type": "Parking"},
	{"location_name": "Collection Area", "location_type": "Collection"},
]

DEFAULT_QC_ITEMS = [
	"Approved work completed to specification",
	"Brake operation checked",
	"Fluid levels checked (oil, coolant, washer)",
	"Lights, indicators and horn checked",
	"Tyre condition and pressure verified",
	"Road test completed",
	"Vehicle clean and no tools/parts left inside",
]

CUSTOM_FIELDS = {
	"Quotation": [
		{
			"fieldname": "vs_service_order",
			"label": "Service Order",
			"fieldtype": "Link",
			"options": "Service Order",
			"insert_after": "customer",
			"read_only": 1,
		},
		{
			"fieldname": "vs_vehicle",
			"label": "Vehicle",
			"fieldtype": "Link",
			"options": "Service Vehicle",
			"insert_after": "vs_service_order",
		},
		{
			"fieldname": "vs_service_advisor",
			"label": "Service Advisor",
			"fieldtype": "Link",
			"options": "User",
			"insert_after": "vs_vehicle",
		},
	],
	"Quotation Item": [
		{
			"fieldname": "vs_job",
			"label": "Service Job",
			"fieldtype": "Link",
			"options": "Service Job",
			"insert_after": "item_code",
			"read_only": 1,
		},
		{
			"fieldname": "vs_part_row",
			"label": "Part Row ID",
			"fieldtype": "Data",
			"insert_after": "vs_job",
			"read_only": 1,
		},
		{
			"fieldname": "vs_category",
			"label": "Service Category",
			"fieldtype": "Select",
			"options": "Essential\nRecommended\nOptional",
			"default": "Essential",
			"insert_after": "vs_part_row",
		},
		{
			"fieldname": "vs_approval",
			"label": "Customer Approval",
			"fieldtype": "Select",
			"options": "Pending\nApproved\nDeclined",
			"default": "Pending",
			"allow_on_submit": 1,
			"insert_after": "vs_category",
		},
	],
	"Sales Order": [
		{
			"fieldname": "vs_service_order",
			"label": "Service Order",
			"fieldtype": "Link",
			"options": "Service Order",
			"insert_after": "customer",
			"read_only": 1,
		}
	],
	"Sales Order Item": [
		{
			"fieldname": "vs_job",
			"label": "Service Job",
			"fieldtype": "Link",
			"options": "Service Job",
			"insert_after": "item_code",
			"read_only": 1,
		},
		{
			"fieldname": "vs_part_row",
			"label": "Part Row ID",
			"fieldtype": "Data",
			"insert_after": "vs_job",
			"read_only": 1,
		},
	],
	"Sales Invoice": [
		{
			"fieldname": "vs_service_order",
			"label": "Service Order",
			"fieldtype": "Link",
			"options": "Service Order",
			"insert_after": "customer",
			"read_only": 1,
		}
	],
	"Sales Invoice Item": [
		{
			"fieldname": "vs_job",
			"label": "Service Job",
			"fieldtype": "Link",
			"options": "Service Job",
			"insert_after": "item_code",
			"read_only": 1,
		},
		{
			"fieldname": "vs_part_row",
			"label": "Part Row ID",
			"fieldtype": "Data",
			"insert_after": "vs_job",
			"read_only": 1,
		},
	],
	"Stock Entry": [
		{
			"fieldname": "vs_service_order",
			"label": "Service Order",
			"fieldtype": "Link",
			"options": "Service Order",
			"insert_after": "purpose",
			"read_only": 1,
		}
	],
	"Stock Entry Detail": [
		{
			"fieldname": "vs_part_row",
			"label": "Part Row ID",
			"fieldtype": "Data",
			"insert_after": "item_code",
			"read_only": 1,
		}
	],
	"Material Request": [
		{
			"fieldname": "vs_service_order",
			"label": "Service Order",
			"fieldtype": "Link",
			"options": "Service Order",
			"insert_after": "material_request_type",
			"read_only": 1,
		}
	],
	"Customer": [
		{
			"fieldname": "vs_credit_release",
			"label": "Allow Service Release on Credit",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "customer_group",
			"description": "If enabled, vehicles can be released after invoice without waiting for full payment entry.",
		}
	],
}


def after_install():
	setup_roles()
	setup_custom_fields()
	setup_default_locations()
	setup_default_qc_template()
	setup_default_service_items()
	setup_default_settings()
	setup_job_controller_permissions()
	setup_default_board_tabs()


def after_migrate():
	setup_roles()
	setup_custom_fields()
	setup_default_locations()
	setup_default_qc_template()
	setup_default_service_items()
	setup_default_settings()
	setup_job_controller_permissions()
	setup_default_board_tabs()


def setup_roles():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			r = frappe.new_doc("Role")
			r.role_name = role
			r.desk_access = 1
			r.save(ignore_permissions=True)
	frappe.db.commit()


def setup_job_controller_permissions():
	"""Ensures Custom DocPerm records exist for Job Controller on supporting DocTypes."""
	core_doctypes = ["Employee", "Customer", "Item", "Service Vehicle", "Workshop Location"]
	for dt in core_doctypes:
		if not frappe.db.exists("Custom DocPerm", {"parent": dt, "role": "Job Controller"}):
			try:
				cdp = frappe.new_doc("Custom DocPerm")
				cdp.parent = dt
				cdp.parenttype = "DocType"
				cdp.parentfield = "permissions"
				cdp.role = "Job Controller"
				cdp.read = 1
				cdp.report = 1
				cdp.export = 1
				cdp.print = 1
				cdp.insert(ignore_permissions=True)
			except Exception:
				pass
	try:
		frappe.reload_doc("vehicle_service", "workspace", "job_control_board", force=True)
	except Exception:
		pass
	frappe.db.commit()



def setup_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, update=True)


def setup_default_locations():
	for loc in DEFAULT_LOCATIONS:
		if not frappe.db.exists("Workshop Location", loc["location_name"]):
			d = frappe.new_doc("Workshop Location")
			d.location_name = loc["location_name"]
			d.location_type = loc["location_type"]
			d.is_active = 1
			d.save(ignore_permissions=True)
	frappe.db.commit()


def setup_default_qc_template():
	if not frappe.db.exists("QC Template", "Standard Workshop QC"):
		qc = frappe.new_doc("QC Template")
		qc.template_name = "Standard Workshop QC"
		qc.is_active = 1
		for item in DEFAULT_QC_ITEMS:
			qc.append("items", {"check_item": item})
		qc.save(ignore_permissions=True)
	frappe.db.commit()


DEFAULT_SERVICE_ITEMS = [
	{
		"item_code": "LABOUR",
		"item_name": "Workshop Labour",
		"item_group": "Services",
		"stock_uom": "Hour",
		"is_stock_item": 0,
		"is_sales_item": 1,
		"is_purchase_item": 0,
		"description": "General workshop, mechanical and electrical labour",
	},
	{
		"item_code": "WHEEL-ALIGN",
		"item_name": "Wheel Alignment",
		"item_group": "Services",
		"stock_uom": "Job",
		"is_stock_item": 0,
		"is_sales_item": 1,
		"is_purchase_item": 0,
		"description": "Vehicle computerized wheel alignment service",
	},
	{
		"item_code": "REGAS",
		"item_name": "A/C Regas",
		"item_group": "Services",
		"stock_uom": "Job",
		"is_stock_item": 0,
		"is_sales_item": 1,
		"is_purchase_item": 0,
		"description": "Air conditioning system evac, vacuum test and regas",
	},
	{
		"item_code": "SUBLET",
		"item_name": "Sublet Outside Service",
		"item_group": "Services",
		"stock_uom": "Job",
		"is_stock_item": 0,
		"is_sales_item": 1,
		"is_purchase_item": 1,
		"description": "Outside specialist sublet work (engineering, auto glass, upholstery)",
	},
]


def setup_default_service_items():
	if not frappe.db.exists("UOM", "Job"):
		uom = frappe.new_doc("UOM")
		uom.uom_name = "Job"
		uom.save(ignore_permissions=True)

	if not frappe.db.exists("Item Group", "Services"):
		ig = frappe.new_doc("Item Group")
		ig.item_group_name = "Services"
		ig.parent_item_group = "All Item Groups"
		ig.save(ignore_permissions=True)

	for itm in DEFAULT_SERVICE_ITEMS:
		if not frappe.db.exists("Item", itm["item_code"]):
			item = frappe.new_doc("Item")
			item.update(itm)
			item.save(ignore_permissions=True)
	frappe.db.commit()


DEFAULT_BOARD_TABS = [
	# (label, sequence, include_if_any_job_in_progress, order statuses)
	("In Progress", 1, 1, ["In Progress"]),
	("Awaiting Parts", 2, 0, ["Waiting for Parts"]),
	("Quality Control", 3, 0, ["QC"]),
	("Paused", 4, 0, ["Paused"]),
	("Ready to Start", 5, 0, ["Checked In", "Approved", "Ready for Work"]),
]


def setup_default_board_tabs():
	"""Seeds the default Job Control Board tabs. Idempotent: existing tabs are left untouched."""
	for label, sequence, job_driven, statuses in DEFAULT_BOARD_TABS:
		if frappe.db.exists("Job Board Tab", label):
			continue
		tab = frappe.new_doc("Job Board Tab")
		tab.tab_label = label
		tab.sequence = sequence
		tab.enabled = 1
		tab.include_if_any_job_in_progress = job_driven
		for status in statuses:
			tab.append("order_statuses", {"status": status})
		tab.insert(ignore_permissions=True)
	frappe.db.commit()


def setup_default_settings():
	settings = frappe.get_single("Vehicle Service Settings")
	changed = False
	if not settings.default_qc_template and frappe.db.exists("QC Template", "Standard Workshop QC"):
		settings.default_qc_template = "Standard Workshop QC"
		changed = True
	if not settings.reception_location and frappe.db.exists("Workshop Location", "Reception"):
		settings.reception_location = "Reception"
		changed = True
	if not settings.qc_location and frappe.db.exists("Workshop Location", "QC Area"):
		settings.qc_location = "QC Area"
		changed = True
	if not settings.parking_location and frappe.db.exists("Workshop Location", "Parking"):
		settings.parking_location = "Parking"
		changed = True
	if not settings.collection_location and frappe.db.exists("Workshop Location", "Collection Area"):
		settings.collection_location = "Collection Area"
		changed = True
	if not settings.labour_item and frappe.db.exists("Item", "LABOUR"):
		settings.labour_item = "LABOUR"
		changed = True
	if not settings.labour_rate:
		settings.labour_rate = 50.0
		changed = True
	if changed:
		settings.save(ignore_permissions=True)
		frappe.db.commit()

