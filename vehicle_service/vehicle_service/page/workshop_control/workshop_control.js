frappe.pages["workshop-control"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Workshop Control"),
		single_column: true,
	});

	frappe.workshop_control = new WorkshopControl(page);
};

class WorkshopControl {
	constructor(page) {
		this.page = page;
		this.filters = {
			bay: "All",
			technician: "All",
			status: "All",
			priority: "All",
			search: "",
		};
		this.auto_refresh = true;
		this.refresh_interval = 30000;
		this.timer = null;

		this.setup_page();
		this.load_data();
		this.start_auto_refresh();
	}

	setup_page() {
		const me = this;
		this.page.clear_actions();

		// Add Primary action for manual refresh
		this.page.set_primary_action(__("Refresh"), () => {
			me.load_data();
		}, "refresh");

		// Auto refresh toggle in page action menu
		this.page.add_inner_button(__("Auto-Refresh: ON"), () => {
			me.toggle_auto_refresh();
		}, __("Refresh Settings"));

		// Main layout container
		this.$container = $(`
			<div class="workshop-control-container">
				<div class="wc-kpi-row" id="wc-kpis"></div>
				<div class="wc-filter-bar" id="wc-filters"></div>
				<div class="wc-table-wrapper">
					<div class="wc-section-header">
						<span><i class="fa fa-cubes"></i> ${__("Active Service Bays")}</span>
						<span class="text-muted text-sm" id="wc-last-updated"></span>
					</div>
					<div class="table-responsive">
						<table class="wc-live-table">
							<thead>
								<tr>
									<th>${__("Bay")}</th>
									<th>${__("Vehicle")}</th>
									<th>${__("Customer")}</th>
									<th>${__("Order #")}</th>
									<th>${__("Active Job")}</th>
									<th>${__("Technician")}</th>
									<th>${__("Status")}</th>
									<th>${__("Live Clock")}</th>
									<th>${__("Est / Act")}</th>
									<th>${__("Parts")}</th>
									<th>${__("Actions")}</th>
								</tr>
							</thead>
							<tbody id="wc-bay-tbody"></tbody>
						</table>
					</div>
				</div>

				<div class="wc-table-wrapper" id="wc-unallocated-section" style="display:none;">
					<div class="wc-section-header">
						<span><i class="fa fa-clock-o"></i> ${__("Unallocated & Staging Orders")}</span>
					</div>
					<div class="table-responsive">
						<table class="wc-live-table">
							<thead>
								<tr>
									<th>${__("Vehicle")}</th>
									<th>${__("Customer")}</th>
									<th>${__("Order #")}</th>
									<th>${__("Location")}</th>
									<th>${__("Status")}</th>
									<th>${__("Parts")}</th>
									<th>${__("Next Action")}</th>
									<th>${__("Actions")}</th>
								</tr>
							</thead>
							<tbody id="wc-unallocated-tbody"></tbody>
						</table>
					</div>
				</div>
			</div>
		`).appendTo(this.page.main);

		this.render_filter_bar();
	}

	render_filter_bar() {
		const me = this;
		const $fb = this.$container.find("#wc-filters");
		$fb.html(`
			<div class="wc-filter-inputs">
				<select id="wc-filter-bay">
					<option value="All">${__("All Bays")}</option>
				</select>
				<select id="wc-filter-status">
					<option value="All">${__("All Statuses")}</option>
					<option value="Draft">${__("Awaiting Approval")}</option>
					<option value="Waiting for Parts">${__("Waiting for Parts")}</option>
					<option value="Ready for Work">${__("Ready for Work")}</option>
					<option value="In Progress">${__("In Progress")}</option>
					<option value="QC">${__("QC")}</option>
					<option value="Ready for Collection">${__("Ready for Collection")}</option>
				</select>
				<select id="wc-filter-priority">
					<option value="All">${__("All Priorities")}</option>
					<option value="Normal">${__("Normal")}</option>
					<option value="Urgent">${__("Urgent")}</option>
					<option value="Breakdown">${__("Breakdown")}</option>
					<option value="VIP">${__("VIP")}</option>
				</select>
				<input type="text" id="wc-filter-search" placeholder="${__("Search Reg, Customer, Order...")}" />
			</div>
			<div class="wc-refresh-controls">
				<span id="wc-timer-indicator"><i class="fa fa-circle text-success wc-pulse-dot"></i> Live</span>
			</div>
		`);

		$fb.find("#wc-filter-status").on("change", function () {
			me.filters.status = $(this).val();
			me.load_data();
		});

		$fb.find("#wc-filter-priority").on("change", function () {
			me.filters.priority = $(this).val();
			me.load_data();
		});

		$fb.find("#wc-filter-bay").on("change", function () {
			me.filters.bay = $(this).val();
			me.load_data();
		});

		let search_timeout;
		$fb.find("#wc-filter-search").on("input", function () {
			clearTimeout(search_timeout);
			const val = $(this).val();
			search_timeout = setTimeout(() => {
				me.filters.search = val;
				me.load_data();
			}, 300);
		});
	}

