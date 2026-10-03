frappe.pages["my-workshop"].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("My Workshop"),
		single_column: true,
	});

	frappe.my_workshop = new MyWorkshopController(page);
};

class MyWorkshopController {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.body);
		this.timerInterval = null;
		this.elapsedSeconds = 0;

		this.setup_page();
		this.load_data();
	}

	setup_page() {
		let me = this;
		this.page.set_primary_action(__("Refresh"), function() {
			me.load_data();
		}, "octicon octicon-sync");

		this.wrapper.html(`
			<div class="my-workshop-container">
				<div id="mw-active-clock-area"></div>
				<div class="mw-section-title">
					<span>${__("My Assigned Work")}</span>
					<span id="mw-job-count" class="badge badge-info" style="font-size: 10pt;">0 Jobs</span>
				</div>
				<div id="mw-assigned-jobs-area" class="job-cards-grid"></div>

				<div class="mw-section-title" style="margin-top: 32px;">
					<span>${__("Completed Today")}</span>
				</div>
				<div id="mw-completed-today-area"></div>
			</div>
		`);
	}

	load_data() {
		let me = this;
		frappe.call({
			method: "vehicle_service.vehicle_service.page.my_workshop.my_workshop.get_technician_jobs",
			callback: function(r) {
				if (r.message) {
					me.data = r.message;
					me.render_all();
				}
			}
		});
	}

	render_all() {
		this.render_active_clock();
		this.render_assigned_jobs();
		this.render_completed_today();
	}

	render_active_clock() {
		let clock = this.data.active_clock;
		let area = this.wrapper.find("#mw-active-clock-area");
		clearInterval(this.timerInterval);

		if (!clock) {
			area.html(`
				<div class="active-clock-banner idle">
					<div class="clock-info-main">
						<div style="font-size: 24pt; opacity: 0.7;">⏱️</div>
						<div>
							<div class="clock-meta-title" style="font-size: 12pt;">${__("No Active Clock")}</div>
							<div class="clock-meta-sub">${__("Select an assigned job below and tap [Start Clock] to begin work.")}</div>
						</div>
					</div>
				</div>
			`);
			return;
		}

		this.elapsedSeconds = clock.elapsed_seconds || 0;

		area.html(`
			<div class="active-clock-banner">
				<div class="clock-info-main">
					<div class="pulse-indicator"></div>
					<div>
						<div class="timer-display" id="mw-live-timer">${this.format_seconds(this.elapsedSeconds)}</div>
						<div class="clock-meta-title">${clock.job_title}</div>
						<div class="clock-meta-sub">
							<span>🚗 <b>${clock.vehicle_reg || ""}</b></span>
							<span>📍 ${clock.bay || "Workshop Bay"}</span>
							<span>📋 ${clock.service_order}</span>
						</div>
					</div>
				</div>
				<div class="clock-actions">
					<button class="touch-btn touch-btn-pause" data-action="pause" data-job="${clock.name}">
						⏸️ ${__("Pause")}
					</button>
					<button class="touch-btn touch-btn-complete" data-action="complete" data-job="${clock.name}">
						✓ ${__("Complete")}
					</button>
					<button class="touch-btn touch-btn-extra" data-action="extra" data-job="${clock.name}" data-order="${clock.service_order}">
						+ ${__("Extra Work")}
					</button>
				</div>
			</div>
		`);

		// Start timer tick
		let me = this;
		this.timerInterval = setInterval(() => {
			me.elapsedSeconds++;
			me.wrapper.find("#mw-live-timer").text(me.format_seconds(me.elapsedSeconds));
		}, 1000);

		// Event handlers
		area.find("[data-action='pause']").on("click", function() {
			let job_name = $(this).attr("data-job");
			frappe.prompt(
				{
					label: __("Reason for pausing"),
					fieldname: "reason",
					fieldtype: "Data",
					default: "Tea break / Waiting for parts",
				},
				function(values) {
					me.clock_action(job_name, "pause", values.reason);
				},
				__("Pause Job Timer")
			);
		});

		area.find("[data-action='complete']").on("click", function() {
			let job_name = $(this).attr("data-job");
			frappe.confirm(__("Confirm work is finished and ready for Quality Control?"), function() {
				me.clock_action(job_name, "complete");
			});
		});

		area.find("[data-action='extra']").on("click", function() {
			let job_name = $(this).attr("data-job");
			let order_name = $(this).attr("data-order");
			me.open_extra_work_dialog(order_name, job_name);
		});
	}

	render_assigned_jobs() {
		let jobs = this.data.assigned_jobs || [];
		let area = this.wrapper.find("#mw-assigned-jobs-area");
		this.wrapper.find("#mw-job-count").text(`${jobs.length} ${__("Jobs")}`);

		if (!jobs.length) {
			area.html(`
				<div style="grid-column: 1 / -1; padding: 30px; text-align: center; color: #94a3b8; background: #ffffff; border-radius: 8px; border: 1px dashed #cbd5e1;">
					<h4>${__("No pending jobs assigned")}</h4>
					<p>${__("Check back later or speak with the Workshop Supervisor.")}</p>
				</div>
			`);
			return;
		}

		let me = this;
		let html = "";
		jobs.forEach(j => {
			let is_paused = j.status === "Paused";
			html += `
				<div class="mw-job-card ${is_paused ? 'is-paused' : ''}">
					<div>
						<div class="card-top">
							<span class="reg-badge">${j.vehicle_reg || j.service_order}</span>
							<span class="bay-badge">📍 ${j.bay || "Unassigned Bay"}</span>
						</div>
						<div class="job-main-title">${j.job_title}</div>
						<div class="job-desc-snippet">${j.customer_complaint || j.vehicle_desc || ""}</div>
						<div class="job-metrics">
							<span>⏱️ Est: <b>${j.estimated_hours || 1} hrs</b></span>
							<span>🏷️ ${j.category || "Essential"}</span>
							<span>Status: <b>${j.status}</b></span>
						</div>
						${is_paused ? `<div style="font-size: 8.5pt; color: #b45309; margin-bottom: 8px;">Paused: ${j.pause_reason || ""}</div>` : ''}
					</div>
					<div class="card-action-bar">
						<button class="touch-btn touch-btn-start" style="flex: 1;" data-action="start" data-job="${j.name}">
							▶️ ${is_paused ? __("Resume Clock") : __("Start Clock")}
						</button>
						<button class="touch-btn touch-btn-extra" style="min-width: 44px; padding: 10px 12px;" title="${__("Report Extra Work")}" data-action="extra" data-job="${j.name}" data-order="${j.service_order}">
							+
						</button>
					</div>
				</div>
			`;
		});

		area.html(html);

		area.find("[data-action='start']").on("click", function() {
			let job_name = $(this).attr("data-job");
			me.clock_action(job_name, "start");
		});

		area.find("[data-action='extra']").on("click", function() {
			let job_name = $(this).attr("data-job");
			let order_name = $(this).attr("data-order");
			me.open_extra_work_dialog(order_name, job_name);
		});
	}

	render_completed_today() {
		let completed = this.data.completed_today || [];
		let area = this.wrapper.find("#mw-completed-today-area");

		if (!completed.length) {
			area.html(`
				<div style="padding: 16px; text-align: center; color: #94a3b8; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0;">
					${__("No jobs completed yet today.")}
				</div>
			`);
			return;
		}

		let html = '<div class="completed-list">';
		completed.forEach(c => {
			html += `
				<div class="completed-item">
					<div>
						<span style="font-weight: 700; color: #0f172a;">${c.job_title}</span>
						<span style="color: #64748b; font-size: 9pt; margin-left: 8px;">(🚗 ${c.vehicle_reg || c.service_order})</span>
					</div>
					<div>
						<span class="badge badge-success" style="font-size: 9pt;">✓ Completed</span>
						<span style="font-size: 9pt; color: #475569; margin-left: 10px;">${c.actual_hours || 0} hrs</span>
					</div>
				</div>
			`;
		});
		html += '</div>';
		area.html(html);
	}

	clock_action(job_name, action, pause_reason) {
		let me = this;
		frappe.call({
			method: "vehicle_service.vehicle_service.page.my_workshop.my_workshop.clock_job_action",
			args: {
				job_name: job_name,
				action: action,
				pause_reason: pause_reason,
			},
			freeze: true,
			freeze_message: __("Updating job clock..."),
			callback: function(r) {
				if (r.message) {
					me.data = r.message;
					me.render_all();
					frappe.show_alert({
						message: __("Job clock updated successfully"),
						indicator: "green",
					});
				}
			}
		});
	}

	open_extra_work_dialog(service_order, parent_job) {
		let me = this;
		let d = new frappe.ui.Dialog({
			title: __("Report Additional Work / Discovery"),
			fields: [
				{
					label: __("Discovered Work Title"),
					fieldname: "job_title",
					fieldtype: "Data",
					reqd: 1,
					placeholder: __("e.g. Leaking coolant thermostat housing"),
				},
				{
					label: __("Category"),
					fieldname: "category",
					fieldtype: "Select",
					options: ["Essential", "Recommended", "Optional"],
					default: "Recommended",
					reqd: 1,
				},
				{
					label: __("Estimated Hours"),
					fieldname: "estimated_hours",
					fieldtype: "Float",
					default: 1.0,
				},
				{
					label: __("Detailed Findings & Recommendations"),
					fieldname: "description",
					fieldtype: "Small Text",
					placeholder: __("Describe what was found, why it should be replaced, and parts required."),
				},
				{
					label: __("Attach Photo of Defect"),
					fieldname: "photo",
					fieldtype: "Attach Image",
				},
			],
			primary_action_label: __("Submit for Advisor Approval"),
			primary_action: function(values) {
				frappe.call({
					method: "vehicle_service.vehicle_service.page.my_workshop.my_workshop.report_additional_work",
					args: {
						service_order: service_order,
						parent_job: parent_job,
						job_title: values.job_title,
						category: values.category,
						estimated_hours: values.estimated_hours,
						description: values.description,
						photo: values.photo,
					},
					freeze: true,
					callback: function(r) {
						d.hide();
						frappe.msgprint({
							title: __("Extra Work Reported"),
							message: __("Additional job <b>{0}</b> logged and routed to the Service Advisor for customer quotation.", [r.message]),
							indicator: "blue",
						});
						me.load_data();
					}
				});
			}
		});
		d.show();
	}

	format_seconds(sec) {
		sec = parseInt(sec, 10) || 0;
		let hrs = Math.floor(sec / 3600);
		let mins = Math.floor((sec % 3600) / 60);
		let s = sec % 60;
		return [
			hrs.toString().padStart(2, '0'),
			mins.toString().padStart(2, '0'),
			s.toString().padStart(2, '0')
		].join(':');
	}
}
