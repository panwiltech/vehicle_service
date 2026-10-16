import frappe


def extend_bootinfo(bootinfo):
	"""Customize Desk launcher icons to display primary business modules directly on the desk."""
	# Ensure desktop_page is Apps
	bootinfo.desktop_page = "Apps"

	# Build clean, direct launcher cards for the requested primary modules
	primary_desk_apps = [
		{
			"on_apps_screen": True,
			"sequence_id": 1,
			"app_name": "accounts",
			"app_title": "Accounts",
			"app_route": "/desk/accounting",
			"desk_route": "",
			"app_logo_url": "/assets/erpnext/desktop_icons/accounting.svg",
			"dock": [],
		},
		{
			"on_apps_screen": True,
			"sequence_id": 2,
			"app_name": "selling",
			"app_title": "Selling",
			"app_route": "/desk/selling",
			"desk_route": "",
			"app_logo_url": "/assets/erpnext/desktop_icons/selling.svg",
			"dock": [],
		},
		{
			"on_apps_screen": True,
			"sequence_id": 3,
			"app_name": "buying",
			"app_title": "Buying",
			"app_route": "/desk/buying",
			"desk_route": "",
			"app_logo_url": "/assets/erpnext/desktop_icons/buying.svg",
			"dock": [],
		},
		{
			"on_apps_screen": True,
			"sequence_id": 4,
			"app_name": "stock",
			"app_title": "Stock",
			"app_route": "/desk/stock",
			"desk_route": "",
			"app_logo_url": "/assets/erpnext/desktop_icons/stock.svg",
			"dock": [],
		},
		{
			"on_apps_screen": True,
			"sequence_id": 5,
			"app_name": "vehicle_service",
			"app_title": "Vehicle Service",
			"app_route": "/desk/vehicle-service",
			"desk_route": "",
			"app_logo_url": "/assets/vehicle_service/images/vehicle-service-logo.svg",
			"dock": [],
		},
	]

	bootinfo.app_data = primary_desk_apps
