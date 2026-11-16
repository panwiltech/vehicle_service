// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

function _consume_history_route_params() {
	const routeOpts = frappe.route_options || {};
	const urlParams = new URLSearchParams(window.location.search || "");
	const vehicle = routeOpts.vehicle || urlParams.get("vehicle") || "";
	const query = routeOpts.q || urlParams.get("q") || "";
	if (frappe.route_options) {
		delete frappe.route_options.vehicle;
		delete frappe.route_options.q;
	}
	return {
		vehicle: String(vehicle || "").trim(),
		q: String(query || "").trim(),
	};
}

function _sync_history_url(vehicleName) {
	try {
		const url = new URL(window.location.href);
		if (vehicleName) {
			url.searchParams.set("vehicle", vehicleName);
			url.searchParams.delete("q");
		} else {
			url.searchParams.delete("vehicle");
		}
		window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
	} catch (e) {}
}

frappe.pages["vehicle-service-history"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Vehicle Service History"),
		single_column: true,
	});

	page.set_primary_action(
		__("Refresh"),
		() => {
			const view = wrapper._vsh_view;
			if (view && view.vehicle) {
				view.load_vehicle(view.vehicle);
			}
		},
		"refresh"
	);

	const { vehicle, q } = _consume_history_route_params();
	wrapper._vsh_initial_handled = true;

	wrapper._vsh_view = new vehicle_service.VehicleServiceHistoryView({
		parent: page.main,
		vehicle: vehicle || null,
		show_search: true,
		on_vehicle_selected: (vehicleDoc) => {
			const name = vehicleDoc && vehicleDoc.name ? vehicleDoc.name : null;
			_sync_history_url(name);
		},
	});

	if (!vehicle && q) {
		wrapper._vsh_view.search_and_resolve(q);
	}
};

frappe.pages["vehicle-service-history"].on_page_show = function (wrapper) {
	if (!wrapper._vsh_view) return;
	if (wrapper._vsh_initial_handled) {
		wrapper._vsh_initial_handled = false;
		return;
	}
	const { vehicle, q } = _consume_history_route_params();
	if (vehicle) {
		wrapper._vsh_view.load_vehicle(vehicle);
	} else if (q) {
		wrapper._vsh_view.search_and_resolve(q);
	}
};