	load_data() {
		const me = this;
		frappe.call({
			method: "vehicle_service.vehicle_service.page.workshop_control.workshop_control.get_workshop_live_board",
			args: { filters: JSON.stringify(this.filters) },
			callback: function (r) {
				if (r.message) {
					me.render_board(r.message);
				}
			},
		});
	}

	render_board(data) {
		this.render_kpis(data.kpis);
		this.render_bays(data.bays);
		this.render_unallocated(data.unallocated_orders);
		this.update_bay_dropdown(data.bays);
		this.$container.find("#wc-last-updated").text(
			__("Updated: {0}", [frappe.datetime.now_time()])
		);
	}

	render_kpis(kpis) {
		if (!kpis) return;
		const $kpis = this.$container.find("#wc-kpis");
		$kpis.html(`
			<div class="wc-kpi-card">
				<div class="wc-kpi-title">${__("Total Vehicles")}</div>
				<div class="wc-kpi-value">${kpis.total_on_site || 0}</div>
				<div class="wc-kpi-sub">${__("On workshop premises")}</div>
			</div>
			<div class="wc-kpi-card kpi-working">
				<div class="wc-kpi-title">${__("In Progress")}</div>
				<div class="wc-kpi-value">
					<i class="fa fa-wrench text-success"></i> ${kpis.in_progress || 0}
				</div>
				<div class="wc-kpi-sub">${__("Active technician clocks")}</div>
			</div>
			<div class="wc-kpi-card kpi-parts">
				<div class="wc-kpi-title">${__("Waiting Parts")}</div>
				<div class="wc-kpi-value">
					<i class="fa fa-cubes text-warning"></i> ${kpis.waiting_parts || 0}
				</div>
				<div class="wc-kpi-sub">${__("Blocked by parts")}</div>
			</div>
			<div class="wc-kpi-card kpi-qc">
				<div class="wc-kpi-title">${__("In QC")}</div>
				<div class="wc-kpi-value">
					<i class="fa fa-check-circle text-primary"></i> ${kpis.in_qc || 0}
				</div>
				<div class="wc-kpi-sub">${__("Awaiting inspection")}</div>
			</div>
			<div class="wc-kpi-card kpi-ready">
				<div class="wc-kpi-title">${__("Ready for Collection")}</div>
				<div class="wc-kpi-value">
					<i class="fa fa-car text-success"></i> ${kpis.ready_for_collection || 0}
				</div>
				<div class="wc-kpi-sub">${__("Billing / Pickup")}</div>
			</div>
			<div class="wc-kpi-card kpi-util">
				<div class="wc-kpi-title">${__("Bay Utilisation")}</div>
				<div class="wc-kpi-value">${kpis.bay_utilisation || 0}%</div>
				<div class="wc-kpi-sub">${kpis.occupied_bays || 0} / ${kpis.total_bays || 0} ${__("bays")}</div>
			</div>
		`);
	}

