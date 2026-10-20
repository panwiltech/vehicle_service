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

	can_control() {
		const userRoles = frappe.user_roles || [];
		return userRoles.includes("Job Controller") ||
			userRoles.includes("Workshop Supervisor") ||
			userRoles.includes("Service Manager") ||
			userRoles.includes("System Manager") ||
			frappe.session.user === "Administrator";
	}

	can_create_order() {
		const userRoles = frappe.user_roles || [];
		return userRoles.includes("Service Advisor") ||
			userRoles.includes("Job Controller") ||
			userRoles.includes("Service Manager") ||
			userRoles.includes("System Manager") ||
			frappe.session.user === "Administrator";
	}

	setup_dom() {
		this.$container.empty();

		const controlButtonsHtml = this.can_control() ? `
			<div class="btn-group" role="group">
				<button class="btn btn-xs btn-default btn-add-job" type="button">
					<svg class="icon icon-xs" style="margin-right: 3px;"><use href="#icon-add"></use></svg>${__("Add Job")}
				</button>
				<button class="btn btn-xs btn-default btn-assign-tech" type="button">
					<svg class="icon icon-xs" style="margin-right: 3px;"><use href="#icon-user"></use></svg>${__("Assign Technician")}
				</button>
				<button class="btn btn-xs btn-default btn-start-clock" type="button">
					<svg class="icon icon-xs" style="margin-right: 3px;"><use href="#icon-play"></use></svg>${__("Start Clock")}
				</button>
				<button class="btn btn-xs btn-default btn-pause-clock" type="button">
					<svg class="icon icon-xs" style="margin-right: 3px;"><use href="#icon-pause"></use></svg>${__("Pause Clock")}
				</button>
				<button class="btn btn-xs btn-primary btn-complete-order" type="button">
					<svg class="icon icon-xs" style="margin-right: 3px;"><use href="#icon-check"></use></svg>${__("Complete Job")}
				</button>
			</div>
		` : `
			<span class="badge badge-default text-muted border" style="padding: 5px 10px; font-weight: 500; font-size: 11px; display: inline-flex; align-items: center; gap: 4px;">
				<svg class="icon icon-xs" style="color: var(--text-muted);"><use href="#icon-view"></use></svg>${__("Workshop View Mode (Read Only)")}
			</span>
		`;

		const newOrderBtnHtml = this.can_create_order() ? `
			<button class="btn btn-xs btn-default btn-new-order" type="button" title="${__("New Service Order")}">
				<svg class="icon icon-xs" style="margin-right: 2px;"><use href="#icon-add"></use></svg>${__("Add Service Order")}
			</button>
		` : ``;

		this.$body = $(`
			<div class="frappe-control form-group jcb-wrapper" style="margin-bottom: 20px;">
				<!-- Top Form Tabs (Native Frappe form-tabs) -->
				<div class="form-tabs-list mb-3">
					<ul class="nav form-tabs jcb-tabs" role="tablist"></ul>
				</div>

				<!-- Grid Field Container (Matches Service Order Jobs/Parts Grid) -->
				<div class="grid-field">
					<!-- Top Custom Action Buttons matching Jobs tab -->
					<div class="grid-custom-buttons d-flex justify-content-between align-items-center mb-2">
						${controlButtonsHtml}
						<div class="d-flex align-items-center" style="gap: 8px;">
							<div class="position-relative">
								<input type="text" class="form-control input-xs jcb-search-input" placeholder="${__("Search orders, vehicles, technicians...")}" style="width: 240px; padding-left: 24px;">
								<svg class="icon icon-xs position-absolute" style="left: 6px; top: 50%; transform: translateY(-50%); color: var(--text-muted); pointer-events: none;"><use href="#icon-search"></use></svg>
							</div>
							<button class="btn btn-xs btn-default btn-refresh-board" type="button" title="${__("Refresh")}">
								<svg class="icon icon-xs"><use href="#icon-refresh"></use></svg>
							</button>
							${newOrderBtnHtml}
						</div>
					</div>

					<!-- Form Grid Table matching Frappe/ERPNext form grid -->
					<div class="form-grid-container">
						<div class="form-grid">
							<div class="grid-heading-row">
								<div class="grid-row">
									<div class="data-row row m-0">
										<div class="row-check sortable-handle col" style="flex: 0 0 38px; max-width: 38px; text-align: center; justify-content: center;">
											<input type="checkbox" class="grid-row-check jcb-check-all" title="${__("Select All")}">
										</div>
										<div class="row-index sortable-handle grid-static-col col" style="flex: 0 0 44px; max-width: 44px; text-align: center; justify-content: center;">
											<span>${__("No.")}</span>
										</div>
										<div class="grid-static-col col bold" style="flex: 1.2 1 140px; min-width: 130px;" data-fieldname="service_order">
											<span>${__("Service Order")}</span>
										</div>
										<div class="grid-static-col col" style="flex: 1.6 1 160px; min-width: 140px;" data-fieldname="customer">
											<span>${__("Customer")}</span>
										</div>
										<div class="grid-static-col col" style="flex: 1.3 1 130px; min-width: 120px;" data-fieldname="vehicle">
											<span>${__("Vehicle")}</span>
										</div>
										<div class="grid-static-col col" style="flex: 1.1 1 120px; min-width: 110px;" data-fieldname="status">
											<span>${__("Status")}</span>
										</div>
										<div class="grid-static-col col" style="flex: 1.6 1 150px; min-width: 130px;" data-fieldname="technicians">
											<span>${__("Technician(s)")}</span>
										</div>
										<div class="grid-static-col col text-center" style="flex: 0.8 1 90px; min-width: 80px; justify-content: center;" data-fieldname="jobs">
											<span>${__("Jobs Done")}</span>
										</div>
										<div class="grid-static-col col text-center" style="flex: 1.0 1 110px; min-width: 100px; justify-content: center;" data-fieldname="clock">
											<span>${__("Clock")}</span>
										</div>
										<div class="grid-static-col col text-center" style="flex: 0 0 95px; max-width: 95px; justify-content: center;" data-fieldname="actions">
											<span>${__("Actions")}</span>
										</div>
									</div>
								</div>
							</div>
							<div class="grid-body">
								<div class="rows jcb-grid-rows"></div>
								<div class="grid-empty text-center text-extra-muted py-4 jcb-grid-empty" style="display: none;">
									${__("No service orders in this tab")}
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>
		`).appendTo(this.$container);

		this.$tabs = this.$body.find(".jcb-tabs");
		this.$rows_container = this.$body.find(".jcb-grid-rows");
		this.$empty_state = this.$body.find(".jcb-grid-empty");
		this.$search = this.$body.find(".jcb-search-input");
		this.$check_all = this.$body.find(".jcb-check-all");

		// Bind toolbar action buttons
		this.$body.find(".btn-refresh-board").on("click", () => this.refresh());
		this.$body.find(".btn-new-order").on("click", () => frappe.new_doc("Service Order"));

		this.$body.find(".btn-add-job").on("click", () => this.trigger_add_job());
		this.$body.find(".btn-assign-tech").on("click", () => this.trigger_assign_technician());
		this.$body.find(".btn-start-clock").on("click", () => this.trigger_start_clock());
		this.$body.find(".btn-pause-clock").on("click", () => this.trigger_pause_clock());
		this.$body.find(".btn-complete-order").on("click", () => this.trigger_complete_order());

		// Select All Checkbox
		this.$check_all.on("change", (e) => {
			const isChecked = $(e.target).is(":checked");
			this.$rows_container.find(".grid-row-check").prop("checked", isChecked);
		});

		// Search input
		this.$search.on("input", (e) => {
			this.search_query = (e.target.value || "").trim().toLowerCase();
			this.filter_and_render_table();
		});
	}

	bind_events() {
		if (frappe.realtime) {
			frappe.realtime.off("job_board_update");
			frappe.realtime.on("job_board_update", () => {
				if (window._current_jcb_instance) {
					window._current_jcb_instance.schedule_refresh();
				}
			});
		}

		if (!window._jcb_floating_listener_bound) {
			window._jcb_floating_listener_bound = true;
			$(document).on("click scroll", (e) => {
				if (!$(e.target).closest(".jcb-btn-row-action, .jcb-floating-menu").length) {
					$(".jcb-floating-menu").remove();
				}
			});
		}
		window._current_jcb_instance = this;

		// Heartbeat sync every 10 seconds to ensure all viewers remain in perfect sync
		if (this.sync_poll_interval) {
			clearInterval(this.sync_poll_interval);
		}
		this.sync_poll_interval = setInterval(() => {
			if (window._current_jcb_instance === this && this.$container && this.$container.is(":visible")) {
				this.load_orders(true);
			}
		}, 10000);
	}

	schedule_refresh() {
		clearTimeout(this.refresh_timer);
		this.refresh_timer = setTimeout(() => this.refresh(), 500);
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
				<li class="nav-item">
					<a class="nav-link ${is_active ? "active" : ""}"
						id="jcb-tab-${frappe.scrub(tab.name)}" role="tab" href="#">
						<span>${esc(tab.label)}</span>
						<span class="badge ${is_active ? "badge-primary" : "badge-light"}" style="margin-left: 6px;">${tab.count}</span>
					</a>
				</li>
			`);
			$t.find(".nav-link").on("click", (e) => {
				e.preventDefault();
				this.active = tab.name;
				this.$check_all.prop("checked", false);
				this.render_tabs();
				this.load_orders();
			});
			this.$tabs.append($t);
		});
	}

	async load_orders(silent = false) {
		if (!this.active) {
			this.current_orders = [];
			this.filter_and_render_table();
			return;
		}
		const tab = this.active;
		try {
			const r = await frappe.call({
				method: "vehicle_service.job_board.get_board_orders",
				args: { tab },
			});
			if (tab !== this.active) return;
			const new_orders = r.message || [];
			if (silent && JSON.stringify(new_orders.map(o => [o.name, o.status, o.jobs_completed, o.has_running_clock, o.technicians])) ===
				JSON.stringify(this.current_orders.map(o => [o.name, o.status, o.jobs_completed, o.has_running_clock, o.technicians]))) {
				return;
			}
			this.current_orders = new_orders;
			this.filter_and_render_table();
		} catch (e) {
			console.warn("Job Control Board could not load orders:", e);
		}
	}

	get_selected_orders() {
		const selected = [];
		this.$rows_container.find(".grid-row-check:checked").each(function () {
			const name = $(this).closest(".grid-row").attr("data-name");
			if (name) selected.push(name);
		});
		return selected;
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
		this.render_rows(orders);
	}

	render_rows(orders) {
		const esc = frappe.utils.escape_html;
		this.$rows_container.empty();

		if (!orders.length) {
			const msg = this.search_query
				? __("No matching service orders found.")
				: __("No service orders in this tab.");
			this.$empty_state.text(msg).show();
			return;
		}

		this.$empty_state.hide();

		orders.forEach((o, index) => {
			const ind_color = this.get_status_indicator_class(o.status);

			let clock_cell = `<span class="text-muted text-xs">—</span>`;
			if (o.has_running_clock) {
				const total_sec = (o.total_seconds !== undefined && o.total_seconds !== null)
					? o.total_seconds
					: ((o.actual_seconds || 0) + (o.running_seconds || 0));
				clock_cell = `
					<div class="d-flex align-items-center justify-content-center" style="gap: 5px;" title="${__("Active Clock Running")}">
						<span class="indicator green blink" style="margin: 0;"></span>
						<span class="jcb-timer-display font-weight-bold text-success font-monospace" style="font-size: 12px; font-variant-numeric: tabular-nums;" data-base-sec="${total_sec}">
							${this.format_time_hhmmss(total_sec)}
						</span>
					</div>
				`;
			} else if (o.actual_seconds && o.actual_seconds > 0) {
				clock_cell = `
					<div class="d-flex align-items-center justify-content-center text-muted" style="gap: 4px;" title="${__("Total Logged: {0} hrs", [o.actual_hours || 0])}">
						<i class="fa fa-clock-o text-muted" style="font-size: 11px;"></i>
						<span class="text-muted font-monospace" style="font-size: 12px; font-variant-numeric: tabular-nums;">
							${this.format_time_hhmmss(o.actual_seconds)}
						</span>
					</div>
				`;
			}

			const $row = $(`
				<div class="grid-row" data-name="${esc(o.name)}" tabindex="0">
					<div class="data-row row m-0">
						<div class="row-check sortable-handle col" style="flex: 0 0 38px; max-width: 38px; text-align: center; justify-content: center;">
							<input type="checkbox" class="grid-row-check">
						</div>
						<div class="row-index sortable-handle grid-static-col col" style="flex: 0 0 44px; max-width: 44px; text-align: center; justify-content: center;">
							<span>${index + 1}</span>
						</div>
						<div class="grid-static-col col bold ellipsis" style="flex: 1.2 1 140px; min-width: 130px;" data-fieldname="service_order">
							<a href="/app/service-order/${encodeURIComponent(o.name)}" class="jcb-order-link">${esc(o.name)}</a>
						</div>
						<div class="grid-static-col col ellipsis" style="flex: 1.6 1 160px; min-width: 140px;" data-fieldname="customer" title="${esc(o.customer_name || "")}">
							<span>${esc(o.customer_name || "—")}</span>
						</div>
						<div class="grid-static-col col ellipsis" style="flex: 1.3 1 130px; min-width: 120px;" data-fieldname="vehicle" title="${esc(o.vehicle || "")}">
							<span>${esc(o.vehicle || "—")}</span>
						</div>
						<div class="grid-static-col col ellipsis" style="flex: 1.1 1 120px; min-width: 110px;" data-fieldname="status">
							<span class="indicator-pill ${ind_color}">${esc(o.status)}</span>
						</div>
						<div class="grid-static-col col ellipsis text-muted" style="flex: 1.6 1 150px; min-width: 130px;" data-fieldname="technicians" title="${esc(o.technicians || __("Unassigned"))}">
							<span>${esc(o.technicians || __("Unassigned"))}</span>
						</div>
						<div class="grid-static-col col text-center" style="flex: 0.8 1 90px; min-width: 80px; justify-content: center;" data-fieldname="jobs">
							<span class="badge ${o.jobs_completed === o.job_count && o.job_count > 0 ? "badge-success" : "badge-light"}">
								${o.jobs_completed} / ${o.job_count}
							</span>
						</div>
						<div class="grid-static-col col text-center" style="flex: 1.0 1 110px; min-width: 100px; justify-content: center;" data-fieldname="clock">
							${clock_cell}
						</div>
						<div class="grid-static-col col text-center" style="flex: 0 0 95px; max-width: 95px; justify-content: center;" data-fieldname="actions">
							${this.can_control() ? `
								<button type="button" class="btn btn-default btn-xs jcb-btn-row-action" title="${__("Order Actions")}">
									${__("Actions")} <i class="fa fa-caret-down" style="margin-left: 2px;"></i>
								</button>
							` : `
								<button type="button" class="btn btn-default btn-xs jcb-btn-row-view" title="${__("View Order")}">
									<svg class="icon icon-xs" style="margin-right: 2px;"><use href="#icon-view"></use></svg>${__("View")}
								</button>
							`}
						</div>
					</div>
				</div>
			`);

			$row.find(".jcb-btn-row-view").on("click", (e) => {
				e.preventDefault();
				e.stopPropagation();
				frappe.set_route("Form", "Service Order", o.name);
			});

			// Bind Row Actions Floating Menu (Attached to body so it never clips)
			$row.find(".jcb-btn-row-action").on("click", (e) => {
				e.preventDefault();
				e.stopPropagation();

				const isCurrentOpen = $(".jcb-floating-menu").length && $(".jcb-floating-menu").data("order") === o.name;
				$(".jcb-floating-menu").remove();
				if (isCurrentOpen) return;

				const rect = e.currentTarget.getBoundingClientRect();
				const menuWidth = 190;
				let leftPos = rect.right - menuWidth;
				if (leftPos < 10) leftPos = 10;
				let topPos = rect.bottom + 4;
				if (topPos + 220 > window.innerHeight) {
					topPos = Math.max(10, rect.top - 200);
				}

				const $menu = $(`
					<div class="dropdown-menu show shadow jcb-floating-menu" data-order="${esc(o.name)}" style="position: fixed; top: ${topPos}px; left: ${leftPos}px; z-index: 10000; min-width: ${menuWidth}px; display: block; border-radius: 6px; padding: 4px 0; background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd); box-shadow: 0 6px 20px rgba(0,0,0,0.15);">
						<a class="dropdown-item jcb-action-add-job" href="#" style="display: flex; align-items: center; padding: 7px 14px; font-size: 13px; color: var(--text-color, #171717); cursor: pointer;"><i class="fa fa-plus text-primary mr-2" style="width: 16px;"></i> ${__("Add Job")}</a>
						<a class="dropdown-item jcb-action-start-clock" href="#" style="display: flex; align-items: center; padding: 7px 14px; font-size: 13px; color: var(--text-color, #171717); cursor: pointer;"><i class="fa fa-play text-success mr-2" style="width: 16px;"></i> ${__("Start Clock")}</a>
						<a class="dropdown-item jcb-action-pause-clock" href="#" style="display: flex; align-items: center; padding: 7px 14px; font-size: 13px; color: var(--text-color, #171717); cursor: pointer;"><i class="fa fa-pause text-warning mr-2" style="width: 16px;"></i> ${__("Pause Job")}</a>
						<a class="dropdown-item jcb-action-assign-tech" href="#" style="display: flex; align-items: center; padding: 7px 14px; font-size: 13px; color: var(--text-color, #171717); cursor: pointer;"><i class="fa fa-user text-info mr-2" style="width: 16px;"></i> ${__("Assign Technician")}</a>
						<div class="dropdown-divider" style="margin: 4px 0; border-top: 1px solid var(--border-color, #ebeff2);"></div>
						<a class="dropdown-item jcb-action-complete-order" href="#" style="display: flex; align-items: center; padding: 7px 14px; font-size: 13px; color: var(--text-color, #171717); cursor: pointer;"><i class="fa fa-check text-success mr-2" style="width: 16px;"></i> ${__("Complete Job")}</a>
					</div>
				`).appendTo("body");

				$menu.find(".jcb-action-add-job").on("click", (evt) => {
					evt.preventDefault();
					evt.stopPropagation();
					$menu.remove();
					this.trigger_add_job(o.name);
				});

				$menu.find(".jcb-action-start-clock").on("click", (evt) => {
					evt.preventDefault();
					evt.stopPropagation();
					$menu.remove();
					this.trigger_start_clock(o.name);
				});

				$menu.find(".jcb-action-pause-clock").on("click", (evt) => {
					evt.preventDefault();
					evt.stopPropagation();
					$menu.remove();
					this.trigger_pause_clock(o.name);
				});

				$menu.find(".jcb-action-assign-tech").on("click", (evt) => {
					evt.preventDefault();
					evt.stopPropagation();
					$menu.remove();
					this.trigger_assign_technician(o.name);
				});

				$menu.find(".jcb-action-complete-order").on("click", (evt) => {
					evt.preventDefault();
					evt.stopPropagation();
					$menu.remove();
					this.trigger_complete_order(o.name);
				});
			});

			// Row click navigation (excluding direct checkbox/link/button clicks)
			$row.on("click", (e) => {
				if ($(e.target).closest("a, button, input").length) return;
				frappe.set_route("Form", "Service Order", o.name);
			}).on("keydown", (e) => {
				if (e.key === "Enter") {
					frappe.set_route("Form", "Service Order", o.name);
				}
			});

			this.$rows_container.append($row);
		});

		this.start_clock_ticker();
	}

	format_time_hhmmss(total_seconds) {
		const s = Math.max(0, Math.floor(total_seconds || 0));
		const hrs = Math.floor(s / 3600);
		const mins = Math.floor((s % 3600) / 60);
		const secs = s % 60;
		const pad = (n) => String(n).padStart(2, "0");
		return `${pad(hrs)}:${pad(mins)}:${pad(secs)}`;
	}

	start_clock_ticker() {
		if (this.clock_ticker_interval) {
			clearInterval(this.clock_ticker_interval);
			this.clock_ticker_interval = null;
		}

		const ticker_started_at = performance.now();

		const update_all_clocks = () => {
			const elapsed_seconds = Math.floor((performance.now() - ticker_started_at) / 1000);
			this.$rows_container.find(".jcb-timer-display").each((_, el) => {
				const $el = $(el);
				const base_sec = parseInt($el.attr("data-base-sec"), 10) || 0;
				$el.text(this.format_time_hhmmss(base_sec + elapsed_seconds));
			});
		};

		update_all_clocks();
		if (this.$rows_container.find(".jcb-timer-display").length) {
			this.clock_ticker_interval = setInterval(update_all_clocks, 1000);
		}
	}

	// Action: Add Job
	trigger_add_job(order_name) {
		if (!order_name) {
			const selected = this.get_selected_orders();
			if (selected.length) {
				order_name = selected[0];
			}
		}

		const fields = [];
		if (!order_name) {
			fields.push({
				fieldname: "service_order",
				label: __("Service Order"),
				fieldtype: "Link",
				options: "Service Order",
				reqd: 1,
				get_query: () => ({
					filters: {
						docstatus: ["!=", 2],
						status: ["not in", ["Cancelled", "Delivered", "Ready for Billing"]]
					}
				})
			});
		}

		fields.push(
			{
				fieldname: "service_item",
				label: __("Service Item"),
				fieldtype: "Link",
				options: "Item",
				default: "LABOUR",
				reqd: 1,
				get_query: () => ({ filters: { is_stock_item: 0 } }),
				onchange: () => {
					const itm = d.get_value("service_item");
					if (itm) {
						frappe.db.get_value("Item", itm, "item_name").then((r) => {
							if (r && r.message && r.message.item_name && !d.get_value("job_title")) {
								d.set_value("job_title", r.message.item_name);
							}
						});
						frappe.db.get_value("Item Price", { item_code: itm, price_list: "Standard Selling" }, "price_list_rate").then((pr) => {
							if (pr && pr.message && pr.message.price_list_rate) {
								d.set_value("rate", pr.message.price_list_rate);
							}
						});
					}
				},
			},
			{ fieldname: "job_title", label: __("Job Description"), fieldtype: "Data", reqd: 1 },
			{ fieldname: "estimated_hours", label: __("Labour Qty (Hours)"), fieldtype: "Float", default: 1.0, reqd: 1 },
			{ fieldname: "rate", label: __("Rate / Unit Price"), fieldtype: "Currency", default: 50.0 },
			{ fieldname: "col_brk_1", fieldtype: "Column Break" },
			{ fieldname: "category", label: __("Category"), fieldtype: "Select", options: "Essential\nRecommended\nOptional", default: "Essential", reqd: 1 },
			{ fieldname: "priority", label: __("Priority"), fieldtype: "Select", options: "Low\nMedium\nHigh\nUrgent", default: "Medium", reqd: 1 },
			{ fieldname: "technician", label: __("Assign Technician"), fieldtype: "Link", options: "Employee" },
			{ fieldname: "bay", label: __("Workshop Bay"), fieldtype: "Link", options: "Workshop Location" },
			{ fieldname: "reason_for_adding", label: __("Reason for Adding"), fieldtype: "Small Text", description: __("Explanation for adding job directly") },
			{ fieldname: "sec_sublet", label: __("Sublet Details (If Outsourced)"), fieldtype: "Section Break" },
			{ fieldname: "supplier", label: __("Sublet Supplier"), fieldtype: "Link", options: "Supplier" },
			{ fieldname: "supplier_cost", label: __("Supplier Cost"), fieldtype: "Currency" },
			{ fieldname: "supplier_invoice_ref", label: __("Supplier Invoice Ref"), fieldtype: "Data" },
			{ fieldname: "description", label: __("Detailed Scope / Notes"), fieldtype: "Small Text" }
		);

		const d = new frappe.ui.Dialog({
			title: order_name ? __("Add Workshop Job ({0})", [order_name]) : __("Add Workshop Job"),
			fields: fields,
			primary_action_label: __("Create Job"),
			primary_action: (vals) => {
				const target_order = order_name || vals.service_order;
				if (!target_order) {
					frappe.msgprint(__("Please select a Service Order."));
					return;
				}
				frappe.call({
					method: "vehicle_service.job_control.add_job",
					args: {
						service_order: target_order,
						job_title: vals.job_title,
						service_item: vals.service_item,
						category: vals.category,
						estimated_hours: vals.estimated_hours,
						rate: vals.rate,
						description: vals.description,
						technician: vals.technician,
						bay: vals.bay,
						priority: vals.priority,
						reason: vals.reason_for_adding,
						supplier: vals.supplier,
						supplier_cost: vals.supplier_cost,
						supplier_invoice_ref: vals.supplier_invoice_ref,
					},
					freeze: true,
					freeze_message: __("Creating Job..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({ message: __("Job created on {0}", [target_order]), indicator: "green" });
							this.refresh();
						}
					},
				});
			},
		});
		d.show();
	}

	// Action: Assign Technician
	trigger_assign_technician(order_name) {
		if (!order_name) {
			const selected = this.get_selected_orders();
			if (!selected.length) {
				frappe.msgprint(__("Please select a Service Order row first."));
				return;
			}
			order_name = selected[0];
		}

		frappe.db.get_doc("Service Order", order_name).then((so) => {
			const job_options = (so.jobs || []).map((j) => ({
				label: `${j.job_title} (${j.status || "Open"})`,
				value: j.service_job,
			}));

			if (!job_options.length) {
				frappe.msgprint(__("This Service Order has no jobs to assign."));
				return;
			}

			const d = new frappe.ui.Dialog({
				title: __("Assign Technician & Bay ({0})", [order_name]),
				fields: [
					{
						fieldname: "job",
						label: __("Select Job"),
						fieldtype: "Select",
						options: job_options,
						default: job_options[0].value,
						reqd: 1,
					},
					{
						fieldname: "technician",
						label: __("Technician"),
						fieldtype: "Link",
						options: "Employee",
						reqd: 1,
					},
					{
						fieldname: "bay",
						label: __("Workshop Bay"),
						fieldtype: "Link",
						options: "Workshop Location",
					},
				],
				primary_action_label: __("Assign"),
				primary_action: (vals) => {
					frappe.call({
						method: "vehicle_service.job_control.assign_technician",
						args: {
							job_name: vals.job,
							technician: vals.technician,
							bay: vals.bay,
						},
						freeze: true,
						callback: (r) => {
							if (!r.exc) {
								d.hide();
								frappe.show_alert({ message: __("Technician assigned successfully"), indicator: "green" });
								this.refresh();
							}
						},
					});
				},
			});
			d.show();
		});
	}

	// Action: Start Clock
	trigger_start_clock(order_name) {
		if (!order_name) {
			const selected = this.get_selected_orders();
			if (!selected.length) {
				frappe.msgprint(__("Please select a Service Order row to start clock."));
				return;
			}
			order_name = selected[0];
		}

		frappe.db.get_doc("Service Order", order_name).then((so) => {
			const eligible_jobs = (so.jobs || []).filter((j) => j.status !== "Completed");

			if (!eligible_jobs.length) {
				frappe.msgprint(__("No uncompleted jobs available on {0} to start clock.", [order_name]));
				return;
			}

			const job_options = eligible_jobs.map((j) => ({
				label: `${j.job_title} — ${j.technician_name || j.assigned_technician || __("Unassigned")}`,
				value: j.service_job,
			}));

			const d = new frappe.ui.Dialog({
				title: __("Start Clock ({0})", [order_name]),
				fields: [
					{
						fieldname: "job",
						label: __("Select Job"),
						fieldtype: "Select",
						options: job_options,
						default: job_options[0].value,
						reqd: 1,
					},
				],
				primary_action_label: __("Start Clock"),
				primary_action: (vals) => {
					frappe.call({
						method: "vehicle_service.job_control.start_clock",
						args: { job_name: vals.job },
						freeze: true,
						callback: (r) => {
							if (!r.exc) {
								d.hide();
								frappe.show_alert({ message: __("Clock started successfully"), indicator: "green" });
								this.refresh();
							}
						},
					});
				},
			});
			d.show();
		});
	}

	// Action: Pause Clock
	trigger_pause_clock(order_name) {
		if (!order_name) {
			const selected = this.get_selected_orders();
			if (!selected.length) {
				frappe.msgprint(__("Please select a Service Order row to pause clock."));
				return;
			}
			order_name = selected[0];
		}

		frappe.db.get_doc("Service Order", order_name).then((so) => {
			const active_jobs = (so.jobs || []).filter((j) => j.status === "In Progress");
			if (!active_jobs.length) {
				frappe.msgprint(__("No running clock on {0}.", [order_name]));
				return;
			}

			const job_options = active_jobs.map((j) => ({
				label: `${j.job_title} — ${j.technician_name || j.assigned_technician}`,
				value: j.service_job,
			}));

			const d = new frappe.ui.Dialog({
				title: __("Pause Clock ({0})", [order_name]),
				fields: [
					{
						fieldname: "job",
						label: __("Select Running Job"),
						fieldtype: "Select",
						options: job_options,
						default: job_options[0].value,
						reqd: 1,
					},
					{
						fieldname: "pause_reason",
						label: __("Pause Reason"),
						fieldtype: "Select",
						options: "Awaiting Parts\nAwaiting Approval\nShift End / Break\nOther",
						default: "Shift End / Break",
						reqd: 1,
					},
				],
				primary_action_label: __("Pause Clock"),
				primary_action: (vals) => {
					frappe.call({
						method: "vehicle_service.job_control.pause_clock",
						args: { job_name: vals.job, pause_reason: vals.pause_reason },
						freeze: true,
						callback: (r) => {
							if (!r.exc) {
								d.hide();
								frappe.show_alert({ message: __("Clock paused successfully"), indicator: "orange" });
								this.refresh();
							}
						},
					});
				},
			});
			d.show();
		});
	}

	// Action: Complete Order
	trigger_complete_order(order_name) {
		if (!order_name) {
			const selected = this.get_selected_orders();
			if (!selected.length) {
				frappe.msgprint(__("Please select a Service Order row to complete."));
				return;
			}
			order_name = selected[0];
		}

		frappe.confirm(
			__("Complete all jobs on Service Order {0} and mark Ready for Billing?", [order_name]),
			() => {
				frappe.call({
					method: "vehicle_service.job_control.complete_service_order",
					args: { order_name },
					freeze: true,
					freeze_message: __("Completing Service Order..."),
					callback: (r) => {
						if (!r.exc) {
							frappe.show_alert({ message: __("Service Order {0} completed and marked Ready for Billing", [order_name]), indicator: "green" });
							this.refresh();
						}
					},
				});
			}
		);
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
		<div id="jcb-workspace-mount" style="width: 100%; max-width: 100%; margin-bottom: var(--margin-md, 16px);"></div>
	`);

	// Hide any workspace editor, number cards, or widgets below
	$container.find(".editor-js-container, .codex-editor, .widget-group, .widget-box, .widget, .workspace-footer").hide();

	const $editor = $container.find(".editor-js-container");
	if ($editor.length) {
		$mount.insertBefore($editor);
	} else {
		$container.prepend($mount);
	}

	// Expand workspace page layout to full width
	$("body").addClass("full-width");
	if ($ws_page && $ws_page.length) {
		$ws_page.find(".layout-main, .layout-main-section, .layout-main-section-wrapper").css({
			"max-width": "100%",
			"width": "100%",
			"margin-left": "0",
			"margin-right": "0"
		});
	}
	$(".page-container:visible .layout-main, .page-container:visible .layout-main-section").css({
		"max-width": "100%",
		"width": "100%",
		"margin-left": "0",
		"margin-right": "0"
	});

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
