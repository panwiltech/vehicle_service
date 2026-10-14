frappe.pages["job-control-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Job Control Board"),
		single_column: true,
	});
	frappe.job_control_board = new JobControlBoard(page);
};

frappe.pages["job-control-board"].on_page_show = function () {
	if (frappe.job_control_board) frappe.job_control_board.refresh();
};

class JobControlBoard {
	constructor(page) {
		this.page = page;
		this.tabs = [];
		this.active = null;
		this.refresh_timer = null;

		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.$body = $(`
			<div class="jcb">
				<div class="jcb-tabs" role="tablist"></div>
				<div class="jcb-cards"></div>
			</div>`).appendTo(this.page.main);
		this.$tabs = this.$body.find(".jcb-tabs");
		this.$cards = this.$body.find(".jcb-cards");

		frappe.realtime.on("job_board_update", () => this.schedule_refresh());
		this.refresh();
	}

	schedule_refresh() {
		// Coalesce bursts of realtime events into one reload.
		clearTimeout(this.refresh_timer);
		this.refresh_timer = setTimeout(() => this.refresh(), 800);
	}

	async refresh() {
		const r = await frappe.call({ method: "vehicle_service.job_board.get_board_tabs" });
		this.tabs = r.message || [];
		if (!this.tabs.find((t) => t.name === this.active)) {
			this.active = this.tabs.length ? this.tabs[0].name : null;
		}
		this.render_tabs();
		await this.load_cards();
	}

	render_tabs() {
		const esc = frappe.utils.escape_html;
		this.$tabs.empty();
		this.tabs.forEach((tab) => {
			const $t = $(`
				<button class="jcb-tab ${tab.name === this.active ? "active" : ""}"
					id="jcb-tab-${frappe.scrub(tab.name)}" role="tab" type="button">
					<span class="jcb-tab-label">${esc(tab.label)}</span>
					<span class="jcb-badge">${tab.count}</span>
				</button>`);
			$t.on("click", () => {
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
		const r = await frappe.call({
			method: "vehicle_service.job_board.get_board_orders",
			args: { tab },
		});
		if (tab !== this.active) return; // user switched tabs while loading
		this.render_cards(r.message || []);
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
			const $c = $(`
				<article class="jcb-card" tabindex="0" id="jcb-card-${esc(o.name)}">
					<header class="jcb-card-head">
						<span class="jcb-order">${esc(o.name)}</span>
						${o.has_running_clock ? `<span class="jcb-clock" title="${__("Clock running")}"></span>` : ""}
					</header>
					<div class="jcb-customer">${esc(o.customer_name || "")}</div>
					<div class="jcb-vehicle">${esc(o.vehicle || "")}</div>
					<div class="jcb-tech">${esc(o.technicians || __("Unassigned"))}</div>
					<div class="jcb-progress"><span style="width:${pct}%"></span></div>
					<footer class="jcb-card-foot">
						<span>${o.jobs_completed}/${o.job_count} ${__("jobs done")}</span>
						<span class="jcb-status">${esc(o.status)}</span>
					</footer>
				</article>`);
			const open = () => frappe.set_route("Form", "Service Order", o.name);
			$c.on("click", open).on("keydown", (e) => {
				if (e.key === "Enter") open();
			});
			this.$cards.append($c);
		});
	}
}