	render_bays(bays) {
		const me = this;
		const $tbody = this.$container.find("#wc-bay-tbody");
		$tbody.empty();

		if (!bays || bays.length === 0) {
			$tbody.html(`<tr><td colspan="11" class="text-center text-muted p-4">${__("No bays found matching criteria.")}</td></tr>`);
			return;
		}

		bays.forEach((bay) => {
			if (bay.is_occupied && bay.order) {
				const o = bay.order;
				const status_class = me.get_status_class(o.status);
				const parts_badge = me.get_parts_badge(o.parts_status);
				const clock_html = o.elapsed_str
					? `<span class="font-weight-bold text-success"><i class="fa fa-clock-o wc-pulse-dot"></i> ${o.elapsed_str}</span>`
					: `<span class="text-muted">—</span>`;

				const $row = $(`
					<tr>
						<td><strong>${bay.location_name}</strong></td>
						<td>
							<a href="/app/service-vehicle/${encodeURIComponent(o.vehicle_reg)}"><strong>${o.vehicle_reg}</strong></a>
							<div class="text-muted text-xs">${o.vehicle_model || ""}</div>
						</td>
						<td><a href="/app/customer/${encodeURIComponent(o.customer)}">${o.customer}</a></td>
						<td><a href="/app/service-order/${encodeURIComponent(o.name)}">${o.name}</a></td>
						<td>
							<div><strong>${o.active_job || "—"}</strong></div>
							<div class="text-xs text-muted">${o.job_status || ""}</div>
						</td>
						<td>${o.technician || "—"}</td>
						<td><span class="wc-badge ${status_class}">${o.status}</span></td>
						<td>${clock_html}</td>
						<td>${o.actual_hours} / ${o.estimated_hours} hrs</td>
						<td>${parts_badge}</td>
						<td>
							<div class="wc-action-group">
								${me.render_job_actions(o)}
								<button class="wc-btn-sm btn-move-bay" data-order="${o.name}" data-current="${bay.location_name}" title="${__("Move Bay")}">
									<i class="fa fa-arrows"></i>
								</button>
								<button class="wc-btn-sm btn-assign-tech" data-job="${o.active_job_name}" data-tech="${o.technician}" data-bay="${bay.location_name}" title="${__("Assign")}">
									<i class="fa fa-user"></i>
								</button>
							</div>
						</td>
					</tr>
				`);
				$tbody.append($row);
			} else {
				// Available bay
				const $row = $(`
					<tr class="wc-bay-available">
						<td><strong>${bay.location_name}</strong></td>
						<td colspan="9">
							<span class="text-success"><i class="fa fa-check-circle"></i> ${__("AVAILABLE")}</span>
						</td>
						<td>
							<button class="wc-btn-sm wc-btn-primary-sm btn-quick-allocate" data-bay="${bay.location_name}">
								<i class="fa fa-plus"></i> ${__("Assign Order")}
							</button>
						</td>
					</tr>
				`);
				$tbody.append($row);
			}
		});

		this.bind_table_actions();
	}

	render_job_actions(order) {
		if (order.job_status === "In Progress") {
			return `<button class="wc-btn-sm wc-btn-warning-sm btn-pause-job" data-job="${order.active_job_name}">${__("Pause")}</button>`;
		} else if (order.job_status === "Assigned" || order.job_status === "Paused" || order.job_status === "Ready") {
			return `<button class="wc-btn-sm wc-btn-success-sm btn-start-job" data-job="${order.active_job_name}">${__("Start")}</button>`;
		} else if (order.status === "QC") {
			return `<button class="wc-btn-sm wc-btn-primary-sm btn-goto-qc" data-order="${order.name}">${__("QC")}</button>`;
		}
		return "";
	}

	render_unallocated(orders) {
		const $section = this.$container.find("#wc-unallocated-section");
		const $tbody = this.$container.find("#wc-unallocated-tbody");
		$tbody.empty();

		if (!orders || orders.length === 0) {
			$section.hide();
			return;
		}

		$section.show();
		orders.forEach((o) => {
			const status_class = this.get_status_class(o.status);
			const parts_badge = this.get_parts_badge(o.parts_status);
			const $row = $(`
				<tr>
					<td>
						<a href="/app/service-vehicle/${encodeURIComponent(o.vehicle_reg)}"><strong>${o.vehicle_reg}</strong></a>
						<div class="text-muted text-xs">${o.vehicle_model || ""}</div>
					</td>
					<td><a href="/app/customer/${encodeURIComponent(o.customer)}">${o.customer}</a></td>
					<td><a href="/app/service-order/${encodeURIComponent(o.name)}">${o.name}</a></td>
					<td><span class="text-muted">${o.vehicle_location || __("Unassigned")}</span></td>
					<td><span class="wc-badge ${status_class}">${o.status}</span></td>
					<td>${parts_badge}</td>
					<td><strong>${o.next_action}</strong></td>
					<td>
						<div class="wc-action-group">
							<button class="wc-btn-sm wc-btn-primary-sm btn-move-bay" data-order="${o.name}" data-current="${o.vehicle_location}">
								<i class="fa fa-arrow-right"></i> ${__("Move to Bay")}
							</button>
							<a href="/app/service-order/${encodeURIComponent(o.name)}" class="wc-btn-sm">${__("Open")}</a>
						</div>
					</td>
				</tr>
			`);
			$tbody.append($row);
		});
	}

