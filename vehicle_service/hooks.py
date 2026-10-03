app_name = "vehicle_service"
app_title = "Vehicle Service"
app_publisher = "Azazel"
app_description = "Vehicle service and workshop management on ERPNext"
app_email = "azazel@example.com"
app_license = "mit"

use_json_request_body = True

# Installation and Migration
after_install = "vehicle_service.install.after_install"
after_migrate = "vehicle_service.install.after_migrate"

# Document Events
doc_events = {
	"Stock Entry": {
		"on_submit": "vehicle_service.stock_events.handle_stock_entry_change",
		"on_cancel": "vehicle_service.stock_events.handle_stock_entry_change",
	},
	"Sales Invoice": {
		"on_submit": "vehicle_service.billing_events.handle_sales_invoice_submit",
		"on_cancel": "vehicle_service.billing_events.handle_sales_invoice_cancel",
	},
	"Payment Entry": {
		"on_submit": "vehicle_service.billing_events.handle_payment_entry_submit",
		"on_cancel": "vehicle_service.billing_events.handle_payment_entry_cancel",
	},
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
}

export_python_type_annotations = True
require_type_annotated_api_methods = False
