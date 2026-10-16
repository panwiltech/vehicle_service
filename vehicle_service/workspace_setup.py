"""Production workspace and Desk setup utility for Vehicle Service and ERPNext."""

import frappe

VEHICLE_SERVICE_WORKSPACES = [
	{
		"name": "Vehicle Service",
		"file": "vehicle_service",
		"icon": "car",
		"sequence_id": 1.0,
		"parent_page": "",
		"indicator_color": "blue",
		"is_hidden": 0,
	},
	{
		"name": "Service Advisor",
		"file": "service_advisor",
		"icon": "clipboard-list",
		"sequence_id": 1.1,
		"parent_page": "Vehicle Service",
		"indicator_color": "orange",
		"is_hidden": 0,
	},
	{
		"name": "Job Control Board",
		"file": "job_control_board",
		"icon": "circle-gauge",
		"sequence_id": 1.2,
		"parent_page": "Vehicle Service",
		"indicator_color": "blue",
		"is_hidden": 0,
	},
	{
		"name": "Technician Portal",
		"file": "technician",
		"icon": "wrench",
		"sequence_id": 1.3,
		"parent_page": "Vehicle Service",
		"indicator_color": "green",
		"is_hidden": 0,
	},
	{
		"name": "Quality Control",
		"file": "service_qc",
		"icon": "clipboard-check",
		"sequence_id": 1.4,
		"parent_page": "Vehicle Service",
		"indicator_color": "purple",
		"is_hidden": 0,
	},
	{
		"name": "Parts Store",
		"file": "parts_store",
		"icon": "package",
		"sequence_id": 1.5,
		"parent_page": "Vehicle Service",
		"indicator_color": "yellow",
		"is_hidden": 0,
	},
]

CORE_ERPNEXT_WORKSPACES = {
	"Invoicing": {
		"sequence_id": 2.0,
		"icon": "accounting",
		"parent_page": "",
		"is_hidden": 0,
		"indicator_color": "blue",
	},
	"Financial Reports": {
		"sequence_id": 2.1,
		"icon": "table",
		"parent_page": "Invoicing",
		"is_hidden": 0,
		"indicator_color": "cyan",
	},
	"Stock": {
		"sequence_id": 3.0,
		"icon": "stock",
		"parent_page": "",
		"is_hidden": 0,
		"indicator_color": "orange",
	},
	"Buying": {
		"sequence_id": 4.0,
		"icon": "buying",
		"parent_page": "",
		"is_hidden": 0,
		"indicator_color": "green",
	},
	"Selling": {
		"sequence_id": 5.0,
		"icon": "sell",
		"parent_page": "",
		"is_hidden": 0,
		"indicator_color": "yellow",
	},
	"ERPNext Settings": {
		"sequence_id": 6.0,
		"icon": "setting",
		"parent_page": "",
		"is_hidden": 0,
		"indicator_color": "grey",
	},
}

HIDDEN_WORKSPACES = [
	"Manufacturing",
	"Subcontracting",
	"Quality",
	"Projects",
	"Support",
	"Website",
	"Build",
	"Email",
	"Automation",
	"Printing",
	"System",
	"Users",
	"Integrations",
	"Assets",
	"CRM",
]


def setup_production_workspaces():
	"""Synchronizes Vehicle Service and ERPNext workspaces for production readiness."""
	frappe.flags.in_patch = True

	# 1. Reload and synchronize Vehicle Service workspaces from JSON files
	for ws_conf in VEHICLE_SERVICE_WORKSPACES:
		ws_name = ws_conf["name"]
		file_name = ws_conf["file"]
		try:
			frappe.reload_doc("vehicle_service", "workspace", file_name, force=True)
		except Exception as e:
			frappe.logger("vehicle_service").warning(f"Could not reload workspace {file_name}: {e}")

		if frappe.db.exists("Workspace", ws_name):
			frappe.db.set_value(
				"Workspace",
				ws_name,
				{
					"parent_page": ws_conf["parent_page"],
					"sequence_id": ws_conf["sequence_id"],
					"icon": ws_conf["icon"],
					"indicator_color": ws_conf["indicator_color"],
					"is_hidden": ws_conf["is_hidden"],
					"public": 1,
				},
				update_modified=False,
			)

	# 2. Configure Core ERPNext Workspaces
	for ws_name, conf in CORE_ERPNEXT_WORKSPACES.items():
		if frappe.db.exists("Workspace", ws_name):
			update_dict = {
				"sequence_id": conf["sequence_id"],
				"is_hidden": conf["is_hidden"],
				"parent_page": conf["parent_page"],
			}
			if conf.get("icon"):
				update_dict["icon"] = conf["icon"]
			if conf.get("indicator_color"):
				update_dict["indicator_color"] = conf["indicator_color"]

			frappe.db.set_value("Workspace", ws_name, update_dict, update_modified=False)

	# 3. Hide clutter / non-essential workspaces
	for ws_name in HIDDEN_WORKSPACES:
		if frappe.db.exists("Workspace", ws_name):
			frappe.db.set_value("Workspace", ws_name, "is_hidden", 1, update_modified=False)

	frappe.db.commit()
	frappe.clear_cache()
	print("Production workspaces setup completed successfully.")
