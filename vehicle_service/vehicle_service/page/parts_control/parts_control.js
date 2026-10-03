frappe.pages["parts-control"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Parts Control"),
		single_column: true,
	});

	frappe.parts_control = new PartsControl(page);
};

class PartsControl {
	constructor(page) {
		this.page = page;
		this.active_tab = "to-issue";
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

		this.page.set_primary_action(__("Refresh"), () => {
			me.load_data();
		}, "refresh");

		this.page.add_inner_button(__("Auto-Refresh: ON"), () => {
			me.toggle_auto_refresh();
		}, __("Refresh Settings"));

		this.$container = $(`
			<div class="parts-control-container">
				<div class="pc-kpi-row" id="pc-kpis"></div>

				<div class="pc-nav-tabs">
					<button class="pc-tab-btn active" data-tab="to-issue">
						<i class="fa fa-hand-lizard-o"></i> ${__("To Issue")}
						<span class="pc-tab-count" id="count-to-issue">0</span>
					</button>
					<button class="pc-tab-btn" data-tab="in-wip">
						<i class="fa fa-wrench"></i> ${__("Issued in WIP")}
						<span class="pc-tab-count" id="count-in-wip">0</span>
					</button>
					<button class="pc-tab-btn" data-tab="subs">
						<i class="fa fa-exchange"></i> ${__("Substitutions Pending")}
						<span class="pc-tab-count" id="count-subs">0</span>
					</button>
					<button class="pc-tab-btn" data-tab="shortages">
						<i class="fa fa-exclamation-triangle text-danger"></i> ${__("Stock Shortages")}
						<span class="pc-tab-count" id="count-shortages">0</span>
					</button>
				</div>

				<div class="pc-tab-panel active" id="panel-to-issue">
					<div class="pc-table-wrapper table-responsive">
						<table class="pc-table">
							<thead>
								<tr>
									<th>${__("Order #")}</th>
									<th>${__("Customer")}</th>
									<th>${__("Job")}</th>
									<th>${__("Part Details")}</th>
									<th>${__("Qty Req")}</th>
									<th>${__("Qty Iss")}</th>
									<th>${__("Qty Left")}</th>
									<th>${__("Stock")}</th>
									<th>${__("Action")}</th>
								</tr>
							</thead>
							<tbody id="pc-to-issue-tbody"></tbody>
						</table>
					</div>
				</div>

				<div class="pc-tab-panel" id="panel-in-wip">
					<div class="pc-table-wrapper table-responsive">
						<table class="pc-table">
							<thead>
								<tr>
									<th>${__("Order #")}</th>
									<th>${__("Bay")}</th>
									<th>${__("Job & Tech")}</th>
									<th>${__("Part Details")}</th>
									<th>${__("Issued")}</th>
									<th>${__("Returned")}</th>
									<th>${__("Current WIP")}</th>
									<th>${__("Action")}</th>
								</tr>
							</thead>
							<tbody id="pc-in-wip-tbody"></tbody>
						</table>
					</div>
				</div>

				<div class="pc-tab-panel" id="panel-subs">
					<div class="pc-table-wrapper table-responsive">
						<table class="pc-table">
							<thead>
								<tr>
									<th>${__("Sub ID")}</th>
									<th>${__("Order #")}</th>
									<th>${__("Original Part")}</th>
									<th>${__("Proposed Substitute")}</th>
									<th>${__("Reason")}</th>
									<th>${__("Requested By")}</th>
									<th>${__("Action")}</th>
								</tr>
							</thead>
							<tbody id="pc-subs-tbody"></tbody>
						</table>
					</div>
				</div>

				<div class="pc-tab-panel" id="panel-shortages">
					<div class="pc-table-wrapper table-responsive">
						<table class="pc-table">
							<thead>
								<tr>
									<th>${__("Item Code")}</th>
									<th>${__("Item Name")}</th>
									<th>${__("Total Required")}</th>
									<th>${__("In Stock")}</th>
									<th>${__("Shortfall")}</th>
									<th>${__("Orders Affected")}</th>
									<th>${__("Action")}</th>
								</tr>
							</thead>
							<tbody id="pc-shortages-tbody"></tbody>
						</table>
					</div>
				</div>
			</div>
		`).appendTo(this.page.main);

		this.bind_tab_switching();
	}

