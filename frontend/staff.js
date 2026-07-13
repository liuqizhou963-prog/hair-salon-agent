(function () {
  "use strict";

  const API_BASE = "";
  const TOKEN_KEY = "hengyi_staff_access_token";
  const app = document.querySelector("#app");
  const toast = document.querySelector("#toast");
  function localDateValue() {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }

  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    user: null,
    view: "dashboard",
    data: { schedule: [], customers: [], members: [], refunds: [], audits: [], reminders: [], birthdays: [], wallets: [], overview: null, changeSlots: [] },
    scheduleDate: localDateValue(),
    customerSearch: "",
    selectedCustomerId: "",
    assistantMessages: [],
    retentionAnalysis: null,
    changeTask: null,
    verification: null,
    verificationLoading: false,
  };

  // Keep employee management aligned with the four stylists shown in the H5 booking page.
  const H5_STYLIST_ORDER = {
    "13800001111": 0,
    "13800002222": 1,
    "13800003333": 2,
    "13800004444": 3,
  };
  const H5_STYLIST_NAMES = new Set(["张三", "李四", "王五", "赵六"]);
  const RETENTION_GROUPS = [
    { key: "churn_risk", title: "流失风险", description: "超过个人复购节奏，需要优先挽回。" },
    { key: "birthday", title: "生日提醒", description: "进入生日窗口，适合提前触达。" },
    { key: "repurchase", title: "复购提醒", description: "到了个人复购节奏，可以安排回店。" },
  ];
  const DEFAULT_RETENTION_RULES = [
    { label: "流失风险", description: "距上次到店达到个人复购周期的 2.5 倍。" },
    { label: "生日提醒", description: "客户生日进入未来 5 天提醒窗口。" },
    { label: "复购提醒", description: "距上次到店达到个人复购周期的 1.2 倍。" },
    { label: "余额客户", description: "账户余额大于 0，作为回访触发点。" },
  ];

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

  function statusLabel(value) {
    return ({ pending: "待处理", approved: "已通过", rejected: "已拒绝", confirmed: "已确认", completed: "已完成", cancelled: "已取消", contacted: "已联系", dismissed: "已忽略" })[value] || value || "未知";
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
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
    let body = null;
    try { body = await response.json(); } catch (_) { body = null; }
    if (response.status === 401) {
      state.token = "";
      state.user = null;
      localStorage.removeItem(TOKEN_KEY);
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
    app.innerHTML = `
      <div class="shell">
        <aside class="sidebar">
          <div class="sidebar-brand"><div class="brand-mark-icon" aria-hidden="true">恒</div><div><strong>恒艺美发</strong><span>员工运营工作台</span></div></div>
          <nav class="nav" aria-label="员工工作台导航">
            ${navButton("dashboard", "⌂", "工作概览")}
            ${navButton("schedule", "◷", "今日预约")}
            ${navButton("customers", "◎", "客户与会员")}
            ${navButton("staff", "♙", "员工管理")}
            ${navButton("finance", "￥", "退款处理")}
            ${navButton("retention", "!", "留存提醒")}
            ${navButton("audit", "≡", "操作审计")}
            ${navButton("assistant", "✦", "员工助手")}
          </nav>
          <div class="sidebar-footer"><div class="staff-mini"><div class="staff-avatar" aria-hidden="true">${esc(initials(state.user?.name))}</div><div><strong>${esc(state.user?.name)}</strong><span>${esc(state.user?.role === "admin" ? "管理员" : "发型师")}</span></div></div><button class="logout-btn" type="button" data-action="logout">退出</button></div>
        </aside>
        <main class="content">
          <header class="content-header"><div><p class="eyebrow">OPERATIONS DESK</p><h1>${esc(viewTitle(state.view))}</h1><p>${esc(viewDescription(state.view))}</p></div><div class="header-actions"><span class="date-chip">${esc(todayLabel())}</span><button class="btn secondary" type="button" data-action="refresh"><span class="btn-icon" aria-hidden="true">↻</span>刷新数据</button></div></header>
          ${viewMarkup(state.view)}
        </main>
      </div>`;
  }

  function viewTitle(view) { return ({ dashboard: "工作概览", schedule: "今日预约", customers: "客户与会员", staff: "员工管理", finance: "退款处理", retention: "留存提醒", audit: "操作审计", assistant: "员工助手" })[view] || "工作概览"; }
  function viewDescription(view) { return ({ dashboard: "快速掌握今天的门店运营状态。", schedule: "按发型师查看当天预约和客户需求。", customers: "查找客户基础资料、会员等级和积分。", staff: "按发型师查看客户服务记录和今日业绩。", finance: "处理客户退款申请，所有决定都会留下记录。", retention: "按优先级跟进需要再次触达的客户。", audit: "查看关键业务动作的操作者和时间。", assistant: "用自然语言查询真实业务数据和门店知识。" })[view] || ""; }

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
    return `<div class="metric-grid">${metric("今日预约", state.data.schedule.reduce((total, group) => total + (group.appointments || []).length, 0), "全店发型师合计", "◷", "schedule")}${metric("会员客户", state.data.members.length, "已建立会员资料", "◎", "customers")}${metric("待处理退款", pendingRefunds, pendingRefunds ? "需要员工审核" : "当前没有待审核申请", "￥", "finance")}${metric("待跟进客户", state.data.reminders.length, "留存规则生成的待办", "!", "retention")}</div>
      <section class="panel revenue-panel"><div class="panel-header"><h2>今日营业额</h2><span>${esc(overview.date || todayLabel())}</span></div><div class="summary-stat-grid"><div class="summary-stat"><span>消费</span><strong>${money(overview.consumption)}</strong><small>${overview.customer_count || 0} 位客户 · ${overview.order_count || 0} 单</small></div><div class="summary-stat"><span>充值</span><strong>${money(overview.recharge)}</strong><small>客户账户充值到账</small></div><div class="summary-stat"><span>退款</span><strong>${money(overview.refund)}</strong><small>已处理退款</small></div><div class="summary-stat"><span>待退款</span><strong>${money(overview.pending_refund)}</strong><small>待审核申请金额</small></div></div><div class="table-wrap"><table><thead><tr><th>服务套餐</th><th>客户数</th><th>订单数</th><th>消费金额</th></tr></thead><tbody>${serviceRows}</tbody></table></div></section>`;
  }

  function scheduleTable(items) {
    if (!items.length) return `<div class="empty">今天还没有预约记录。</div>`;
    return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>客户</th><th>项目</th><th>发型师</th><th>状态</th><th>操作</th></tr></thead><tbody>${items.map((item) => `<tr><td class="mono">${formatDate(item.appointment_datetime)}</td><td><strong>${esc(item.customer_name)}</strong><br><span class="muted">${esc(item.customer_phone)}</span></td><td>${esc(item.service)}</td><td>${esc(item.stylist_name)}</td><td>${statusTag(item.status)}</td><td>${item.status === "cancelled" ? `<span class="muted">已取消</span>` : item.status === "completed" ? `<span class="status completed">已完成</span>` : `<button class="btn secondary small" type="button" data-verify-appointment="${esc(item.appointment_id)}">核验服务</button>`}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function verificationMarkup() {
    if (state.verificationLoading) return `<section class="panel verification-panel"><div class="panel-body"><div class="empty">正在读取客户套餐和预约状态...</div></div></section>`;
    const data = state.verification;
    if (!data) return "";
    const verification = data.verification;
    const packageOptions = data.packages.length
      ? data.packages.map((item) => `<option value="${esc(item.customer_package_id)}">${esc(item.package_name)} · 剩余 ${item.remaining_uses}/${item.total_uses} 次 · 到期 ${formatDate(item.expires_at, false)}</option>`).join("")
      : `<option value="">暂无匹配套餐</option>`;
    const statusBlock = verification
      ? `<div class="verification-status"><span>核验状态</span>${statusTag(verification.status)}<strong>${money(verification.amount)}</strong>${verification.package_name ? `<small>${esc(verification.package_name)} · 完成后扣 1 次</small>` : `<small>直接消费记录</small>`}</div>${verification.status === "verified" ? `<button class="btn" type="button" data-action="complete-service" data-verification-id="${esc(verification.verification_id)}">确认完成服务</button>` : `<div class="helper-note">该服务已经完成并计入员工绩效。</div>`}`
      : `<div class="verification-form"><div class="field"><label for="verification-package">使用客户套餐</label><select id="verification-package"><option value="">不使用套餐，直接记录消费</option>${packageOptions}</select></div><div class="field"><label for="verification-amount">直接消费金额</label><input id="verification-amount" type="number" min="0.01" step="0.01" placeholder="使用套餐时可留空" /></div><div class="helper-note">核验只建立服务记录；点击“确认完成服务”后才会扣套餐次数并计入绩效。</div><button class="btn" type="button" data-action="verify-service" data-appointment-id="${esc(data.appointment_id)}">核验服务</button></div>`;
    return `<section class="panel verification-panel"><div class="panel-header"><div><h2>服务核验</h2><span>${esc(data.customer_name)} · ${esc(data.service)} · ${esc(data.stylist_name)}</span></div><button class="btn secondary small" type="button" data-action="close-verification">关闭</button></div><div class="panel-body"><div class="verification-summary"><div><span>预约时间</span><strong>${formatDate(data.appointment_datetime)}</strong></div><div><span>预约状态</span>${statusTag(data.appointment_status)}</div><div><span>可用套餐</span><strong>${data.packages.length} 个</strong></div></div>${statusBlock}</div></section>`;
  }

  function scheduleMarkup() {
    return `<div class="toolbar"><div class="toolbar-left"><label class="muted" for="schedule-date">日期</label><input class="date-input" id="schedule-date" type="date" value="${esc(state.scheduleDate)}" /></div><div class="toolbar-right"><button class="btn secondary small" type="button" data-action="refresh-schedule">重新查询</button></div></div><div class="schedule-list">${state.data.schedule.length ? state.data.schedule.map((group) => `<section class="panel schedule-group"><div class="schedule-group-title"><span>${esc(group.stylist_name)}</span><span>${(group.appointments || []).length} 条预约</span></div>${scheduleTable((group.appointments || []).map((item) => ({ ...item, stylist_name: group.stylist_name })))}</section>`).join("") : `<div class="panel empty">${esc(state.scheduleDate)} 没有预约记录。</div>`}</div>${verificationMarkup()}${appointmentChangeMarkup()}`;
  }

  function appointmentChangeMarkup() {
    const proposal = state.changeTask?.result_payload;
    const result = proposal ? `<div class="helper-note" style="margin-top:14px"><strong>调整方案</strong><br>${esc(proposal.customer_name || "客户")}：${esc(proposal.old_datetime || "")} -> ${esc(proposal.new_datetime || "")}，发型师：${esc(proposal.old_stylist_name || "")} -> ${esc(proposal.new_stylist_name || "")}${state.changeTask.awaiting_confirmation ? `<div class="action-row" style="margin-top:12px"><button class="btn small" type="button" data-agent-confirm="true" data-task-id="${esc(state.changeTask.task_id)}">确认执行</button><button class="btn danger small" type="button" data-agent-confirm="false" data-task-id="${esc(state.changeTask.task_id)}">拒绝方案</button></div>` : `<br><span class="muted">${esc(state.changeTask.status)}</span>`}</div>` : "";
    const appointments = flattenSchedule().filter((item) => !["cancelled", "completed"].includes(item.status));
    const appointmentOptions = appointments.length
      ? appointments.map((item) => `<option value="${esc(item.appointment_id)}">${esc(item.customer_name)} · ${esc(item.customer_phone || "无手机号")} · ${esc(formatDate(item.appointment_datetime))} · ${esc(item.stylist_name)}</option>`).join("")
      : `<option value="">当前日期没有可调整的未完成预约</option>`;
    const slotOptions = state.data.changeSlots.length
      ? state.data.changeSlots.map((slot) => `<option value="${esc(slot.slot_id)}">${esc(slot.stylist_name)} · ${esc(slot.date)} ${esc(slot.time)}</option>`).join("")
      : `<option value="">暂无可用时间</option>`;
    return `<section class="panel" style="margin-top:16px"><div class="panel-header"><h2>预约调整</h2><span>人工确认后才写入</span></div><div class="panel-body"><form id="change-form" class="form-grid"><div class="toolbar-left"><div class="field"><label for="change-appointment-id">选择要调整的预约</label><select id="change-appointment-id" name="appointment_id" required>${appointmentOptions}</select></div><div class="field"><label for="change-slot-id">选择新的发型师和时间</label><select id="change-slot-id" name="new_slot_id" required>${slotOptions}</select></div><div class="helper-note">页面显示客户手机号、预约时间和发型师姓名；系统会在后台自动使用对应编号完成校验。</div><button class="btn" type="submit"${appointments.length && state.data.changeSlots.length ? "" : " disabled"}>生成调整方案</button></div></form>${result}</div></section>`;
  }

  function customersMarkup() {
    const keyword = state.customerSearch.trim().toLowerCase();
    const customers = state.data.customers.filter((item) => !keyword || [item.name, item.phone].some((value) => String(value || "").toLowerCase().includes(keyword)));
    const memberMap = new Map(state.data.members.map((item) => [item.customer_id, item]));
    const walletMap = new Map(state.data.wallets.map((item) => [item.customer_id, item]));
    const selectedWallet = walletMap.get(state.selectedCustomerId);
    const walletDetail = selectedWallet ? `<section class="panel wallet-detail"><div class="panel-header"><h2>${esc(selectedWallet.name)} 的账户流水</h2><span>当前余额 ${money(selectedWallet.balance)}</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>类型</th><th>金额</th><th>余额</th><th>备注</th></tr></thead><tbody>${selectedWallet.transactions.length ? selectedWallet.transactions.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td>${esc(walletTransactionLabel(item))}</td><td class="mono ${item.direction === "debit" ? "amount-debit" : "amount-credit"}">${item.direction === "debit" ? "-" : "+"}${money(Number(item.amount_cents || 0) / 100)}</td><td class="mono">${money(Number(item.balance_after_cents || 0) / 100)}</td><td>${esc(item.note || "-")}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">暂无账户流水。</div></td></tr>`}</tbody></table></div></section>` : "";
    return `<div class="toolbar"><div class="toolbar-left"><input class="search-input" id="customer-search" type="search" value="${esc(state.customerSearch)}" placeholder="搜索姓名或手机号" aria-label="搜索客户" /></div><div class="toolbar-right"><span class="muted">显示 ${customers.length} / ${state.data.customers.length} 位客户</span></div></div><section class="panel"><div class="table-wrap customer-table-wrap"><table><thead><tr><th>客户</th><th>手机号</th><th>会员等级</th><th>积分</th><th>累计消费</th><th>当前余额</th><th>累计充值</th><th>操作</th></tr></thead><tbody>${customers.length ? customers.map((item) => { const member = memberMap.get(item.customer_id); const wallet = walletMap.get(item.customer_id) || {}; return `<tr><td><strong>${esc(item.name)}</strong></td><td class="mono">${esc(item.phone)}</td><td>${member ? `<span class="status confirmed">${esc(member.level)}</span>` : `<span class="muted">非会员</span>`}</td><td class="mono">${member ? member.points : "-"}</td><td class="mono">${money(item.total_spent)}</td><td class="mono"><strong>${money(wallet.balance)}</strong></td><td class="mono">${money(wallet.recharge_total)}</td><td><button class="btn secondary small" type="button" data-customer-wallet="${esc(item.customer_id)}">查看流水</button></td></tr>`; }).join("") : `<tr><td colspan="8"><div class="empty">没有找到匹配客户。</div></td></tr>`}</tbody></table></div></section>${walletDetail}`;
  }

  function staffMarkup() {
    const performances = visibleStaffPerformances(state.data.overview?.performances || []);
    if (!performances.length) return `<section class="panel empty">今日暂无消费记录，暂时没有可展示的员工绩效。</section>`;
    return `<div class="toolbar"><div class="toolbar-left"><span class="muted">按今日已记录的消费统计员工服务业绩</span></div><div class="toolbar-right"><span class="muted">共 ${performances.length} 个服务分组</span></div></div><div class="performance-list">${performances.map((item) => `<section class="panel performance-card"><div class="panel-header"><div><h2>${esc(item.stylist_name)}</h2><span>${item.customer_count} 位客户 · ${item.order_count} 单</span></div><strong class="performance-total">${money(item.amount)}</strong></div><div class="panel-body"><div class="service-chip-list">${item.services.length ? item.services.map((service) => `<span class="service-chip">${esc(service.service)} ${money(service.amount)}</span>`).join("") : `<span class="muted">暂无套餐明细</span>`}</div><div class="table-wrap"><table><thead><tr><th>客户</th><th>套餐</th><th>消费金额</th><th>服务时间</th><th>预约状态</th></tr></thead><tbody>${item.customers.length ? item.customers.map((customer) => `<tr><td><strong>${esc(customer.customer_name)}</strong><br><span class="muted">${esc(customer.customer_phone || "")}</span></td><td>${esc(customer.service)}</td><td class="mono">${money(customer.amount)}</td><td class="mono">${formatDate(customer.created_at)}</td><td>${customer.status === "unlinked" ? `<span class="status pending">未关联预约</span>` : statusTag(customer.status)}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">暂无员工服务记录。</div></td></tr>`}</tbody></table></div></div></section>`).join("")}</div>`;
  }

  function financeMarkup() {
    const refunds = state.data.refunds;
    return `<p class="helper-note">退款申请先进入待审核状态；员工审核后，后端会在同一事务中完成余额、流水、审计和客户通知处理。</p><section class="panel"><div class="panel-header"><h2>退款申请</h2><span>共 ${refunds.length} 条</span></div><div class="table-wrap"><table><thead><tr><th>申请时间</th><th>金额</th><th>原因</th><th>状态</th><th>操作</th></tr></thead><tbody>${refunds.length ? refunds.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td class="mono"><strong>￥${Number(item.amount || 0).toFixed(2)}</strong></td><td>${esc(item.reason || "未填写")}</td><td>${statusTag(item.status)}</td><td>${item.status === "pending" ? `<div class="action-row"><button class="btn small" type="button" data-refund-action="approve" data-refund-id="${esc(item.refund_id)}">通过</button><button class="btn danger small" type="button" data-refund-action="reject" data-refund-id="${esc(item.refund_id)}">拒绝</button></div>` : `<span class="muted">已处理</span>`}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">暂无退款申请。</div></td></tr>`}</tbody></table></div></section>`;
  }

  function reminderList(items) {
    if (!items.length) return `<div class="empty">当前没有待跟进客户。</div>`;
    const label = (type) => ({ churn_risk: "流失风险", birthday: "生日提醒", balance_customer: "余额客户", repurchase: "复购提醒" }[type] || "待跟进");
    return `<div class="reminder-list">${items.map((item) => `<article class="reminder-item ${item.reminder_type === "churn_risk" ? "high" : ""}"><strong>${esc(item.customer_name)} · ${esc(label(item.reminder_type))}</strong><p>${esc(item.reason)}</p>${item.evidence ? `<small class="reminder-evidence">分析依据：${esc(item.evidence)}</small>` : ""}<div class="reminder-meta"><div class="reminder-owner"><span>常用理发师：${esc(item.stylist_name || "暂未指定")}</span><span>${esc(item.customer_phone)}</span></div>${item.reminder_id ? `<div class="action-row"><button class="btn secondary small" type="button" data-reminder-action="contacted" data-reminder-id="${esc(item.reminder_id)}">已联系</button><button class="btn danger small" type="button" data-reminder-action="dismiss" data-reminder-id="${esc(item.reminder_id)}">忽略</button></div>` : ""}</div></article>`).join("")}</div>`;
  }

  function retentionModules(items) {
    return `<div class="retention-modules">${RETENTION_GROUPS.map((group) => {
      const groupItems = items.filter((item) => item.reminder_type === group.key);
      return `<section class="panel retention-module ${group.key}" data-retention-panel="${esc(group.key)}" hidden><div class="retention-module-header"><div><h2>${esc(group.title)}</h2><p>${esc(group.description)}</p></div><strong>${groupItems.length}</strong></div><div class="reminder-scroll" role="region" aria-label="${esc(group.title)}列表">${reminderList(groupItems)}</div></section>`;
    }).join("")}</div>`;
  }

  function mergeRetentionItems(items, analysisItems) {
    const merged = [...items];
    analysisItems.forEach((item) => {
      if (!RETENTION_GROUPS.some((group) => group.key === item.reminder_type)) return;
      const duplicate = merged.some((existing) => existing.customer_id === item.customer_id && existing.reminder_type === item.reminder_type);
      if (!duplicate) merged.push(item);
    });
    return merged;
  }

  function analysisBasisMarkup(analysis, items) {
    const basis = analysis?.analysis_basis || {};
    const sourceRules = Array.isArray(basis.rules) ? basis.rules : [];
    const rules = DEFAULT_RETENTION_RULES.map((defaultRule) => sourceRules.find((rule) => rule.label === defaultRule.label) || defaultRule);
    sourceRules.filter((rule) => !rules.some((item) => item.label === rule.label)).forEach((rule) => rules.push(rule));
    const sources = Array.isArray(basis.data_sources) && basis.data_sources.length ? basis.data_sources : ["历史到店记录", "最近服务项目", "账户余额"];
    const scanned = analysis ? `已扫描 ${basis.scanned_customer_count || 0} 位客户` : "运行分析后显示本次扫描数量";
    const counts = new Map(RETENTION_GROUPS.map((group) => [group.key, items.filter((item) => item.reminder_type === group.key).length]));
    const focusKeys = { "流失风险": "churn_risk", "生日提醒": "birthday", "复购提醒": "repurchase" };
    return `<section class="panel analysis-basis-panel"><div class="panel-header"><div><h2>分析判断条件</h2><span>点击提醒类型，查看对应客户列表</span></div><span>${esc(scanned)}</span></div><div class="analysis-basis-body"><div class="analysis-source"><span>数据来源</span><strong>${esc(sources.join("、"))}</strong></div><div class="analysis-rule-grid">${rules.map((rule) => { const focusKey = focusKeys[rule.label]; return focusKey ? `<button class="analysis-rule clickable" type="button" data-retention-focus="${focusKey}"><strong>${esc(rule.label)}</strong><span>${esc(rule.description)}</span><small>${counts.get(focusKey) || 0} 条待跟进 · 点击查看</small></button>` : `<div class="analysis-rule"><strong>${esc(rule.label)}</strong><span>${esc(rule.description)}</span><small>规则说明</small></div>`; }).join("")}</div></div></section>`;
  }

  function retentionMarkup() {
    const analysis = state.retentionAnalysis;
    const analysisRecommendations = analysis?.recommendations?.map((item) => ({
      ...item,
      reminder_id: "",
      reminder_type: item.segment,
      priority: 0,
      customer_id: item.customer_id,
      customer_name: item.name,
      customer_phone: item.phone,
      reason: item.reason,
      evidence: item.segment === "churn_risk"
        ? `${item.evidence?.cycle_basis || ""}；当前 ${item.evidence?.days_since_last_visit || 0} 天，阈值 ${item.evidence?.threshold_days || 0} 天`
        : item.segment === "birthday"
          ? `生日 ${item.evidence?.birthday || "-"}，还有 ${item.evidence?.days_until_birthday ?? "-"} 天`
          : item.segment === "repurchase"
            ? `${item.evidence?.cycle_basis || ""}；当前 ${item.evidence?.days_since_last_visit || 0} 天，阈值 ${item.evidence?.threshold_days || 0} 天`
            : `账户余额 ￥${Number(item.evidence?.balance || 0).toFixed(2)}`,
    })) || [];
    const displayItems = mergeRetentionItems(state.data.reminders, analysisRecommendations);
    const analysisBlock = analysis ? `<section class="panel analysis-panel"><div class="panel-header"><h2>本次运营分析结果</h2><span>任务 ${esc(analysis.task_id)}</span></div><div class="panel-body"><div class="metric-grid analysis-metric-grid">${metric("流失风险", analysis.summary.churn_risk || 0, "按个人到店节奏判断", "!")}${metric("余额客户", analysis.summary.balance_customer || 0, "账户余额大于 0", "￥")}</div><div class="helper-note">分析建议已合并到上方提醒入口，点击类型卡片即可查看对应客户。</div></div></section>` : "";
    return `<div class="toolbar"><div class="toolbar-left"><span class="muted">待跟进 ${state.data.reminders.length} 条</span></div><div class="toolbar-right"><button class="btn" type="button" data-action="run-retention"><span class="btn-icon" aria-hidden="true">✦</span>运行运营分析</button></div></div>${analysisBasisMarkup(analysis, displayItems)}<section class="retention-overview"><div class="section-heading"><div><p class="eyebrow">FOLLOW-UP QUEUE</p><h2>待跟进客户</h2></div><span>点击上方类型后查看列表</span></div><div class="retention-focus-hint" data-retention-hint>请选择上方的提醒类型，页面会展开对应客户列表。</div>${retentionModules(displayItems)}</section>${analysisBlock}`;
  }

  function auditMarkup() {
    return `<section class="panel"><div class="panel-header"><h2>最近关键操作</h2><span>最多展示 100 条</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>业务对象</th><th>详情</th></tr></thead><tbody>${state.data.audits.length ? state.data.audits.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td>${esc(item.action)}</td><td>${esc(item.entity_type)}<br><span class="muted">${esc(item.entity_id)}</span></td><td>${esc(item.details || "-")}</td></tr>`).join("") : `<tr><td colspan="4"><div class="empty">暂无审计记录。</div></td></tr>`}</tbody></table></div></section>`;
  }

  function assistantMarkup() {
    const messages = state.assistantMessages.length ? state.assistantMessages.map((item) => `<div class="message ${item.role}">${esc(item.content)}</div>`).join("") : `<div class="empty">可以试试：今天有哪些预约？、李雷最近有没有预约？、护理后多久可以洗头？</div>`;
    return `<section class="panel"><div class="panel-header"><h2>员工查询助手</h2><span>只读查询</span></div><div class="message-list" id="assistant-messages">${messages}</div><form class="assistant-form" id="assistant-form"><label class="sr-only" for="assistant-input">输入员工问题</label><input id="assistant-input" name="message" required placeholder="输入你想查询的门店信息" autocomplete="off" /><button class="btn" type="submit">查询</button></form></section>`;
  }

  async function loadData() {
    const [user, schedule, customers, members, refunds, audits, reminders, birthdays, wallets, overview, stylists] = await Promise.all([
      api("/api/auth/me"),
      safeGet(`/api/staff/schedule?date=${encodeURIComponent(state.scheduleDate)}`, []),
      safeGet("/api/customers", []),
      safeGet("/api/members", []),
      safeGet("/api/refunds", []),
      safeGet("/api/audit-logs", []),
      safeGet("/api/retention/reminders?status=pending", []),
      safeGet("/api/marketing/birthdays", []),
      safeGet("/api/staff/customer-wallets", []),
      safeGet("/api/staff/overview", null),
      safeGet("/api/stylists", []),
    ]);
    if (!["stylist", "admin"].includes(user.role)) throw new Error("当前账号不是员工账号");
    const changeSlots = (await Promise.all(stylists
      .filter((stylist) => H5_STYLIST_NAMES.has(stylist.name) && stylist.is_available)
      .map(async (stylist) => (await safeGet(`/api/stylists/${encodeURIComponent(stylist.stylist_id)}/slots?days_ahead=7`, [])).map((slot) => ({ ...slot, stylist_name: stylist.name })))))
      .flat()
      .sort((a, b) => `${a.date} ${a.time}${a.stylist_name}`.localeCompare(`${b.date} ${b.time}${b.stylist_name}`));
    state.user = user;
    state.data = { schedule: visibleStaffSchedule(schedule), customers, members, refunds, audits, reminders, birthdays, wallets, overview, changeSlots };
  }

  async function enterApp() {
    try {
      await loadData();
      renderShell();
    } catch (error) {
      state.token = "";
      localStorage.removeItem(TOKEN_KEY);
      renderLogin(error.message || "无法进入员工工作台");
    }
  }

  async function login(form) {
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    try {
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ phone: form.phone.value.trim(), password: form.password.value }) });
      state.token = result.access_token;
      localStorage.setItem(TOKEN_KEY, state.token);
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
    try { await api(`/api/refunds/${encodeURIComponent(id)}/${action}`, { method: "POST" }); await refresh("finance"); notify(action === "approve" ? "退款已通过" : "退款已拒绝"); } catch (error) { notify(error.message, true); }
  }

  async function askAssistant(form) {
    const input = form.message;
    const message = input.value.trim();
    if (!message) return;
    state.assistantMessages.push({ role: "user", content: message });
    input.value = "";
    renderShell();
    try {
      const result = await api("/api/staff/agent/query", { method: "POST", body: JSON.stringify({ message }) });
      state.assistantMessages.push({ role: "assistant", content: result.reply || "没有得到可展示的回答。" });
    } catch (error) {
      if (error.code === "AUTH_EXPIRED") return;
      state.assistantMessages.push({ role: "assistant", content: `查询失败：${error.message}` });
    }
    renderShell();
    document.querySelector("#assistant-input")?.focus();
  }

  async function runRetentionAnalysis() {
    try {
      state.retentionAnalysis = await api("/api/retention/agent/run", { method: "POST" });
      state.view = "retention";
      renderShell();
      notify("运营分析已完成");
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
    try {
      state.changeTask = await api(`/api/staff/agent/tasks/${encodeURIComponent(taskId)}/confirm`, {
        method: "POST", body: JSON.stringify({ confirmed }),
      });
      renderShell();
      notify(confirmed ? "预约调整已执行" : "已拒绝调整方案");
    } catch (error) { notify(error.message, true); }
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
      state.verification = await api(`/api/staff/appointments/${encodeURIComponent(appointmentId)}/verification`);
      renderShell();
      notify("服务已核验，请在完成后确认扣次");
    } catch (error) { notify(error.message, true); }
  }

  async function completeService(verificationId) {
    try {
      await api(`/api/staff/service-verifications/${encodeURIComponent(verificationId)}/complete`, { method: "POST" });
      state.verification = null;
      await refresh("schedule");
      notify("服务已完成，套餐次数和员工绩效已更新");
    } catch (error) { notify(error.message, true); }
  }

  document.addEventListener("submit", (event) => {
    if (event.target.id === "login-form") { event.preventDefault(); login(event.target); }
    if (event.target.id === "assistant-form") { event.preventDefault(); askAssistant(event.target); }
    if (event.target.id === "change-form") { event.preventDefault(); proposeAppointmentChange(event.target); }
  });

  document.addEventListener("click", (event) => {
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
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) { state.view = viewButton.dataset.view; renderShell(); return; }
    const actionButton = event.target.closest("[data-action]");
    const action = actionButton?.dataset.action;
    if (action === "logout") { state.token = ""; localStorage.removeItem(TOKEN_KEY); state.user = null; renderLogin(); return; }
    if (action === "refresh") { refresh(); return; }
    if (action === "refresh-schedule") { refresh("schedule"); return; }
    if (action === "run-retention") { runRetentionAnalysis(); return; }
    if (action === "close-verification") { state.verification = null; renderShell(); return; }
    if (action === "verify-service") { verifyService(actionButton.dataset.appointmentId); return; }
    if (action === "complete-service") { completeService(actionButton.dataset.verificationId); return; }
    const verifyButton = event.target.closest("[data-verify-appointment]");
    if (verifyButton) { openServiceVerification(verifyButton.dataset.verifyAppointment); return; }
    const walletButton = event.target.closest("[data-customer-wallet]");
    if (walletButton) { state.selectedCustomerId = walletButton.dataset.customerWallet; renderShell(); return; }
    const confirmation = event.target.closest("[data-agent-confirm]");
    if (confirmation) { confirmAppointmentChange(confirmation.dataset.taskId, confirmation.dataset.agentConfirm === "true"); return; }
    const refund = event.target.closest("[data-refund-action]");
    if (refund) { mutateRefund(refund.dataset.refundId, refund.dataset.refundAction); return; }
    const reminder = event.target.closest("[data-reminder-action]");
    if (reminder) { mutateReminder(reminder.dataset.reminderId, reminder.dataset.reminderAction); }
  });

  document.addEventListener("input", (event) => {
    if (event.target.id === "customer-search") { state.customerSearch = event.target.value; const selectionStart = event.target.selectionStart; renderShell(); const next = document.querySelector("#customer-search"); next?.focus(); next?.setSelectionRange(selectionStart, selectionStart); }
  });
  document.addEventListener("change", (event) => { if (event.target.id === "schedule-date") { state.scheduleDate = event.target.value; refresh("schedule"); } });

  renderLogin();
  if (state.token) enterApp();
})();
