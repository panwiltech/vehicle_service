// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.pages["reports-dashboard"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Reports & Analytics Dashboard"),
		single_column: true,
	});

	new ReportsDashboard(page);
};

class ReportsDashboard {
	constructor(page) {
		this.page = page;
		this.filters = {
			from_date: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			to_date: frappe.datetime.get_today(),
			branch: "",
		};

		this.setup_actions();
		this.setup_filters();
		this.render_containers();
		this.refresh();
	}

	setup_actions() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");

		this.page.add_inner_button(__("Completed Orders Report"), () => {
			frappe.set_route("query-report", "Completed Service Orders", this.get_filter_params());
		}, __("View Reports"));

		this.page.add_inner_button(__("Daily Throughput Report"), () => {
			frappe.set_route("query-report", "Service Order Throughput", this.get_filter_params());
		}, __("View Reports"));
	}

	setup_filters() {
		let me = this;
		this.from_date_field = this.page.add_field({
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: this.filters.from_date,
			change: function () {
				me.filters.from_date = this.get_value();
				me.refresh();
			},
		});

		this.to_date_field = this.page.add_field({
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: this.filters.to_date,
			change: function () {
				me.filters.to_date = this.get_value();
				me.refresh();
			},
		});

		this.branch_field = this.page.add_field({
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
			change: function () {
				me.filters.branch = this.get_value();
				me.refresh();
			},
		});
	}

	get_filter_params() {
		let p = {
			from_date: this.filters.from_date,
			to_date: this.filters.to_date,
		};
		if (this.filters.branch) {
			p.branch = this.filters.branch;
		}
		return p;
	}

	render_containers() {
		this.page.main.empty();
		this.$container = $('<div class="reports-dashboard-container"></div>').appendTo(this.page.main);
		this.$kpi_grid = $('<div class="kpi-cards-grid"></div>').appendTo(this.$container);

		// Throughput chart container
		this.$throughput_chart_card = $(`
			<div class="chart-card mb-4">
				<div class="chart-card-header">
					<span>${__("Workshop Daily Throughput: Received vs Completed")}</span>
				</div>
				<div id="chart-throughput" style="min-height: 280px;"></div>
			</div>
		`).appendTo(this.$container);

		// Two-column charts container (WIP Valuation + Tech Productivity)
		this.$two_col_charts = $('<div class="charts-grid-two-col"></div>').appendTo(this.$container);

		this.$wip_chart_card = $(`
			<div class="chart-card">
				<div class="chart-card-header">
					<span>${__("Active WIP Valuation by Branch")}</span>
				</div>
				<div id="chart-wip" style="min-height: 280px;"></div>
			</div>
		`).appendTo(this.$two_col_charts);

		this.$tech_chart_card = $(`
			<div class="chart-card">
				<div class="chart-card-header">
					<span>${__("Technician Productivity (Units Sold vs Actual Hours)")}</span>
				</div>
				<div id="chart-technician" style="min-height: 280px;"></div>
			</div>
		`).appendTo(this.$two_col_charts);
	}

	refresh() {
		let me = this;
		frappe.call({
			method: "vehicle_service.vehicle_service.page.reports_dashboard.reports_dashboard.get_dashboard_data",
			args: {
				filters: JSON.stringify(this.filters),
			},
			freeze: true,
			freeze_message: __("Loading reports & analytics..."),
			callback: function (r) {
				if (r.message) {
					me.render_kpi_cards(r.message.cards || []);
					me.render_charts(r.message.charts || {});
				}
			},
		});
	}

	render_kpi_cards(cards) {
		let me = this;
		this.$kpi_grid.empty();

		cards.forEach((card) => {
			let icon_html = frappe.utils.icon(card.icon || "file-text", "sm");
			let $card = $(`
				<div class="kpi-card" data-report="${card.report || ""}">
					<div class="kpi-header">
						<span class="kpi-title">${card.title}</span>
						<div class="kpi-icon ${card.color || "blue"}">${icon_html}</div>
					</div>
					<div class="kpi-value">${card.value}</div>
					<div class="kpi-subtitle">${card.subtitle}</div>
				</div>
			`);

			$card.on("click", function () {
				let rep = $(this).attr("data-report");
				if (rep) {
					frappe.set_route("query-report", rep, me.get_filter_params());
				}
			});

			me.$kpi_grid.append($card);
		});
	}

	render_charts(charts) {
		if (charts.throughput && charts.throughput.data && charts.throughput.data.labels.length) {
			this.throughput_chart = new frappe.Chart("#chart-throughput", {
				data: charts.throughput.data,
				type: "line",
				height: 280,
				colors: charts.throughput.colors,
				lineOptions: { hideDots: 0, regionFill: 1 },
				axisOptions: { xIsSeries: 1 },
			});
		}

		if (charts.wip && charts.wip.data && charts.wip.data.labels.length) {
			this.wip_chart = new frappe.Chart("#chart-wip", {
				data: charts.wip.data,
				type: "bar",
				height: 280,
				colors: charts.wip.colors,
				barOptions: { stacked: 1 },
			});
		}

		if (charts.technician && charts.technician.data && charts.technician.data.labels.length) {
			this.tech_chart = new frappe.Chart("#chart-technician", {
				data: charts.technician.data,
				type: "bar",
				height: 280,
				colors: charts.technician.colors,
			});
		}
	}
}