	bind_tab_switching() {
		const me = this;
		this.$container.find(".pc-tab-btn").on("click", function () {
			const target = $(this).attr("data-tab");
			me.$container.find(".pc-tab-btn").removeClass("active");
			$(this).addClass("active");

			me.$container.find(".pc-tab-panel").removeClass("active");
			me.$container.find("#panel-" + target).addClass("active");
			me.active_tab = target;
		});
	}

	load_data() {
		const me = this;
		frappe.call({
			method: "vehicle_service.vehicle_service.page.parts_control.parts_control.get_parts_control_board",
			callback: function (r) {
				if (r.message) {
					me.render_board(r.message);
				}
			},
		});
	}

	render_board(data) {
		this.render_kpis(data.kpis);
		this.render_to_issue(data.to_issue);
		this.render_in_wip(data.in_wip);
		this.render_substitutions(data.substitutions);
		this.render_shortages(data.shortages);
	}

	render_kpis(kpis) {
		if (!kpis) return;
		this.$container.find("#count-to-issue").text(kpis.lines_to_pick || 0);
		this.$container.find("#count-in-wip").text(kpis.lines_in_wip || 0);
		this.$container.find("#count-subs").text(kpis.pending_substitutions || 0);
		this.$container.find("#count-shortages").text(kpis.critical_shortages || 0);

		this.$container.find("#pc-kpis").html(`
			<div class="pc-kpi-card kpi-pick">
				<div class="pc-kpi-title">${__("Lines to Pick")}</div>
				<div class="pc-kpi-value">${kpis.lines_to_pick || 0}</div>
				<div class="pc-kpi-sub">${__("Approved for issue")}</div>
			</div>
			<div class="pc-kpi-card kpi-wip">
				<div class="pc-kpi-title">${__("Parts in WIP")}</div>
				<div class="pc-kpi-value">${kpis.lines_in_wip || 0}</div>
				<div class="pc-kpi-sub">${__("Issued to bays")}</div>
			</div>
			<div class="pc-kpi-card kpi-sub">
				<div class="pc-kpi-title">${__("Substitutions")}</div>
				<div class="pc-kpi-value">${kpis.pending_substitutions || 0}</div>
				<div class="pc-kpi-sub">${__("Awaiting approval")}</div>
			</div>
			<div class="pc-kpi-card kpi-shortage">
				<div class="pc-kpi-title">${__("Stock Shortages")}</div>
				<div class="pc-kpi-value text-danger">${kpis.critical_shortages || 0}</div>
				<div class="pc-kpi-sub">${__("Lines blocking work")}</div>
			</div>
		`);
	}

