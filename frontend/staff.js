(function () {
  "use strict";

  const API_BASE = "";
  const app = document.querySelector("#app");
  const toast = document.querySelector("#toast");
  function localDateValue() {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }

  const state = {
    token: "",
    user: null,
    view: "dashboard",
    data: { schedule: [], customers: [], members: [], refunds: [], audits: [], retentionTasks: [], retentionRecords: [], birthdays: [], wallets: [], overview: null, changeSlots: [] },
    scheduleDate: localDateValue(),
    customerSearch: "",
    selectedCustomerId: "",
    assistantMessages: [],
    assistantReplyTo: null,
    assistantContextMenu: null,
    assistantTask: null,
    refundDecision: null,
    retentionAnalysis: null,
    retentionView: "today",
    retentionFilter: "all",
    retentionSearch: "",
    retentionDetail: null,
    retentionDetailLoading: false,
    auditDetail: null,
    changeTask: null,
    approvalTask: null,
    verification: null,
    verificationLoading: false,
    bookingCustomerId: "",
    bookingCustomerQuery: "",
    bookingStylistId: "",
    bookingSlots: [],
    bookingSlotsLoading: false,
  };

  // Keep employee management aligned with the four stylists shown in the H5 booking page.
  const H5_STYLIST_ORDER = {
    "13800001111": 0,
    "13800002222": 1,
    "13800003333": 2,
    "13800004444": 3,
  };
  const H5_STYLIST_NAMES = new Set(["张三", "李四", "王五", "赵六"]);
  function visibleStaffSchedule(schedule) {
    return schedule.filter((group) => H5_STYLIST_NAMES.has(group.stylist_name));
  }

  function visibleStaffPerformances(performances) {
    return performances
      .filter((item) => Object.prototype.hasOwnProperty.call(H5_STYLIST_ORDER, item.stylist_phone))
      .sort((a, b) => H5_STYLIST_ORDER[a.stylist_phone] - H5_STYLIST_ORDER[b.stylist_phone]);
  }

  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));

  function assistantMessageId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function assistantMessage(role, content, replyTo = null) {
    return { id: assistantMessageId(), role, content, replyTo };
  }

  function assistantQuote(value, limit = 180) {
    const text = String(value || "");
    return text.length > limit ? `${text.slice(0, limit)}...` : text;
  }

  function formatDate(value, withTime = true) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return esc(value);
    return new Intl.DateTimeFormat("zh-CN", withTime
      ? { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }
      : { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
  }

  function todayLabel() {
    return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" }).format(new Date());
  }

  function initials(name) { return String(name || "员工").trim().slice(0, 1); }

  function isManager() { return state.user?.role === "admin"; }

  function statusLabel(value) {
    return ({ pending: "待处理", approved: "已通过", rejected: "已拒绝", confirmed: "已确认", completed: "已完成", cancelled: "已取消", contacted: "已联系", dismissed: "已忽略", verified: "已核验", pending_review: "待审核", sending: "发送中", sent: "已发送", send_failed: "发送失败", replied: "已回复", manual_followup: "人工跟进", cooling: "冷却中", ignored: "已忽略", closed: "已关闭", attempting: "发送中", failed: "发送失败" })[value] || value || "未知";
  }

  function statusTag(value) { return `<span class="status ${esc(value)}">${esc(statusLabel(value))}</span>`; }

  function money(value) { return `￥${Number(value || 0).toFixed(2)}`; }

  function walletTransactionLabel(item) {
    if (item.transaction_type === "recharge") return "充值到账";
    if (item.transaction_type === "refund") return "退款扣减";
    if (item.transaction_type === "purchase") return "消费扣款";
    return item.transaction_type || "账户调整";
  }

  function notify(message, isError = false) {
    toast.textContent = message;
    toast.className = `toast ${isError ? "error" : "show"}`;
    window.clearTimeout(notify.timer);
    notify.timer = window.setTimeout(() => { toast.className = "toast"; }, 3200);
  }

  async function api(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers, credentials: "include" });
    let body = null;
    try { body = await response.json(); } catch (_) { body = null; }
    if (response.status === 401) {
      state.token = "";
      state.user = null;
      renderLogin("登录已失效，请重新登录");
      const error = new Error("登录已失效，请重新登录");
      error.code = "AUTH_EXPIRED";
      throw error;
    }
    if (!response.ok) throw new Error(body?.detail || `请求失败（${response.status}）`);
    return body;
  }

  async function safeGet(path, fallback) {
    try { return await api(path); } catch (error) { console.warn(path, error); return fallback; }
  }

  function renderLogin(error = "") {
    app.innerHTML = `
      <main class="login-page">
        <section class="login-panel" aria-labelledby="login-title">
          <div class="brand-mark">
            <div class="brand-mark-icon" aria-hidden="true">恒</div>
            <div><strong>恒艺美发</strong><span>员工运营工作台</span></div>
          </div>
          <h1 id="login-title">员工登录</h1>
          <p class="lead">登录后查看门店预约、客户运营和资金处理任务。</p>
          <form id="login-form" class="form-grid">
            <div class="field"><label for="login-phone">手机号</label><input id="login-phone" name="phone" type="tel" autocomplete="username" required placeholder="请输入员工手机号" /></div>
            <div class="field"><label for="login-password">密码</label><input id="login-password" name="password" type="password" autocomplete="current-password" required placeholder="请输入登录密码" /></div>
            <p class="form-error" role="alert">${esc(error)}</p>
            <button class="btn" type="submit">进入工作台</button>
          </form>
        </section>
      </main>`;
  }

  function navButton(view, icon, label) {
    return `<button type="button" class="${state.view === view ? "active" : ""}" data-view="${view}" aria-current="${state.view === view ? "page" : "false"}"><span class="nav-icon" aria-hidden="true">${icon}</span><span>${label}</span></button>`;
  }

  function renderShell() {
    const manager = isManager();
    app.innerHTML = `
      <div class="shell">
        <aside class="sidebar">
          <div class="sidebar-brand"><div class="brand-mark-icon" aria-hidden="true">恒</div><div><strong>恒艺美发</strong><span>员工运营工作台</span></div></div>
          <nav class="nav" aria-label="员工工作台导航">
            ${manager ? navButton("dashboard", "⌂", "工作概览") : ""}
            ${navButton("schedule", "◷", "今日预约")}
            ${navButton("customers", "◎", "客户与会员")}
            ${manager ? navButton("staff", "♙", "员工管理") : ""}
            ${manager ? navButton("finance", "￥", "退款处理") : ""}
            ${manager ? navButton("retention", "!", "留存提醒") : ""}
            ${manager ? navButton("audit", "≡", "操作审计") : ""}
            ${navButton("assistant", "✦", "智能助手")}
          </nav>
          <div class="sidebar-footer"><div class="staff-mini"><div class="staff-avatar" aria-hidden="true">${esc(initials(state.user?.name))}</div><div><strong>${esc(state.user?.name)}</strong><span>${esc(state.user?.role === "admin" ? "管理员" : "发型师")}</span></div></div><button class="logout-btn" type="button" data-action="logout">退出</button></div>
        </aside>
        <main class="content">
          <header class="content-header"><div><p class="eyebrow">OPERATIONS DESK</p><h1>${esc(viewTitle(state.view))}</h1><p>${esc(viewDescription(state.view))}</p></div><div class="header-actions"><span class="date-chip">${esc(todayLabel())}</span><button class="btn secondary" type="button" data-action="refresh"><span class="btn-icon" aria-hidden="true">↻</span>刷新数据</button></div></header>
          ${viewMarkup(state.view)}
        </main>
      </div>`;
  }

  function viewTitle(view) { return ({ dashboard: "工作概览", schedule: "今日预约", customers: "客户与会员", staff: "员工管理", finance: "退款处理", retention: "留存提醒", audit: "操作审计", assistant: "智能助手" })[view] || "工作概览"; }
  function viewDescription(view) { return ({ dashboard: "快速掌握今天的门店运营状态。", schedule: "按发型师查看当天预约和客户需求。", customers: "查找客户基础资料、会员等级和积分。", staff: "按发型师查看客户服务记录和今日业绩。", finance: "处理客户退款申请，所有决定都会留下记录。", retention: "按优先级跟进需要再次触达的客户。", audit: "查看关键业务动作的操作者和时间。", assistant: isManager() ? "用自然语言查询和操作真实工作台业务。" : "用自然语言查询门店信息和护理知识。" })[view] || ""; }

  function flattenSchedule() { return state.data.schedule.flatMap((group) => (group.appointments || []).map((item) => ({ ...item, stylist_name: group.stylist_name }))); }
  function metric(label, value, note, icon, view = "") {
    const tag = view ? "button" : "article";
    const className = view ? "metric metric-link" : "metric";
    const attributes = view
      ? ` type="button" data-view="${esc(view)}" aria-label="打开${esc(label)}页面"`
      : "";
    return `<${tag} class="${className}"${attributes}><div class="metric-label"><span>${esc(label)}</span><b aria-hidden="true">${esc(icon)}</b></div><strong class="mono">${esc(value)}</strong><small>${esc(note)}${view ? " · 点击查看" : ""}</small></${tag}>`;
  }

  function viewMarkup(view) {
    return `<section class="view active" data-view-panel="${view}">${({ dashboard: dashboardMarkup, schedule: scheduleMarkup, customers: customersMarkup, staff: staffMarkup, finance: financeMarkup, retention: retentionMarkup, audit: auditMarkup, assistant: assistantMarkup })[view]()}</section>`;
  }

  function dashboardMarkup() {
    const pendingRefunds = state.data.refunds.filter((item) => item.status === "pending").length;
    const overview = state.data.overview || {};
    const serviceRows = overview.services?.length ? overview.services.map((item) => `<tr><td><strong>${esc(item.service)}</strong></td><td class="mono">${item.customer_count} 人</td><td class="mono">${item.order_count} 单</td><td class="mono">${money(item.amount)}</td></tr>`).join("") : `<tr><td colspan="4"><div class="empty">今日暂无消费记录。</div></td></tr>`;
    return `<div class="metric-grid">${metric("今日预约", state.data.schedule.reduce((total, group) => total + (group.appointments || []).length, 0), "全店发型师合计", "◷", "schedule")}${metric("会员客户", state.data.members.length, "已建立会员资料", "◎", "customers")}${metric("待处理退款", pendingRefunds, pendingRefunds ? "需要员工审核" : "当前没有待审核申请", "￥", "finance")}${metric("待跟进客户", state.data.retentionTasks.length, "今天允许处理的留存任务", "!", "retention")}</div>
      <section class="panel revenue-panel"><div class="panel-header"><h2>今日营业额</h2><span>${esc(overview.date || todayLabel())}</span></div><div class="summary-stat-grid"><div class="summary-stat"><span>消费</span><strong>${money(overview.consumption)}</strong><small>${overview.customer_count || 0} 位客户 · ${overview.order_count || 0} 单</small></div><div class="summary-stat"><span>充值</span><strong>${money(overview.recharge)}</strong><small>客户账户充值到账</small></div><div class="summary-stat"><span>退款</span><strong>${money(overview.refund)}</strong><small>已处理退款</small></div><div class="summary-stat"><span>待退款</span><strong>${money(overview.pending_refund)}</strong><small>待审核申请金额</small></div></div><div class="table-wrap"><table><thead><tr><th>服务套餐</th><th>客户数</th><th>订单数</th><th>消费金额</th></tr></thead><tbody>${serviceRows}</tbody></table></div></section>`;
  }

  function scheduleTable(items) {
    if (!items.length) return `<div class="empty">今天还没有预约记录。</div>`;
    const showActionColumn = isManager() || items.some((item) => item.status === "pending");
    const actionHeader = showActionColumn ? "<th>操作</th>" : "";
    const actionCell = (item) => !showActionColumn ? "" : `<td>${item.status === "pending" ? `<button class="btn small" type="button" data-approve-appointment="${esc(item.appointment_id)}">批准预约</button>` : isManager() && item.status !== "cancelled" && item.status !== "completed" ? `<button class="btn secondary small" type="button" data-verify-appointment="${esc(item.appointment_id)}">${item.status === "verified" ? "确认完成服务" : "核验服务"}</button>` : item.status === "cancelled" ? `<span class="muted">已取消</span>` : item.status === "completed" ? `<span class="status completed">已完成</span>` : `<span class="muted">已确认</span>`}</td>`;
    return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>客户</th><th>项目</th><th>发型师</th><th>状态</th>${actionHeader}</tr></thead><tbody>${items.map((item) => `<tr><td class="mono">${formatDate(item.appointment_datetime)}</td><td><strong>${esc(item.customer_name)}</strong><br><span class="muted">${esc(item.customer_phone)}</span></td><td>${esc(item.service)}</td><td>${esc(item.stylist_name)}</td><td>${statusTag(item.status)}</td>${actionCell(item)}</tr>`).join("")}</tbody></table></div>`;
  }

  function verificationMarkup() {
    if (state.verificationLoading) return `<div class="detail-drawer-backdrop" role="presentation"><aside class="detail-drawer verification-drawer" role="dialog" aria-modal="true" aria-labelledby="verification-title"><div class="detail-drawer-header"><div><span class="eyebrow">SERVICE CHECK</span><h2 id="verification-title">服务核验</h2><p>正在读取客户套餐和预约状态...</p></div><button class="btn secondary small" type="button" data-action="close-verification">关闭</button></div><div class="detail-drawer-body"><div class="empty">正在读取客户套餐和预约状态...</div></div></aside></div>`;
    const data = state.verification;
    if (!data) return "";
    const verification = data.verification;
    const packageOptions = data.packages.length
      ? data.packages.map((item) => `<option value="${esc(item.customer_package_id)}">${esc(item.package_name)} · 剩余 ${item.remaining_uses}/${item.total_uses} 次 · 到期 ${formatDate(item.expires_at, false)}</option>`).join("")
      : `<option value="">暂无匹配套餐</option>`;
    const statusBlock = verification
      ? `<div class="verification-status"><span>核验状态</span>${statusTag(verification.status)}<strong>${money(verification.amount)}</strong>${verification.package_name ? `<small>${esc(verification.package_name)} · 完成后扣 1 次</small>` : `<small>直接消费记录</small>`}</div>${verification.status === "verified" ? `<button class="btn" type="button" data-action="complete-service" data-verification-id="${esc(verification.verification_id)}">确认完成服务</button>` : `<div class="helper-note">该服务已经完成并计入员工绩效。</div>`}`
      : `<div class="verification-form"><div class="field"><label for="verification-package">使用客户套餐</label><select id="verification-package"><option value="">不使用套餐，直接记录消费</option>${packageOptions}</select></div><div class="field"><label for="verification-amount">直接消费金额</label><input id="verification-amount" type="number" min="0.01" step="0.01" placeholder="使用套餐时可留空" /></div><div class="helper-note">核验只建立服务记录；点击“确认完成服务”后才会扣套餐次数并计入绩效。</div><button class="btn" type="button" data-action="verify-service" data-appointment-id="${esc(data.appointment_id)}">核验服务</button></div>`;
    return `<div class="detail-drawer-backdrop" role="presentation"><aside class="detail-drawer verification-drawer" role="dialog" aria-modal="true" aria-labelledby="verification-title"><div class="detail-drawer-header"><div><span class="eyebrow">SERVICE CHECK</span><h2 id="verification-title">服务核验</h2><p>${esc(data.customer_name)} · ${esc(data.service)} · ${esc(data.stylist_name)}</p></div><button class="btn secondary small" type="button" data-action="close-verification">关闭</button></div><div class="detail-drawer-body"><div class="verification-summary"><div><span>预约时间</span><strong>${formatDate(data.appointment_datetime)}</strong></div><div><span>预约状态</span>${statusTag(data.appointment_status)}</div><div><span>可用套餐</span><strong>${data.packages.length} 个</strong></div></div>${statusBlock}</div></aside></div>`;
  }

  function scheduleMarkup() {
    return `<div class="toolbar"><div class="toolbar-left"><label class="muted" for="schedule-date">日期</label><input class="date-input" id="schedule-date" type="date" value="${esc(state.scheduleDate)}" /></div><div class="toolbar-right"><button class="btn secondary small" type="button" data-action="refresh-schedule">重新查询</button></div></div><div class="schedule-list">${state.data.schedule.length ? state.data.schedule.map((group) => `<section class="panel schedule-group"><div class="schedule-group-title"><span>${esc(group.stylist_name)}</span><span>${(group.appointments || []).length} 条预约</span></div>${scheduleTable((group.appointments || []).map((item) => ({ ...item, stylist_name: group.stylist_name })))}</section>`).join("") : `<div class="panel empty">${esc(state.scheduleDate)} 没有预约记录。</div>`}</div>${isManager() ? verificationMarkup() : ""}${isManager() ? appointmentApprovalMarkup() : ""}${isManager() ? appointmentChangeMarkup() : ""}`;
  }

  function appointmentChangeMarkup() {
    const proposal = state.changeTask?.result_payload;
    const result = proposal ? `<div class="helper-note" style="margin-top:14px"><strong>调整方案</strong><br>${esc(proposal.customer_name || "客户")}：${esc(proposal.old_datetime || "")} -> ${esc(proposal.new_datetime || "")}，发型师：${esc(proposal.old_stylist_name || "")} -> ${esc(proposal.new_stylist_name || "")}${state.changeTask.awaiting_confirmation ? `<div class="action-row" style="margin-top:12px"><button class="btn small" type="button" data-agent-confirm="true" data-agent-task-kind="change" data-task-id="${esc(state.changeTask.task_id)}">确认执行</button><button class="btn danger small" type="button" data-agent-confirm="false" data-agent-task-kind="change" data-task-id="${esc(state.changeTask.task_id)}">拒绝方案</button></div>` : `<br><span class="muted">${esc(state.changeTask.status)}</span>`}</div>` : "";
    const appointments = flattenSchedule().filter((item) => !["cancelled", "completed"].includes(item.status));
    const appointmentOptions = appointments.length
      ? appointments.map((item) => `<option value="${esc(item.appointment_id)}">${esc(item.customer_name)} · ${esc(item.customer_phone || "无手机号")} · ${esc(formatDate(item.appointment_datetime))} · ${esc(item.stylist_name)}</option>`).join("")
      : `<option value="">当前日期没有可调整的未完成预约</option>`;
    const slotOptions = state.data.changeSlots.length
      ? state.data.changeSlots.map((slot) => `<option value="${esc(slot.slot_id)}">${esc(slot.stylist_name)} · ${esc(slot.date)} ${esc(slot.time)}</option>`).join("")
      : `<option value="">暂无可用时间</option>`;
    return `<section class="panel" style="margin-top:16px"><div class="panel-header"><h2>预约调整</h2><span>人工确认后才写入</span></div><div class="panel-body"><form id="change-form" class="form-grid"><div class="toolbar-left"><div class="field"><label for="change-appointment-id">选择要调整的预约</label><select id="change-appointment-id" name="appointment_id" required>${appointmentOptions}</select></div><div class="field"><label for="change-slot-id">选择新的发型师和时间</label><select id="change-slot-id" name="new_slot_id" required>${slotOptions}</select></div><div class="helper-note">页面显示客户手机号、预约时间和发型师姓名；系统会在后台自动使用对应编号完成校验。</div><button class="btn" type="submit"${appointments.length && state.data.changeSlots.length ? "" : " disabled"}>生成调整方案</button></div></form>${result}</div></section>`;
  }

  function appointmentApprovalMarkup() {
    if (!state.approvalTask) return "";
    const proposal = state.approvalTask.result_payload || {};
    const task = state.approvalTask;
    const content = task.awaiting_confirmation
      ? `<div class="action-row" style="margin-top:12px"><button class="btn small" type="button" data-agent-confirm="true" data-agent-task-kind="approval" data-task-id="${esc(task.task_id)}">确认批复</button><button class="btn danger small" type="button" data-agent-confirm="false" data-agent-task-kind="approval" data-task-id="${esc(task.task_id)}">拒绝批复</button></div>`
      : `<br><span class="muted">${esc(proposal.message || task.status)}</span>`;
    return `<section class="panel" style="margin-top:16px"><div class="panel-header"><h2>预约批复</h2><span>店长确认后才生效</span></div><div class="panel-body"><div class="helper-note"><strong>${esc(proposal.customer_name || "客户")}</strong>：${esc(formatDate(proposal.appointment_datetime || ""))} · ${esc(proposal.service || "")} · ${esc(proposal.stylist_name || "")}${content}</div></div></section>`;
  }

  function staffBookingMarkup() {
    if (!isManager()) return "";
    const customers = state.data.customers || [];
    const stylists = (state.data.stylists || []).filter((item) => item.is_available);
    const selectedCustomer = customers.find((item) => item.customer_id === state.bookingCustomerId);
    const customerValue = selectedCustomer
      ? `${selectedCustomer.name} · ${selectedCustomer.phone || "未填写手机号"}`
      : state.bookingCustomerQuery;
    const customerOptions = customers.length
      ? customers.map((item) => `<option value="${esc(`${item.name} · ${item.phone || "未填写手机号"}`)}"></option>`).join("")
      : `<option value="暂无客户"></option>`;
    const stylistOptions = stylists.length
      ? `<option value="" ${state.bookingStylistId ? "" : "selected"}>请选择发型师</option>${stylists.map((item) => `<option value="${esc(item.stylist_id)}" ${item.stylist_id === state.bookingStylistId ? "selected" : ""}>${esc(item.name)} · ${esc(item.specialty || "综合服务")}</option>`).join("")}`
      : `<option value="">暂无可预约发型师</option>`;
    let slotOptions = `<option value="">${state.bookingStylistId ? "请选择可用时间" : "请先选择发型师"}</option>`;
    if (state.bookingSlotsLoading) slotOptions = `<option value="">正在读取可用时间...</option>`;
    else if (state.bookingSlots.length) slotOptions += state.bookingSlots.map((item) => `<option value="${esc(item.slot_id)}">${esc(item.date)} ${esc(item.time)}</option>`).join("");
    else if (state.bookingStylistId) slotOptions = `<option value="">该老师近 7 天暂无可用时间</option>`;
    return `<section class="panel staff-booking-panel"><div class="panel-header"><div><h2>帮客户预约</h2><span>输入客户姓名或手机号，再选择老师和时间</span></div><span class="booking-sync-badge">共享预约记录</span></div><div class="panel-body"><p class="helper-note">员工代约和客户自主预约使用同一套时间槽。创建成功后，客户 H5、小程序和员工日程都会读取这条预约。</p><form id="staff-booking-form" class="booking-form-grid"><div class="field"><label for="staff-booking-customer">客户姓名或手机号</label><input id="staff-booking-customer" name="customer_label" type="search" list="staff-booking-customer-options" value="${esc(customerValue)}" placeholder="输入姓名或手机号" autocomplete="off" required /><datalist id="staff-booking-customer-options">${customerOptions}</datalist><input type="hidden" name="customer_id" value="${esc(state.bookingCustomerId)}" /></div><div class="field"><label for="staff-booking-service">服务项目</label><select id="staff-booking-service" name="service" required><option value="剪发">剪发</option><option value="洗剪吹">洗剪吹</option><option value="烫发">烫发</option><option value="染发">染发</option><option value="护理">护理</option><option value="头皮护理">头皮护理</option></select></div><div class="field"><label for="staff-booking-stylist">发型师</label><select id="staff-booking-stylist" name="stylist_id" required>${stylistOptions}</select></div><div class="field"><label for="staff-booking-slot">可用时间</label><select id="staff-booking-slot" name="slot_id" required>${slotOptions}</select></div><div class="field booking-notes-field"><label for="staff-booking-notes">备注（可选）</label><input id="staff-booking-notes" name="notes" maxlength="500" placeholder="例如：客户希望保留长度" /></div><div class="booking-form-actions"><button class="btn" type="submit"${!customers.length || !stylists.length ? " disabled" : ""}>创建预约</button><span class="muted">时间槽以后台实时占用状态为准</span></div></form></div></section>`;
  }

  function customersMarkup() {
    const manager = isManager();
    const keyword = state.customerSearch.trim().toLowerCase();
    const customers = state.data.customers.filter((item) => !keyword || [item.name, item.phone].some((value) => String(value || "").toLowerCase().includes(keyword)));
    const memberMap = new Map(state.data.members.map((item) => [item.customer_id, item]));
    const walletMap = new Map(state.data.wallets.map((item) => [item.customer_id, item]));
    const selectedWallet = walletMap.get(state.selectedCustomerId);
    const walletDetail = selectedWallet ? `<div class="detail-drawer-backdrop" role="presentation"><aside class="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="wallet-detail-title"><div class="detail-drawer-header"><div><span class="eyebrow">ACCOUNT LEDGER</span><h2 id="wallet-detail-title">${esc(selectedWallet.name)} 的账户流水</h2><p>当前余额 ${money(selectedWallet.balance)} · 累计充值 ${money(selectedWallet.recharge_total)}</p></div><button class="btn secondary small" type="button" data-wallet-close aria-label="关闭账户流水">关闭</button></div><div class="detail-drawer-body"><section class="detail-drawer-section"><h3>流水明细</h3><div class="table-wrap detail-drawer-table"><table><thead><tr><th>时间</th><th>类型</th><th>金额</th><th>余额</th><th>备注</th></tr></thead><tbody>${selectedWallet.transactions.length ? selectedWallet.transactions.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td>${esc(walletTransactionLabel(item))}</td><td class="mono ${item.direction === "debit" ? "amount-debit" : "amount-credit"}">${item.direction === "debit" ? "-" : "+"}${money(Number(item.amount_cents || 0) / 100)}</td><td class="mono">${money(Number(item.balance_after_cents || 0) / 100)}</td><td>${esc(item.note || "-")}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">暂无账户流水。</div></td></tr>`}</tbody></table></div></section></div></aside></div>` : "";
    const financialHeaders = manager ? "<th>累计消费</th><th>当前余额</th><th>累计充值</th><th>操作</th>" : "";
    const columnCount = manager ? 8 : 4;
    return `${staffBookingMarkup()}<div class="toolbar"><div class="toolbar-left"><input class="search-input" id="customer-search" type="search" value="${esc(state.customerSearch)}" placeholder="搜索姓名或手机号" aria-label="搜索客户" /></div><div class="toolbar-right"><span class="muted">显示 ${customers.length} / ${state.data.customers.length} 位客户</span></div></div><section class="panel"><div class="table-wrap customer-table-wrap"><table><thead><tr><th>客户</th><th>手机号</th><th>会员等级</th><th>积分</th>${financialHeaders}</tr></thead><tbody>${customers.length ? customers.map((item) => { const member = memberMap.get(item.customer_id); const wallet = walletMap.get(item.customer_id) || {}; const financialCells = manager ? `<td class="mono">${money(item.total_spent)}</td><td class="mono"><strong>${money(wallet.balance)}</strong></td><td class="mono">${money(wallet.recharge_total)}</td><td><button class="btn secondary small" type="button" data-customer-wallet="${esc(item.customer_id)}">查看流水</button></td>` : ""; return `<tr><td><strong>${esc(item.name)}</strong></td><td class="mono">${esc(item.phone)}</td><td>${member ? `<span class="status confirmed">${esc(member.level)}</span>` : `<span class="muted">非会员</span>`}</td><td class="mono">${member ? member.points : "-"}</td>${financialCells}</tr>`; }).join("") : `<tr><td colspan="${columnCount}"><div class="empty">没有找到匹配客户。</div></td></tr>`}</tbody></table></div></section>${manager ? walletDetail : ""}`;
  }

  function staffMarkup() {
    const performances = visibleStaffPerformances(state.data.overview?.performances || []);
    const verifiedServices = state.data.overview?.verified_services || [];
    if (!performances.length && !verifiedServices.length) return `<section class="panel empty">今日暂无消费或服务核验记录。</section>`;
    const performanceMarkup = performances.length ? `<div class="performance-list">${performances.map((item) => `<section class="panel performance-card"><div class="panel-header"><div><h2>${esc(item.stylist_name)}</h2><span>${item.customer_count} 位客户 · ${item.order_count} 单</span></div><strong class="performance-total">${money(item.amount)}</strong></div><div class="panel-body"><div class="service-chip-list">${item.services.length ? item.services.map((service) => `<span class="service-chip">${esc(service.service)} ${money(service.amount)}</span>`).join("") : `<span class="muted">暂无套餐明细</span>`}</div><div class="table-wrap"><table><thead><tr><th>客户</th><th>套餐</th><th>消费金额</th><th>服务时间</th><th>预约状态</th></tr></thead><tbody>${item.customers.length ? item.customers.map((customer) => `<tr><td><strong>${esc(customer.customer_name)}</strong><br><span class="muted">${esc(customer.customer_phone || "")}</span></td><td>${esc(customer.service)}</td><td class="mono">${money(customer.amount)}</td><td class="mono">${formatDate(customer.created_at)}</td><td>${customer.status === "unlinked" ? `<span class="status pending">未关联预约</span>` : statusTag(customer.status)}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">暂无员工服务记录。</div></td></tr>`}</tbody></table></div></div></section>`).join("")}</div>` : "";
    const verificationGroups = Array.from(verifiedServices.reduce((groups, item) => {
      const key = item.stylist_id || item.stylist_name;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
      return groups;
    }, new Map()).values());
    const verifiedMarkup = verificationGroups.length ? `<div class="performance-list verification-group-list">${verificationGroups.map((items) => `<section class="panel performance-card verification-card"><div class="panel-header"><div><h2>${esc(items[0].stylist_name)}</h2><span>${items.length} 条服务核验记录 · 未计入正式绩效</span></div><span class="status verified">已核验</span></div><div class="panel-body"><div class="table-wrap"><table><thead><tr><th>客户</th><th>服务</th><th>核验金额</th><th>核验时间</th><th>状态</th></tr></thead><tbody>${items.map((item) => `<tr><td><strong>${esc(item.customer_name)}</strong><br><span class="muted">${esc(item.customer_phone || "")}</span></td><td>${esc(item.service)}</td><td class="mono">${money(item.amount)}</td><td class="mono">${formatDate(item.verified_at)}</td><td>${statusTag(item.status)}</td></tr>`).join("")}</tbody></table></div><div class="helper-note">服务完成后才会扣套餐、记入消费和正式绩效。</div></div></section>`).join("")}</div>` : "";
    return `<div class="toolbar"><div class="toolbar-left"><span class="muted">正式绩效按已完成消费统计；核验记录归档在对应发型师下面</span></div><div class="toolbar-right"><span class="muted">${performances.length} 个绩效分组 · ${verifiedServices.length} 条核验</span></div></div>${performanceMarkup}${verifiedMarkup}`;
  }

  function financeMarkup() {
    const refunds = state.data.refunds;
    const decision = state.refundDecision;
    const decisionMarkup = decision ? `<section class="panel" style="margin-bottom:16px"><div class="panel-header"><h2>确认退款处理</h2><span>需要店长密码复验</span></div><div class="panel-body"><div class="field"><label for="refund-manager-password">店长密码</label><input id="refund-manager-password" type="password" autocomplete="current-password" /></div><div class="action-row"><button class="btn ${decision.action === "reject" ? "danger" : ""}" type="button" data-refund-confirm="true">确认${decision.action === "approve" ? "通过" : "拒绝"}</button><button class="btn secondary" type="button" data-refund-confirm="false">取消</button></div></div></section>` : "";
    return `<p class="helper-note">退款申请先进入待审核状态；店长密码复验后，后端会在同一事务中完成余额、流水、审计和客户通知处理。</p>${decisionMarkup}<section class="panel"><div class="panel-header"><h2>退款申请</h2><span>共 ${refunds.length} 条</span></div><div class="table-wrap"><table><thead><tr><th>申请时间</th><th>金额</th><th>原因</th><th>状态</th><th>操作</th></tr></thead><tbody>${refunds.length ? refunds.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td class="mono"><strong>￥${Number(item.amount || 0).toFixed(2)}</strong></td><td>${esc(item.reason || "未填写")}</td><td>${statusTag(item.status)}</td><td>${item.status === "pending" ? `<div class="action-row"><button class="btn small" type="button" data-refund-action="approve" data-refund-id="${esc(item.refund_id)}">通过</button><button class="btn danger small" type="button" data-refund-action="reject" data-refund-id="${esc(item.refund_id)}">拒绝</button></div>` : `<span class="muted">已处理</span>`}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">暂无退款申请。</div></td></tr>`}</tbody></table></div></section>`;
  }

  function retentionTypeLabel(type) {
    return ({ churn_risk: "流失风险", birthday: "生日提醒", repurchase: "复购提醒" })[type] || "留存任务";
  }

  function relativeContact(value) {
    if (!value) return "尚未联系";
    const time = new Date(value).getTime();
    if (Number.isNaN(time)) return "联系时间未知";
    const days = Math.max(0, Math.floor((Date.now() - time) / 86400000));
    return days ? `已联系 ${days} 天` : "今天已联系";
  }

  function retentionReason(task) {
    const reasons = Array.isArray(task.trigger_reasons) ? task.trigger_reasons : [];
    return reasons.map((item) => item.reason).filter(Boolean).join("；") || task.suggestion_reason || "符合留存规则";
  }

  function retentionTags(task) {
    const tags = [...(task.strategy_tags || [])];
    const reasons = new Set((task.trigger_reasons || []).map((item) => item.type));
    if (reasons.size > 1) tags.push("多原因合并");
    return tags.length ? `<div class="task-tags">${tags.map((tag) => `<span>${esc(tag === "balance_customer" ? "余额客户" : tag)}</span>`).join("")}</div>` : "";
  }

  function retentionTaskTable(tasks, isToday) {
    if (!tasks.length) return `<div class="empty">${isToday ? "今天没有可处理的留存任务。运行今日扫描后，符合规则的客户会出现在这里。" : "暂无留存联系记录。"}</div>`;
    return `<div class="table-wrap retention-table-wrap"><table><thead><tr><th>客户</th><th>提醒类型</th><th>触发原因</th><th>最近联系</th><th>下次可联系</th><th>Agent 建议</th><th>状态</th><th>操作</th></tr></thead><tbody>${tasks.map((task) => `<tr><td><strong>${esc(task.customer_name)}</strong><br><span class="muted">${esc(task.customer_phone || "未填写手机号")}</span></td><td>${statusTag(task.primary_type === "churn_risk" ? "rejected" : task.primary_type === "birthday" ? "pending" : "confirmed").replace(/>[^<]*</, `>${esc(retentionTypeLabel(task.primary_type))}<`)}${retentionTags(task)}</td><td class="retention-reason">${esc(retentionReason(task))}</td><td><span class="mono">${esc(relativeContact(task.last_contact_at))}</span>${task.last_contact_status ? `<br><span class="muted">${esc(statusLabel(task.last_contact_status))}</span>` : ""}</td><td>${task.next_contact_at ? `<span class="mono">${esc(formatDate(task.next_contact_at))}</span>` : "今天可联系"}</td><td class="retention-suggestion">${esc(task.suggested_message || "待生成建议")}</td><td>${statusTag(task.status)}</td><td><button class="btn secondary small" type="button" data-retention-open="${esc(task.task_id)}">查看</button></td></tr>`).join("")}</tbody></table></div>`;
  }

  function retentionDetailMarkup() {
    if (state.retentionDetailLoading) return `<div class="retention-drawer-backdrop"><aside class="retention-drawer" aria-label="留存任务详情"><div class="empty">正在读取任务详情...</div></aside></div>`;
    const task = state.retentionDetail;
    if (!task) return "";
    const canSend = ["pending_review", "send_failed"].includes(task.status);
    const canIgnore = ["pending_review", "send_failed", "replied", "manual_followup"].includes(task.status);
    const canClose = ["replied", "manual_followup"].includes(task.status);
    const canReply = task.status === "cooling";
    const contacts = task.contacts || [];
    const history = contacts.length ? contacts.map((contact) => `<li><strong>${esc(statusLabel(contact.status))}</strong><span>${esc(formatDate(contact.sent_at || contact.attempted_at))} · ${esc(contact.channel)}</span><p>${esc(contact.actual_message)}</p>${contact.failure_reason ? `<small>失败原因：${esc(contact.failure_reason)}</small>` : ""}${contact.reply_content ? `<small>客户回复：${esc(contact.reply_content)}</small>` : ""}</li>`).join("") : `<li class="muted">暂无联系记录。</li>`;
    return `<div class="retention-drawer-backdrop" role="presentation"><aside class="retention-drawer" role="dialog" aria-modal="true" aria-labelledby="retention-detail-title"><div class="retention-drawer-header"><div><span class="eyebrow">RETENTION TASK</span><h2 id="retention-detail-title">${esc(task.customer_name)} · ${esc(retentionTypeLabel(task.primary_type))}</h2><p>${esc(task.customer_phone || "未填写手机号")}</p></div><button class="btn secondary small" type="button" data-retention-close aria-label="关闭留存任务详情">关闭</button></div><div class="retention-drawer-body"><section class="retention-detail-section"><h3>触发原因</h3><p>${esc(retentionReason(task))}</p>${retentionTags(task)}</section><section class="retention-detail-section"><h3>Agent 建议</h3><p class="muted">${esc(task.suggestion_reason || "安全模板建议，可由员工修改后发送")}</p><label for="retention-message">发送消息</label><textarea id="retention-message" ${canSend ? "" : "readonly"}>${esc(task.suggested_message || "")}</textarea></section>${canSend ? `<div class="action-row retention-primary-action"><button class="btn" type="button" data-retention-task-action="${task.status === "send_failed" ? "retry" : "send"}" data-retention-task-id="${esc(task.task_id)}">${task.status === "send_failed" ? "重试发送" : "确认发送"}</button></div>` : ""}${canReply ? `<section class="retention-detail-section"><h3>客户回复</h3><label for="retention-reply">回复内容</label><textarea id="retention-reply" placeholder="记录客户实际回复"></textarea><button class="btn secondary small" type="button" data-retention-task-action="reply" data-retention-task-id="${esc(task.task_id)}">记录回复并转人工</button></section>` : ""}${canIgnore || canClose ? `<section class="retention-detail-section"><h3>人工处理</h3>${canIgnore ? `<label for="retention-followup-reason">跟进或忽略原因</label><input id="retention-followup-reason" type="text" maxlength="500" placeholder="例如：客户暂不需要" />${task.status !== "manual_followup" ? `<button class="btn secondary small" type="button" data-retention-task-action="manual-followup" data-retention-task-id="${esc(task.task_id)}">转人工跟进</button>` : ""}<label for="retention-ignore-mode">忽略期限</label><select id="retention-ignore-mode"><option value="30_days">忽略 30 天</option><option value="90_days">忽略 90 天</option><option value="permanent">永久忽略</option><option value="unsubscribe">客户明确退订</option></select><button class="btn danger small" type="button" data-retention-task-action="ignore" data-retention-task-id="${esc(task.task_id)}">确认设置</button>` : ""}${canClose ? `<button class="btn secondary small" type="button" data-retention-task-action="close" data-retention-task-id="${esc(task.task_id)}">完成跟进</button>` : ""}</section>` : ""}<section class="retention-detail-section"><h3>联系记录</h3><ol class="retention-history">${history}</ol></section></div></aside></div>`;
  }

  function retentionMarkup() {
    const todayTasks = state.data.retentionTasks || [];
    const source = state.retentionView === "today" ? todayTasks : (state.data.retentionRecords || []);
    const keyword = state.retentionSearch.trim().toLowerCase();
    const visible = source.filter((task) => (state.retentionFilter === "all" || task.primary_type === state.retentionFilter) && (!keyword || [task.customer_name, task.customer_phone, task.suggestion_reason].some((value) => String(value || "").toLowerCase().includes(keyword))));
    const counts = ["birthday", "repurchase", "churn_risk"].reduce((result, type) => ({ ...result, [type]: todayTasks.filter((task) => task.primary_type === type).length }), {});
    const viewCounts = ["birthday", "repurchase", "churn_risk"].reduce((result, type) => ({ ...result, [type]: source.filter((task) => task.primary_type === type).length }), {});
    const failed = todayTasks.filter((task) => task.status === "send_failed").length;
    const tabs = [{ key: "all", label: "全部 " + source.length }, { key: "birthday", label: "生日 " + viewCounts.birthday }, { key: "repurchase", label: "复购 " + viewCounts.repurchase }, { key: "churn_risk", label: "流失 " + viewCounts.churn_risk }];
    return `<section class="retention-workbench"><div class="retention-metrics"><span>今日待处理 <strong>${todayTasks.length}</strong></span><span>生日 <strong>${counts.birthday}</strong></span><span>复购 <strong>${counts.repurchase}</strong></span><span>流失风险 <strong>${counts.churn_risk}</strong></span><span>发送失败 <strong>${failed}</strong></span></div><div class="toolbar retention-toolbar"><div class="retention-view-tabs" role="tablist" aria-label="留存任务视图"><button type="button" role="tab" aria-selected="${state.retentionView === "today"}" class="${state.retentionView === "today" ? "active" : ""}" data-retention-view="today">今日待处理</button><button type="button" role="tab" aria-selected="${state.retentionView === "records"}" class="${state.retentionView === "records" ? "active" : ""}" data-retention-view="records">联系记录</button></div><div class="toolbar-right">${state.retentionView === "today" ? `<button class="btn" type="button" data-action="run-retention">运行今日扫描</button>` : ""}</div></div><div class="retention-filters"><div class="retention-type-tabs" role="tablist" aria-label="留存任务类型">${tabs.map((tab) => `<button type="button" class="${state.retentionFilter === tab.key ? "active" : ""}" data-retention-filter="${tab.key}">${esc(tab.label)}</button>`).join("")}</div><label class="sr-only" for="retention-search">搜索客户</label><input id="retention-search" class="search-input" value="${esc(state.retentionSearch)}" placeholder="搜索客户姓名或手机号" /></div><p class="helper-note">${state.retentionView === "today" ? "这里是今天可以处理的任务；尚未实际联系的客户不会进入联系记录。" : "这里只显示已有发送尝试或人工跟进事实的客户；纯扫描任务不会显示。"}</p><section class="panel"><div class="panel-header"><h2>${state.retentionView === "today" ? "今日待处理客户" : "联系记录"}</h2><span>${visible.length} 条</span></div>${retentionTaskTable(visible, state.retentionView === "today")}</section></section>${retentionDetailMarkup()}`;
  }

  function auditMarkup() {
    const detail = state.auditDetail;
    const drawer = detail ? `<div class="detail-drawer-backdrop" role="presentation"><aside class="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="audit-detail-title"><div class="detail-drawer-header"><div><span class="eyebrow">AUDIT LOG</span><h2 id="audit-detail-title">操作审计详情</h2><p>${esc(formatDate(detail.created_at))}</p></div><button class="btn secondary small" type="button" data-audit-close aria-label="关闭操作审计详情">关闭</button></div><div class="detail-drawer-body"><section class="detail-drawer-section"><h3>操作信息</h3><dl class="detail-list"><div><dt>动作</dt><dd>${esc(detail.action || "-")}</dd></div><div><dt>业务对象</dt><dd>${esc(detail.entity_type || "-")}</dd></div><div><dt>对象编号</dt><dd class="mono">${esc(detail.entity_id || "-")}</dd></div><div><dt>操作人编号</dt><dd class="mono">${esc(detail.actor_user_id || "系统")}</dd></div><div><dt>审计编号</dt><dd class="mono">${esc(detail.audit_id || "-")}</dd></div></dl></section><section class="detail-drawer-section"><h3>记录详情</h3><pre class="audit-detail-content">${esc(detail.details || "没有额外详情")}</pre></section></div></aside></div>` : "";
    return `<section class="panel"><div class="panel-header"><h2>最近关键操作</h2><span>最多展示 100 条</span></div><div class="table-wrap audit-table-wrap" role="region" aria-label="操作审计列表" tabindex="0"><table><thead><tr><th>时间</th><th>动作</th><th>业务对象</th><th>操作</th></tr></thead><tbody>${state.data.audits.length ? state.data.audits.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td>${esc(item.action)}</td><td>${esc(item.entity_type)}<br><span class="muted">${esc(item.entity_id)}</span></td><td><button class="btn secondary small" type="button" data-audit-open="${esc(item.audit_id)}">查看详情</button></td></tr>`).join("") : `<tr><td colspan="4"><div class="empty">暂无审计记录。</div></td></tr>`}</tbody></table></div></section>${drawer}`;
  }

  function assistantMessageMarkup(item) {
    const reference = item.replyTo
      ? `<blockquote class="message-reply-reference"><span>回复${item.replyTo.role === "user" ? "用户" : "智能助手"}</span><p>${esc(assistantQuote(item.replyTo.content))}</p></blockquote>`
      : "";
    return `<div class="message ${esc(item.role)}" data-assistant-message-id="${esc(item.id)}" tabindex="0">${reference}<div class="message-content">${esc(item.content)}</div></div>`;
  }

  function assistantReplyPreviewMarkup() {
    const replyTo = state.assistantReplyTo;
    if (!replyTo) return "";
    return `<div class="assistant-reply-preview" role="status"><div><strong>回复${replyTo.role === "user" ? "用户" : "智能助手"}</strong><p>${esc(assistantQuote(replyTo.content, 240))}</p></div><button class="btn secondary small" type="button" data-assistant-reply-cancel>取消引用</button></div>`;
  }

  function assistantContextMenuMarkup() {
    const menu = state.assistantContextMenu;
    if (!menu) return "";
    const item = state.assistantMessages.find((message) => message.id === menu.messageId);
    if (!item) return "";
    const left = Math.max(8, Math.min(Number(menu.x) || 8, window.innerWidth - 150));
    const top = Math.max(8, Math.min(Number(menu.y) || 8, window.innerHeight - 58));
    return `<div class="assistant-context-menu" role="menu" style="left:${left}px;top:${top}px"><button type="button" role="menuitem" data-assistant-context-action="reply" data-assistant-message-id="${esc(item.id)}">回复</button></div>`;
  }

  function assistantMarkup() {
    const manager = isManager();
    const messages = state.assistantMessages.length ? state.assistantMessages.map(assistantMessageMarkup).join("") : `<div class="empty">${manager ? "可以试试：查看今天预约、给客户代约明天的护理、批复预约、记录留存回复、发送全部生日提醒。" : "可以试试：今天有哪些预约？、李雷最近有没有预约？、护理后多久可以洗头？"}</div>`;
    const task = state.assistantTask;
    const proposal = task?.result_payload?.proposal || task?.result_payload || {};
    const isRefundTask = task?.workflow_type === "refund_approve" || task?.workflow_type === "refund_reject";
    const isChangeTask = task?.workflow_type === "appointment_change";
    const isServiceCompletionTask = task?.workflow_type === "service_completion";
    const isRetentionSendTask = task?.workflow_type === "retention_send" || task?.workflow_type === "retention_retry";
    const taskKind = isRefundTask ? "assistant-refund" : isServiceCompletionTask ? "assistant-service-completion" : isRetentionSendTask ? "assistant-retention-send" : isChangeTask ? "assistant-change" : "assistant-approval";
    const detail = isRefundTask
      ? `${esc(proposal.customer_name || "客户")}：${money(proposal.amount)} 退款`
      : isServiceCompletionTask
        ? `${esc(proposal.customer_name || "客户")}：${esc(proposal.service || "服务")} · ${money(proposal.amount)}${proposal.package_name ? ` · ${esc(proposal.package_name)} 剩余 ${esc(proposal.remaining_uses_before)} 次` : ""}`
      : isRetentionSendTask
        ? `${esc(proposal.customer_name || "客户")}：${esc(proposal.message || "")}`
      : isChangeTask
        ? `${esc(proposal.customer_name || "客户")}：${esc(formatDate(proposal.old_datetime || ""))} -> ${esc(formatDate(proposal.new_datetime || ""))}`
      : `${esc(proposal.customer_name || "预约")}：${esc(formatDate(proposal.appointment_datetime || ""))} · ${esc(proposal.service || "")}`;
    const taskMarkup = task ? `<div class="helper-note" style="margin:12px 0"><strong>待确认操作</strong><br>${detail}${task.awaiting_confirmation ? `${isRefundTask ? `<div class="field" style="margin-top:10px"><label for="assistant-step-up-password">当前账号密码</label><input id="assistant-step-up-password" type="password" autocomplete="current-password" /></div>` : ""}<div class="action-row" style="margin-top:10px"><button class="btn small" type="button" data-agent-confirm="true" data-agent-task-kind="${taskKind}" data-task-id="${esc(task.task_id)}">${isRefundTask ? `确认${proposal.decision === "reject" ? "拒绝" : "通过"}` : isServiceCompletionTask ? "确认完成服务" : isRetentionSendTask ? "确认发送" : isChangeTask ? "确认改约" : "确认批复"}</button><button class="btn danger small" type="button" data-agent-confirm="false" data-agent-task-kind="${taskKind}" data-task-id="${esc(task.task_id)}">取消</button></div>` : `<br><span class="muted">${esc(task.result_payload?.message || task.status)}</span>`}</div>` : "";
    return `<section class="panel"><div class="panel-header"><h2>${manager ? "店长智能助手" : "智能助手"}</h2><span>${manager ? "查询与工作台操作" : "只读查询"}</span></div><div class="message-list" id="assistant-messages">${messages}</div>${assistantContextMenuMarkup()}${taskMarkup}<form class="assistant-form" id="assistant-form">${assistantReplyPreviewMarkup()}<div class="assistant-form-row"><label class="sr-only" for="assistant-input">输入问题</label><input id="assistant-input" name="message" required placeholder="${manager ? "输入要查询或处理的工作台事项" : "输入你想查询的门店信息"}" autocomplete="off" /><button class="btn" type="submit">${manager ? "发送" : "查询"}</button></div></form></section>`;
  }

  function scrollAssistantToLatest() {
    const list = document.querySelector("#assistant-messages");
    if (list) list.scrollTop = list.scrollHeight;
  }

  async function loadData() {
    const user = await api("/api/auth/me");
    if (!["stylist", "admin"].includes(user.role)) throw new Error("当前账号不是员工账号");
    const manager = user.role === "admin";
    const [schedule, customers, members, retentionTasks, retentionRecords, birthdays, stylists, refunds, audits, wallets, overview] = await Promise.all([
      safeGet(`/api/staff/schedule?date=${encodeURIComponent(state.scheduleDate)}`, []),
      safeGet("/api/customers", []),
      safeGet("/api/members", []),
      manager ? safeGet("/api/retention/tasks?view=today", []) : Promise.resolve([]),
      manager ? safeGet("/api/retention/tasks?view=records", []) : Promise.resolve([]),
      manager ? safeGet("/api/marketing/birthdays", []) : Promise.resolve([]),
      safeGet("/api/stylists", []),
      manager ? safeGet("/api/refunds", []) : Promise.resolve([]),
      manager ? safeGet("/api/audit-logs", []) : Promise.resolve([]),
      manager ? safeGet("/api/staff/customer-wallets", []) : Promise.resolve([]),
      manager ? safeGet("/api/staff/overview", null) : Promise.resolve(null),
    ]);
    let changeSlots = [];
    if (manager) {
      const slotsByStylist = await Promise.all(stylists
        .filter((stylist) => H5_STYLIST_NAMES.has(stylist.name) && stylist.is_available)
        .map(async (stylist) => (await safeGet(
          `/api/stylists/${encodeURIComponent(stylist.stylist_id)}/slots?days_ahead=7`, []
        )).map((slot) => ({ ...slot, stylist_name: stylist.name }))));
      changeSlots = slotsByStylist
        .flat()
        .sort((a, b) => `${a.date} ${a.time}${a.stylist_name}`.localeCompare(`${b.date} ${b.time}${b.stylist_name}`));
    }
    state.user = user;
    state.data = { schedule: visibleStaffSchedule(schedule), customers, members, refunds, audits, retentionTasks, retentionRecords, birthdays, wallets, overview, changeSlots, stylists };
    if (!manager && !["schedule", "customers", "assistant"].includes(state.view)) state.view = "schedule";
  }

  async function enterApp() {
    try {
      await loadData();
      renderShell();
    } catch (error) {
      state.token = "";
      renderLogin(error.message || "无法进入员工工作台");
    }
  }

  async function login(form) {
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ phone: form.phone.value.trim(), password: form.password.value }) });
      state.token = result.access_token;
      await enterApp();
    } catch (error) {
      renderLogin(error.message || "登录失败，请检查账号和密码");
    } finally { button.disabled = false; }
  }

  async function refresh(view = state.view) {
    try { await loadData(); state.view = view; renderShell(); notify("数据已刷新"); } catch (error) { notify(error.message, true); }
  }

  async function mutateReminder(id, action) {
    try { await api(`/api/retention/reminders/${encodeURIComponent(id)}/${action}`, { method: "POST" }); await refresh("retention"); notify(action === "contacted" ? "已标记为已联系" : "已忽略提醒"); } catch (error) { notify(error.message, true); }
  }

  async function mutateRefund(id, action) {
    state.refundDecision = { id, action };
    state.view = "finance";
    renderShell();
  }

  async function confirmRefundDecision(confirmed) {
    if (!confirmed) {
      state.refundDecision = null;
      renderShell();
      return;
    }
    const password = document.querySelector("#refund-manager-password")?.value || "";
    if (!password) { notify("请输入店长密码", true); return; }
    const decision = state.refundDecision;
    try {
      await api(`/api/refunds/${encodeURIComponent(decision.id)}/${decision.action}`, {
        method: "POST", body: JSON.stringify({ manager_password: password }),
      });
      state.refundDecision = null;
      await refresh("finance");
      notify(decision.action === "approve" ? "退款已通过" : "退款已拒绝");
    } catch (error) { notify(error.message, true); }
  }

  async function askAssistant(form) {
    const input = form.message;
    const message = input.value.trim();
    if (!message) return;
    const replyTo = state.assistantReplyTo ? { ...state.assistantReplyTo } : null;
    state.assistantMessages.push(assistantMessage("user", message, replyTo));
    state.assistantReplyTo = null;
    state.assistantContextMenu = null;
    input.value = "";
    renderShell();
    scrollAssistantToLatest();
    try {
      const result = await api("/api/staff/agent/query", {
        method: "POST",
        body: JSON.stringify({ message, reply_to: replyTo }),
      });
      state.assistantMessages.push(assistantMessage("assistant", result.reply || "没有得到可展示的回答。"));
      if (result.agent_task) state.assistantTask = result.agent_task;
      const mutationMarkers = [
        "tool:batch_send_birthday_retention",
        "tool:batch_send_retention_by_visit_age",
        "tool:scan_retention",
        "tool:create_staff_appointment",
        "tool:verify_appointment_service",
        "tool:retention_task_action",
        "tool:legacy_reminder_action",
      ];
      if ((result.actions || []).some((action) => mutationMarkers.includes(action))) {
        try { await loadData(); } catch (refreshError) { console.warn("助手操作完成，但工作台刷新失败", refreshError); }
      }
    } catch (error) {
      if (error.code === "AUTH_EXPIRED") return;
      state.assistantMessages.push(assistantMessage("assistant", `查询失败：${error.message}`));
    }
    renderShell();
    scrollAssistantToLatest();
    document.querySelector("#assistant-input")?.focus();
  }

  async function runRetentionAnalysis() {
    try {
      state.retentionAnalysis = await api("/api/retention/agent/run", { method: "POST" });
      await loadData();
      state.view = "retention";
      renderShell();
      notify("今日留存任务已生成");
    } catch (error) { notify(error.message, true); }
  }

  async function openRetentionTask(taskId) {
    state.retentionDetail = null;
    state.retentionDetailLoading = true;
    renderShell();
    try {
      state.retentionDetail = await api(`/api/retention/tasks/${encodeURIComponent(taskId)}`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      state.retentionDetailLoading = false;
      renderShell();
    }
  }

  async function mutateRetentionTask(taskId, action) {
    const message = document.querySelector("#retention-message")?.value?.trim() || "";
    const reason = document.querySelector("#retention-followup-reason")?.value?.trim() || null;
    const ignoreMode = document.querySelector("#retention-ignore-mode")?.value || "30_days";
    const replyContent = document.querySelector("#retention-reply")?.value?.trim() || "";
    const pathByAction = {
      send: "send", retry: "retry", "manual-followup": "manual-followup", ignore: "ignore", reply: "reply", close: "close",
    };
    const payloadByAction = {
      send: { message }, retry: { message }, "manual-followup": { reason }, ignore: { mode: ignoreMode, reason }, reply: { reply_content: replyContent }, close: { reason },
    };
    if (["send", "retry"].includes(action) && !message) { notify("请先填写要发送的消息", true); return; }
    if (action === "reply" && !replyContent) { notify("请先填写客户回复内容", true); return; }
    try {
      const result = await api(`/api/retention/tasks/${encodeURIComponent(taskId)}/${pathByAction[action]}`, {
        method: "POST", body: JSON.stringify(payloadByAction[action]),
      });
      await loadData();
      state.retentionDetail = await api(`/api/retention/tasks/${encodeURIComponent(taskId)}`);
      state.view = "retention";
      renderShell();
      notify(({ send: "消息已发送并进入冷却", retry: "重试发送成功", "manual-followup": "已转人工跟进", ignore: "已设置忽略", reply: "客户回复已记录", close: "跟进已完成" })[action]);
      return result;
    } catch (error) { notify(error.message, true); }
  }

  async function proposeAppointmentChange(form) {
    try {
      state.changeTask = await api("/api/staff/agent/appointment-change/propose", {
        method: "POST",
        body: JSON.stringify({
          appointment_id: form.appointment_id.value.trim(),
          new_slot_id: form.new_slot_id.value.trim(),
          new_stylist_id: form.new_stylist_id.value.trim() || null,
        }),
      });
      state.view = "schedule";
      renderShell();
      notify("调整方案已生成，等待员工确认");
    } catch (error) { notify(error.message, true); }
  }

  async function confirmAppointmentChange(taskId, confirmed) {
    return confirmAgentTask(taskId, confirmed, "change");
  }

  async function approveAppointment(appointmentId, button) {
    if (button) {
      button.disabled = true;
      button.textContent = "生成批复方案...";
    }
    try {
      state.approvalTask = await api("/api/staff/agent/appointment-approval/propose", {
        method: "POST", body: JSON.stringify({ appointment_id: appointmentId }),
      });
      state.view = "schedule";
      renderShell();
      notify("批复方案已生成，请核对后确认");
    } catch (error) { notify(error.message, true); }
  }

  async function confirmAgentTask(taskId, confirmed, kind) {
    const managerPassword = kind === "assistant-refund"
      ? (document.querySelector("#assistant-step-up-password")?.value || "")
      : null;
    if (confirmed && kind === "assistant-refund" && !managerPassword) {
      notify("请输入店长密码", true);
      return;
    }
    try {
      const task = await api(`/api/staff/agent/tasks/${encodeURIComponent(taskId)}/confirm`, {
        method: "POST", body: JSON.stringify({ confirmed, manager_password: managerPassword }),
      });
      if (kind === "approval") state.approvalTask = task;
      else if (kind === "assistant-approval" || kind === "assistant-refund" || kind === "assistant-change" || kind === "assistant-service-completion" || kind === "assistant-retention-send") state.assistantTask = task;
      else state.changeTask = task;
      if (confirmed) await loadData();
      renderShell();
      notify(confirmed ? (kind === "approval" ? "预约已批复并同步客户记录" : kind === "assistant-refund" ? "退款已处理并同步客户账户" : kind === "assistant-service-completion" ? "服务已完成，套餐和绩效已同步" : kind === "assistant-retention-send" ? "留存消息已发送并同步客户通知" : "预约调整已执行") : "已取消方案");
    } catch (error) { notify(error.message, true); }
  }

  async function loadStaffBookingSlots(stylistId) {
    state.bookingStylistId = stylistId;
    state.bookingSlots = [];
    if (!stylistId) { renderShell(); return; }
    state.bookingSlotsLoading = true;
    renderShell();
    try {
      state.bookingSlots = await api(`/api/stylists/${encodeURIComponent(stylistId)}/slots?days_ahead=7`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      state.bookingSlotsLoading = false;
      renderShell();
    }
  }

  function resolveBookingCustomer(value) {
    const text = String(value || "").trim();
    if (!text) return null;
    return (state.data.customers || []).find((item) => {
      const label = `${item.name} · ${item.phone || "未填写手机号"}`;
      return text === label || text === item.name || text === item.phone;
    }) || null;
  }

  async function createStaffAppointment(form) {
    const matchedCustomer = resolveBookingCustomer(form.customer_label.value);
    const customerId = matchedCustomer?.customer_id || "";
    const stylistId = form.stylist_id.value;
    const slotId = form.slot_id.value;
    if (!customerId) { notify("请输入并选择已有客户", true); return; }
    if (!stylistId || !slotId) { notify("请先选择发型师和可用时间", true); return; }
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const result = await api("/api/staff/appointments", {
        method: "POST",
        body: JSON.stringify({
          customer_id: customerId,
          stylist_id: stylistId,
          slot_id: slotId,
          service: form.service.value,
          notes: form.notes.value.trim() || null,
        }),
      });
      state.scheduleDate = String(result.appointment_datetime || "").slice(0, 10) || state.scheduleDate;
      state.bookingSlots = [];
      state.bookingCustomerId = "";
      state.bookingCustomerQuery = "";
      state.bookingStylistId = "";
      await loadData();
      state.view = "schedule";
      renderShell();
      notify(`已为${result.customer_name}预约${result.stylist_name}老师，客户端已同步`);
    } catch (error) {
      notify(error.message, true);
      button.disabled = false;
    }
  }

  async function openServiceVerification(appointmentId) {
    state.view = "schedule";
    state.verification = null;
    state.verificationLoading = true;
    renderShell();
    try {
      state.verification = await api(`/api/staff/appointments/${encodeURIComponent(appointmentId)}/verification`);
    } catch (error) {
      notify(error.message, true);
    } finally {
      state.verificationLoading = false;
      renderShell();
    }
  }

  async function verifyService(appointmentId) {
    const packageId = document.querySelector("#verification-package")?.value || "";
    const amountValue = document.querySelector("#verification-amount")?.value || "";
    const amount = amountValue ? Number(amountValue) : null;
    try {
      await api(`/api/staff/appointments/${encodeURIComponent(appointmentId)}/verify`, {
        method: "POST",
        body: JSON.stringify({ customer_package_id: packageId || null, amount }),
      });
      await loadData();
      state.verification = await api(`/api/staff/appointments/${encodeURIComponent(appointmentId)}/verification`);
      renderShell();
      notify("服务已核验，预约和员工管理记录已同步");
    } catch (error) { notify(error.message, true); }
  }

  async function completeService(verificationId) {
    try {
      await api(`/api/staff/service-verifications/${encodeURIComponent(verificationId)}/complete`, {
        method: "POST", body: JSON.stringify({}),
      });
      state.verification = null;
      // refresh() reloads schedule, customers, wallets, and staff overview together.
      await refresh("schedule");
      notify("服务已完成，余额、消费总览和员工绩效已同步");
    } catch (error) { notify(error.message, true); }
  }

  function selectAssistantReply(messageId) {
    const item = state.assistantMessages.find((message) => message.id === messageId);
    if (!item) return;
    state.assistantReplyTo = { message_id: item.id, role: item.role, content: item.content };
    state.assistantContextMenu = null;
    renderShell();
    requestAnimationFrame(() => document.querySelector("#assistant-input")?.focus());
  }

  document.addEventListener("contextmenu", (event) => {
    const message = event.target.closest?.("#assistant-messages .message[data-assistant-message-id]");
    if (!message) return;
    event.preventDefault();
    state.assistantContextMenu = {
      messageId: message.dataset.assistantMessageId,
      x: event.clientX,
      y: event.clientY,
    };
    renderShell();
  });

  document.addEventListener("submit", (event) => {
    if (event.target.id === "login-form") { event.preventDefault(); login(event.target); }
    if (event.target.id === "assistant-form") { event.preventDefault(); askAssistant(event.target); }
    if (event.target.id === "change-form") { event.preventDefault(); proposeAppointmentChange(event.target); }
    if (event.target.id === "staff-booking-form") { event.preventDefault(); createStaffAppointment(event.target); }
  });

  document.addEventListener("click", (event) => {
    if (state.assistantContextMenu && !event.target.closest(".assistant-context-menu")) {
      state.assistantContextMenu = null;
      renderShell();
      return;
    }
    const assistantContextAction = event.target.closest("[data-assistant-context-action]");
    if (assistantContextAction?.dataset.assistantContextAction === "reply") {
      selectAssistantReply(assistantContextAction.dataset.assistantMessageId);
      return;
    }
    if (event.target.closest("[data-assistant-reply-cancel]")) {
      state.assistantReplyTo = null;
      renderShell();
      return;
    }
    const retentionFocus = event.target.closest("[data-retention-focus]");
    if (retentionFocus) {
      const key = retentionFocus.dataset.retentionFocus;
      document.querySelectorAll("[data-retention-panel]").forEach((panel) => { panel.hidden = panel.dataset.retentionPanel !== key; });
      document.querySelector("[data-retention-hint]")?.setAttribute("hidden", "");
      const target = document.querySelector(`[data-retention-panel="${key}"]`);
      target?.removeAttribute("hidden");
      target?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const retentionView = event.target.closest("[data-retention-view]");
    if (retentionView) {
      state.retentionView = retentionView.dataset.retentionView;
      state.retentionFilter = "all";
      state.retentionDetail = null;
      renderShell();
      return;
    }
    const retentionFilter = event.target.closest("[data-retention-filter]");
    if (retentionFilter) {
      state.retentionFilter = retentionFilter.dataset.retentionFilter;
      renderShell();
      return;
    }
    const retentionOpen = event.target.closest("[data-retention-open]");
    if (retentionOpen) { openRetentionTask(retentionOpen.dataset.retentionOpen); return; }
    if (event.target.closest("[data-retention-close]")) { state.retentionDetail = null; renderShell(); return; }
    const auditOpen = event.target.closest("[data-audit-open]");
    if (auditOpen) {
      state.auditDetail = state.data.audits.find((item) => item.audit_id === auditOpen.dataset.auditOpen) || null;
      renderShell();
      return;
    }
    if (event.target.closest("[data-audit-close]")) { state.auditDetail = null; renderShell(); return; }
    if (event.target.closest("[data-wallet-close]")) { state.selectedCustomerId = ""; renderShell(); return; }
    const retentionTaskAction = event.target.closest("[data-retention-task-action]");
    if (retentionTaskAction) { mutateRetentionTask(retentionTaskAction.dataset.retentionTaskId, retentionTaskAction.dataset.retentionTaskAction); return; }
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) { state.view = viewButton.dataset.view; renderShell(); return; }
    const actionButton = event.target.closest("[data-action]");
    const action = actionButton?.dataset.action;
    if (action === "logout") { api("/api/auth/logout", { method: "POST" }).catch(() => {}); state.token = ""; state.user = null; renderLogin(); return; }
    if (action === "refresh") { refresh(); return; }
    if (action === "refresh-schedule") { refresh("schedule"); return; }
    if (action === "run-retention") { runRetentionAnalysis(); return; }
    if (action === "close-verification") { state.verification = null; renderShell(); return; }
    if (action === "verify-service") { verifyService(actionButton.dataset.appointmentId); return; }
    if (action === "complete-service") { completeService(actionButton.dataset.verificationId); return; }
    const verifyButton = event.target.closest("[data-verify-appointment]");
    if (verifyButton) { openServiceVerification(verifyButton.dataset.verifyAppointment); return; }
    const approvalButton = event.target.closest("[data-approve-appointment]");
    if (approvalButton) { approveAppointment(approvalButton.dataset.approveAppointment, approvalButton); return; }
    const walletButton = event.target.closest("[data-customer-wallet]");
    if (walletButton) { state.selectedCustomerId = walletButton.dataset.customerWallet; renderShell(); return; }
    const confirmation = event.target.closest("[data-agent-confirm]");
    if (confirmation) { confirmAgentTask(confirmation.dataset.taskId, confirmation.dataset.agentConfirm === "true", confirmation.dataset.agentTaskKind || "change"); return; }
    const refundConfirmation = event.target.closest("[data-refund-confirm]");
    if (refundConfirmation) { confirmRefundDecision(refundConfirmation.dataset.refundConfirm === "true"); return; }
    const refund = event.target.closest("[data-refund-action]");
    if (refund) { mutateRefund(refund.dataset.refundId, refund.dataset.refundAction); return; }
    const reminder = event.target.closest("[data-reminder-action]");
    if (reminder) { mutateReminder(reminder.dataset.reminderId, reminder.dataset.reminderAction); }
  });

  document.addEventListener("input", (event) => {
    if (event.target.id === "customer-search") { state.customerSearch = event.target.value; const selectionStart = event.target.selectionStart; renderShell(); const next = document.querySelector("#customer-search"); next?.focus(); next?.setSelectionRange(selectionStart, selectionStart); }
    if (event.target.id === "retention-search") { state.retentionSearch = event.target.value; const selectionStart = event.target.selectionStart; renderShell(); const next = document.querySelector("#retention-search"); next?.focus(); next?.setSelectionRange(selectionStart, selectionStart); }
    if (event.target.id === "staff-booking-customer") {
      state.bookingCustomerQuery = event.target.value;
      const matched = resolveBookingCustomer(event.target.value);
      state.bookingCustomerId = matched?.customer_id || "";
      const hidden = document.querySelector("#staff-booking-form input[name='customer_id']");
      if (hidden) hidden.value = state.bookingCustomerId;
    }
  });
  document.addEventListener("change", (event) => {
    if (event.target.id === "schedule-date") { state.scheduleDate = event.target.value; refresh("schedule"); }
    if (event.target.id === "staff-booking-customer") {
      state.bookingCustomerQuery = event.target.value;
      const matched = resolveBookingCustomer(event.target.value);
      state.bookingCustomerId = matched?.customer_id || "";
      const hidden = document.querySelector("#staff-booking-form input[name='customer_id']");
      if (hidden) hidden.value = state.bookingCustomerId;
    }
    if (event.target.id === "staff-booking-stylist") { loadStaffBookingSlots(event.target.value); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (state.assistantContextMenu) { state.assistantContextMenu = null; renderShell(); return; }
    if (state.assistantReplyTo) { state.assistantReplyTo = null; renderShell(); return; }
    if (state.retentionDetail || state.retentionDetailLoading) { state.retentionDetail = null; state.retentionDetailLoading = false; renderShell(); return; }
    if (state.verification || state.verificationLoading) { state.verification = null; state.verificationLoading = false; renderShell(); return; }
    if (state.auditDetail) { state.auditDetail = null; renderShell(); return; }
    if (state.selectedCustomerId) { state.selectedCustomerId = ""; renderShell(); }
  });

  renderLogin();
  enterApp();
})();
