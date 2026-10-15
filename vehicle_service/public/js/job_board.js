// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

class JobControlBoardUI {
	constructor($container) {
		this.$container = $container;
		this.tabs = [];
		this.active = null;
		this.current_orders = [];
		this.search_query = "";
		this.refresh_timer = null;

		this.setup_dom();
		this.bind_events();
		this.refresh();
	}

	setup_dom() {
		this.$container.empty();
		this.$body = $(`
			<div class="jcb-container">
				<div class="jcb-top-bar d-flex justify-content-between align-items-center mb-3">
					<div class="d-flex align-items-center" style="gap: 10px;">
						<div class="jcb-search-wrapper position-relative">
							<input type="text" class="form-control input-sm jcb-search-input" placeholder="${__("Search orders, customers, vehicles...")}" style="width: 280px; padding-left: 28px;">
							<svg class="icon icon-xs position-absolute jcb-search-icon" style="left: 8px; top: 50%; transform: translateY(-50%); color: var(--text-muted); pointer-events: none;"><use href="#icon-search"></use></svg>
						</div>
					</div>
					<div class="d-flex align-items-center" style="gap: 8px;">
						<button class="btn btn-default btn-sm jcb-refresh-btn" type="button" title="${__("Refresh")}">
							<svg class="icon icon-xs" style="margin-right: 4px;"><use href="#icon-refresh"></use></svg>${__("Refresh")}
						</button>
						<button class="btn btn-primary btn-sm jcb-new-order-btn" type="button">
							<svg class="icon icon-xs" style="margin-right: 4px;"><use href="#icon-add"></use></svg>${__("New Service Order")}
						</button>
					</div>
				</div>
				<div class="jcb-tabs-wrap">
					<ul class="nav nav-tabs form-tabs jcb-tabs" role="tablist"></ul>
				</div>
				<div class="jcb-content-area"></div>
			</div>
		`).appendTo(this.$container);

		this.$tabs = this.$body.find(".jcb-tabs");
		this.$content = this.$body.find(".jcb-content-area");
		this.$search = this.$body.find(".jcb-search-input");
		this.$refresh_btn = this.$body.find(".jcb-refresh-btn");
		this.$new_order_btn = this.$body.find(".jcb-new-order-btn");

		this.$refresh_btn.on("click", () => this.refresh());
		this.$new_order_btn.on("click", () => frappe.new_doc("Service Order"));

		this.$search.on("input", (e) => {
			this.search_query = (e.target.value || "").trim().toLowerCase();
			this.filter_and_render_table();
		});
	}

	bind_events() {
		if (!window._jcb_realtime_bound) {
			window._jcb_realtime_bound = true;
			frappe.realtime.on("job_board_update", () => {
				if (window._current_jcb_instance) {
					window._current_jcb_instance.schedule_refresh();
				}
			});
		}
		window._current_jcb_instance = this;
	}

	schedule_refresh() {
		clearTimeout(this.refresh_timer);
		this.refresh_timer = setTimeout(() => this.refresh(), 800);
	}

	async refresh() {
		try {
			const r = await frappe.call({ method: "vehicle_service.job_board.get_board_tabs" });
			this.tabs = r.message || [];
			if (!this.tabs.find((t) => t.name === this.active)) {
				this.active = this.tabs.length ? this.tabs[0].name : null;
			}
			this.render_tabs();
			await this.load_orders();
		} catch (e) {
			console.warn("Job Control Board could not load tabs:", e);
		}
	}

	render_tabs() {
		const esc = frappe.utils.escape_html;
		this.$tabs.empty();
		this.tabs.forEach((tab) => {
			const is_active = tab.name === this.active;
			const $t = $(`
				<li class="nav-item jcb-tab-item">
					<button class="nav-link ${is_active ? "active" : ""}"
						id="jcb-tab-${frappe.scrub(tab.name)}" role="tab" type="button">
						<span>${esc(tab.label)}</span>
						<span class="jcb-tab-count badge ${is_active ? "badge-primary" : "badge-light"}" style="margin-left: 6px;">${tab.count}</span>
					</button>
				</li>
			`);
			$t.find(".nav-link").on("click", (e) => {
				e.preventDefault();
				this.active = tab.name;
				this.render_tabs();
				this.load_orders();
			});
			this.$tabs.append($t);
		});
	}

	async load_orders() {
		if (!this.active) {
			this.$content.html(`<div class="text-center text-muted py-5">${__("No tabs configured. Add Job Board Tabs from the desk.")}</div>`);
			return;
		}
		const tab = this.active;
		try {
			const r = await frappe.call({
				method: "vehicle_service.job_board.get_board_orders",
				args: { tab },
			});
			if (tab !== this.active) return;
			this.current_orders = r.message || [];
			this.filter_and_render_table();
		} catch (e) {
			console.warn("Job Control Board could not load orders:", e);
		}
	}

