// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

class JobControlBoardUI {
	constructor($container) {
		this.$container = $container;
		this.tabs = [];
		this.active = null;
		this.refresh_timer = null;

		this.setup_dom();
		this.bind_events();
		this.refresh();
	}

	setup_dom() {
		this.$container.empty();
		this.$body = $(`
			<div class="jcb">
				<div class="jcb-header d-flex justify-content-between align-items-center mb-3">
					<h5 class="jcb-title">${__("Job Control Board")}</h5>
					<button class="btn btn-default btn-xs jcb-refresh-btn" type="button">
						<svg class="icon icon-xs" style="margin-right: 4px;"><use href="#icon-refresh"></use></svg>${__("Refresh")}
					</button>
				</div>
				<div class="jcb-tabs-wrap">
					<ul class="nav nav-tabs form-tabs jcb-tabs" role="tablist"></ul>
				</div>
				<div class="jcb-cards"></div>
			</div>
		`).appendTo(this.$container);

		this.$tabs = this.$body.find(".jcb-tabs");
		this.$cards = this.$body.find(".jcb-cards");
		this.$refresh_btn = this.$body.find(".jcb-refresh-btn");

		this.$refresh_btn.on("click", () => this.refresh());
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
			await this.load_cards();
		} catch (e) {
			// Permission or connection error
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
						<span class="jcb-tab-count">${tab.count}</span>
					</button>
				</li>
			`);
			$t.find(".nav-link").on("click", (e) => {
				e.preventDefault();
				this.active = tab.name;
				this.render_tabs();
				this.load_cards();
			});
			this.$tabs.append($t);
		});
	}

	async load_cards() {
		if (!this.active) {
			this.$cards.html(`<div class="jcb-empty">${__("No tabs configured. Add Job Board Tabs from the desk.")}</div>`);
			return;
		}
		const tab = this.active;
		try {
			const r = await frappe.call({
				method: "vehicle_service.job_board.get_board_orders",
				args: { tab },
			});
			if (tab !== this.active) return; // user switched tabs while loading
			this.render_cards(r.message || []);
		} catch (e) {
			console.warn("Job Control Board could not load orders:", e);
		}
	}

	get_status_indicator_class(status) {
		const s = (status || "").toLowerCase();
		if (s === "in progress" || s === "completed" || s === "closed") return "green";
		if (s === "waiting for parts" || s === "on hold" || s === "paused") return "orange";
		if (s === "ready for work" || s === "approved" || s === "checked in") return "blue";
		if (s === "qc" || s === "quality control") return "purple";
		if (s === "cancelled") return "red";
		return "gray";
	}

	render_cards(orders) {
		const esc = frappe.utils.escape_html;
		if (!orders.length) {
			this.$cards.html(`<div class="jcb-empty">${__("No service orders in this tab.")}</div>`);
			return;
		}
		this.$cards.empty();
		orders.forEach((o) => {
			const pct = o.job_count ? Math.round((o.jobs_completed / o.job_count) * 100) : 0;
			const ind_color = this.get_status_indicator_class(o.status);
			const $c = $(`
				<article class="jcb-card" tabindex="0" id="jcb-card-${esc(o.name)}">
					<div>
						<header class="jcb-card-head">
							<a class="jcb-order-link" href="/app/service-order/${encodeURIComponent(o.name)}">${esc(o.name)}</a>
							${o.has_running_clock ? `<span class="indicator green blink" title="${__("Active clock running")}"></span>` : ""}
						</header>
						<div class="jcb-customer-name">${esc(o.customer_name || "")}</div>
						<div class="jcb-meta-text">${esc(o.vehicle || "")}</div>
						<div class="jcb-meta-text">${esc(o.technicians || __("Unassigned"))}</div>
					</div>
					<div>
						<div class="jcb-progress-bar">
							<div class="jcb-progress-fill" style="width: ${pct}%"></div>
						</div>
						<footer class="jcb-card-footer">
							<span class="jobs-done">${o.jobs_completed}/${o.job_count} ${__("jobs done")}</span>
							<span class="indicator-pill ${ind_color}">${esc(o.status)}</span>
						</footer>
					</div>
				</article>`);
			const open = (e) => {
				if ($(e.target).closest("a").length) return;
				frappe.set_route("Form", "Service Order", o.name);
			};
			$c.on("click", open).on("keydown", (e) => {
				if (e.key === "Enter") frappe.set_route("Form", "Service Order", o.name);
			});
			this.$cards.append($c);
		});
	}
}

// Global exposure
frappe.provide("frappe.vehicle_service");
frappe.vehicle_service.JobControlBoardUI = JobControlBoardUI;

// Auto-mount into Workspace "Job Control Board"
function try_mount_jcb_in_workspace() {
	const route = frappe.get_route ? frappe.get_route() : [];
	const is_jcb_workspace = (
		(route[0] === "Workspaces" && (route[1] === "Job Control Board" || route[1] === "job-control-board")) ||
		(route[0] === "job-control-board")
	);

	if (!is_jcb_workspace) {
		$("#jcb-workspace-mount").remove();
		return;
	}

	const $main = $(".layout-main-section");
	if (!$main.length) {
		setTimeout(try_mount_jcb_in_workspace, 150);
		return;
	}

	if (!$("#jcb-workspace-mount").length) {
		const $mount = $(`
			<div id="jcb-workspace-mount" style="margin-bottom: var(--margin-lg, 24px); padding-bottom: var(--margin-md, 16px); border-bottom: 1px solid var(--border-color);"></div>
		`);
		// Prepend to main section so it appears right above the workspace widgets
		$main.prepend($mount);
		new JobControlBoardUI($mount);
	}
}

// Hook into route changes & page load
$(document).ready(() => {
	if (frappe.router) {
		frappe.router.on("change", () => {
			setTimeout(try_mount_jcb_in_workspace, 100);
		});
	}
	setTimeout(try_mount_jcb_in_workspace, 200);
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
	}
};