	bind_table_actions() {
		const me = this;

		// Start job button
		this.$container.find(".btn-start-job").off("click").on("click", function () {
			const job_name = $(this).attr("data-job");
			frappe.call({
				method: "vehicle_service.vehicle_service.page.workshop_control.workshop_control.quick_start_job",
				args: { job_name: job_name },
				callback: function (r) {
					frappe.show_alert({ message: __("Job started"), indicator: "green" });
					me.load_data();
				},
			});
		});

		// Pause job button
		this.$container.find(".btn-pause-job").off("click").on("click", function () {
			const job_name = $(this).attr("data-job");
			const d = new frappe.ui.Dialog({
				title: __("Pause Job"),
				fields: [
					{
						label: __("Reason for Pausing"),
						fieldname: "reason",
						fieldtype: "Select",
						options: "Parts Delay\nCustomer Clarification\nTechnician Break\nEnd of Shift\nSupervisor Reallocation",
						reqd: 1,
					},
				],
				primary_action_label: __("Pause Work"),
				primary_action: function (values) {
					frappe.call({
						method: "vehicle_service.vehicle_service.page.workshop_control.workshop_control.quick_pause_job",
						args: { job_name: job_name, reason: values.reason },
						callback: function () {
							d.hide();
							frappe.show_alert({ message: __("Job paused"), indicator: "orange" });
							me.load_data();
						},
					});
				},
			});
			d.show();
		});

		// Move Bay button
		this.$container.find(".btn-move-bay").off("click").on("click", function () {
			const order_name = $(this).attr("data-order");
			const current_bay = $(this).attr("data-current");

			const d = new frappe.ui.Dialog({
				title: __("Move Vehicle to Bay"),
				fields: [
					{
						label: __("Current Location"),
						fieldname: "from_location",
						fieldtype: "Data",
						default: current_bay,
						read_only: 1,
					},
					{
						label: __("Target Bay"),
						fieldname: "new_location",
						fieldtype: "Link",
						options: "Workshop Location",
						get_query: () => {
							return { filters: { location_type: "Bay", is_active: 1 } };
						},
						reqd: 1,
					},
					{
						label: __("Movement Reason"),
						fieldname: "reason",
						fieldtype: "Data",
						default: "Reallocation in Workshop Control",
					},
				],
				primary_action_label: __("Move"),
				primary_action: function (values) {
					frappe.call({
						method: "vehicle_service.vehicle_service.page.workshop_control.workshop_control.quick_move_bay",
						args: {
							order_name: order_name,
							new_location: values.new_location,
							reason: values.reason,
						},
						callback: function () {
							d.hide();
							frappe.show_alert({ message: __("Vehicle moved successfully"), indicator: "green" });
							me.load_data();
						},
					});
				},
			});
			d.show();
		});

		// Assign Tech button
		this.$container.find(".btn-assign-tech").off("click").on("click", function () {
			const job_name = $(this).attr("data-job");
			const current_tech = $(this).attr("data-tech");
			const current_bay = $(this).attr("data-bay");

			const d = new frappe.ui.Dialog({
				title: __("Assign Technician & Bay"),
				fields: [
					{
						label: __("Technician"),
						fieldname: "technician",
						fieldtype: "Link",
						options: "Employee",
						default: current_tech !== "—" ? current_tech : "",
					},
					{
						label: __("Bay"),
						fieldname: "bay_location",
						fieldtype: "Link",
						options: "Workshop Location",
						default: current_bay,
						get_query: () => {
							return { filters: { location_type: "Bay", is_active: 1 } };
						},
					},
				],
				primary_action_label: __("Save Assignment"),
				primary_action: function (values) {
					frappe.call({
						method: "vehicle_service.vehicle_service.page.workshop_control.workshop_control.quick_assign_technician_bay",
						args: {
							job_name: job_name,
							technician: values.technician,
							bay_location: values.bay_location,
						},
						callback: function () {
							d.hide();
							frappe.show_alert({ message: __("Assignment updated"), indicator: "green" });
							me.load_data();
						},
					});
				},
			});
			d.show();
		});

		// Quick allocate order to available bay
		this.$container.find(".btn-quick-allocate").off("click").on("click", function () {
			const target_bay = $(this).attr("data-bay");
			const d = new frappe.ui.Dialog({
				title: __("Allocate Order to {0}", [target_bay]),
				fields: [
					{
						label: __("Active Service Order"),
						fieldname: "order_name",
						fieldtype: "Link",
						options: "Service Order",
						get_query: () => {
							return {
								filters: {
									status: ["not in", ["Delivered", "Cancelled"]],
								},
							};
						},
						reqd: 1,
					},
				],
				primary_action_label: __("Allocate to Bay"),
				primary_action: function (values) {
					frappe.call({
						method: "vehicle_service.vehicle_service.page.workshop_control.workshop_control.quick_move_bay",
						args: {
							order_name: values.order_name,
							new_location: target_bay,
							reason: "Allocated to empty bay",
						},
						callback: function () {
							d.hide();
							frappe.show_alert({ message: __("Order allocated to {0}", [target_bay]), indicator: "green" });
							me.load_data();
						},
					});
				},
			});
			d.show();
		});

		// Go to QC
		this.$container.find(".btn-goto-qc").off("click").on("click", function () {
			const order_name = $(this).attr("data-order");
			frappe.set_route("Form", "Service Order", order_name);
		});
	}