	get_status_indicator_class(status) {
		const s = (status || "").toLowerCase();
		if (s === "in progress" || s === "completed" || s === "closed" || s === "ready for billing") return "green";
		if (s === "waiting for parts" || s === "on hold" || s === "paused") return "orange";
		if (s === "ready for work" || s === "approved" || s === "checked in") return "blue";
		if (s === "qc" || s === "quality control") return "purple";
		if (s === "cancelled") return "red";
		return "gray";
	}

	filter_and_render_table() {
		let orders = this.current_orders;
		if (this.search_query) {
			const q = this.search_query;
			orders = orders.filter((o) => {
				return (
					(o.name && o.name.toLowerCase().includes(q)) ||
					(o.customer_name && o.customer_name.toLowerCase().includes(q)) ||
					(o.vehicle && o.vehicle.toLowerCase().includes(q)) ||
					(o.technicians && o.technicians.toLowerCase().includes(q)) ||
					(o.status && o.status.toLowerCase().includes(q))
				);
			});
		}
		this.render_table(orders);
	}

	render_table(orders) {
		const esc = frappe.utils.escape_html;
		if (!orders.length) {
			const msg = this.search_query
				? __("No matching service orders found.")
				: __("No service orders in this tab.");
			this.$content.html(`
				<div class="text-center text-muted py-5 jcb-empty-state">
					<div class="mb-2"><svg class="icon icon-xl text-muted"><use href="#icon-list"></use></svg></div>
					<div>${msg}</div>
				</div>
			`);
			return;
		}

		let rows_html = "";
		orders.forEach((o) => {
			const pct = o.job_count ? Math.round((o.jobs_completed / o.job_count) * 100) : 0;
			const ind_color = this.get_status_indicator_class(o.status);

			const clock_badge = o.has_running_clock
				? `<span class="badge badge-success" style="font-weight: 500; font-size: 11px;"><span class="indicator green blink" style="margin-right: 3px;"></span>${__("Active")}</span>`
				: `<span class="text-muted text-xs">—</span>`;

			rows_html += `
				<tr class="jcb-row" data-order="${esc(o.name)}" tabindex="0">
					<td class="bold">
						<a class="jcb-order-link" href="/app/service-order/${encodeURIComponent(o.name)}">${esc(o.name)}</a>
					</td>
					<td>
						<span class="jcb-cell-truncate" title="${esc(o.customer_name || "")}">${esc(o.customer_name || "—")}</span>
					</td>
					<td>
						<span class="jcb-cell-truncate" title="${esc(o.vehicle || "")}">${esc(o.vehicle || "—")}</span>
					</td>
					<td>
						<span class="indicator-pill ${ind_color}">${esc(o.status)}</span>
					</td>
					<td>
						<span class="jcb-cell-truncate text-muted" title="${esc(o.technicians || __("Unassigned"))}">${esc(o.technicians || __("Unassigned"))}</span>
					</td>
					<td>
						<div class="d-flex align-items-center" style="gap: 8px;">
							<div class="progress flex-grow-1" style="height: 6px; background-color: var(--border-color); border-radius: 3px; min-width: 50px;">
								<div class="progress-bar ${pct === 100 ? "bg-success" : "bg-primary"}" role="progressbar" style="width: ${pct}%;"></div>
							</div>
							<span class="text-muted text-xs text-nowrap">${o.jobs_completed}/${o.job_count}</span>
						</div>
					</td>
					<td class="text-center">
						${clock_badge}
					</td>
					<td class="text-right">
						<a href="/app/service-order/${encodeURIComponent(o.name)}" class="btn btn-default btn-xs jcb-open-btn" title="${__("Open Order")}">
							${__("Open")} <i class="fa fa-angle-right" style="margin-left: 2px;"></i>
						</a>
					</td>
				</tr>
			`;
		});

		const table_html = `
			<div class="form-grid jcb-table-card">
				<div class="table-responsive">
					<table class="table table-bordered table-hover jcb-table mb-0">
						<thead>
							<tr class="grid-heading-row">
								<th style="width: 14%;">${__("Service Order")}</th>
								<th style="width: 20%;">${__("Customer")}</th>
								<th style="width: 15%;">${__("Vehicle")}</th>
								<th style="width: 13%;">${__("Status")}</th>
								<th style="width: 15%;">${__("Technician(s)")}</th>
								<th style="width: 13%;">${__("Jobs Progress")}</th>
								<th style="width: 10%; text-align: center;">${__("Clock")}</th>
								<th style="width: 8%; text-align: right;">${__("Actions")}</th>
							</tr>
						</thead>
						<tbody class="jcb-tbody">
							${rows_html}
						</tbody>
					</table>
				</div>
			</div>
		`;

		this.$content.html(table_html);

		// Handle row clicks
		this.$content.find(".jcb-row").on("click", (e) => {
			if ($(e.target).closest("a, button").length) return;
			const order_name = $(e.currentTarget).attr("data-order");
			if (order_name) frappe.set_route("Form", "Service Order", order_name);
		}).on("keydown", (e) => {
			if (e.key === "Enter") {
				const order_name = $(e.currentTarget).attr("data-order");
				if (order_name) frappe.set_route("Form", "Service Order", order_name);
			}
		});
	}
}

