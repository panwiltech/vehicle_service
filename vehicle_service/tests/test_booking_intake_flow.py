import frappe
from frappe.tests.utils import FrappeTestCase
from vehicle_service.vehicle_service.doctype.service_booking.service_booking import check_in_booking
from vehicle_service.vehicle_service.doctype.vehicle_intake.vehicle_intake import (
	complete_check_in,
	create_service_order_from_intake,
)

class TestBookingIntakeFlow(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Vehicle Intake", {"vehicle": "BOOK-TEST-001"})
		frappe.db.delete("Service Order", {"vehicle": "BOOK-TEST-001"})
		frappe.db.delete("Service Booking", {"vehicle": "BOOK-TEST-001"})
		frappe.db.delete("Service Vehicle", {"registration_no": "BOOK-TEST-001"})

		if not frappe.db.exists("Customer", "Test Booking Customer"):
			c = frappe.new_doc("Customer")
			c.customer_name = "Test Booking Customer"
			c.customer_type = "Individual"
			c.insert(ignore_permissions=True)

		v = frappe.new_doc("Service Vehicle")
		v.registration_no = "BOOK-TEST-001"
		v.vin = "VINBOOK12345678"
		v.make = "Ford"
		v.model = "Ranger"
		v.year = 2023
		v.customer = "Test Booking Customer"
		v.current_mileage = 15000
		v.insert(ignore_permissions=True)

	def test_check_in_booking_creates_vehicle_intake(self):
		booking = frappe.new_doc("Service Booking")
		booking.vehicle = "BOOK-TEST-001"
		booking.customer = "Test Booking Customer"
		booking.preferred_date = frappe.utils.now_datetime()
		booking.requested_service = "15,000 km routine oil service"
		booking.insert(ignore_permissions=True)

		res = check_in_booking(booking.name)
		self.assertEqual(res["status"], "success")
		self.assertTrue("vehicle_intake" in res, "Expected 'vehicle_intake' in check_in_booking response")

		intake = frappe.get_doc("Vehicle Intake", res["vehicle_intake"])
		self.assertEqual(intake.status, "Draft")
		self.assertEqual(intake.vehicle, "BOOK-TEST-001")
		self.assertEqual(intake.customer, "Test Booking Customer")
		self.assertEqual(intake.booking, booking.name)
		self.assertEqual(intake.customer_complaint, "15,000 km routine oil service")

		# Now complete check-in on intake and create Service Order
		intake.odometer_in = 15200
		intake.customer_signature = "data:image/png;base64,signature_data"
		intake.save(ignore_permissions=True)
		complete_check_in(intake.name)

		order_res = create_service_order_from_intake(intake.name)
		self.assertTrue(bool(order_res["service_order"]))

		booking.reload()
		self.assertEqual(booking.status, "Arrived")
		self.assertEqual(booking.service_order, order_res["service_order"])
