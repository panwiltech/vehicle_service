// Copyright (c) 2026, Azazel and contributors
// For license information, please see license.txt

frappe.provide("vehicle_service");

vehicle_service.VehicleServiceHistoryView = class VehicleServiceHistoryView {
	constructor(opts = {}) {
		this.$parent = $(opts.parent);
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

		this._render_shell();
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

	_doc_link(doctype, name, label = null, cls = "vsh-link") {
		if (!name) return `<span class="vsh-muted">—</span>`;
		const slug = this._doc_slug(doctype);
		const href = `/app/${slug}/${encodeURIComponent(name)}`;
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

	_status_tone(status) {
		const s = String(status || "").toLowerCase();
		if (
			["delivered", "completed", "passed", "paid", "pass", "ready for collection", "outside workshop"].includes(s)
		) {
			return "green";
		}
		if (["in progress", "approved", "ready for work", "checked in", "invoiced", "ready for billing", "in workshop"].includes(s)) {
			return "blue";
		}
		if (["paused", "waiting for parts", "waiting", "awaiting approval", "pending approval", "partly paid", "due", "recommended"].includes(s)) {
			return "amber";
		}
		if (["qc", "quality control"].includes(s)) {
			return "purple";
		}
		if (["cancelled", "declined", "fail", "qc failed", "overdue", "unpaid"].includes(s)) {
			return "red";
		}
		return "slate";
	}

	_pill(text, tone = null) {
		const resolved = tone || this._status_tone(text);
		return `<span class="vsh-pill vsh-pill--${this._esc(resolved)}">${this._esc(text || "—")}</span>`;
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

	_render_shell() {
		this.$parent.empty();

		const searchHtml = this.show_search
			? `
			<div class="vsh-search-card">
				<div class="vsh-search-bar-row">
					<div class="vsh-search-input-wrap">
						<i class="fa fa-search vsh-search-icon" aria-hidden="true"></i>
						<input
							type="text"
							class="form-control vsh-search-input"
							placeholder="${this._esc(__("Enter Registration Number, Previous Plate, or VIN/Chassis No..."))}"
							autocomplete="off"
							aria-label="${this._esc(__("Search vehicle by registration number or VIN"))}"
							aria-expanded="false"
						/>
						<button type="button" class="vsh-search-clear" title="${this._esc(__("Clear search"))}" style="display: none;">
							<i class="fa fa-times" aria-hidden="true"></i>
						</button>
						<div class="vsh-autocomplete" role="listbox" style="display: none;"></div>
					</div>
					<button type="button" class="btn btn-primary vsh-search-btn">
						<i class="fa fa-search mr-1" aria-hidden="true"></i>${this._esc(__("Lookup Vehicle"))}
					</button>
				</div>
			</div>
		`
			: "";

		this.$root = $(`
			<div class="vsh-root ${this.show_search ? "vsh-root--page" : "vsh-root--embedded"}">
				${searchHtml}
				<div class="vsh-content"></div>
			</div>
		`).appendTo(this.$parent);

		this.$content = this.$root.find(".vsh-content");
		this.$search_input = this.$root.find(".vsh-search-input");
		this.$search_clear = this.$root.find(".vsh-search-clear");
		this.$autocomplete = this.$root.find(".vsh-autocomplete");
	}

	_bind_events() {
		if (this.show_search) {
			this.$search_input.on("input", () => {
				const query = (this.$search_input.val() || "").trim();
				this.$search_clear.toggle(Boolean(query));
				clearTimeout(this.search_timer);
				if (!query) {
					this._hide_autocomplete();
					return;
				}
				this.search_timer = setTimeout(() => this._fetch_autocomplete(query), 250);
			});

			this.$search_input.on("keydown", (e) => {
				if (e.key === "ArrowDown") {
					if (this.search_results.length && this.$autocomplete.is(":visible")) {
						e.preventDefault();
						this.active_dropdown_index = Math.min(
							this.active_dropdown_index + 1,
							this.search_results.length - 1
						);
						this._highlight_autocomplete_item();
					}
				} else if (e.key === "ArrowUp") {
					if (this.search_results.length && this.$autocomplete.is(":visible")) {
						e.preventDefault();
						this.active_dropdown_index = Math.max(this.active_dropdown_index - 1, 0);
						this._highlight_autocomplete_item();
					}
				} else if (e.key === "Escape") {
					this._hide_autocomplete();
				} else if (e.key === "Enter") {
					e.preventDefault();
					if (
						this.$autocomplete.is(":visible") &&
						this.active_dropdown_index >= 0 &&
						this.search_results[this.active_dropdown_index]
					) {
						this._select_search_candidate(this.search_results[this.active_dropdown_index]);
					} else {
						this.search_and_resolve(this.$search_input.val());
					}
				}
			});

			this.$search_clear.on("click", () => {
				this.$search_input.val("").focus();
				this.$search_clear.hide();
				this._hide_autocomplete();
			});

			this.$root.find(".vsh-search-btn").on("click", () => {
				this.search_and_resolve(this.$search_input.val());
			});

			this.$autocomplete.on("click", ".vsh-autocomplete-item", (e) => {
				const idx = cint($(e.currentTarget).attr("data-index"));
				const item = this.search_results[idx];
				if (item) {
					this._select_search_candidate(item);
				}
			});

			this._outside_click_handler = (e) => {
				if (!this.$root || !this.$root.length) return;
				if (!$(e.target).closest(this.$root.find(".vsh-search-input-wrap")).length) {
					this._hide_autocomplete();
				}
			};
			$(document).on("click", this._outside_click_handler);
		}

		// Disambiguation card selection
		this.$content.on("click", ".vsh-disambig-card", (e) => {
			const name = $(e.currentTarget).attr("data-vehicle");
			if (name) {
				this.load_vehicle(name);
			}
		});
		this.$content.on("keydown", ".vsh-disambig-card", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				const name = $(e.currentTarget).attr("data-vehicle");
				if (name) {
					this.load_vehicle(name);
				}
			}
		});

		// Quick actions
		this.$content.on("click", ".vsh-btn-open-vehicle", () => {
			if (this.vehicle) frappe.set_route("Form", "Service Vehicle", this.vehicle);
		});
		this.$content.on("click", ".vsh-btn-view-open-order", () => {
			const order = this.data && this.data.vehicle && this.data.vehicle.current_service_order;
			if (order) frappe.set_route("Form", "Service Order", order);
		});
		this.$content.on("click", ".vsh-btn-new-order", () => {
			const v = (this.data && this.data.vehicle) || {};
			frappe.new_doc("Service Order", {
				vehicle: v.name,
				customer: v.customer,
				driver_name: v.driver_name,
				driver_phone: v.driver_phone,
			});
		});
		this.$content.on("click", ".vsh-btn-export", () => {
			this.open_export_dialog();
		});

		// Recommendations tabs & follow-up modal
		this.$content.on("click", ".vsh-rec-tab", (e) => {
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

		// Filter bar changes
		this.$content.on("change", ".vsh-filter-control", (e) => {
			const $el = $(e.currentTarget);
			const key = $el.attr("data-filter");
			if (!key) return;
			this.filters[key] = $el.val() || "";
			this._reload_timeline_only();
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
		const $chevron = $card.find(".vsh-visit-chevron");
		const isOpen = this.expanded_visits.has(key);

		if (isOpen) {
			this.expanded_visits.delete(key);
			$body.slideUp(140);
			$card.removeClass("is-expanded");
			$header.attr("aria-expanded", "false");
			$chevron.removeClass("fa-chevron-down").addClass("fa-chevron-right");
		} else {
			this.expanded_visits.add(key);
			$body.slideDown(140);
			$card.addClass("is-expanded");
			$header.attr("aria-expanded", "true");
			$chevron.removeClass("fa-chevron-right").addClass("fa-chevron-down");
		}

		const timeline = (this.data && this.data.timeline) || [];
		this.all_expanded = timeline.length > 0 && timeline.every((v) => this.expanded_visits.has(v.service_order || v.vehicle_intake));
		this._update_toggle_all_button();
	}

	_update_toggle_all_button() {
		const $btn = this.$content.find(".vsh-btn-toggle-all");
		if (!$btn.length) return;
		$btn.html(
			this.all_expanded
				? `<i class="fa fa-compress mr-1"></i>${this._esc(__("Collapse All"))}`
				: `<i class="fa fa-expand mr-1"></i>${this._esc(__("Expand All"))}`
		);
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

	_match_badge_html(source) {
		if (!source) return "";
		let tone = "slate";
		if (source === "Previous Registration") tone = "amber";
		else if (source === "Historical Record") tone = "purple";
		else if (source === "VIN") tone = "blue";
		else if (source === "Registration") tone = "green";
		return `<span class="vsh-pill vsh-pill--${tone} vsh-match-badge">${this._esc(source)}</span>`;
	}

	_render_autocomplete(query) {
		if (!this.search_results.length) {
			this.$autocomplete
				.html(
					`<div class="vsh-autocomplete-empty">${this._esc(
						__("No matching vehicles found for \"{0}\"", [query])
					)}</div>`
				)
				.show();
			this.$search_input.attr("aria-expanded", "true");
			return;
		}

		const itemsHtml = this.search_results
			.map((item, idx) => {
				const modelDesc = [item.make, item.model, item.year ? `(${item.year})` : ""].filter(Boolean).join(" ");
				const prevHtml = item.previous_registration_nos
					? `<span class="vsh-muted text-xs ml-1">(${this._esc(__("Prev"))}: ${this._esc(item.previous_registration_nos)})</span>`
					: "";
				return `
					<div class="vsh-autocomplete-item" role="option" data-index="${idx}">
						<div class="vsh-ac-top">
							<div>
								<strong class="vsh-ac-plate">${this._esc(item.registration_no || item.name)}</strong>
								${prevHtml}
								${this._match_badge_html(item.match_source)}
							</div>
							<div>${this._pill(item.vehicle_status || "Outside Workshop")}</div>
						</div>
						<div class="vsh-ac-meta">
							<span>${this._esc(modelDesc || "—")}</span>
							<span>&middot; VIN: <code>${this._esc(item.vin || "—")}</code></span>
							<span>&middot; ${this._esc(item.customer_name || item.customer || "—")}</span>
						</div>
					</div>
				`;
			})
			.join("");

		this.$autocomplete.html(itemsHtml).show();
		this.$search_input.attr("aria-expanded", "true");
	}

	_highlight_autocomplete_item() {
		const $items = this.$autocomplete.find(".vsh-autocomplete-item");
		$items.removeClass("is-active");
		if (this.active_dropdown_index >= 0) {
			const $active = $items.eq(this.active_dropdown_index);
			$active.addClass("is-active");
			if ($active[0] && $active[0].scrollIntoView) {
				$active[0].scrollIntoView({ block: "nearest" });
			}
		}
	}

	_hide_autocomplete() {
		if (this.$autocomplete) {
			this.$autocomplete.hide().empty();
		}
		if (this.$search_input) {
			this.$search_input.attr("aria-expanded", "false");
		}
		this.active_dropdown_index = -1;
	}

	_select_search_candidate(item) {
		this._hide_autocomplete();
		if (this.$search_input && this.$search_input.length) {
			this.$search_input.val(item.registration_no || item.name);
			this.$search_clear.show();
		}
		this.load_vehicle(item.name);
	}

	_clear_selected_vehicle() {
		this.vehicle = null;
		this.data = null;
		this.editable_open_order = null;
		if (this.on_vehicle_selected) {
			this.on_vehicle_selected(null);
		}
	}

	search_and_resolve(rawQuery) {
		const query = String(rawQuery || "").trim();
		clearTimeout(this.search_timer);
		this._hide_autocomplete();

		if (this.$search_input && this.$search_input.length) {
			this.$search_input.val(query);
			this.$search_clear.toggle(Boolean(query));
		}

		if (!query) {
			this._render_initial_empty();
			return;
		}

		const seq = ++this._search_seq;
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
				this._render_error_state(__("Unable to search vehicles right now. Please check your permissions and try again."));
			},
		});
	}

	_loading_html(label) {
		return `
			<div class="vsh-state-box">
				<div class="vsh-spinner" aria-hidden="true"></div>
				<div class="vsh-state-title">${this._esc(label || __("Loading service history..."))}</div>
			</div>
		`;
	}

	_render_initial_empty() {
		this.$content.html(`
			<div class="vsh-state-box">
				<div class="vsh-state-icon"><i class="fa fa-car" aria-hidden="true"></i></div>
				<div class="vsh-state-title">${this._esc(__("Lookup Vehicle Service History"))}</div>
				<div class="vsh-state-sub">${this._esc(__("Enter a vehicle Registration Number (Number Plate), Previous Plate, or VIN/Chassis Number above to inspect its full maintenance, inspection, recommendation, and billing history."))}</div>
			</div>
		`);
	}

	_render_no_match(query) {
		this.$content.html(`
			<div class="vsh-state-box vsh-state-box--warning">
				<div class="vsh-state-icon"><i class="fa fa-search" aria-hidden="true"></i></div>
				<div class="vsh-state-title">${this._esc(__("No vehicle matched \"{0}\"", [query]))}</div>
				<div class="vsh-state-sub">${this._esc(__("Check the spelling or try searching by full VIN/Chassis Number or an earlier registration plate."))}</div>
			</div>
		`);
	}

	_render_error_state(message) {
		this.$content.html(`
			<div class="vsh-state-box vsh-state-box--error">
				<div class="vsh-state-icon"><i class="fa fa-exclamation-triangle" aria-hidden="true"></i></div>
				<div class="vsh-state-title">${this._esc(__("Service History Unavailable"))}</div>
				<div class="vsh-state-sub">${this._esc(message)}</div>
			</div>
		`);
	}

	_render_disambiguation(query, matches) {
		const cardsHtml = matches
			.map((m) => {
				const modelDesc = [m.make, m.model, m.year ? `(${m.year})` : ""].filter(Boolean).join(" ");
				return `
					<div class="vsh-disambig-card" data-vehicle="${this._esc(m.name)}" role="button" tabindex="0">
						<div class="vsh-disambig-top">
							<div>
								<span class="vsh-plate-badge vsh-plate-badge--sm">${this._esc(m.registration_no || m.name)}</span>
								${this._match_badge_html(m.match_source)}
							</div>
							${this._pill(m.vehicle_status || "Outside Workshop")}
						</div>
						${
							m.previous_registration_nos
								? `<div class="vsh-muted text-xs mt-1">${this._esc(__("Previous Plates"))}: <strong>${this._esc(m.previous_registration_nos)}</strong></div>`
								: ""
						}
						<div class="vsh-disambig-title">${this._esc(modelDesc || "—")}</div>
						<div class="vsh-disambig-meta">
							<div><span class="vsh-muted">${this._esc(__("VIN"))}:</span> <code>${this._esc(m.vin || "—")}</code></div>
							<div><span class="vsh-muted">${this._esc(__("Customer"))}:</span> ${this._esc(m.customer_name || m.customer || "—")}</div>
							<div><span class="vsh-muted">${this._esc(__("Mileage"))}:</span> ${this._esc(this._fmt_km(m.current_mileage))}</div>
						</div>
						<div class="vsh-disambig-cta">${this._esc(__("View Service History"))} &rarr;</div>
					</div>
				`;
			})
			.join("");

		this.$content.html(`
			<div class="vsh-disambig-section">
				<div class="vsh-disambig-header">
					<h5>${this._esc(__("Multiple Vehicles Matched \"{0}\"", [query]))}</h5>
					<span class="vsh-muted">${this._esc(__("{0} vehicles found — select one to open its full history.", [matches.length]))}</span>
				</div>
				<div class="vsh-disambig-grid">${cardsHtml}</div>
			</div>
		`);
	}

	load_vehicle(vehicleName) {
		if (!vehicleName) {
			this.vehicle = null;
			this.data = null;
			this.editable_open_order = null;
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
					this._render_error_state(__("No history payload returned."));
					return;
				}
				this.data = r.message;
				this.vehicle = (this.data.vehicle && this.data.vehicle.name) || vehicleName;

				if (this.$search_input && this.$search_input.length) {
					this.$search_input.val((this.data.vehicle && this.data.vehicle.registration_no) || this.vehicle);
					this.$search_clear.show();
				}

				if (this._has_no_timeline_filters()) {
					this._resolve_editable_open_order();
				}

				this._render_full_dashboard();

				if (this.on_vehicle_selected) {
					this.on_vehicle_selected(this.data.vehicle);
				}
			},
			error: () => {
				if (seq !== this._load_seq) return;
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
					$timelineSlot.html(
						`<div class="vsh-empty-inline">${this._esc(__("Failed to apply filters. Please try again."))}</div>`
					);
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
			<div class="vsh-header-slot"></div>
			<div class="vsh-kpi-slot"></div>
			<div class="vsh-recommendations-slot"></div>
			<div class="vsh-filter-slot"></div>
			<div class="vsh-timeline-slot"></div>
		`);

		this._render_vehicle_header();
		this._render_kpis();
		this._render_recommendations();
		this._render_filter_bar();
		this._render_timeline();
	}

	_render_vehicle_header() {
		const v = (this.data && this.data.vehicle) || {};
		const c = (this.data && this.data.customer) || {};
		const clusterIds = (this.data && this.data.vehicle_ids) || [];

		const prevBadge = v.previous_registration_nos
			? `<span class="vsh-prev-plate-badge">${this._esc(__("Previous"))}: ${this._esc(v.previous_registration_nos)}</span>`
			: "";

		const clusterBadge =
			clusterIds.length > 1
				? `<span class="vsh-cluster-badge" title="${this._esc(__("Aggregated across linked vehicle records sharing this VIN"))}">${this._esc(__("Merged VIN History ({0})", [clusterIds.length]))}</span>`
				: "";

		const modelTitle = [v.make, v.model, v.year ? `(${v.year})` : ""].filter(Boolean).join(" ") || __("Service Vehicle");
		const specsText = [v.colour, v.fuel_type, v.transmission].filter(Boolean).join(" · ") || "—";

		const canCreateOrder =
			frappe.model && typeof frappe.model.can_create === "function" && frappe.model.can_create("Service Order");

		const openVehicleBtn = this.show_search
			? `<button type="button" class="btn btn-sm btn-default vsh-btn-open-vehicle"><i class="fa fa-external-link mr-1" aria-hidden="true"></i>${this._esc(__("Open Vehicle"))}</button>`
			: "";

		let orderBtn = "";
		if (v.current_service_order) {
			orderBtn = `<button type="button" class="btn btn-sm btn-info vsh-btn-view-open-order"><i class="fa fa-wrench mr-1" aria-hidden="true"></i>${this._esc(__("View Open Service Order"))}</button>`;
		} else if (canCreateOrder) {
			orderBtn = `<button type="button" class="btn btn-sm btn-default vsh-btn-new-order"><i class="fa fa-plus mr-1" aria-hidden="true"></i>${this._esc(__("+ New Service Order"))}</button>`;
		}

		const customerDisplay = v.customer
			? this._doc_link("Customer", v.customer, c.customer_name || v.customer_name || v.customer)
			: `<span class="vsh-muted">—</span>`;
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

		this.$content.find(".vsh-header-slot").html(`
			<div class="vsh-section-card vsh-profile-card">
				<div class="vsh-profile-top">
					<div class="vsh-profile-identity">
						<div class="vsh-plate-row">
							<span class="vsh-plate-badge">${this._esc(v.registration_no || v.name)}</span>
							${prevBadge}
							${this._pill(v.vehicle_status || "Outside Workshop")}
							${clusterBadge}
						</div>
						<h3 class="vsh-vehicle-title">${this._esc(modelTitle)}</h3>
						<div class="vsh-profile-specs">
							<span><strong>${this._esc(__("VIN"))}:</strong> <code>${this._esc(v.vin || "—")}</code></span>
							<span><strong>${this._esc(__("Specs"))}:</strong> ${this._esc(specsText)}</span>
							${v.engine_no ? `<span><strong>${this._esc(__("Engine No"))}:</strong> ${this._esc(v.engine_no)}</span>` : ""}
							<span><strong>${this._esc(__("Current Mileage"))}:</strong> ${this._esc(this._fmt_km(v.current_mileage))}</span>
							${v.current_location ? `<span><strong>${this._esc(__("Location"))}:</strong> ${this._esc(v.current_location)}</span>` : ""}
						</div>
					</div>
					<div class="vsh-profile-actions">
						${openVehicleBtn}
						${orderBtn}
						<button type="button" class="btn btn-sm btn-primary vsh-btn-export">
							<i class="fa fa-print mr-1" aria-hidden="true"></i>${this._esc(__("Print / Export History"))}
						</button>
					</div>
				</div>
				<div class="vsh-profile-owner-bar">
					<div><span class="vsh-muted">${this._esc(__("Customer"))}:</span> ${customerDisplay}</div>
					<div><span class="vsh-muted">${this._esc(__("Contact"))}:</span> ${contactParts || "—"}</div>
					<div><span class="vsh-muted">${this._esc(__("Default Driver"))}:</span> ${driverDisplay}</div>
					<div><span class="vsh-muted">${this._esc(__("Next Service Due"))}:</span> ${nextServiceParts || "—"}</div>
				</div>
			</div>
		`);
	}

	_render_kpis() {
		const stats = (this.data && this.data.overview_stats) || {};
		const showFinancials =
			this._can_view_financials() &&
			stats.total_historical_service_value !== null &&
			stats.total_historical_service_value !== undefined;

		const cards = [
			{ label: __("Total Visits"), value: this._esc(stats.total_visits || 0), tone: "blue" },
			{ label: __("Total Service Orders"), value: this._esc(stats.total_service_orders || 0), tone: "slate" },
			{ label: __("Completed Repairs"), value: this._esc(stats.total_completed_repairs || 0), tone: "green" },
			{
				label: __("Last Service Date"),
				value: stats.last_service_date ? this._fmt_date(stats.last_service_date) : "—",
				tone: "slate",
			},
			{
				label: __("Last Recorded Mileage"),
				value: this._esc(this._fmt_km(stats.last_recorded_mileage || 0)),
				tone: "slate",
			},
		];

		if (showFinancials) {
			cards.push({
				label: __("Total Historical Service Value"),
				value: this._fmt_currency(stats.total_historical_service_value || 0),
				tone: "highlight",
			});
		}

		cards.push({
			label: __("Outstanding Orders"),
			value: this._esc(stats.outstanding_service_orders || 0),
			tone: (stats.outstanding_service_orders || 0) > 0 ? "amber" : "slate",
		});

		const cardsHtml = cards
			.map(
				(c) => `
				<div class="vsh-kpi-card vsh-kpi-card--${this._esc(c.tone)}">
					<div class="vsh-kpi-label">${this._esc(c.label)}</div>
					<div class="vsh-kpi-value">${c.value}</div>
				</div>
			`
			)
			.join("");

		this.$content.find(".vsh-kpi-slot").html(`<div class="vsh-kpi-grid">${cardsHtml}</div>`);
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
			<div class="vsh-scheduled-grid">
				${scheduled
					.map((s) => {
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
							<div class="vsh-scheduled-item">
								<div>
									<div class="vsh-scheduled-title">${this._esc(s.title)}</div>
									<div class="vsh-scheduled-detail">${detail}</div>
								</div>
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
				<button type="button" class="vsh-rec-tab ${this.active_rec_tab === t.id ? "is-active" : ""}" data-tab="${this._esc(t.id)}">
					<span>${this._esc(t.label)}</span>
					<span class="vsh-tab-count">${this._esc(t.count)}</span>
				</button>
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
			<div class="vsh-section-card">
				<div class="vsh-section-header">
					<div class="vsh-section-title-group">
						<h4 class="vsh-section-title">${this._esc(__("Maintenance & Repair Recommendations"))}</h4>
						<span class="vsh-muted text-xs">${this._esc(__("Recommendations stay Outstanding until completed via a linked Service Job or follow-up record."))}</span>
					</div>
					<div class="vsh-rec-tabs">${tabsHtml}</div>
				</div>
				${scheduledHtml}
				<div class="vsh-rec-body">${bodyHtml}</div>
			</div>
		`);
	}

	_render_outstanding_recs(items) {
		if (!items.length) {
			return `<div class="vsh-empty-inline">${this._esc(__("No outstanding maintenance or repair recommendations."))}</div>`;
		}
		const canSchedule = this._can_schedule_followup() && Boolean(this.editable_open_order);
		return `
			<div class="table-responsive">
				<table class="table vsh-table">
					<thead>
						<tr>
							<th style="width: 72px;">${this._esc(__("Type"))}</th>
							<th>${this._esc(__("Recommendation"))}</th>
							<th style="width: 115px;">${this._esc(__("Recommended On"))}</th>
							<th style="width: 140px;">${this._esc(__("Origin Order"))}</th>
							<th style="width: 130px;">${this._esc(__("Status"))}</th>
							${canSchedule ? `<th style="width: 180px;" class="text-right">${this._esc(__("Action"))}</th>` : ""}
						</tr>
					</thead>
					<tbody>
						${items
							.map((rec, idx) => {
								const desc = rec.description ? `<div class="vsh-muted text-xs">${this._esc(rec.description)}</div>` : "";
								const actionCell = canSchedule
									? `<td class="text-right">
											<button type="button" class="btn btn-xs btn-primary vsh-btn-followup" data-idx="${idx}">
												<i class="fa fa-calendar-plus-o mr-1" aria-hidden="true"></i>${this._esc(__("Schedule Follow-up Job"))}
											</button>
										</td>`
									: "";
								return `
									<tr>
										<td>${this._pill(rec.source_type || "Job", "slate")}</td>
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
			return `<div class="vsh-empty-inline">${this._esc(__("No completed recommendations yet."))}</div>`;
		}
		return `
			<div class="table-responsive">
				<table class="table vsh-table">
					<thead>
						<tr>
							<th style="width: 72px;">${this._esc(__("Type"))}</th>
							<th>${this._esc(__("Recommendation"))}</th>
							<th style="width: 115px;">${this._esc(__("Recommended On"))}</th>
							<th style="width: 140px;">${this._esc(__("Origin Order"))}</th>
							<th style="width: 220px;">${this._esc(__("Linked Completion"))}</th>
							<th style="width: 110px;">${this._esc(__("Status"))}</th>
						</tr>
					</thead>
					<tbody>
						${items
							.map((rec) => {
								const desc = rec.description ? `<div class="vsh-muted text-xs">${this._esc(rec.description)}</div>` : "";
								const completionOrderLink = rec.linked_completion_order
									? this._doc_link("Service Order", rec.linked_completion_order)
									: "—";
								const completionJobLink = rec.linked_completion_job
									? `<div class="text-xs">${this._doc_link("Service Job", rec.linked_completion_job)}</div>`
									: "";
								const completedOn = rec.completed_on
									? `<div class="vsh-muted text-xs">${this._fmt_date(rec.completed_on)}</div>`
									: "";
								return `
									<tr>
										<td>${this._pill(rec.source_type || "Job", "slate")}</td>
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
			return `<div class="vsh-empty-inline">${this._esc(__("No delivery or QC advisory notes recorded."))}</div>`;
		}
		return `
			<div class="table-responsive">
				<table class="table vsh-table">
					<thead>
						<tr>
							<th style="width: 115px;">${this._esc(__("Recorded On"))}</th>
							<th style="width: 140px;">${this._esc(__("Origin Order"))}</th>
							<th style="width: 210px;">${this._esc(__("Source"))}</th>
							<th>${this._esc(__("Advisory Note"))}</th>
							<th style="width: 130px;">${this._esc(__("Tag"))}</th>
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

	_select_options_html(options, selectedValue, allLabel) {
		const opts = [`<option value="">${this._esc(allLabel)}</option>`];
		(options || []).forEach((opt) => {
			const val = typeof opt === "object" ? opt.value : opt;
			const label = typeof opt === "object" ? opt.label : opt;
			const sel = val === selectedValue ? " selected" : "";
			opts.push(`<option value="${this._esc(val)}"${sel}>${this._esc(label)}</option>`);
		});
		return opts.join("");
	}

	_render_filter_bar() {
		const opts = (this.data && this.data.filter_options) || {};
		const canFin = this._can_view_financials();

		const invoiceFilterHtml = canFin
			? `
			<div class="vsh-filter-item">
				<label class="vsh-filter-label">${this._esc(__("Invoice Status"))}</label>
				<select class="form-control input-sm vsh-filter-control" data-filter="invoice_status">
					${this._select_options_html(opts.invoice_statuses, this.filters.invoice_status, __("All"))}
				</select>
			</div>
		`
			: "";

		this.$content.find(".vsh-filter-slot").html(`
			<div class="vsh-section-card vsh-filter-card">
				<div class="vsh-filter-grid">
					<div class="vsh-filter-item">
						<label class="vsh-filter-label">${this._esc(__("From Date"))}</label>
						<input type="date" class="form-control input-sm vsh-filter-control" data-filter="from_date" value="${this._esc(this.filters.from_date)}" />
					</div>
					<div class="vsh-filter-item">
						<label class="vsh-filter-label">${this._esc(__("To Date"))}</label>
						<input type="date" class="form-control input-sm vsh-filter-control" data-filter="to_date" value="${this._esc(this.filters.to_date)}" />
					</div>
					<div class="vsh-filter-item">
						<label class="vsh-filter-label">${this._esc(__("Service Status"))}</label>
						<select class="form-control input-sm vsh-filter-control" data-filter="status">
							${this._select_options_html(opts.statuses, this.filters.status, __("All (Excl. Cancelled)"))}
						</select>
					</div>
					<div class="vsh-filter-item">
						<label class="vsh-filter-label">${this._esc(__("Service Type"))}</label>
						<select class="form-control input-sm vsh-filter-control" data-filter="order_type">
							${this._select_options_html(opts.order_types, this.filters.order_type, __("All"))}
						</select>
					</div>
					<div class="vsh-filter-item">
						<label class="vsh-filter-label">${this._esc(__("Technician"))}</label>
						<select class="form-control input-sm vsh-filter-control" data-filter="technician">
							${this._select_options_html(opts.technicians, this.filters.technician, __("All"))}
						</select>
					</div>
					<div class="vsh-filter-item">
						<label class="vsh-filter-label">${this._esc(__("Service Advisor"))}</label>
						<select class="form-control input-sm vsh-filter-control" data-filter="service_advisor">
							${this._select_options_html(opts.service_advisors, this.filters.service_advisor, __("All"))}
						</select>
					</div>
					${invoiceFilterHtml}
					<div class="vsh-filter-item">
						<label class="vsh-filter-label">${this._esc(__("Sort Order"))}</label>
						<select class="form-control input-sm vsh-filter-control" data-filter="sort_order">
							<option value="desc"${this.filters.sort_order !== "asc" ? " selected" : ""}>${this._esc(__("Newest First"))}</option>
							<option value="asc"${this.filters.sort_order === "asc" ? " selected" : ""}>${this._esc(__("Oldest First"))}</option>
						</select>
					</div>
				</div>
				<div class="vsh-filter-actions">
					<button type="button" class="btn btn-xs btn-default vsh-btn-toggle-all"></button>
					<button type="button" class="btn btn-xs btn-default vsh-btn-reset-filters">
						<i class="fa fa-undo mr-1" aria-hidden="true"></i>${this._esc(__("Reset Filters"))}
					</button>
				</div>
			</div>
		`);

		this._update_toggle_all_button();
	}

	_sync_filter_inputs() {
		const $bar = this.$content.find(".vsh-filter-card");
		Object.keys(this.filters).forEach((key) => {
			$bar.find(`[data-filter="${key}"]`).val(this.filters[key] || "");
		});
	}

	_render_timeline() {
		const timeline = (this.data && this.data.timeline) || [];
		const canFin = this._can_view_financials();
		const $slot = this.$content.find(".vsh-timeline-slot");

		if (!timeline.length) {
			$slot.html(`
				<div class="vsh-section-card">
					<div class="vsh-section-header">
						<h4 class="vsh-section-title">${this._esc(__("Chronological Visit Timeline"))} <span class="vsh-tab-count">0</span></h4>
					</div>
					<div class="vsh-empty-inline">${this._esc(__("No service visits match the current filter criteria."))}</div>
				</div>
			`);
			return;
		}

		const cardsHtml = timeline.map((visit) => this._render_visit_card(visit, canFin)).join("");

		$slot.html(`
			<div class="vsh-timeline-section">
				<div class="vsh-timeline-section-header">
					<h4 class="vsh-section-title">${this._esc(__("Chronological Visit Timeline"))} <span class="vsh-tab-count">${this._esc(timeline.length)}</span></h4>
				</div>
				<div class="vsh-timeline-list">${cardsHtml}</div>
			</div>
		`);
	}

	_render_visit_card(visit, canFin) {
		const visitKey = visit.service_order || visit.vehicle_intake || "";
		const isExpanded = this.expanded_visits.has(visitKey);
		const refDoctype = visit.service_order ? "Service Order" : "Vehicle Intake";
		const refLink = this._doc_link(refDoctype, visitKey, visitKey, "vsh-visit-ref");

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
				<div class="vsh-visit-fin-badge">
					<span class="vsh-visit-total">${amountText}</span>
					${this._pill(fin.payment_status || "Not Invoiced")}
				</div>
			`;
		}

		const bodyHtml = this._render_visit_body(visit, canFin);

		return `
			<div class="vsh-visit-card ${isExpanded ? "is-expanded" : ""}" data-visit-key="${this._esc(visitKey)}">
				<div class="vsh-visit-header" role="button" tabindex="0" aria-expanded="${isExpanded ? "true" : "false"}">
					<div class="vsh-visit-header-left">
						<i class="fa ${isExpanded ? "fa-chevron-down" : "fa-chevron-right"} vsh-visit-chevron" aria-hidden="true"></i>
						<div>
							<div class="vsh-visit-title-row">
								${refLink}
								${this._pill(visit.visit_type || "Service Order", "slate")}
								${visit.order_type ? this._pill(visit.order_type, "blue") : ""}
								${visit.branch ? `<span class="vsh-branch-chip"><i class="fa fa-map-marker mr-1" aria-hidden="true"></i>${this._esc(visit.branch)}</span>` : ""}
							</div>
							<div class="vsh-visit-sub-row">
								<span><i class="fa fa-calendar mr-1" aria-hidden="true"></i>${dateSummary}</span>
								<span>&middot; <strong>${this._esc(__("Odometer"))}:</strong> ${this._esc(this._fmt_km(visit.odometer_in))}</span>
								${visit.service_advisor_name ? `<span>&middot; <strong>${this._esc(__("Advisor"))}:</strong> ${this._esc(visit.service_advisor_name)}</span>` : ""}
								${techNames.length ? `<span>&middot; <strong>${this._esc(__("Techs"))}:</strong> ${this._esc(techNames.join(", "))}</span>` : ""}
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

	_render_visit_intake_section(visit) {
		const odoText = visit.odometer_out
			? `${this._fmt_km(visit.odometer_in)} / ${this._fmt_km(visit.odometer_out)}`
			: this._fmt_km(visit.odometer_in);

		const notesBlocks = [
			{ label: __("Customer Complaint"), value: visit.customer_complaint, cls: "" },
			{ label: __("Existing Damage"), value: visit.existing_damage, cls: "vsh-note-box--danger" },
			{ label: __("Declared Contents / Valuables"), value: visit.vehicle_contents, cls: "" },
			{ label: __("Delivery Notes"), value: visit.delivery_notes, cls: "" },
			{ label: __("Reception Notes"), value: visit.reception_notes, cls: "vsh-note-box--internal" },
			{ label: __("Hold Reason"), value: visit.hold_reason, cls: "vsh-note-box--warning" },
			{ label: __("Pause Reason"), value: visit.pause_reason, cls: "vsh-note-box--warning" },
			{ label: __("Dispute Notes"), value: visit.dispute_notes, cls: "vsh-note-box--danger" },
			{ label: __("Cancellation Reason"), value: visit.cancellation_reason, cls: "vsh-note-box--danger" },
		]
			.filter((b) => b.value && String(b.value).trim())
			.map(
				(b) => `
				<div class="vsh-note-box ${b.cls}">
					<div class="vsh-note-label">${this._esc(b.label)}</div>
					<div class="vsh-pre-wrap">${this._esc(b.value)}</div>
				</div>
			`
			)
			.join("");

		const photos = (visit.intake_photos || []).filter((p) => this._safe_url(p.photo));
		const photosHtml = photos.length
			? `
			<div class="vsh-photos-block">
				<div class="vsh-sub-heading">${this._esc(__("Intake Inspection Photos ({0})", [photos.length]))}</div>
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
			<div class="vsh-sub-section">
				<div class="vsh-sub-heading">${this._esc(__("Visit & Intake Condition"))}</div>
				<div class="vsh-kv-grid">
					<div><span class="vsh-muted">${this._esc(__("Checked In"))}:</span> <strong>${this._fmt_datetime(visit.checked_in_on)}</strong></div>
					<div><span class="vsh-muted">${this._esc(__("Completed / Delivered"))}:</span> <strong>${this._fmt_datetime(visit.delivered_on || visit.work_completed_on)}</strong></div>
					<div><span class="vsh-muted">${this._esc(__("Odometer In / Out"))}:</span> <strong>${this._esc(odoText)}</strong></div>
					<div><span class="vsh-muted">${this._esc(__("Fuel Level"))}:</span> <strong>${this._esc(visit.fuel_level || "—")}</strong></div>
					<div><span class="vsh-muted">${this._esc(__("Service Advisor"))}:</span> <strong>${this._esc(visit.service_advisor_name || "—")}</strong></div>
					<div><span class="vsh-muted">${this._esc(__("Collected By"))}:</span> <strong>${this._esc(visit.collected_by || "—")}</strong></div>
					<div><span class="vsh-muted">${this._esc(__("Vehicle Intake"))}:</span> ${visit.vehicle_intake ? this._doc_link("Vehicle Intake", visit.vehicle_intake) : "—"}</div>
					<div><span class="vsh-muted">${this._esc(__("Branch / Company"))}:</span> <strong>${this._esc([visit.branch, visit.company].filter(Boolean).join(" · ") || "—")}</strong></div>
				</div>
				${notesBlocks ? `<div class="vsh-notes-grid">${notesBlocks}</div>` : ""}
				${photosHtml}
			</div>
		`;
	}

	_render_visit_jobs_section(jobs, canFin) {
		if (!jobs.length) {
			return `
				<div class="vsh-sub-section">
					<div class="vsh-sub-heading">${this._esc(__("Jobs & Labour"))}</div>
					<div class="vsh-empty-inline">${this._esc(__("No workshop jobs recorded for this visit."))}</div>
				</div>
			`;
		}

		return `
			<div class="vsh-sub-section">
				<div class="vsh-sub-heading">${this._esc(__("Jobs & Labour ({0})", [jobs.length]))}</div>
				<div class="table-responsive">
					<table class="table vsh-table">
						<thead>
							<tr>
								<th style="width: 36px;" class="text-center">#</th>
								<th>${this._esc(__("Job Description"))}</th>
								<th style="width: 100px;">${this._esc(__("Category"))}</th>
								<th style="width: 120px;">${this._esc(__("Status"))}</th>
								<th style="width: 135px;">${this._esc(__("Technician"))}</th>
								<th style="width: 110px;">${this._esc(__("Bay"))}</th>
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
												${j.service_job ? `<span class="vsh-muted text-xs ml-1">(${this._doc_link("Service Job", j.service_job)})</span>` : ""}
												${notes.length ? `<div class="vsh-muted text-xs mt-1">${notes.join("")}</div>` : ""}
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
			<div class="vsh-sub-section">
				<div class="vsh-sub-heading">${this._esc(__("Parts & Materials ({0})", [parts.length]))}</div>
				<div class="table-responsive">
					<table class="table vsh-table">
						<thead>
							<tr>
								<th style="width: 36px;" class="text-center">#</th>
								<th>${this._esc(__("Part / Item"))}</th>
								<th style="width: 120px;">${this._esc(__("Status"))}</th>
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
										partSubNotes.push(`<span class="vsh-muted text-xs">(${this._esc(p.item_code)})</span>`);
									}
									if (p.reason_for_adding) {
										partSubNotes.push(`<div class="vsh-muted text-xs"><em>${this._esc(__("Reason Added"))}:</em> ${this._esc(p.reason_for_adding)}</div>`);
									}
									if (p.substituted_by) {
										partSubNotes.push(`<div class="vsh-muted text-xs"><em>${this._esc(__("Substituted By"))}:</em> ${this._esc(p.substituted_by)}</div>`);
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
			<div class="vsh-sub-section">
				<div class="vsh-sub-heading">${this._esc(__("Quality Control Inspection ({0})", [qcs.length]))}</div>
				${qcs
					.map((qc) => {
						const roadTest = qc.road_test_done
							? `${__("Yes")}${qc.road_test_km ? ` (${this._fmt_num(qc.road_test_km, 1)} km)` : ""}`
							: __("No");
						const checklistHtml =
							qc.checklist && qc.checklist.length
								? `
								<div class="table-responsive mt-2">
									<table class="table vsh-table vsh-table--compact">
										<thead>
											<tr>
												<th>${this._esc(__("Check Item"))}</th>
												<th style="width: 85px;">${this._esc(__("Result"))}</th>
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
							<div class="vsh-qc-card">
								<div class="vsh-qc-meta">
									<div>${this._doc_link("Service QC", qc.name)} ${this._pill(qc.result || "Pending")}</div>
									<div><span class="vsh-muted">${this._esc(__("Inspector"))}:</span> ${this._esc(qc.inspector || "—")}</div>
									<div><span class="vsh-muted">${this._esc(__("Inspected On"))}:</span> ${this._fmt_datetime(qc.inspected_on)}</div>
									<div><span class="vsh-muted">${this._esc(__("Road Test"))}:</span> ${this._esc(roadTest)}</div>
								</div>
								${qc.findings ? `<div class="vsh-qc-note"><strong>${this._esc(__("Findings"))}:</strong> <span class="vsh-pre-wrap">${this._esc(qc.findings)}</span></div>` : ""}
								${qc.fail_reason ? `<div class="vsh-qc-note text-danger"><strong>${this._esc(__("Fail Reason"))}:</strong> <span class="vsh-pre-wrap">${this._esc(qc.fail_reason)}</span></div>` : ""}
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
			: `<span class="vsh-muted">${this._esc(__("Not Invoiced"))}</span>`;

		const creditNotesHtml =
			fin.credit_notes && fin.credit_notes.length
				? `<span class="vsh-muted text-xs ml-2">(${this._esc(__("Credit Notes"))}: ${fin.credit_notes
						.map((cn) => this._doc_link("Sales Invoice", cn))
						.join(", ")})</span>`
				: "";

		const paymentsHtml =
			fin.payments && fin.payments.length
				? `
				<div class="vsh-payments-block">
					<div class="vsh-muted text-xs font-weight-bold mb-1">${this._esc(__("Recorded Payments"))}</div>
					<div class="table-responsive">
						<table class="table vsh-table vsh-table--compact">
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
			<div class="vsh-sub-section">
				<div class="vsh-fin-box">
					<div class="vsh-fin-top">
						<div>
							<span class="vsh-sub-heading mb-0 mr-2">${this._esc(__("Financial Summary"))}</span>
							${invLink}
							${creditNotesHtml}
						</div>
						<div>${this._pill(fin.payment_status || "Not Invoiced")}</div>
					</div>
					<div class="vsh-fin-grid">
						<div><span class="vsh-muted">${this._esc(__("Labour Charges"))}</span><strong>${this._fmt_currency(fin.labour_charges || 0)}</strong></div>
						<div><span class="vsh-muted">${this._esc(__("Parts Charges"))}</span><strong>${this._fmt_currency(fin.parts_charges || 0)}</strong></div>
						<div><span class="vsh-muted">${this._esc(__("Additional / Taxes"))}</span><strong>${this._fmt_currency(fin.additional_charges || 0)}</strong></div>
						<div><span class="vsh-muted">${this._esc(__("Discounts"))}</span><strong>${this._fmt_currency(fin.discounts || 0)}</strong></div>
						<div><span class="vsh-muted">${this._esc(__("Paid Amount"))}</span><strong>${this._fmt_currency(fin.paid_amount || 0)}</strong></div>
						<div><span class="vsh-muted">${this._esc(__("Outstanding Amount"))}</span><strong>${this._fmt_currency(fin.outstanding_amount || 0)}</strong></div>
						<div class="vsh-fin-total"><span class="vsh-muted">${this._esc(__("Total Invoice Value"))}</span><strong>${this._fmt_currency(fin.total_invoice_value || 0)}</strong></div>
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
			? `<div class="vsh-muted text-xs mt-2">${this._esc(__("Taken On"))}: ${this._fmt_datetime(taken)}</div>`
			: "";
		d.fields_dict.preview.$wrapper.html(`
			<div class="text-center p-2">
				<img src="${this._esc(safeSrc)}" alt="${this._esc(desc || __("Intake Photo"))}" style="max-width: 100%; max-height: 70vh; border-radius: 6px; border: 1px solid var(--border-color, #e2e8f0);" />
				${desc ? `<div class="mt-2 font-weight-bold">${this._esc(desc)}</div>` : ""}
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
