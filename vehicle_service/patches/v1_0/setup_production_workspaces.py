import frappe
from vehicle_service.workspace_setup import setup_production_workspaces

def execute():
	setup_production_workspaces()