// Global exposure
frappe.provide("frappe.vehicle_service");
frappe.vehicle_service.JobControlBoardUI = JobControlBoardUI;

// Robust check whether current view is the Job Control Board workspace
function is_on_jcb_workspace() {
	const path = (window.location.pathname || "").toLowerCase();
	if (path.includes("job-control-board")) return true;

	const hash = (window.location.hash || "").toLowerCase();
	if (hash.includes("job-control-board")) return true;

	if (window.frappe) {
		if (frappe.get_route_str) {
			const r = (frappe.get_route_str() || "").toLowerCase();
			if (r.includes("job-control-board") || r.includes("job control board")) return true;
		}
		if (frappe.get_route) {
			const route = frappe.get_route();
			if (Array.isArray(route)) {
				const joined = route.map((s) => String(s).toLowerCase()).join("/");
				if (joined.includes("job-control-board") || joined.includes("job control board")) return true;
			}
		}
		if (frappe.workspace && frappe.workspace.page) {
			const p = (frappe.workspace.page.name || "").toLowerCase();
			if (p.includes("job-control-board") || p.includes("job control board")) return true;
		}
	}
	return false;
}

// Auto-mount into Workspace "Job Control Board"
function check_and_mount_jcb() {
	if (!is_on_jcb_workspace()) {
		$("#jcb-workspace-mount").remove();
		return;
	}

	let $container = null;
	const $ws_page = $('.page-container[data-page-route="Workspaces"]:visible');
	if ($ws_page.length) {
		const $main = $ws_page.find(".layout-main-section");
		if ($main.length) $container = $main;
	}
	if (!$container && frappe.workspace && frappe.workspace.body && frappe.workspace.body.is(":visible")) {
		$container = frappe.workspace.body;
	}
	if (!$container) {
		const $vis = $(".layout-main-section:visible");
		if ($vis.length) $container = $vis;
	}
	if (!$container) {
		const $any_main = $(".layout-main-section");
		if ($any_main.length) $container = $any_main;
	}

	if (!$container || !$container.length) return;

	// Already mounted inside this container
	if ($container.find("#jcb-workspace-mount").length) {
		return;
	}

	// Remove any misplaced mount
	$("#jcb-workspace-mount").remove();

	const $mount = $(`
		<div id="jcb-workspace-mount" style="margin-bottom: var(--margin-lg, 24px); padding-bottom: var(--margin-md, 16px); border-bottom: 1px solid var(--border-color);"></div>
	`);

	const $editor = $container.find(".editor-js-container");
	if ($editor.length) {
		$mount.insertBefore($editor);
	} else {
		$container.prepend($mount);
	}

	new JobControlBoardUI($mount);
}

// Hook into router changes, desk page change, ajax calls, and heartbeat
if (window.frappe && frappe.router) {
	frappe.router.on("change", () => {
		setTimeout(check_and_mount_jcb, 50);
		setTimeout(check_and_mount_jcb, 250);
		setTimeout(check_and_mount_jcb, 600);
	});
}

$(document).on("page-change", () => {
	setTimeout(check_and_mount_jcb, 50);
	setTimeout(check_and_mount_jcb, 250);
});

$(document).ajaxComplete(() => {
	setTimeout(check_and_mount_jcb, 100);
});

if (!window._jcb_mount_interval) {
	window._jcb_mount_interval = setInterval(check_and_mount_jcb, 400);
}

$(document).ready(() => {
	check_and_mount_jcb();
	setTimeout(check_and_mount_jcb, 100);
	setTimeout(check_and_mount_jcb, 300);
	setTimeout(check_and_mount_jcb, 800);
	setTimeout(check_and_mount_jcb, 1500);
});

// Standalone page definition for /app/job-board
frappe.pages["job-board"] = {
	on_page_load: function (wrapper) {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Job Control Board"),
			single_column: true,
		});
		new JobControlBoardUI(page.main);
	},
};
