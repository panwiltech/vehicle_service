// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.pages["job-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Job Control Board"),
		single_column: true,
	});
	frappe.job_control_board = new frappe.vehicle_service.JobControlBoardUI(page.main);
};

frappe.pages["job-board"].on_page_show = function () {
	if (frappe.job_control_board) frappe.job_control_board.refresh();
};