	render_to_issue(items) {
		const me = this;
		const $tbody = this.$container.find("#pc-to-issue-tbody");
		$tbody.empty();

		if (!items || items.length === 0) {
			$tbody.html(`<tr><td colspan="9" class="text-center text-muted p-4">${__("No parts pending issue.")}</td></tr>`);
			return;
		}

		items.forEach((item) => {
			const stock_class = item.is_shortage ? "pc-stock-low" : "pc-stock-ok";
			const stock_text = item.is_shortage ? `${item.stock_available} (${__("Low")})` : `${item.stock_available}`;

			const $row = $(`
				<tr>
					<td><a href="/app/service-order/${encodeURIComponent(item.order)}"><strong>${item.order}</strong></a></td>
					<td>${item.customer}</td>
					<td>
						<div><strong>${item.job_title}</strong></div>
						<div class="text-xs text-muted">${item.technician}</div>
					</td>
					<td>
						<div><strong>${item.item_code}</strong></div>
						<div class="text-xs text-muted">${item.item_name}</div>
					</td>
					<td>${item.qty_required}</td>
					<td>${item.qty_issued}</td>
					<td><strong>${item.qty_remaining}</strong></td>
					<td><span class="pc-stock-badge ${stock_class}">${stock_text}</span></td>
					<td>
						<button class="pc-btn-sm pc-btn-primary-sm btn-issue-part"
							data-order="${item.order}"
							data-part="${item.part_row}"
							data-item="${item.item_code}"
							data-remaining="${item.qty_remaining}">
							<i class="fa fa-arrow-right"></i> ${__("Issue to WIP")}
						</button>
					</td>
				</tr>
			`);
			$tbody.append($row);
		});

		$tbody.find(".btn-issue-part").on("click", function () {
			const order = $(this).attr("data-order");
			const part_row = $(this).attr("data-part");
			const item_code = $(this).attr("data-item");
			const remaining = parseFloat($(this).attr("data-remaining"));

			const d = new frappe.ui.Dialog({
				title: __("Issue Part to WIP"),
				fields: [
					{
						label: __("Item Code"),
						fieldname: "item_code",
						fieldtype: "Data",
						default: item_code,
						read_only: 1,
					},
					{
						label: __("Quantity to Issue"),
						fieldname: "qty",
						fieldtype: "Float",
						default: remaining,
						reqd: 1,
					},
				],
				primary_action_label: __("Confirm Issue"),
				primary_action: function (values) {
					frappe.call({
						method: "vehicle_service.vehicle_service.page.parts_control.parts_control.quick_issue_part",
						args: {
							order_name: order,
							part_row: part_row,
							qty: values.qty,
						},
						callback: function () {
							d.hide();
							frappe.show_alert({ message: __("Part issued to workshop WIP"), indicator: "green" });
							me.load_data();
						},
					});
				},
			});
			d.show();
		});
	}

	render_in_wip(items) {
		const me = this;
		const $tbody = this.$container.find("#pc-in-wip-tbody");
		$tbody.empty();

		if (!items || items.length === 0) {
			$tbody.html(`<tr><td colspan="8" class="text-center text-muted p-4">${__("No parts currently in workshop WIP.")}</td></tr>`);
			return;
		}

		items.forEach((item) => {
			const $row = $(`
				<tr>
					<td><a href="/app/service-order/${encodeURIComponent(item.order)}"><strong>${item.order}</strong></a></td>
					<td><strong>${item.bay}</strong></td>
					<td>
						<div><strong>${item.job_title}</strong></div>
						<div class="text-xs text-muted">${item.technician}</div>
					</td>
					<td>
						<div><strong>${item.item_code}</strong></div>
						<div class="text-xs text-muted">${item.item_name}</div>
					</td>
					<td>${item.qty_issued}</td>
					<td>${item.qty_returned}</td>
					<td><strong class="text-success">${item.qty_in_wip}</strong></td>
					<td>
						<button class="pc-btn-sm btn-return-part"
							data-order="${item.order}"
							data-part="${item.part_row}"
							data-item="${item.item_code}"
							data-wip="${item.qty_in_wip}">
							<i class="fa fa-undo"></i> ${__("Return to Store")}
						</button>
					</td>
				</tr>
			`);
			$tbody.append($row);
		});

		$tbody.find(".btn-return-part").on("click", function () {
			const order = $(this).attr("data-order");
			const part_row = $(this).attr("data-part");
			const item_code = $(this).attr("data-item");
			const wip = parseFloat($(this).attr("data-wip"));

			const d = new frappe.ui.Dialog({
				title: __("Return Part to Stores"),
				fields: [
					{
						label: __("Item Code"),
						fieldname: "item_code",
						fieldtype: "Data",
						default: item_code,
						read_only: 1,
					},
					{
						label: __("Quantity to Return"),
						fieldname: "qty",
						fieldtype: "Float",
						default: wip,
						reqd: 1,
					},
				],
				primary_action_label: __("Return to Store"),
				primary_action: function (values) {
					frappe.call({
						method: "vehicle_service.vehicle_service.page.parts_control.parts_control.quick_return_part",
						args: {
							order_name: order,
							part_row: part_row,
							qty: values.qty,
						},
						callback: function () {
							d.hide();
							frappe.show_alert({ message: __("Part returned to store warehouse"), indicator: "green" });
							me.load_data();
						},
					});
				},
			});
			d.show();
		});
	}

