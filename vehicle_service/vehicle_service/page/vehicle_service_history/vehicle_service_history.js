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

function _set_history_breadcrumbs(page, vehicleDoc, view) {
	if (!page || typeof page.set_breadcrumbs !== "function") return;
	const crumbs = [{ label: __("Vehicle Service"), href: "/desk/vehicle-service" }];
	if (vehicleDoc && vehicleDoc.name) {
		crumbs.push({
			label: __("Vehicle Service History"),
			onclick: () => {
				if (view) view.search_and_resolve("");
			},
		});
		crumbs.push({ label: vehicleDoc.registration_no || vehicleDoc.name });
	} else {
		crumbs.push({ label: __("Vehicle Service History") });
	}
	page.set_breadcrumbs(crumbs);
}

function _update_history_page_header(page, vehicleDoc, view) {
	if (!page) return;
	page.clear_inner_toolbar();

	if (vehicleDoc && vehicleDoc.name) {
		const statusLabel = vehicleDoc.vehicle_status || "Outside Workshop";
		const indicatorColor = view ? view._status_color(statusLabel) : "gray";
		page.set_indicator(__(statusLabel), indicatorColor);

		page.add_inner_button(__("Print / Export PDF"), () => {
			if (view) view.open_export_dialog();
		});
		page.add_inner_button(__("Open Vehicle"), () => {
			frappe.set_route("Form", "Service Vehicle", vehicleDoc.name);
		});
		if (vehicleDoc.current_service_order) {
			page.add_inner_button(__("View Open Service Order"), () => {
				frappe.set_route("Form", "Service Order", vehicleDoc.current_service_order);
			});
		} else if (frappe.model && typeof frappe.model.can_create === "function" && frappe.model.can_create("Service Order")) {
			page.add_inner_button(__("New Service Order"), () => {
				frappe.new_doc("Service Order", {
					vehicle: vehicleDoc.name,
					customer: vehicleDoc.customer,
					driver_name: vehicleDoc.driver_name,
					driver_phone: vehicleDoc.driver_phone,
				});
			});
		}
	} else {
		page.clear_indicator();
	}

	_set_history_breadcrumbs(page, vehicleDoc, view);
}

frappe.pages["vehicle-service-history"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Vehicle Service History"),
		single_column: true,
		card_layout: true,
	});
	page.main.addClass("frappe-card");

	page.set_primary_action(
		__("Refresh"),
		() => {
			if (wrapper.history_view) {
				wrapper.history_view.refresh();
			}
		},
		"refresh"
	);

	const { vehicle, q } = _consume_history_route_params();
	wrapper._vsh_initial_handled = true;

	const view = new vehicle_service.VehicleServiceHistoryView({
		parent: page.main,
		page: page,
		vehicle: vehicle || null,
		show_search: true,
		on_vehicle_selected: (vehicleDoc) => {
			const name = vehicleDoc && vehicleDoc.name ? vehicleDoc.name : null;
			_sync_history_url(name);
			_update_history_page_header(page, vehicleDoc, view);
		},
	});
	wrapper.history_view = view;
	wrapper._vsh_view = view;

	// pageview.js sets a single-item breadcrumb immediately after on_page_load;
	// defer one microtask so the module trail persists cleanly.
	Promise.resolve().then(() => {
		const currentVehicle = view.data && view.data.vehicle ? view.data.vehicle : null;
		_set_history_breadcrumbs(page, currentVehicle, view);
	});

	if (!vehicle && q) {
		view.search_and_resolve(q);
	}
};

frappe.pages["vehicle-service-history"].on_page_show = function (wrapper) {
	const view = wrapper.history_view || wrapper._vsh_view;
	if (!view) return;
	const currentVehicle = view.data && view.data.vehicle ? view.data.vehicle : null;
	_set_history_breadcrumbs(wrapper.page, currentVehicle, view);

	if (wrapper._vsh_initial_handled) {
		wrapper._vsh_initial_handled = false;
		return;
	}
	const { vehicle, q } = _consume_history_route_params();
	if (vehicle) {
		view.load_vehicle(vehicle);
	} else if (q) {
		view.search_and_resolve(q);
	}
};
