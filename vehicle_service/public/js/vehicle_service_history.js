// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.provide("vehicle_service");

vehicle_service.VehicleServiceHistoryView = class VehicleServiceHistoryView {
	constructor(opts = {}) {
		this.$parent = $(opts.parent);
		this.page = opts.page || null;
		this.vehicle = opts.vehicle || null;
		this.show_search = opts.show_search !== undefined ? Boolean(opts.show_search) : true;
		this.on_vehicle_selected = typeof opts.on_vehicle_selected === "function" ? opts.on_vehicle_selected : null;

		this.filters = this._default_filters();
		this.data = null;
		this.search_results = [];
		this.active_dropdown_index = -1;
		this.search_timer = null;
		this._search_seq = 0;
		this._load_seq = 0;
		this.expanded_visits = new Set();
		this.all_expanded = false;
		this.active_rec_tab = "outstanding";
		this.editable_open_order = null;
		this._current_recommendations = [];
		this._controls = {};
		this._syncing_filters = false;
		this._event_ns = `.vsh_${frappe.utils.get_random(6)}`;

		this._make_skeleton();
		this._setup_filter_controls();
		this._toggle_filter_controls(false);
		this._bind_events();

		if (this.vehicle) {
			this.load_vehicle(this.vehicle);
		} else if (this.show_search) {
			this._render_initial_empty();
		}
	}

	_default_filters() {
		return {
			from_date: "",
			to_date: "",
			status: "",
			order_type: "",
			technician: "",
			service_advisor: "",
			invoice_status: "",
			sort_order: "desc",
		};
	}

	_esc(value) {
		return frappe.utils.escape_html(value === null || value === undefined ? "" : String(value));
	}

	_safe_url(raw) {
		const url = String(raw || "").trim();
		if (!url) return "";
		if (
			url.startsWith("/files/") ||
			url.startsWith("/private/files/") ||
			url.startsWith("/assets/") ||
			url.startsWith("https://") ||
			url.startsWith("http://")
		) {
			return url;
		}
		return "";
	}

	_doc_slug(doctype) {
		return String(doctype || "")
			.trim()
			.toLowerCase()
			.replace(/\s+/g, "-");
	}

	_doc_link(doctype, name, label = null, cls = "bold") {
		if (!name) return `<span class="text-muted">—</span>`;
		const href =
			frappe.utils && typeof frappe.utils.get_form_link === "function"
				? frappe.utils.get_form_link(doctype, name)
				: `/desk/${this._doc_slug(doctype)}/${encodeURIComponent(name)}`;
		return `<a href="${this._esc(href)}" class="${this._esc(cls)}" data-vsh-doc-link="1">${this._esc(label || name)}</a>`;
	}

	_fmt_km(value) {
		const num = Math.round(Number(value) || 0);
		return `${num.toLocaleString()} km`;
	}

	_fmt_num(value, decimals = 2) {
		const num = flt(value);
		return num.toLocaleString(undefined, {
			minimumFractionDigits: decimals,
			maximumFractionDigits: decimals,
		});
	}

	_fmt_currency(value) {
		const currency =
			(frappe.defaults && frappe.defaults.get_default && frappe.defaults.get_default("currency")) ||
			(frappe.boot && frappe.boot.sysdefaults && frappe.boot.sysdefaults.currency) ||
			"ZMW";
		if (typeof format_currency === "function") {
			return this._esc(format_currency(flt(value), currency));
		}
		return this._esc(`${currency} ${this._fmt_num(value, 2)}`);
	}

	_fmt_date(val) {
		if (!val) return "—";
		try {
			if (frappe.datetime && frappe.datetime.str_to_user) {
				return this._esc(frappe.datetime.str_to_user(String(val).slice(0, 10)));
			}
		} catch (e) {}
		return this._esc(String(val).slice(0, 10));
	}

	_fmt_datetime(val) {
		if (!val) return "—";
		try {
			if (frappe.datetime && frappe.datetime.str_to_user) {
				return this._esc(frappe.datetime.str_to_user(String(val)));
			}
		} catch (e) {}
		return this._esc(String(val));
	}

	_status_color(status) {
		const s = String(status || "").trim().toLowerCase();
		if (
			[
				"completed",
				"delivered",
				"paid",
				"pass",
				"passed",
				"approved",
				"issued",
				"awaiting collection",
				"ready for collection",
				"awaiting release",
			].includes(s)
		) {
			return "green";
		}
		if (
			[
				"in progress",
				"in qc",
				"qc",
				"booked",
				"assigned",
				"partly issued",
				"registration",
				"vin",
				"advisory logged",
				"checked in",
				"arrived",
			].includes(s)
		) {
			return "blue";
		}
		if (
			[
				"in service",
				"in workshop",
				"waiting for parts",
				"waiting",
				"pending approval",
				"awaiting approval",
				"recommended",
				"optional",
				"deferred",
				"paused",
				"on hold",
				"partly paid",
				"due soon",
				"due",
				"previous registration",
				"ready for billing",
				"ready for work",
			].includes(s)
		) {
			return "orange";
		}
		if (["invoiced", "credit note issued", "historical record", "additional", "quality control"].includes(s)) {
			return "purple";
		}
		if (["overdue", "declined", "cancelled", "fail", "qc failed", "disputed", "unpaid"].includes(s)) {
			return "red";
		}
		return "gray";
	}

	_pill(label, forcedColor = null) {
		const text = label || "—";
		const color = forcedColor || this._status_color(text);
		return `<span class="indicator-pill ${this._esc(color)}">${this._esc(text)}</span>`;
	}

	_can_view_financials() {
		return Boolean(this.data && this.data.permissions && this.data.permissions.can_view_financials);
	}

	_can_schedule_followup() {
		if (frappe.session && frappe.session.user === "Administrator") return true;
		const roles = frappe.user_roles || [];
		return ["Job Controller", "Workshop Supervisor", "Service Manager", "System Manager"].some((r) =>
			roles.includes(r)
		);
	}

	_has_no_timeline_filters() {
		return (
			!this.filters.from_date &&
			!this.filters.to_date &&
			!this.filters.status &&
			!this.filters.order_type &&
			!this.filters.technician &&
			!this.filters.service_advisor &&
			!this.filters.invoice_status
		);
	}

	_active_filters_payload() {
		const payload = { sort_order: this.filters.sort_order || "desc" };
		["from_date", "to_date", "status", "order_type", "technician", "service_advisor", "invoice_status"].forEach(
			(key) => {
				if (this.filters[key]) {
					payload[key] = this.filters[key];
				}
			}
		);
		return payload;
	}

	refresh() {
		if (this.vehicle) {
			this.load_vehicle(this.vehicle);
			return;
		}
		if (this.show_search) {
			const query = this._get_search_query();
			if (query) {
				this.search_and_resolve(query);
			}
		}
	}

	_make_skeleton() {
		// On a standard Frappe Desk page, page.page_form lives inside page.main,
		// so only remove prior .vsh-root instead of wiping page.main.
		if (this.page && this.page.page_form) {
			this.$parent.find(".vsh-root").remove();
			this.page.clear_fields();
			this.page.show_form();
			this.$filter_form = this.page.page_form;
			this.$root = $(`<div class="vsh-root vsh-root--page"><div class="vsh-content"></div></div>`).appendTo(
				this.$parent
			);
		} else {
			this.$parent.empty();
			this.$root = $(`
				<div class="vsh-root vsh-root--embedded">
					<div class="page-form row vsh-inline-page-form"></div>
					<div class="vsh-content"></div>
				</div>
			`).appendTo(this.$parent);
			this.$filter_form = this.$root.find(".vsh-inline-page-form");
		}

		this.$content = this.$root.find(".vsh-content");
	}

	_add_filter_field(df) {
		let ctrl;
		if (this.page && typeof this.page.add_field === "function") {
			ctrl = this.page.add_field(df);
		} else {
			if (!df.placeholder) {
				df.placeholder = df.label;
			}
			df.input_class = "input-xs";
			ctrl = frappe.ui.form.make_control({
				df: df,
				parent: this.$filter_form,
				render_input: true,
				only_input: df.fieldtype === "Check" ? false : true,
			});
			ctrl.refresh();
			$(ctrl.wrapper)
				.addClass("col-md-2")
				.attr("title", __(df.label))
				.tooltip({ delay: { show: 600, hide: 100 }, trigger: "hover" });
			if (!ctrl.$input && df.fieldtype !== "HTML") {
				ctrl.make_input();
			}
			if (ctrl.$input && df.fieldtype !== "Button") {
				ctrl.$input.attr("placeholder", __(df.placeholder || df.label));
			}
			if (df.default && ctrl.set_input) {
				ctrl.set_input(df.default);
			}
		}

		if (df.fieldname) {
			this._controls[df.fieldname] = ctrl;
		}
		return ctrl;
	}

	_setup_filter_controls() {
		this._controls = {};
		this.$search_input = null;
		this.$autocomplete = null;

		if (this.show_search) {
			const searchCtrl = this._add_filter_field({
				fieldname: "vehicle_query",
				label: __("Vehicle (Reg No / VIN)"),
				placeholder: __("Reg No, Prev Plate, or VIN..."),
				fieldtype: "Data",
			});
			$(searchCtrl.wrapper).removeClass("col-md-2").addClass("col-md-3 vsh-search-control");
			this.$search_input = searchCtrl.$input;
			if (this.$search_input && this.$search_input.length) {
				this.$search_input
					.attr("autocomplete", "off")
					.attr("aria-label", __("Search vehicle by registration number or VIN"))
					.attr("aria-expanded", "false");
				const $awesomplete = $('<div class="awesomplete"></div>');
				this.$search_input.wrap($awesomplete);
				this.$autocomplete = $('<ul role="listbox" class="vsh-autocomplete" hidden></ul>').insertAfter(
					this.$search_input
				);
			}

			const lookupCtrl = this._add_filter_field({
				fieldname: "lookup_vehicle",
				label: __("Lookup"),
				fieldtype: "Button",
				click: () => this.search_and_resolve(this._get_search_query()),
			});
			$(lookupCtrl.wrapper).removeClass("col-md-2").addClass("col-md-1");
		}

		this._add_filter_field({
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			change: () => this._on_filter_control_change("from_date"),
		});
		this._add_filter_field({
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			change: () => this._on_filter_control_change("to_date"),
		});
		this._add_filter_field({
			fieldname: "status",
			label: __("Service Status"),
			fieldtype: "Select",
			options: [{ label: __("Status: All (Excl. Cancelled)"), value: "" }],
			change: () => this._on_filter_control_change("status"),
		});
		this._add_filter_field({
			fieldname: "order_type",
			label: __("Service Type"),
			fieldtype: "Select",
			options: [{ label: __("Service Type: All"), value: "" }],
			change: () => this._on_filter_control_change("order_type"),
		});
		this._add_filter_field({
			fieldname: "technician",
			label: __("Technician"),
			fieldtype: "Select",
			options: [{ label: __("Technician: All"), value: "" }],
			change: () => this._on_filter_control_change("technician"),
		});
		this._add_filter_field({
			fieldname: "service_advisor",
			label: __("Service Advisor"),
			fieldtype: "Select",
			options: [{ label: __("Advisor: All"), value: "" }],
			change: () => this._on_filter_control_change("service_advisor"),
		});
		this._add_filter_field({
			fieldname: "invoice_status",
			label: __("Invoice Status"),
			fieldtype: "Select",
			options: [{ label: __("Invoice Status: All"), value: "" }],
			change: () => this._on_filter_control_change("invoice_status"),
		});
		this._add_filter_field({
			fieldname: "sort_order",
			label: __("Sort Order"),
			fieldtype: "Select",
			options: [
				{ label: __("Newest First"), value: "desc" },
				{ label: __("Oldest First"), value: "asc" },
			],
			default: "desc",
			change: () => this._on_filter_control_change("sort_order"),
		});
	}

	_get_search_query() {
		const ctrl = this._controls.vehicle_query;
		if (ctrl && typeof ctrl.get_value === "function") {
			return String(ctrl.get_value() || "").trim();
		}
		if (this.$search_input && this.$search_input.length) {
			return String(this.$search_input.val() || "").trim();
		}
		return "";
	}

	_set_search_query(val) {
		const text = val || "";
		const ctrl = this._controls.vehicle_query;
		if (ctrl && typeof ctrl.set_input === "function") {
			ctrl.set_input(text);
		} else if (this.$search_input && this.$search_input.length) {
			this.$search_input.val(text);
		}
	}

	_toggle_filter_controls(show) {
		const filterKeys = [
			"from_date",
			"to_date",
			"status",
			"order_type",
			"technician",
			"service_advisor",
			"invoice_status",
			"sort_order",
		];
		filterKeys.forEach((key) => {
			const ctrl = this._controls[key];
			if (!ctrl || !ctrl.wrapper) return;
			const visible = key === "invoice_status" ? Boolean(show && this._can_view_financials()) : Boolean(show);
			$(ctrl.wrapper).toggle(visible);
		});
		if (!this.show_search && this.$filter_form) {
			this.$filter_form.toggleClass("hide", !show);
		}
	}

	_populate_filter_options() {
		const opts = (this.data && this.data.filter_options) || {};
		const selectConfig = [
			{ key: "status", items: opts.statuses, allLabel: __("Status: All (Excl. Cancelled)") },
			{ key: "order_type", items: opts.order_types, allLabel: __("Service Type: All") },
			{ key: "technician", items: opts.technicians, allLabel: __("Technician: All") },
			{ key: "service_advisor", items: opts.service_advisors, allLabel: __("Advisor: All") },
			{ key: "invoice_status", items: opts.invoice_statuses, allLabel: __("Invoice Status: All") },
		];

		this._syncing_filters = true;
		try {
			selectConfig.forEach(({ key, items, allLabel }) => {
				const ctrl = this._controls[key];
				if (!ctrl) return;
				const normalized = (items || []).map((opt) =>
					typeof opt === "object"
						? { value: opt.value || "", label: opt.label || opt.value || "" }
						: { value: opt, label: opt }
				);
				ctrl.df.options = [{ label: allLabel, value: "" }, ...normalized];
				if (typeof ctrl.set_options === "function") {
					ctrl.set_options(this.filters[key] || "");
				}
				if (typeof ctrl.set_input === "function") {
					ctrl.set_input(this.filters[key] || "");
				}
			});
		} finally {
			this._syncing_filters = false;
		}
		this._toggle_filter_controls(true);
		this._sync_filter_inputs();
	}

	_on_filter_control_change(key) {
		if (this._syncing_filters || !this.vehicle) return;
		const ctrl = this._controls[key];
		if (!ctrl) return;
		const rawVal = typeof ctrl.get_value === "function" ? ctrl.get_value() : ctrl.$input ? ctrl.$input.val() : "";
		const nextVal = key === "sort_order" ? rawVal || "desc" : rawVal || "";
		if ((this.filters[key] || "") === nextVal) return;
		this.filters[key] = nextVal;
		this._reload_timeline_only();
	}

	_sync_filter_inputs() {
		this._syncing_filters = true;
		try {
			Object.keys(this.filters).forEach((key) => {
				const ctrl = this._controls[key];
				if (!ctrl) return;
				const val = key === "sort_order" ? this.filters[key] || "desc" : this.filters[key] || "";
				if (typeof ctrl.set_input === "function") {
					ctrl.set_input(val);
				} else if (ctrl.$input) {
					ctrl.$input.val(val);
				}
			});
		} finally {
			this._syncing_filters = false;
		}
	}

	_bind_events() {
		if (this.show_search && this.$search_input && this.$search_input.length) {
			this.$search_input.on("input", () => {
				const query = this._get_search_query();
				clearTimeout(this.search_timer);
				if (!query) {
					this._hide_autocomplete();
					return;
				}
				this.search_timer = setTimeout(() => this._fetch_autocomplete(query), 220);
			});

			this.$search_input.on("keydown", (e) => {
				if (e.key === "ArrowDown") {
					if (this.search_results.length && this.$autocomplete && !this.$autocomplete.is("[hidden]")) {
						e.preventDefault();
						this.active_dropdown_index = Math.min(
							this.active_dropdown_index + 1,
							this.search_results.length - 1
						);
						this._highlight_autocomplete_item();
					}
				} else if (e.key === "ArrowUp") {
					if (this.search_results.length && this.$autocomplete && !this.$autocomplete.is("[hidden]")) {
						e.preventDefault();
						this.active_dropdown_index = Math.max(this.active_dropdown_index - 1, 0);
						this._highlight_autocomplete_item();
					}
				} else if (e.key === "Escape") {
					this._hide_autocomplete();
				} else if (e.key === "Enter") {
					e.preventDefault();
					if (
						this.$autocomplete &&
						!this.$autocomplete.is("[hidden]") &&
						this.active_dropdown_index >= 0 &&
						this.search_results[this.active_dropdown_index]
					) {
						this._select_search_candidate(this.search_results[this.active_dropdown_index]);
					} else {
						this.search_and_resolve(this._get_search_query());
					}
				}
			});

			this.$autocomplete.on("click", ".vsh-autocomplete-item", (e) => {
				const idx = cint($(e.currentTarget).attr("data-index"));
				const item = this.search_results[idx];
				if (item) {
					this._select_search_candidate(item);
				}
			});

			$(document)
				.off(`click${this._event_ns}`)
				.on(`click${this._event_ns}`, (e) => {
					if (!this.$root || !document.contains(this.$root[0])) {
						$(document).off(`click${this._event_ns}`);
						return;
					}
					const searchCtrl = this._controls.vehicle_query;
					if (searchCtrl && searchCtrl.wrapper && !$(e.target).closest(searchCtrl.wrapper).length) {
						this._hide_autocomplete();
					}
				});
		}

		// Disambiguation table row selection
		this.$content.on("click", ".vsh-disambig-row", (e) => {
			if ($(e.target).closest("a[data-vsh-doc-link]").length) return;
			const name = $(e.currentTarget).attr("data-vehicle");
			if (name) {
				this.load_vehicle(name);
			}
		});
		this.$content.on("keydown", ".vsh-disambig-row", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				const name = $(e.currentTarget).attr("data-vehicle");
				if (name) {
					this.load_vehicle(name);
				}
			}
		});

		// Export modal button (used in embedded Service Vehicle tab)
		this.$content.on("click", ".vsh-btn-export", () => {
			this.open_export_dialog();
		});

		// Recommendations tabs & follow-up modal
		this.$content.on("click", ".vsh-rec-tab", (e) => {
			e.preventDefault();
			const tab = $(e.currentTarget).attr("data-tab");
			if (tab) {
				this.active_rec_tab = tab;
				this._render_recommendations();
			}
		});
		this.$content.on("click", ".vsh-btn-followup", (e) => {
			const idx = cint($(e.currentTarget).attr("data-idx"));
			const rec = this._current_recommendations[idx];
			if (rec) {
				this._open_followup_dialog(rec);
			}
		});

		this.$content.on("click", ".vsh-btn-reset-filters", () => {
			this.filters = this._default_filters();
			this._sync_filter_inputs();
			this._reload_timeline_only();
		});

		this.$content.on("click", ".vsh-btn-toggle-all", () => {
			const timeline = (this.data && this.data.timeline) || [];
			if (!timeline.length) return;
			if (this.all_expanded) {
				this.expanded_visits.clear();
				this.all_expanded = false;
			} else {
				timeline.forEach((v) => {
					const key = v.service_order || v.vehicle_intake;
					if (key) this.expanded_visits.add(key);
				});
				this.all_expanded = true;
			}
			this._render_timeline();
			this._update_toggle_all_button();
		});

		// Visit expand / collapse
		this.$content.on("click", ".vsh-visit-header", (e) => {
			if ($(e.target).closest("a[data-vsh-doc-link]").length) return;
			this._toggle_visit_card($(e.currentTarget).closest(".vsh-visit-card"));
		});
		this.$content.on("keydown", ".vsh-visit-header", (e) => {
			if ((e.key === "Enter" || e.key === " ") && !$(e.target).closest("a").length) {
				e.preventDefault();
				this._toggle_visit_card($(e.currentTarget).closest(".vsh-visit-card"));
			}
		});

		// Intake photo preview modal
		this.$content.on("click", ".vsh-photo-thumb", (e) => {
			const src = $(e.currentTarget).attr("data-src");
			const desc = $(e.currentTarget).attr("data-desc") || "";
			const taken = $(e.currentTarget).attr("data-taken") || "";
			if (src) {
				this._open_photo_modal(src, desc, taken);
			}
		});
	}

	_toggle_visit_card($card) {
		const key = $card.attr("data-visit-key");
		if (!key) return;
		const $body = $card.find(".vsh-visit-body");
		const $header = $card.find(".vsh-visit-header");
		const $indicator = $card.find(".vsh-visit-header .collapse-indicator");
		const isOpen = this.expanded_visits.has(key);

		if (isOpen) {
			this.expanded_visits.delete(key);
			$body.slideUp(140);
			$header.addClass("collapsed").attr("aria-expanded", "false");
			$indicator.html(frappe.utils.icon("chevron-right", "sm"));
		} else {
			this.expanded_visits.add(key);
			$body.slideDown(140);
			$header.removeClass("collapsed").attr("aria-expanded", "true");
			$indicator.html(frappe.utils.icon("chevron-down", "sm"));
		}

		const timeline = (this.data && this.data.timeline) || [];
		this.all_expanded =
			timeline.length > 0 && timeline.every((v) => this.expanded_visits.has(v.service_order || v.vehicle_intake));
		this._update_toggle_all_button();
	}

	_update_toggle_all_button() {
		const $btn = this.$content.find(".vsh-btn-toggle-all");
		if (!$btn.length) return;
		$btn.text(this.all_expanded ? __("Collapse All") : __("Expand All"));
	}

	_fetch_autocomplete(query) {
		const seq = ++this._search_seq;
		frappe.call({
			method: "vehicle_service.service_history.search_vehicles",
			args: { query, limit: 10 },
			callback: (r) => {
				if (seq !== this._search_seq) return;
				this.search_results = r.message || [];
				this.active_dropdown_index = -1;
				this._render_autocomplete(query);
			},
		});
	}

	_render_autocomplete(query) {
		if (!this.$autocomplete) return;
		if (!this.search_results.length) {
			this.$autocomplete
				.html(
					`<li class="vsh-autocomplete-empty" role="option" aria-disabled="true">
						<p class="text-muted mb-0">${this._esc(__('No matching vehicles found for "{0}"', [query]))}</p>
					</li>`
				)
				.removeAttr("hidden");
			this.$search_input && this.$search_input.attr("aria-expanded", "true");
			return;
		}

		const itemsHtml = this.search_results
			.map((item, idx) => {
				const modelDesc = [item.make, item.model, item.year ? `(${item.year})` : ""].filter(Boolean).join(" ");
				const prevHtml = item.previous_registration_nos
					? `<span class="text-muted small ml-1">(${this._esc(__("Prev"))}: ${this._esc(item.previous_registration_nos)})</span>`
					: "";
				return `
					<li class="vsh-autocomplete-item" role="option" data-index="${idx}" aria-selected="false">
						<p class="d-flex justify-content-between align-items-center mb-1">
							<span>
								<strong>${this._esc(item.registration_no || item.name)}</strong>
								${prevHtml}
								${item.match_source ? `<span class="text-muted small ml-1">[${this._esc(item.match_source)}]</span>` : ""}
							</span>
							${this._pill(item.vehicle_status || "Outside Workshop")}
						</p>
						<p class="text-muted small mb-0">
							${this._esc(modelDesc || "—")} &middot; VIN: ${this._esc(item.vin || "—")} &middot; ${this._esc(item.customer_name || item.customer || "—")}
						</p>
					</li>
				`;
			})
			.join("");

		this.$autocomplete.html(itemsHtml).removeAttr("hidden");
		this.$search_input && this.$search_input.attr("aria-expanded", "true");
	}

	_highlight_autocomplete_item() {
		if (!this.$autocomplete) return;
		const $items = this.$autocomplete.find(".vsh-autocomplete-item");
		$items.attr("aria-selected", "false");
		if (this.active_dropdown_index >= 0) {
			const $active = $items.eq(this.active_dropdown_index);
			$active.attr("aria-selected", "true");
			if ($active[0] && $active[0].scrollIntoView) {
				$active[0].scrollIntoView({ block: "nearest" });
			}
		}
	}

	_hide_autocomplete() {
		if (this.$autocomplete) {
			this.$autocomplete.attr("hidden", true).empty();
		}
		if (this.$search_input) {
			this.$search_input.attr("aria-expanded", "false");
		}
		this.active_dropdown_index = -1;
	}

	_select_search_candidate(item) {
		this._hide_autocomplete();
		this._set_search_query(item.registration_no || item.name);
		this.load_vehicle(item.name);
	}

	_clear_selected_vehicle() {
		this.vehicle = null;
		this.data = null;
		this.editable_open_order = null;
		this._toggle_filter_controls(false);
		if (this.on_vehicle_selected) {
			this.on_vehicle_selected(null);
		}
	}

	search_and_resolve(rawQuery) {
		const query = String(rawQuery || "").trim();
		clearTimeout(this.search_timer);
		this._hide_autocomplete();
		this._set_search_query(query);

		if (!query) {
			this._clear_selected_vehicle();
			this._render_initial_empty();
			return;
		}

		const seq = ++this._search_seq;
		this._toggle_filter_controls(false);
		this.$content.html(this._loading_html(__("Searching vehicles...")));

		frappe.call({
			method: "vehicle_service.service_history.search_vehicles",
			args: { query, limit: 10 },
			callback: (r) => {
				if (seq !== this._search_seq) return;
				const matches = r.message || [];
				if (!matches.length) {
					this._clear_selected_vehicle();
					this._render_no_match(query);
				} else if (matches.length === 1) {
					this.load_vehicle(matches[0].name);
				} else {
					this._clear_selected_vehicle();
					this.search_results = matches;
					this._render_disambiguation(query, matches);
				}
			},
			error: () => {
				if (seq !== this._search_seq) return;
				this._clear_selected_vehicle();
				this._render_error_state(__("Unable to search vehicles right now. Please check your permissions and try again."));
			},
		});
	}

	_state_box_html(title, subtitle = "") {
		return `
			<div class="no-result text-muted flex justify-center align-center vsh-empty-box">
				<div class="msg-box">
					<p class="bold mb-1">${this._esc(title)}</p>
					${subtitle ? `<p class="text-muted mb-0">${this._esc(subtitle)}</p>` : ""}
				</div>
			</div>
		`;
	}

	_loading_html(label) {
		return this._state_box_html(label || __("Loading service history..."));
	}

	_render_initial_empty() {
		this.$content.html(
			this._state_box_html(
				__("Lookup Vehicle Service History"),
				__(
					"Enter a vehicle Registration Number, Previous Plate, or VIN/Chassis Number above to inspect its full service, inspection, recommendation, and billing history."
				)
			)
		);
	}

	_render_no_match(query) {
		this.$content.html(
			this._state_box_html(
				__('No vehicle matched "{0}"', [query]),
				__("Check the spelling or try searching by full VIN/Chassis Number or an earlier registration plate.")
			)
		);
	}

	_render_error_state(message) {
		this.$content.html(this._state_box_html(__("Service History Unavailable"), message));
	}

	_render_disambiguation(query, matches) {
		const rowsHtml = matches
			.map((m) => {
				const modelDesc = [m.make, m.model, m.year ? `(${m.year})` : ""].filter(Boolean).join(" ");
				const prevLine = m.previous_registration_nos
					? `<div class="text-muted small">${this._esc(__("Prev"))}: ${this._esc(m.previous_registration_nos)}</div>`
					: "";
				return `
					<tr class="vsh-disambig-row pointer" data-vehicle="${this._esc(m.name)}" role="button" tabindex="0">
						<td>
							<strong>${this._esc(m.registration_no || m.name)}</strong>
							${prevLine}
						</td>
						<td>${m.match_source ? this._pill(m.match_source) : "—"}</td>
						<td>${this._esc(modelDesc || "—")}</td>
						<td><code>${this._esc(m.vin || "—")}</code></td>
						<td>${this._esc(m.customer_name || m.customer || "—")}</td>
						<td class="text-right">${this._esc(this._fmt_km(m.current_mileage))}</td>
						<td>${this._pill(m.vehicle_status || "Outside Workshop")}</td>
						<td class="text-right">
							<button type="button" class="btn btn-xs btn-default">${this._esc(__("Open"))}</button>
						</td>
					</tr>
				`;
			})
			.join("");

		this.$content.html(`
			<div class="form-section card-section">
				<div class="section-head">
					<span>${this._esc(__('Multiple Vehicles Matched "{0}" ({1})', [query, matches.length]))}</span>
				</div>
				<div class="section-body">
					<div class="w-100">
						<p class="text-muted small mb-2">${this._esc(__("Select a vehicle below to open its full service history."))}</p>
						<div class="table-responsive">
							<table class="table table-bordered table-hover vsh-table">
								<thead>
									<tr>
										<th>${this._esc(__("Registration No"))}</th>
										<th>${this._esc(__("Match"))}</th>
										<th>${this._esc(__("Vehicle"))}</th>
										<th>${this._esc(__("VIN / Chassis"))}</th>
										<th>${this._esc(__("Customer"))}</th>
										<th class="text-right">${this._esc(__("Current Mileage"))}</th>
										<th>${this._esc(__("Status"))}</th>
										<th class="text-right" style="width: 72px;">${this._esc(__("Action"))}</th>
									</tr>
								</thead>
								<tbody>${rowsHtml}</tbody>
							</table>
						</div>
					</div>
				</div>
			</div>
		`);
	}

	load_vehicle(vehicleName) {
		if (!vehicleName) {
			this._clear_selected_vehicle();
			if (this.show_search) {
				this._render_initial_empty();
			} else {
				this.$content.empty();
			}
			return;
		}

		const isSwitch = vehicleName !== this.vehicle;
		if (isSwitch) {
			this.vehicle = vehicleName;
			this.filters = this._default_filters();
			this.expanded_visits.clear();
			this.all_expanded = false;
			this.active_rec_tab = "outstanding";
			this.editable_open_order = null;
		}

		this._hide_autocomplete();
		const seq = ++this._load_seq;
		this.$content.html(this._loading_html(__("Loading service history for {0}...", [vehicleName])));

		frappe.call({
			method: "vehicle_service.service_history.get_vehicle_service_history",
			args: {
				vehicle: vehicleName,
				filters: JSON.stringify(this._active_filters_payload()),
			},
			callback: (r) => {
				if (seq !== this._load_seq) return;
				if (!r.message) {
					this._clear_selected_vehicle();
					this._render_error_state(__("No history payload returned."));
					return;
				}
				this.data = r.message;
				this.vehicle = (this.data.vehicle && this.data.vehicle.name) || vehicleName;

				if (this.show_search) {
					this._set_search_query((this.data.vehicle && this.data.vehicle.registration_no) || this.vehicle);
				}

				if (this._has_no_timeline_filters()) {
					this._resolve_editable_open_order();
				}

				this._populate_filter_options();
				this._render_full_dashboard();

				if (this.on_vehicle_selected) {
					this.on_vehicle_selected(this.data.vehicle);
				}
			},
			error: () => {
				if (seq !== this._load_seq) return;
				this._clear_selected_vehicle();
				this._render_error_state(
					__("Could not load service history for {0}. Verify the vehicle exists and you have access.", [vehicleName])
				);
			},
		});
	}

	_reload_timeline_only() {
		if (!this.vehicle) return;
		const seq = ++this._load_seq;
		const $timelineSlot = this.$content.find(".vsh-timeline-slot");
		if ($timelineSlot.length) {
			$timelineSlot.html(this._loading_html(__("Applying filters...")));
		}

		frappe.call({
			method: "vehicle_service.service_history.get_vehicle_service_history",
			args: {
				vehicle: this.vehicle,
				filters: JSON.stringify(this._active_filters_payload()),
			},
			callback: (r) => {
				if (seq !== this._load_seq || !r.message) return;
				this.data = r.message;
				const timeline = this.data.timeline || [];
				this.all_expanded =
					timeline.length > 0 &&
					timeline.every((v) => this.expanded_visits.has(v.service_order || v.vehicle_intake));
				this._render_timeline();
				this._update_toggle_all_button();
			},
			error: () => {
				if (seq !== this._load_seq) return;
				if ($timelineSlot.length) {
					$timelineSlot.html(this._state_box_html(__("Failed to apply filters. Please try again.")));
				}
			},
		});
	}

	_resolve_editable_open_order() {
		const currentOrder = this.data && this.data.vehicle && this.data.vehicle.current_service_order;
		if (!currentOrder) {
			this.editable_open_order = null;
			return;
		}
		const match = (this.data.timeline || []).find((v) => v.service_order === currentOrder);
		if (!match) {
			this.editable_open_order = null;
			return;
		}
		const lockedStatuses = ["Ready for Billing", "Invoiced", "Ready for Collection", "Delivered", "Cancelled", "Draft"];
		const hasSubmittedInvoice = Boolean(
			match.financials &&
				Array.isArray(match.financials.invoices) &&
				match.financials.invoices.some((inv) => !inv.is_return)
		);
		this.editable_open_order = !lockedStatuses.includes(match.status) && !hasSubmittedInvoice ? currentOrder : null;
	}

	_render_full_dashboard() {
		this.$content.html(`
			<div class="form-layout">
				<div class="form-page">
					<div class="vsh-kpi-slot"></div>
					<div class="vsh-header-slot"></div>
					<div class="vsh-recommendations-slot"></div>
					<div class="vsh-timeline-slot"></div>
				</div>
			</div>
		`);

		this._render_kpis();
		this._render_vehicle_header();
		this._render_recommendations();
		this._render_timeline();
	}

	_render_kpis() {
		const stats = (this.data && this.data.overview_stats) || {};
		const showFinancials =
			this._can_view_financials() &&
			stats.total_historical_service_value !== null &&
			stats.total_historical_service_value !== undefined;

		const items = [
			{ label: __("Total Visits"), value: this._esc(stats.total_visits || 0), colorClass: "blue" },
			{ label: __("Total Service Orders"), value: this._esc(stats.total_service_orders || 0), colorClass: "" },
			{ label: __("Completed Repairs"), value: this._esc(stats.total_completed_repairs || 0), colorClass: "green" },
			{
				label: __("Last Service Date"),
				value: stats.last_service_date ? this._fmt_date(stats.last_service_date) : "—",
				colorClass: "",
			},
			{
				label: __("Last Recorded Mileage"),
				value: this._esc(this._fmt_km(stats.last_recorded_mileage || 0)),
				colorClass: "",
			},
		];

		if (showFinancials) {
			items.push({
				label: __("Total Service Value"),
				value: this._fmt_currency(stats.total_historical_service_value || 0),
				colorClass: "blue",
			});
		}

		const outstandingCount = stats.outstanding_service_orders || 0;
		items.push({
			label: __("Outstanding Orders"),
			value: this._esc(outstandingCount),
			colorClass: outstandingCount > 0 ? "red" : "",
		});

		const summaryHtml = items
			.map(
				(item) => `
				<div class="summary-item">
					<div class="summary-label">${this._esc(item.label)}</div>
					<div class="summary-value ${this._esc(item.colorClass)}">${item.value}</div>
				</div>
			`
			)
			.join("");

		this.$content.find(".vsh-kpi-slot").html(`
			<div class="form-dashboard-section">
				<div class="section-head">
					<span>${this._esc(__("Overview"))}</span>
				</div>
				<div class="section-body">
					<div class="report-summary vsh-report-summary">${summaryHtml}</div>
				</div>
			</div>
		`);
	}

	_field_html(label, valueHtml) {
		return `
			<div class="frappe-control">
				<div class="form-group">
					<div class="clearfix">
						<label class="control-label">${this._esc(label)}</label>
					</div>
					<div class="control-input-wrapper">
						<div class="control-value like-disabled-input">${valueHtml}</div>
					</div>
				</div>
			</div>
		`;
	}

	_render_vehicle_header() {
		const v = (this.data && this.data.vehicle) || {};
		const c = (this.data && this.data.customer) || {};
		const clusterIds = (this.data && this.data.vehicle_ids) || [];

		const modelTitle = [v.make, v.model, v.year ? `(${v.year})` : ""].filter(Boolean).join(" ") || __("Service Vehicle");
		const specsParts = [v.colour, v.fuel_type, v.transmission, v.engine_no ? __("Engine: {0}", [v.engine_no]) : ""]
			.filter(Boolean);
		const specsText = specsParts.length ? specsParts.join(" · ") : "—";

		const customerDisplay = v.customer
			? this._doc_link("Customer", v.customer, c.customer_name || v.customer_name || v.customer)
			: `<span class="text-muted">—</span>`;
		const contactParts = [c.mobile_no || v.driver_phone, c.email_id].filter(Boolean).map((x) => this._esc(x)).join(" · ");
		const driverDisplay = v.driver_name
			? `${this._esc(v.driver_name)}${v.driver_phone ? ` (${this._esc(v.driver_phone)})` : ""}`
			: "—";
		const nextServiceParts = [
			v.next_service_date ? this._fmt_date(v.next_service_date) : null,
			v.next_service_mileage ? this._esc(this._fmt_km(v.next_service_mileage)) : null,
		]
			.filter(Boolean)
			.join(" · ");

		const prevBadge = v.previous_registration_nos
			? `<span class="indicator-pill orange">${this._esc(__("Previous Plates"))}: ${this._esc(v.previous_registration_nos)}</span>`
			: "";

		const clusterBadge =
			clusterIds.length > 1
				? `<span class="indicator-pill purple" title="${this._esc(__("Aggregated across linked vehicle records sharing this VIN"))}">${this._esc(__("Merged VIN History ({0})", [clusterIds.length]))}</span>`
				: "";

		// In embedded Service Vehicle tab, surface Export directly in the section header;
		// on the Desk Page it lives in the native page toolbar via add_inner_button.
		const embeddedExportBtn = !this.show_search
			? `<button type="button" class="btn btn-xs btn-default vsh-btn-export">
					${frappe.utils.icon("printer", "xs")}
					<span class="ml-1">${this._esc(__("Print / Export PDF"))}</span>
				</button>`
			: "";

		const regDisplay = this.show_search
			? this._doc_link("Service Vehicle", v.name, v.registration_no || v.name)
			: `<strong>${this._esc(v.registration_no || v.name)}</strong>`;

		const openOrderDisplay = v.current_service_order
			? this._doc_link("Service Order", v.current_service_order)
			: `<span class="text-muted">—</span>`;

		const col1 = [
			this._field_html(__("Registration Number"), regDisplay),
			this._field_html(__("Make / Model / Year"), this._esc(modelTitle)),
			this._field_html(__("VIN / Chassis Number"), `<code>${this._esc(v.vin || "—")}</code>`),
			this._field_html(__("Specifications"), this._esc(specsText)),
		].join("");

		const col2 = [
			this._field_html(__("Customer"), customerDisplay),
			this._field_html(__("Customer Contact"), contactParts || `<span class="text-muted">—</span>`),
			this._field_html(__("Default Driver"), driverDisplay),
			this._field_html(__("Vehicle Status"), this._pill(v.vehicle_status || "Outside Workshop")),
		].join("");

		const col3 = [
			this._field_html(__("Current Mileage"), this._esc(this._fmt_km(v.current_mileage))),
			this._field_html(__("Workshop Location"), this._esc(v.current_location || "—")),
			this._field_html(__("Active Service Order"), openOrderDisplay),
			this._field_html(__("Next Service Due"), nextServiceParts || `<span class="text-muted">—</span>`),
		].join("");

		this.$content.find(".vsh-header-slot").html(`
			<div class="form-section card-section">
				<div class="section-head vsh-section-head-flex">
					<span>${this._esc(__("Vehicle & Customer Summary"))}</span>
					<div class="vsh-head-actions">
						${prevBadge}
						${clusterBadge}
						${embeddedExportBtn}
					</div>
				</div>
				<div class="section-body">
					<div class="form-column col-sm-4">${col1}</div>
					<div class="form-column col-sm-4">${col2}</div>
					<div class="form-column col-sm-4">${col3}</div>
				</div>
			</div>
		`);
	}

	_render_recommendations() {
		const recs = (this.data && this.data.recommendations) || {};
		const outstanding = recs.outstanding || [];
		const completed = recs.completed || [];
		const advisories = recs.advisory_notes || [];
		const scheduled = recs.scheduled || [];
		this._current_recommendations = outstanding;

		const scheduledHtml = scheduled.length
			? `
			<div class="vsh-scheduled-banners mb-3">
				${scheduled
					.map((s) => {
						const msgColor = s.status === "Overdue" ? "red" : s.status === "Due Soon" ? "orange" : "blue";
						const detail =
							s.metric === "Date"
								? `${this._fmt_date(s.due_date)}${
										s.days_remaining !== null && s.days_remaining !== undefined
											? ` (${this._esc(
													s.days_remaining < 0
														? __("{0} day(s) overdue", [Math.abs(s.days_remaining)])
														: __("{0} day(s) remaining", [s.days_remaining])
												)})`
											: ""
									}`
								: `${this._esc(this._fmt_km(s.target_mileage))} (${this._esc(__("Current"))}: ${this._esc(this._fmt_km(s.current_mileage))})`;
						return `
							<div class="form-message ${msgColor} mb-2 d-flex justify-content-between align-items-center flex-wrap" style="gap: 8px;">
								<span><strong>${this._esc(s.title)}</strong> &mdash; ${detail}</span>
								${this._pill(s.status)}
							</div>
						`;
					})
					.join("")}
			</div>
		`
			: "";

		const tabs = [
			{ id: "outstanding", label: __("Outstanding"), count: outstanding.length },
			{ id: "completed", label: __("Completed"), count: completed.length },
			{ id: "advisory", label: __("Advisory Notes"), count: advisories.length },
		];

		const tabsHtml = tabs
			.map(
				(t) => `
				<li class="nav-item">
					<a class="nav-link vsh-rec-tab ${this.active_rec_tab === t.id ? "active" : ""}" href="#" data-tab="${this._esc(t.id)}" role="tab">
						<span>${this._esc(t.label)}</span>
						<span class="text-muted small">(${this._esc(t.count)})</span>
					</a>
				</li>
			`
			)
			.join("");

		let bodyHtml = "";
		if (this.active_rec_tab === "outstanding") {
			bodyHtml = this._render_outstanding_recs(outstanding);
		} else if (this.active_rec_tab === "completed") {
			bodyHtml = this._render_completed_recs(completed);
		} else {
			bodyHtml = this._render_advisory_notes(advisories);
		}

		this.$content.find(".vsh-recommendations-slot").html(`
			<div class="form-section card-section">
				<div class="section-head vsh-section-head-flex">
					<span>${this._esc(__("Maintenance & Repair Recommendations"))}</span>
					<span class="text-muted small font-weight-normal">${this._esc(__("Recommendations stay Outstanding until completed via a linked Service Job or follow-up record."))}</span>
				</div>
				<div class="section-body">
					<div class="w-100">
						${scheduledHtml}
						<div class="form-tabs-list vsh-rec-tabs-list">
							<ul class="nav form-tabs" role="tablist">${tabsHtml}</ul>
						</div>
						<div class="form-tab-content pt-2">${bodyHtml}</div>
					</div>
				</div>
			</div>
		`);
	}

	_render_outstanding_recs(items) {
		if (!items.length) {
			return `<div class="text-muted small py-3">${this._esc(__("No outstanding maintenance or repair recommendations."))}</div>`;
		}
		const canSchedule = this._can_schedule_followup() && Boolean(this.editable_open_order);
		return `
			<div class="table-responsive">
				<table class="table table-bordered table-hover vsh-table">
					<thead>
						<tr>
							<th style="width: 85px;">${this._esc(__("Type"))}</th>
							<th>${this._esc(__("Recommendation"))}</th>
							<th style="width: 115px;">${this._esc(__("Recommended On"))}</th>
							<th style="width: 145px;">${this._esc(__("Origin Order"))}</th>
							<th style="width: 135px;">${this._esc(__("Status"))}</th>
							${canSchedule ? `<th style="width: 185px;" class="text-right">${this._esc(__("Action"))}</th>` : ""}
						</tr>
					</thead>
					<tbody>
						${items
							.map((rec, idx) => {
								const desc = rec.description ? `<div class="text-muted small">${this._esc(rec.description)}</div>` : "";
								const actionCell = canSchedule
									? `<td class="text-right">
											<button type="button" class="btn btn-xs btn-default vsh-btn-followup" data-idx="${idx}">
												${this._esc(__("Schedule Follow-up Job"))}
											</button>
										</td>`
									: "";
								return `
									<tr>
										<td>${this._pill(rec.source_type || "Job", "gray")}</td>
										<td><strong>${this._esc(rec.title || "—")}</strong>${desc}</td>
										<td>${this._fmt_date(rec.recommended_on)}</td>
										<td>${this._doc_link("Service Order", rec.origin_order)}</td>
										<td>${this._pill(rec.original_status || rec.status)}</td>
										${actionCell}
									</tr>
								`;
							})
							.join("")}
					</tbody>
				</table>
			</div>
		`;
	}

	_render_completed_recs(items) {
		if (!items.length) {
			return `<div class="text-muted small py-3">${this._esc(__("No completed recommendations yet."))}</div>`;
		}
		return `
			<div class="table-responsive">
				<table class="table table-bordered table-hover vsh-table">
					<thead>
						<tr>
							<th style="width: 85px;">${this._esc(__("Type"))}</th>
							<th>${this._esc(__("Recommendation"))}</th>
							<th style="width: 115px;">${this._esc(__("Recommended On"))}</th>
							<th style="width: 145px;">${this._esc(__("Origin Order"))}</th>
							<th style="width: 220px;">${this._esc(__("Linked Completion"))}</th>
							<th style="width: 115px;">${this._esc(__("Status"))}</th>
						</tr>
					</thead>
					<tbody>
						${items
							.map((rec) => {
								const desc = rec.description ? `<div class="text-muted small">${this._esc(rec.description)}</div>` : "";
								const completionOrderLink = rec.linked_completion_order
									? this._doc_link("Service Order", rec.linked_completion_order)
									: "—";
								const completionJobLink = rec.linked_completion_job
									? `<div class="small">${this._doc_link("Service Job", rec.linked_completion_job)}</div>`
									: "";
								const completedOn = rec.completed_on
									? `<div class="text-muted small">${this._fmt_date(rec.completed_on)}</div>`
									: "";
								return `
									<tr>
										<td>${this._pill(rec.source_type || "Job", "gray")}</td>
										<td><strong>${this._esc(rec.title || "—")}</strong>${desc}</td>
										<td>${this._fmt_date(rec.recommended_on)}</td>
										<td>${this._doc_link("Service Order", rec.origin_order)}</td>
										<td>${completionOrderLink}${completionJobLink}${completedOn}</td>
										<td>${this._pill(rec.status || "Completed", "green")}</td>
									</tr>
								`;
							})
							.join("")}
					</tbody>
				</table>
			</div>
		`;
	}

	_render_advisory_notes(items) {
		if (!items.length) {
			return `<div class="text-muted small py-3">${this._esc(__("No delivery or QC advisory notes recorded."))}</div>`;
		}
		return `
			<div class="table-responsive">
				<table class="table table-bordered table-hover vsh-table">
					<thead>
						<tr>
							<th style="width: 115px;">${this._esc(__("Recorded On"))}</th>
							<th style="width: 145px;">${this._esc(__("Origin Order"))}</th>
							<th style="width: 210px;">${this._esc(__("Source"))}</th>
							<th>${this._esc(__("Advisory Note"))}</th>
							<th style="width: 135px;">${this._esc(__("Tag"))}</th>
						</tr>
					</thead>
					<tbody>
						${items
							.map(
								(adv) => `
								<tr>
									<td>${this._fmt_date(adv.recorded_on)}</td>
									<td>${this._doc_link("Service Order", adv.origin_order)}</td>
									<td><strong>${this._esc(adv.title || "—")}</strong></td>
									<td class="vsh-pre-wrap">${this._esc(adv.note || "")}</td>
									<td>${this._pill(adv.status || "Advisory Logged", "blue")}</td>
								</tr>
							`
							)
							.join("")}
					</tbody>
				</table>
			</div>
		`;
	}

	_render_timeline() {
		const timeline = (this.data && this.data.timeline) || [];
		const canFin = this._can_view_financials();
		const $slot = this.$content.find(".vsh-timeline-slot");

		const bodyContent = timeline.length
			? timeline.map((visit) => this._render_visit_card(visit, canFin)).join("")
			: this._state_box_html(
					__("No Service Visits Found"),
					__("No service visits match the current filter criteria.")
				);

		$slot.html(`
			<div class="form-section card-section hide-border">
				<div class="section-head vsh-section-head-flex">
					<span>${this._esc(__("Service Visit History"))} <span class="text-muted small font-weight-normal">(${this._esc(timeline.length)})</span></span>
					<div class="vsh-head-actions">
						${
							timeline.length
								? `<button type="button" class="btn btn-xs btn-default vsh-btn-toggle-all"></button>`
								: ""
						}
						<button type="button" class="btn btn-xs btn-default vsh-btn-reset-filters">
							${this._esc(__("Reset Filters"))}
						</button>
					</div>
				</div>
				<div class="section-body">
					<div class="w-100">${bodyContent}</div>
				</div>
			</div>
		`);

		this._update_toggle_all_button();
	}

	_render_visit_card(visit, canFin) {
		const visitKey = visit.service_order || visit.vehicle_intake || "";
		const isExpanded = this.expanded_visits.has(visitKey);
		const refDoctype = visit.service_order ? "Service Order" : "Vehicle Intake";
		const refLink = this._doc_link(refDoctype, visitKey, visitKey, "bold");

		const techNames = [];
		const seenTechs = new Set();
		(visit.jobs || []).forEach((j) => {
			const label = j.technician_name || j.technician;
			if (label && !seenTechs.has(label)) {
				seenTechs.add(label);
				techNames.push(label);
			}
		});

		const dateSummary =
			visit.work_completed_on || visit.delivered_on
				? `${this._fmt_date(visit.visit_date)} &rarr; ${this._fmt_date(visit.delivered_on || visit.work_completed_on)}`
				: this._fmt_date(visit.visit_date);

		let finSummaryHtml = "";
		if (canFin && visit.financials) {
			const fin = visit.financials;
			const amountText = fin.invoice_number
				? this._fmt_currency(fin.total_invoice_value || 0)
				: `${this._esc(__("Est."))} ${this._fmt_currency(flt(fin.labour_charges) + flt(fin.parts_charges))}`;
			finSummaryHtml = `
				<span class="bold text-color">${amountText}</span>
				${this._pill(fin.payment_status || "Not Invoiced")}
			`;
		}

		const bodyHtml = this._render_visit_body(visit, canFin);

		return `
			<div class="frappe-card-outline vsh-visit-card mb-3" data-visit-key="${this._esc(visitKey)}">
				<div class="section-head collapsible vsh-visit-header ${isExpanded ? "" : "collapsed"}" role="button" tabindex="0" aria-expanded="${isExpanded ? "true" : "false"}">
					<div class="vsh-visit-header-left">
						<span class="collapse-indicator mr-2">${frappe.utils.icon(isExpanded ? "chevron-down" : "chevron-right", "sm")}</span>
						<div class="min-w-0">
							<div class="d-flex align-items-center flex-wrap mb-1" style="gap: 6px;">
								${refLink}
								${this._pill(visit.visit_type || "Service Order", "gray")}
								${visit.order_type ? this._pill(visit.order_type, "blue") : ""}
								${visit.branch ? `<span class="text-muted small">${this._esc(visit.branch)}</span>` : ""}
							</div>
							<div class="text-muted small font-weight-normal d-flex flex-wrap" style="gap: 8px;">
								<span>${dateSummary}</span>
								<span>&middot; ${this._esc(__("Odometer"))}: ${this._esc(this._fmt_km(visit.odometer_in))}</span>
								${visit.service_advisor_name ? `<span>&middot; ${this._esc(__("Advisor"))}: ${this._esc(visit.service_advisor_name)}</span>` : ""}
								${techNames.length ? `<span>&middot; ${this._esc(__("Techs"))}: ${this._esc(techNames.join(", "))}</span>` : ""}
								<span>&middot; ${this._esc(__("{0} Job(s), {1} Part(s)", [(visit.jobs || []).length, (visit.parts || []).length]))}</span>
							</div>
						</div>
					</div>
					<div class="vsh-visit-header-right">
						${finSummaryHtml}
						${this._pill(visit.status || "Open")}
					</div>
				</div>
				<div class="vsh-visit-body" style="${isExpanded ? "" : "display: none;"}">
					${bodyHtml}
				</div>
			</div>
		`;
	}

	_render_visit_body(visit, canFin) {
		const intakeSection = this._render_visit_intake_section(visit);
		const jobsSection = this._render_visit_jobs_section(visit.jobs || [], canFin);
		const partsSection = this._render_visit_parts_section(visit.parts || [], canFin);
		const qcSection = this._render_visit_qc_section(visit.qc_inspections || []);
		const finSection = canFin && visit.financials ? this._render_visit_financials_section(visit.financials) : "";

		return `
			${intakeSection}
			${jobsSection}
			${partsSection}
			${qcSection}
			${finSection}
		`;
	}

	_kv_cell(label, valueHtml) {
		return `
			<div class="col-sm-3 mb-2">
				<div class="control-label small mb-0">${this._esc(label)}</div>
				<div class="text-color bold">${valueHtml}</div>
			</div>
		`;
	}

	_render_visit_intake_section(visit) {
		const odoText = visit.odometer_out
			? `${this._fmt_km(visit.odometer_in)} / ${this._fmt_km(visit.odometer_out)}`
			: this._fmt_km(visit.odometer_in);

		const notesBlocks = [
			{ label: __("Customer Complaint"), value: visit.customer_complaint, color: "blue" },
			{ label: __("Existing Damage"), value: visit.existing_damage, color: "red" },
			{ label: __("Declared Contents / Valuables"), value: visit.vehicle_contents, color: "blue" },
			{ label: __("Delivery Notes"), value: visit.delivery_notes, color: "blue" },
			{ label: __("Reception Notes"), value: visit.reception_notes, color: "yellow" },
			{ label: __("Hold Reason"), value: visit.hold_reason, color: "yellow" },
			{ label: __("Pause Reason"), value: visit.pause_reason, color: "yellow" },
			{ label: __("Dispute Notes"), value: visit.dispute_notes, color: "red" },
			{ label: __("Cancellation Reason"), value: visit.cancellation_reason, color: "red" },
		]
			.filter((b) => b.value && String(b.value).trim())
			.map(
				(b) => `
				<div class="col-md-6 mb-2">
					<div class="form-message ${b.color}">
						<div class="small bold mb-1">${this._esc(b.label)}</div>
						<div class="vsh-pre-wrap small">${this._esc(b.value)}</div>
					</div>
				</div>
			`
			)
			.join("");

		const photos = (visit.intake_photos || []).filter((p) => this._safe_url(p.photo));
		const photosHtml = photos.length
			? `
			<div class="mt-2">
				<div class="control-label small mb-1">${this._esc(__("Intake Inspection Photos ({0})", [photos.length]))}</div>
				<div class="vsh-photo-strip">
					${photos
						.map((p) => {
							const safeSrc = this._safe_url(p.photo);
							return `
								<button type="button" class="vsh-photo-thumb" data-src="${this._esc(safeSrc)}" data-desc="${this._esc(p.description || "")}" data-taken="${this._esc(p.taken_on || "")}" title="${this._esc(p.description || __("View intake photo"))}">
									<img src="${this._esc(safeSrc)}" alt="${this._esc(p.description || __("Vehicle intake photo"))}" loading="lazy" />
									${p.description ? `<span class="vsh-photo-caption">${this._esc(p.description)}</span>` : ""}
								</button>
							`;
						})
						.join("")}
				</div>
			</div>
		`
			: "";

		return `
			<div class="vsh-visit-sub">
				<div class="control-label bold mb-2">${this._esc(__("Visit & Intake Condition"))}</div>
				<div class="row">
					${this._kv_cell(__("Checked In"), this._fmt_datetime(visit.checked_in_on))}
					${this._kv_cell(__("Completed / Delivered"), this._fmt_datetime(visit.delivered_on || visit.work_completed_on))}
					${this._kv_cell(__("Odometer In / Out"), this._esc(odoText))}
					${this._kv_cell(__("Fuel Level"), this._esc(visit.fuel_level || "—"))}
					${this._kv_cell(__("Service Advisor"), this._esc(visit.service_advisor_name || "—"))}
					${this._kv_cell(__("Collected By"), this._esc(visit.collected_by || "—"))}
					${this._kv_cell(__("Vehicle Intake"), visit.vehicle_intake ? this._doc_link("Vehicle Intake", visit.vehicle_intake) : "—")}
					${this._kv_cell(__("Branch / Company"), this._esc([visit.branch, visit.company].filter(Boolean).join(" · ") || "—"))}
				</div>
				${notesBlocks ? `<div class="row mt-1">${notesBlocks}</div>` : ""}
				${photosHtml}
			</div>
		`;
	}

	_render_visit_jobs_section(jobs, canFin) {
		if (!jobs.length) {
			return `
				<div class="vsh-visit-sub">
					<div class="control-label bold mb-2">${this._esc(__("Jobs & Labour"))}</div>
					<div class="text-muted small">${this._esc(__("No workshop jobs recorded for this visit."))}</div>
				</div>
			`;
		}

		return `
			<div class="vsh-visit-sub">
				<div class="control-label bold mb-2">${this._esc(__("Jobs & Labour ({0})", [jobs.length]))}</div>
				<div class="table-responsive">
					<table class="table table-bordered table-hover vsh-table">
						<thead>
							<tr>
								<th style="width: 36px;" class="text-center">#</th>
								<th>${this._esc(__("Job Description"))}</th>
								<th style="width: 105px;">${this._esc(__("Category"))}</th>
								<th style="width: 125px;">${this._esc(__("Status"))}</th>
								<th style="width: 140px;">${this._esc(__("Technician"))}</th>
								<th style="width: 115px;">${this._esc(__("Bay"))}</th>
								<th style="width: 95px;" class="text-right">${this._esc(__("Est / Act Hrs"))}</th>
								${canFin ? `<th style="width: 95px;" class="text-right">${this._esc(__("Rate"))}</th><th style="width: 105px;" class="text-right">${this._esc(__("Amount"))}</th>` : ""}
							</tr>
						</thead>
						<tbody>
							${jobs
								.map((j, idx) => {
									const notes = [];
									if (j.description) notes.push(`<div>${this._esc(j.description)}</div>`);
									if (j.reason_for_adding) {
										notes.push(`<div><em>${this._esc(__("Reason Added"))}:</em> ${this._esc(j.reason_for_adding)}</div>`);
									}
									if (j.pause_reason) {
										notes.push(`<div><em>${this._esc(__("Pause Reason"))}:</em> ${this._esc(j.pause_reason)}</div>`);
									}
									if (j.qc_fail_reason) {
										notes.push(`<div class="text-danger"><em>${this._esc(__("QC Fail Reason"))}:</em> ${this._esc(j.qc_fail_reason)}</div>`);
									}
									if (j.follows_up_job) {
										notes.push(`<div><em>${this._esc(__("Follows Up"))}:</em> ${this._doc_link("Service Job", j.follows_up_job)}</div>`);
									}
									const finCols = canFin
										? `<td class="text-right">${this._fmt_currency(j.rate || 0)}</td><td class="text-right"><strong>${this._fmt_currency(j.amount || 0)}</strong></td>`
										: "";
									return `
										<tr>
											<td class="text-center">${idx + 1}</td>
											<td>
												<strong>${this._esc(j.job_title || "—")}</strong>
												${j.service_job ? `<span class="text-muted small ml-1">(${this._doc_link("Service Job", j.service_job)})</span>` : ""}
												${notes.length ? `<div class="text-muted small mt-1">${notes.join("")}</div>` : ""}
											</td>
											<td>${this._esc(j.category || "Essential")}</td>
											<td>${this._pill(j.status || "Open")}</td>
											<td>${this._esc(j.technician_name || j.technician || __("Unassigned"))}</td>
											<td>${this._esc(j.bay || "—")}</td>
											<td class="text-right">${this._esc(`${this._fmt_num(j.estimated_hours || 0, 1)} / ${this._fmt_num(j.actual_hours || 0, 1)}`)}</td>
											${finCols}
										</tr>
									`;
								})
								.join("")}
						</tbody>
					</table>
				</div>
			</div>
		`;
	}

	_render_visit_parts_section(parts, canFin) {
		if (!parts.length) {
			return "";
		}

		return `
			<div class="vsh-visit-sub">
				<div class="control-label bold mb-2">${this._esc(__("Parts & Materials ({0})", [parts.length]))}</div>
				<div class="table-responsive">
					<table class="table table-bordered table-hover vsh-table">
						<thead>
							<tr>
								<th style="width: 36px;" class="text-center">#</th>
								<th>${this._esc(__("Part / Item"))}</th>
								<th style="width: 125px;">${this._esc(__("Status"))}</th>
								<th style="width: 65px;" class="text-right">${this._esc(__("Req"))}</th>
								<th style="width: 65px;" class="text-right">${this._esc(__("Issued"))}</th>
								<th style="width: 65px;" class="text-right">${this._esc(__("Ret"))}</th>
								<th style="width: 65px;" class="text-right">${this._esc(__("Used"))}</th>
								${canFin ? `<th style="width: 100px;" class="text-right">${this._esc(__("Rate"))}</th>` : ""}
							</tr>
						</thead>
						<tbody>
							${parts
								.map((p, idx) => {
									const partSubNotes = [];
									if (p.item_code && p.item_name && p.item_code !== p.item_name) {
										partSubNotes.push(`<span class="text-muted small">(${this._esc(p.item_code)})</span>`);
									}
									if (p.reason_for_adding) {
										partSubNotes.push(`<div class="text-muted small"><em>${this._esc(__("Reason Added"))}:</em> ${this._esc(p.reason_for_adding)}</div>`);
									}
									if (p.substituted_by) {
										partSubNotes.push(`<div class="text-muted small"><em>${this._esc(__("Substituted By"))}:</em> ${this._esc(p.substituted_by)}</div>`);
									}
									const statusLabel = p.part_status || p.approval_status || "Required";
									return `
										<tr>
											<td class="text-center">${idx + 1}</td>
											<td><strong>${this._esc(p.item_name || p.item_code || "—")}</strong> ${partSubNotes.join("")}</td>
											<td>${this._pill(statusLabel)}</td>
											<td class="text-right">${this._esc(this._fmt_num(p.qty_required || 0, 2))}</td>
											<td class="text-right">${this._esc(this._fmt_num(p.qty_issued || 0, 2))}</td>
											<td class="text-right">${this._esc(this._fmt_num(p.qty_returned || 0, 2))}</td>
											<td class="text-right"><strong>${this._esc(this._fmt_num(p.qty_used || 0, 2))}</strong></td>
											${canFin ? `<td class="text-right">${this._fmt_currency(p.rate || 0)}</td>` : ""}
										</tr>
									`;
								})
								.join("")}
						</tbody>
					</table>
				</div>
			</div>
		`;
	}

	_render_visit_qc_section(qcs) {
		if (!qcs.length) return "";

		return `
			<div class="vsh-visit-sub">
				<div class="control-label bold mb-2">${this._esc(__("Quality Control Inspection ({0})", [qcs.length]))}</div>
				${qcs
					.map((qc) => {
						const roadTest = qc.road_test_done
							? `${__("Yes")}${qc.road_test_km ? ` (${this._fmt_num(qc.road_test_km, 1)} km)` : ""}`
							: __("No");
						const checklistHtml =
							qc.checklist && qc.checklist.length
								? `
								<div class="table-responsive mt-2">
									<table class="table table-bordered vsh-table">
										<thead>
											<tr>
												<th>${this._esc(__("Check Item"))}</th>
												<th style="width: 90px;">${this._esc(__("Result"))}</th>
												<th>${this._esc(__("Remarks"))}</th>
											</tr>
										</thead>
										<tbody>
											${qc.checklist
												.map(
													(chk) => `
													<tr>
														<td>${this._esc(chk.check_item || "—")}</td>
														<td>${this._pill(chk.passed ? __("Pass") : __("Fail"), chk.passed ? "green" : "red")}</td>
														<td>${this._esc(chk.remarks || "—")}</td>
													</tr>
												`
												)
												.join("")}
										</tbody>
									</table>
								</div>
							`
								: "";

						return `
							<div class="frappe-card-outline mb-2">
								<div class="d-flex flex-wrap align-items-center" style="gap: 12px;">
									<div>${this._doc_link("Service QC", qc.name)} ${this._pill(qc.result || "Pending")}</div>
									<div class="small"><span class="text-muted">${this._esc(__("Inspector"))}:</span> ${this._esc(qc.inspector || "—")}</div>
									<div class="small"><span class="text-muted">${this._esc(__("Inspected On"))}:</span> ${this._fmt_datetime(qc.inspected_on)}</div>
									<div class="small"><span class="text-muted">${this._esc(__("Road Test"))}:</span> ${this._esc(roadTest)}</div>
								</div>
								${qc.findings ? `<div class="small mt-2"><strong>${this._esc(__("Findings"))}:</strong> <span class="vsh-pre-wrap">${this._esc(qc.findings)}</span></div>` : ""}
								${qc.fail_reason ? `<div class="small mt-1 text-danger"><strong>${this._esc(__("Fail Reason"))}:</strong> <span class="vsh-pre-wrap">${this._esc(qc.fail_reason)}</span></div>` : ""}
								${checklistHtml}
							</div>
						`;
					})
					.join("")}
			</div>
		`;
	}

	_render_visit_financials_section(fin) {
		const invLink = fin.invoice_number
			? this._doc_link("Sales Invoice", fin.invoice_number)
			: `<span class="text-muted">${this._esc(__("Not Invoiced"))}</span>`;

		const creditNotesHtml =
			fin.credit_notes && fin.credit_notes.length
				? `<span class="text-muted small ml-2">(${this._esc(__("Credit Notes"))}: ${fin.credit_notes
						.map((cn) => this._doc_link("Sales Invoice", cn))
						.join(", ")})</span>`
				: "";

		const paymentsHtml =
			fin.payments && fin.payments.length
				? `
				<div class="mt-2 pt-2 border-top">
					<div class="control-label small bold mb-1">${this._esc(__("Recorded Payments"))}</div>
					<div class="table-responsive">
						<table class="table table-bordered vsh-table">
							<thead>
								<tr>
									<th>${this._esc(__("Payment Entry"))}</th>
									<th>${this._esc(__("Date"))}</th>
									<th>${this._esc(__("Mode"))}</th>
									<th>${this._esc(__("Reference"))}</th>
									<th class="text-right">${this._esc(__("Allocated"))}</th>
								</tr>
							</thead>
							<tbody>
								${fin.payments
									.map(
										(pay) => `
										<tr>
											<td>${this._doc_link("Payment Entry", pay.payment_entry)}</td>
											<td>${this._fmt_date(pay.posting_date)}</td>
											<td>${this._esc(pay.mode_of_payment || pay.payment_type || "—")}</td>
											<td>${this._esc(pay.reference_no || "—")}</td>
											<td class="text-right">${this._fmt_currency(pay.allocated_amount || 0)}</td>
										</tr>
									`
									)
									.join("")}
							</tbody>
						</table>
					</div>
				</div>
			`
				: "";

		return `
			<div class="vsh-visit-sub">
				<div class="frappe-card-outline">
					<div class="d-flex justify-content-between align-items-center flex-wrap mb-2" style="gap: 8px;">
						<div>
							<span class="control-label bold mr-2">${this._esc(__("Financial Summary"))}</span>
							${invLink}
							${creditNotesHtml}
						</div>
						<div>${this._pill(fin.payment_status || "Not Invoiced")}</div>
					</div>
					<div class="row">
						${this._kv_cell(__("Labour Charges"), this._fmt_currency(fin.labour_charges || 0))}
						${this._kv_cell(__("Parts Charges"), this._fmt_currency(fin.parts_charges || 0))}
						${this._kv_cell(__("Additional / Taxes"), this._fmt_currency(fin.additional_charges || 0))}
						${this._kv_cell(__("Discounts"), this._fmt_currency(fin.discounts || 0))}
						${this._kv_cell(__("Paid Amount"), this._fmt_currency(fin.paid_amount || 0))}
						${this._kv_cell(__("Outstanding Amount"), this._fmt_currency(fin.outstanding_amount || 0))}
						${this._kv_cell(__("Total Invoice Value"), this._fmt_currency(fin.total_invoice_value || 0))}
					</div>
					${paymentsHtml}
				</div>
			</div>
		`;
	}

	_open_photo_modal(src, desc, taken) {
		const safeSrc = this._safe_url(src);
		if (!safeSrc) return;
		const d = new frappe.ui.Dialog({
			title: this._esc(desc || __("Vehicle Intake Photo")),
			size: "large",
			fields: [{ fieldname: "preview", fieldtype: "HTML" }],
		});
		const metaHtml = taken
			? `<div class="text-muted small mt-2">${this._esc(__("Taken On"))}: ${this._fmt_datetime(taken)}</div>`
			: "";
		d.fields_dict.preview.$wrapper.html(`
			<div class="text-center p-2">
				<img src="${this._esc(safeSrc)}" alt="${this._esc(desc || __("Intake Photo"))}" class="vsh-photo-preview-img" />
				${desc ? `<div class="mt-2 bold">${this._esc(desc)}</div>` : ""}
				${metaHtml}
			</div>
		`);
		d.show();
	}

	_open_followup_dialog(rec) {
		if (!this.editable_open_order) {
			frappe.msgprint(__("An open, editable Service Order is required before scheduling a follow-up job."));
			return;
		}
		const targetOrder = this.editable_open_order;
		const followsUpJob = rec.source_type === "Job" ? rec.source_id : null;
		const defaultTitle =
			rec.source_type === "Part"
				? `${__("Install / Replace")}: ${rec.title || ""}`.trim()
				: rec.title || "";
		const defaultReason = rec.origin_order
			? __("Follow-up to {0} recommendation from {1}", [rec.source_type || "service", rec.origin_order])
			: __("Follow-up to prior recommendation");

		const d = new frappe.ui.Dialog({
			title: this._esc(__("Schedule Follow-up Job ({0})", [targetOrder])),
			fields: [
				{
					fieldname: "service_order",
					label: __("Active Service Order"),
					fieldtype: "Data",
					default: targetOrder,
					read_only: 1,
				},
				{
					fieldname: "job_title",
					label: __("Job Title"),
					fieldtype: "Data",
					default: defaultTitle,
					reqd: 1,
				},
				{
					fieldname: "service_item",
					label: __("Service Item"),
					fieldtype: "Link",
					options: "Item",
					default: "LABOUR",
					reqd: 1,
					get_query: () => ({ filters: { is_stock_item: 0 } }),
				},
				{
					fieldname: "estimated_hours",
					label: __("Estimated Hours"),
					fieldtype: "Float",
					default: 1.0,
					reqd: 1,
				},
				{ fieldname: "cb_1", fieldtype: "Column Break" },
				{
					fieldname: "category",
					label: __("Category"),
					fieldtype: "Select",
					options: "Essential\nRecommended\nOptional",
					default: "Essential",
					reqd: 1,
				},
				{
					fieldname: "priority",
					label: __("Priority"),
					fieldtype: "Select",
					options: "Low\nMedium\nHigh\nUrgent",
					default: "Medium",
					reqd: 1,
				},
				{
					fieldname: "technician",
					label: __("Assign Technician"),
					fieldtype: "Link",
					options: "Employee",
				},
				{
					fieldname: "bay",
					label: __("Workshop Bay"),
					fieldtype: "Link",
					options: "Workshop Location",
				},
				{ fieldname: "sb_notes", fieldtype: "Section Break" },
				{
					fieldname: "reason",
					label: __("Reason for Adding"),
					fieldtype: "Small Text",
					default: defaultReason,
				},
				{
					fieldname: "description",
					label: __("Job Scope / Description"),
					fieldtype: "Small Text",
					default: rec.description || "",
				},
			],
			primary_action_label: __("Create Follow-up Job"),
			primary_action: (vals) => {
				frappe.call({
					method: "vehicle_service.job_control.add_job",
					args: {
						service_order: targetOrder,
						job_title: vals.job_title,
						service_item: vals.service_item,
						estimated_hours: vals.estimated_hours,
						category: vals.category,
						priority: vals.priority,
						technician: vals.technician || null,
						bay: vals.bay || null,
						reason: vals.reason || null,
						description: vals.description || null,
						follows_up_job: followsUpJob,
					},
					freeze: true,
					freeze_message: __("Scheduling Follow-up Job..."),
					callback: (r) => {
						if (!r.exc) {
							d.hide();
							frappe.show_alert({
								message: __("Follow-up job added to {0}", [this._esc(targetOrder)]),
								indicator: "green",
							});
							this.load_vehicle(this.vehicle);
						}
					},
				});
			},
		});
		d.show();
	}

	open_export_dialog() {
		if (!this.vehicle) return;
		const canFin = this._can_view_financials();

		const fields = [
			{
				fieldname: "mode",
				label: __("Report Version"),
				fieldtype: "Select",
				options: [
					{ label: __("Complete Service History (Internal)"), value: "internal" },
					{ label: __("Customer-Friendly Version"), value: "customer" },
				],
				default: "internal",
				reqd: 1,
			},
			{
				fieldname: "include_financials",
				label: __("Include Financial & Invoice Summary"),
				fieldtype: "Check",
				default: canFin ? 1 : 0,
				hidden: canFin ? 0 : 1,
			},
			{
				fieldname: "apply_filters",
				label: __("Apply Current Timeline Filters"),
				fieldtype: "Check",
				default: 1,
			},
		];

		const resolveExportParams = (vals) => {
			const mode = vals.mode === "customer" ? "customer" : "internal";
			const includeFinancials = canFin && cint(vals.include_financials) ? 1 : 0;
			const filters = cint(vals.apply_filters) ? this._active_filters_payload() : {};
			return {
				vehicle: this.vehicle,
				mode,
				include_financials: includeFinancials,
				filters: JSON.stringify(filters),
			};
		};

		const d = new frappe.ui.Dialog({
			title: __("Print / Export Vehicle Service History"),
			fields,
			primary_action_label: __("Export PDF"),
			primary_action: (vals) => {
				const params = resolveExportParams(vals);
				d.hide();
				if (typeof window.open_url_post === "function") {
					const form = window.open_url_post(
						"/api/method/vehicle_service.service_history.download_vehicle_service_history_pdf",
						params,
						true
					);
					if (form && form.remove) {
						setTimeout(() => form.remove(), 1500);
					}
				} else {
					const qs = new URLSearchParams(params).toString();
					window.open(`/api/method/vehicle_service.service_history.download_vehicle_service_history_pdf?${qs}`, "_blank");
				}
			},
			secondary_action_label: __("Print Report"),
			secondary_action: () => {
				const vals = d.get_values();
				if (!vals) return;
				const params = resolveExportParams(vals);
				frappe.call({
					method: "vehicle_service.service_history.render_vehicle_service_history_print",
					args: params,
					freeze: true,
					freeze_message: __("Preparing printable report..."),
					callback: (r) => {
						if (r.exc || !r.message) return;
						d.hide();
						const printWin = window.open("", "_blank");
						if (!printWin) {
							frappe.msgprint(__("Pop-up blocked. Please allow pop-ups to print the service history report."));
							return;
						}
						printWin.document.open();
						printWin.document.write(r.message);
						printWin.document.close();
						let printed = false;
						const triggerPrint = () => {
							if (printed || printWin.closed) return;
							printed = true;
							try {
								printWin.focus();
								printWin.print();
							} catch (e) {}
						};
						printWin.addEventListener("load", () => setTimeout(triggerPrint, 150), { once: true });
						setTimeout(triggerPrint, 700);
					},
				});
			},
		});
		d.show();
	}
};
