app_name = "vehicle_service"
app_title = "Vehicle Service"
app_publisher = "Azazel"
app_description = "Vehicle service and workshop management on ERPNext"
app_email = "azazel@example.com"
app_license = "mit"

app_logo_url = "/assets/vehicle_service/images/vehicle-service-logo.svg"
app_home = "/desk/vehicle-service"

add_to_apps_screen = [
	{
		"name": "vehicle_service",
		"logo": "/assets/vehicle_service/images/vehicle-service-logo.svg",
		"title": "Vehicle Service",
		"route": "/desk/vehicle-service",
	}
]

use_json_request_body = True

# Installation and Migration
after_install = "vehicle_service.install.after_install"
after_migrate = "vehicle_service.install.after_migrate"
extend_bootinfo = "vehicle_service.boot.extend_bootinfo"

app_include_js = "/assets/vehicle_service/js/job_board.js?v=20261023-1"
app_include_css = "/assets/vehicle_service/css/job_board.css?v=20261023-1"

# Document Events
doc_events = {
	"Service Order": {
		"on_update": "vehicle_service.job_board.publish_board_update",
	},
	"Service Job": {
		"on_update": "vehicle_service.job_board.publish_board_update",
	},
	"Quotation": {
		"on_update": "vehicle_service.vehicle_service.doctype.service_order.service_order.sync_quotation_to_service_order",
		"on_submit": "vehicle_service.vehicle_service.doctype.service_order.service_order.on_quotation_submit",
	},
	"Stock Entry": {
		"on_submit": "vehicle_service.stock_events.handle_stock_entry_change",
		"on_cancel": "vehicle_service.stock_events.handle_stock_entry_change",
	},
	"Sales Invoice": {
		"validate": "vehicle_service.billing_events.validate_sales_invoice",
		"before_submit": "vehicle_service.billing_events.validate_sales_invoice",
		"on_submit": "vehicle_service.billing_events.handle_sales_invoice_submit",
		"on_cancel": "vehicle_service.billing_events.handle_sales_invoice_cancel",
	},
	"Payment Entry": {
		"on_submit": "vehicle_service.billing_events.handle_payment_entry_submit",
		"on_cancel": "vehicle_service.billing_events.handle_payment_entry_cancel",
	},
}

has_permission = {
	"Service Order": "vehicle_service.job_control.order_has_permission",
}

# Scheduled Tasks
scheduler_events = {
	"daily": [
		"vehicle_service.tasks.daily"
	]
}

# DocType JS
doctype_js = {
	"Service Order": "public/js/service_order.js",
	"Service Job": "public/js/service_job.js",
	"Service Vehicle": "public/js/service_vehicle.js",
	"Service Booking": "public/js/service_booking.js",
	"Sales Invoice": "public/js/sales_invoice.js",
}

export_python_type_annotations = True
require_type_annotated_api_methods = False