	update_bay_dropdown(bays) {
		const $select = this.$container.find("#wc-filter-bay");
		const current = $select.val() || "All";
		$select.find("option:not([value='All'])").remove();

		if (bays) {
			bays.forEach((b) => {
				$select.append(`<option value="${b.location_name}">${b.location_name}</option>`);
			});
		}
		$select.val(current);
	}

	get_status_class(status) {
		switch (status) {
			case "Draft":
				return "st-draft";
			case "Approved":
				return "st-approved";
			case "Waiting for Parts":
				return "st-waiting-parts";
			case "Ready for Work":
				return "st-ready-work";
			case "In Progress":
				return "st-in-progress";
			case "QC":
				return "st-qc";
			case "Ready for Collection":
			case "Invoiced":
				return "st-ready-collection";
			default:
				return "st-draft";
		}
	}

	get_parts_badge(status) {
		switch (status) {
			case "Issued":
				return `<span class="wc-badge st-in-progress"><i class="fa fa-check"></i> ${__("Issued")}</span>`;
			case "Shortage":
				return `<span class="wc-badge st-waiting-parts"><i class="fa fa-exclamation-triangle"></i> ${__("Shortage")}</span>`;
			case "Pending Approval":
				return `<span class="wc-badge st-approved"><i class="fa fa-hourglass-start"></i> ${__("Pending")}</span>`;
			default:
				return `<span class="text-muted text-xs">—</span>`;
		}
	}

	start_auto_refresh() {
		const me = this;
		this.timer = setInterval(() => {
			if (me.auto_refresh) {
				me.load_data();
			}
		}, this.refresh_interval);
	}

	toggle_auto_refresh() {
		this.auto_refresh = !this.auto_refresh;
		frappe.show_alert({
			message: this.auto_refresh ? __("Auto-Refresh Enabled (30s)") : __("Auto-Refresh Paused"),
			indicator: this.auto_refresh ? "green" : "orange",
		});
		this.$container.find("#wc-timer-indicator").html(
			this.auto_refresh
				? `<i class="fa fa-circle text-success wc-pulse-dot"></i> Live`
				: `<i class="fa fa-circle text-muted"></i> Paused`
		);
	}
}