	render_substitutions(items) {
		const me = this;
		const $tbody = this.$container.find("#pc-subs-tbody");
		$tbody.empty();

		if (!items || items.length === 0) {
			$tbody.html(`<tr><td colspan="7" class="text-center text-muted p-4">${__("No pending substitutions.")}</td></tr>`);
			return;
		}

		items.forEach((item) => {
			const $row = $(`
				<tr>
					<td><a href="/app/parts-substitution/${encodeURIComponent(item.name)}"><strong>${item.name}</strong></a></td>
					<td><a href="/app/service-order/${encodeURIComponent(item.service_order)}">${item.service_order}</a></td>
					<td>
						<div>${item.original_item} (Qty: ${item.original_qty})</div>
						<div class="text-xs text-muted">${__("Stock")}: ${item.stock_original}</div>
					</td>
					<td>
						<div><strong>${item.substitute_item}</strong> (Qty: ${item.qty})</div>
						<div class="text-xs text-muted">${__("Stock")}: ${item.stock_substitute}</div>
					</td>
					<td>${item.reason}</td>
					<td>${item.requested_by}</td>
					<td>
						<button class="pc-btn-sm pc-btn-primary-sm btn-approve-sub" data-sub="${item.name}">
							<i class="fa fa-check"></i> ${__("Approve")}
						</button>
					</td>
				</tr>
			`);
			$tbody.append($row);
		});

		$tbody.find(".btn-approve-sub").on("click", function () {
			const sub_name = $(this).attr("data-sub");
			frappe.confirm(__("Are you sure you want to approve this substitution?"), () => {
				frappe.call({
					method: "vehicle_service.vehicle_service.page.parts_control.parts_control.approve_substitution",
					args: { substitution_name: sub_name },
					callback: function () {
						frappe.show_alert({ message: __("Substitution approved"), indicator: "green" });
						me.load_data();
					},
				});
			});
		});
	}

	render_shortages(items) {
		const me = this;
		const $tbody = this.$container.find("#pc-shortages-tbody");
		$tbody.empty();

		if (!items || items.length === 0) {
			$tbody.html(`<tr><td colspan="7" class="text-center text-muted p-4">${__("No stock shortages! All parts available.")}</td></tr>`);
			return;
		}

		items.forEach((item) => {
			const orders_html = item.orders_affected.map(o => `<a href="/app/service-order/${encodeURIComponent(o)}" class="mr-1">${o}</a>`).join(", ");
			const $row = $(`
				<tr>
					<td><strong>${item.item_code}</strong></td>
					<td>${item.item_name}</td>
					<td>${item.total_required}</td>
					<td>${item.stock_available}</td>
					<td><strong class="text-danger">${item.shortfall}</strong></td>
					<td>${orders_html}</td>
					<td>
						<button class="pc-btn-sm pc-btn-danger-sm btn-create-mr"
							data-item="${item.item_code}"
							data-shortfall="${item.shortfall}">
							<i class="fa fa-shopping-cart"></i> ${__("Create Material Request")}
						</button>
					</td>
				</tr>
			`);
			$tbody.append($row);
		});

		$tbody.find(".btn-create-mr").on("click", function () {
			const item_code = $(this).attr("data-item");
			const shortfall = parseFloat($(this).attr("data-shortfall"));

			frappe.call({
				method: "vehicle_service.vehicle_service.page.parts_control.parts_control.create_shortage_material_request",
				args: { item_code: item_code, qty: shortfall },
				callback: function (r) {
					if (r.message) {
						frappe.msgprint({
							title: __("Material Request Created"),
							indicator: "green",
							message: __("Created Material Request <a href='/app/material-request/{0}'><strong>{0}</strong></a> for {1} units.", [r.message, shortfall]),
						});
						me.load_data();
					}
				},
			});
		});
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
	}
}
