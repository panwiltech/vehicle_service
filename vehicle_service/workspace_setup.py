"""Production workspace and Desk setup utility for Vehicle Service."""

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


def setup_production_workspaces():
	"""Synchronizes Vehicle Service workspaces for production readiness."""
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

	# 2. Reload and sync standard Vehicle Service Sidebar
	try:
		frappe.reload_doc("vehicle_service", "sidebar", "vehicle_service", force=True)
	except Exception as e:
		frappe.logger("vehicle_service").warning(f"Could not reload sidebar vehicle_service: {e}")

	# 3. Configure Dock for Vehicle Service
	vs_dock_items = [
		{"link_type": "Workspace", "link_to": "Vehicle Service", "icon": "car", "title": "Vehicle Service"},
		{"link_type": "Workspace", "link_to": "Job Control Board", "icon": "folder-kanban", "title": "Job Control Board"},
		{"link_type": "Sidebar", "link_to": "CRM", "icon": "handshake-soft", "title": "CRM"},
	]
	if not frappe.db.exists("Dock", "vehicle_service"):
		d = frappe.new_doc("Dock")
		d.name = "vehicle_service"
		d.app = "vehicle_service"
		d.standard = 1
		for it in vs_dock_items:
			d.append("items", it)
		d.insert(ignore_permissions=True)
	else:
		d = frappe.get_doc("Dock", "vehicle_service")
		d.items = []
		for it in vs_dock_items:
			d.append("items", it)
		d.save(ignore_permissions=True)

	# Ensure CRM in erpnext Dock is unhidden
	if frappe.db.exists("Dock", "erpnext"):
		erpnext_dock = frappe.get_doc("Dock", "erpnext")
		crm_updated = False
		for item in erpnext_dock.items:
			if item.link_to == "CRM" and item.hidden:
				item.hidden = 0
				crm_updated = True
		if crm_updated:
			erpnext_dock.save(ignore_permissions=True)

	# 3. Configure Desktop Settings & Desktop Icons (Grid layout on Desk)
	if frappe.db.exists("DocType", "Desktop Settings"):
		frappe.db.set_single_value("Desktop Settings", "desktop_page", "Desktop Icons")

	sub_pages_to_hide = [
		"Accounts Setup",
		"Organization",
		"Share Management",
		"Banking",
		"Taxes",
		"Budget",
		"Subscription",
		"Data",
		"Home",
		"Payments",
		"Financial Reports",
		"ERPNext",
		"Framework",
		"Frappe Framework",
	]
	for label in sub_pages_to_hide:
		if frappe.db.exists("Desktop Icon", label):
			frappe.db.set_value("Desktop Icon", label, "hidden", 1, update_modified=False)

	if frappe.db.exists("Desktop Icon", "Vehicle Service"):
		frappe.db.set_value(
			"Desktop Icon",
			"Vehicle Service",
			{
				"icon_type": "Link",
				"link_type": "Workspace Sidebar",
				"link_to": "Vehicle Service",
				"icon": "car",
				"parent_icon": None,
				"hidden": 0,
			},
			update_modified=False,
		)

	if not frappe.db.exists("Desktop Icon", "CRM"):
		crm_icon = frappe.new_doc("Desktop Icon")
		crm_icon.name = "CRM"
		crm_icon.label = "CRM"
		crm_icon.icon_type = "Link"
		crm_icon.link_type = "Workspace Sidebar"
		crm_icon.link_to = "CRM"
		crm_icon.icon = "handshake"
		crm_icon.hidden = 0
		crm_icon.parent_icon = None
		crm_icon.app = "erpnext"
		crm_icon.insert(ignore_permissions=True)

	primary_workspaces = [
		("Vehicle Service", "car"),
		("Job Control Board", "circle-gauge"),
		("CRM", "handshake"),
		("Service Advisor", "clipboard-list"),
		("Technician Portal", "wrench"),
		("Quality Control", "clipboard-check"),
		("Parts Store", "package"),
		("Accounting", "landmark"),
		("Invoicing", "wallet"),
		("Selling", "store"),
		("Buying", "shopping-cart"),
		("Stock", "package"),
		("Manufacturing", "building-complex"),
		("Subcontracting", "organization"),
		("Projects", "folder-kanban"),
		("Assets", "archive"),
		("Quality", "shield-check"),
		("Support", "headset"),
		("ERPNext Settings", "sliders-horizontal"),
		("Users", "users"),
		("Integrations", "cable"),
		("Automation", "repeat"),
		("Printing", "printer"),
		("Email", "mail"),
		("System", "monitor-check"),
		("Website", "app-window"),
		("Build", "hammer"),
	]

	for idx, (label, icon) in enumerate(primary_workspaces, 1):
		if frappe.db.exists("Desktop Icon", label):
			frappe.db.set_value(
				"Desktop Icon",
				label,
				{
					"idx": idx,
					"hidden": 0,
					"parent_icon": None,
					"icon": icon,
				},
				update_modified=False,
			)

	from frappe.desk.doctype.desktop_icon.desktop_icon import clear_every_users_desktop_icons

	clear_every_users_desktop_icons()
	frappe.db.commit()
	frappe.clear_cache()
	print("Vehicle Service production workspaces setup completed successfully.")

