(function () {
  "use strict";

  const API_BASE = "";
  const TOKEN_KEY = "hengyi_staff_access_token";
  const app = document.querySelector("#app");
  const toast = document.querySelector("#toast");
  const state = {
    token: localStorage.getItem(TOKEN_KEY) || "",
    user: null,
    view: "dashboard",
    data: { schedule: [], customers: [], members: [], refunds: [], audits: [], reminders: [], birthdays: [] },
    scheduleDate: new Date().toISOString().slice(0, 10),
    customerSearch: "",
    assistantMessages: [],
    retentionAnalysis: null,
    changeTask: null,
  };

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

  function viewTitle(view) { return ({ dashboard: "工作概览", schedule: "今日预约", customers: "客户与会员", finance: "退款处理", retention: "留存提醒", audit: "操作审计", assistant: "员工助手" })[view] || "工作概览"; }
  function viewDescription(view) { return ({ dashboard: "快速掌握今天的门店运营状态。", schedule: "按发型师查看当天预约和客户需求。", customers: "查找客户基础资料、会员等级和积分。", finance: "处理客户退款申请，所有决定都会留下记录。", retention: "按优先级跟进需要再次触达的客户。", audit: "查看关键业务动作的操作者和时间。", assistant: "用自然语言查询真实业务数据和门店知识。" })[view] || ""; }

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
    return `<section class="view active" data-view-panel="${view}">${({ dashboard: dashboardMarkup, schedule: scheduleMarkup, customers: customersMarkup, finance: financeMarkup, retention: retentionMarkup, audit: auditMarkup, assistant: assistantMarkup })[view]()}</section>`;
  }

  function dashboardMarkup() {
    const appointments = flattenSchedule();
    const pendingRefunds = state.data.refunds.filter((item) => item.status === "pending").length;
    return `<div class="metric-grid">${metric("今日预约", appointments.length, "全店发型师合计", "◷", "schedule")}${metric("会员客户", state.data.members.length, "已建立会员资料", "◎", "customers")}${metric("待处理退款", pendingRefunds, pendingRefunds ? "需要员工审核" : "当前没有待审核申请", "￥", "finance")}${metric("待跟进客户", state.data.reminders.length, "留存规则生成的待办", "!", "retention")}</div>
      <div class="dashboard-grid"><section class="panel"><div class="panel-header"><h2>今日预约</h2><span>${appointments.length ? `共 ${appointments.length} 条` : "暂无预约"}</span></div>${scheduleTable(appointments.slice(0, 8))}<div class="panel-body"><button class="btn secondary small" type="button" data-view="schedule">查看全部预约</button></div></section><section class="panel"><div class="panel-header"><h2>优先跟进</h2><span>按风险排序</span></div><div class="panel-body">${reminderList(state.data.reminders.slice(0, 4))}<div style="margin-top:12px"><button class="btn secondary small" type="button" data-view="retention">打开留存提醒</button></div></div></section></div>`;
  }

  function scheduleTable(items) {
    if (!items.length) return `<div class="empty">今天还没有预约记录。</div>`;
    return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>客户</th><th>项目</th><th>发型师</th><th>状态</th></tr></thead><tbody>${items.map((item) => `<tr><td class="mono">${formatDate(item.appointment_datetime)}</td><td><strong>${esc(item.customer_name)}</strong><br><span class="muted">${esc(item.customer_phone)}</span></td><td>${esc(item.service)}</td><td>${esc(item.stylist_name)}</td><td>${statusTag(item.status)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function scheduleMarkup() {
    return `<div class="toolbar"><div class="toolbar-left"><label class="muted" for="schedule-date">日期</label><input class="date-input" id="schedule-date" type="date" value="${esc(state.scheduleDate)}" /></div><div class="toolbar-right"><button class="btn secondary small" type="button" data-action="refresh-schedule">重新查询</button></div></div><div class="schedule-list">${state.data.schedule.length ? state.data.schedule.map((group) => `<section class="panel schedule-group"><div class="schedule-group-title"><span>${esc(group.stylist_name)}</span><span>${(group.appointments || []).length} 条预约</span></div>${scheduleTable((group.appointments || []).map((item) => ({ ...item, stylist_name: group.stylist_name })))}</section>`).join("") : `<div class="panel empty">${esc(state.scheduleDate)} 没有预约记录。</div>`}</div>${appointmentChangeMarkup()}`;
  }

  function appointmentChangeMarkup() {
    const proposal = state.changeTask?.result_payload;
    const result = proposal ? `<div class="helper-note" style="margin-top:14px"><strong>调整方案</strong><br>${esc(proposal.customer_name || "客户")}：${esc(proposal.old_datetime || "")} -> ${esc(proposal.new_datetime || "")}，发型师：${esc(proposal.old_stylist_name || "")} -> ${esc(proposal.new_stylist_name || "")}${state.changeTask.awaiting_confirmation ? `<div class="action-row" style="margin-top:12px"><button class="btn small" type="button" data-agent-confirm="true" data-task-id="${esc(state.changeTask.task_id)}">确认执行</button><button class="btn danger small" type="button" data-agent-confirm="false" data-task-id="${esc(state.changeTask.task_id)}">拒绝方案</button></div>` : `<br><span class="muted">${esc(state.changeTask.status)}</span>`}</div>` : "";
    return `<section class="panel" style="margin-top:16px"><div class="panel-header"><h2>预约调整</h2><span>人工确认后才写入</span></div><div class="panel-body"><form id="change-form" class="form-grid"><div class="toolbar-left"><div class="field"><label for="change-appointment-id">预约 ID</label><input id="change-appointment-id" name="appointment_id" required placeholder="粘贴预约编号" /></div><div class="field"><label for="change-slot-id">新时间槽 ID</label><input id="change-slot-id" name="new_slot_id" required placeholder="粘贴可用时间槽编号" /></div><div class="field"><label for="change-stylist-id">新发型师 ID（可选）</label><input id="change-stylist-id" name="new_stylist_id" placeholder="不填则按时间槽归属" /></div><button class="btn" type="submit">生成调整方案</button></div></form>${result}</div></section>`;
  }

  function customersMarkup() {
    const keyword = state.customerSearch.trim().toLowerCase();
    const customers = state.data.customers.filter((item) => !keyword || [item.name, item.phone].some((value) => String(value || "").toLowerCase().includes(keyword)));
    const memberMap = new Map(state.data.members.map((item) => [item.customer_id, item]));
    return `<div class="toolbar"><div class="toolbar-left"><input class="search-input" id="customer-search" type="search" value="${esc(state.customerSearch)}" placeholder="搜索姓名或手机号" aria-label="搜索客户" /></div><div class="toolbar-right"><span class="muted">显示 ${customers.length} / ${state.data.customers.length} 位客户</span></div></div><section class="panel"><div class="table-wrap"><table><thead><tr><th>客户</th><th>手机号</th><th>会员等级</th><th>积分</th><th>累计消费</th><th>最近到店</th></tr></thead><tbody>${customers.length ? customers.map((item) => { const member = memberMap.get(item.customer_id); return `<tr><td><strong>${esc(item.name)}</strong></td><td class="mono">${esc(item.phone)}</td><td>${member ? `<span class="status confirmed">${esc(member.level)}</span>` : `<span class="muted">非会员</span>`}</td><td class="mono">${member ? member.points : "-"}</td><td class="mono">￥${Number(item.total_spent || 0).toFixed(2)}</td><td>${formatDate(item.last_visit, false)}</td></tr>`; }).join("") : `<tr><td colspan="6"><div class="empty">没有找到匹配客户。</div></td></tr>`}</tbody></table></div></section>`;
  }

  function financeMarkup() {
    const refunds = state.data.refunds;
    return `<p class="helper-note">退款申请先进入待审核状态；员工审核后，后端会在同一事务中完成余额、流水、审计和客户通知处理。</p><section class="panel"><div class="panel-header"><h2>退款申请</h2><span>共 ${refunds.length} 条</span></div><div class="table-wrap"><table><thead><tr><th>申请时间</th><th>金额</th><th>原因</th><th>状态</th><th>操作</th></tr></thead><tbody>${refunds.length ? refunds.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td class="mono"><strong>￥${Number(item.amount || 0).toFixed(2)}</strong></td><td>${esc(item.reason || "未填写")}</td><td>${statusTag(item.status)}</td><td>${item.status === "pending" ? `<div class="action-row"><button class="btn small" type="button" data-refund-action="approve" data-refund-id="${esc(item.refund_id)}">通过</button><button class="btn danger small" type="button" data-refund-action="reject" data-refund-id="${esc(item.refund_id)}">拒绝</button></div>` : `<span class="muted">已处理</span>`}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">暂无退款申请。</div></td></tr>`}</tbody></table></div></section>`;
  }

  function reminderList(items) {
    if (!items.length) return `<div class="empty">当前没有待跟进客户。</div>`;
    return `<div class="reminder-list">${items.map((item) => `<article class="reminder-item ${item.reminder_type === "churn_risk" ? "high" : ""}"><strong>${esc(item.customer_name)} · ${esc(item.reminder_type === "churn_risk" ? "流失风险" : item.reminder_type === "birthday" ? "生日提醒" : item.reminder_type === "membership_expiring" ? "会员到期" : item.reminder_type === "balance_customer" ? "余额客户" : "复购提醒")}</strong><p>${esc(item.reason)}</p><div class="reminder-meta"><div class="reminder-owner"><span>常用理发师：${esc(item.stylist_name || "暂未指定")}</span><span>${esc(item.customer_phone)}</span></div>${item.reminder_id ? `<div class="action-row"><button class="btn secondary small" type="button" data-reminder-action="contacted" data-reminder-id="${esc(item.reminder_id)}">已联系</button><button class="btn danger small" type="button" data-reminder-action="dismiss" data-reminder-id="${esc(item.reminder_id)}">忽略</button></div>` : ""}</div></article>`).join("")}</div>`;
  }

  function retentionMarkup() {
    const analysis = state.retentionAnalysis;
    const analysisBlock = analysis ? `<section class="panel" style="margin-top:16px"><div class="panel-header"><h2>运营分析结果</h2><span>任务 ${esc(analysis.task_id)}</span></div><div class="panel-body"><div class="metric-grid">${metric("流失风险", analysis.summary.churn_risk || 0, "距上次到店较久", "!")}${metric("余额客户", analysis.summary.balance_customer || 0, "账户仍有余额", "￥")}${metric("会员到期", analysis.summary.membership_expiring || 0, "30 天内到期", "◎")}</div>${analysis.recommendations?.length ? reminderList(analysis.recommendations.map((item) => ({ ...item, reminder_id: "", reminder_type: item.segment === "churn_risk" ? "churn_risk" : item.segment, priority: 0, customer_name: item.name, customer_phone: item.phone, reason: item.reason }))) : `<div class="empty">暂无运营建议。</div>`}</div></section>` : "";
    return `<div class="toolbar"><div class="toolbar-left"><span class="muted">待跟进 ${state.data.reminders.length} 条</span></div><div class="toolbar-right"><button class="btn" type="button" data-action="run-retention"><span class="btn-icon" aria-hidden="true">✦</span>运行运营分析</button></div></div><section class="panel"><div class="panel-header"><h2>待跟进客户</h2><span>按优先级排序</span></div><div class="panel-body">${reminderList(state.data.reminders)}</div></section>${analysisBlock}`;
  }

  function auditMarkup() {
    return `<section class="panel"><div class="panel-header"><h2>最近关键操作</h2><span>最多展示 100 条</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>业务对象</th><th>详情</th></tr></thead><tbody>${state.data.audits.length ? state.data.audits.map((item) => `<tr><td class="mono">${formatDate(item.created_at)}</td><td>${esc(item.action)}</td><td>${esc(item.entity_type)}<br><span class="muted">${esc(item.entity_id)}</span></td><td>${esc(item.details || "-")}</td></tr>`).join("") : `<tr><td colspan="4"><div class="empty">暂无审计记录。</div></td></tr>`}</tbody></table></div></section>`;
  }

  function assistantMarkup() {
    const messages = state.assistantMessages.length ? state.assistantMessages.map((item) => `<div class="message ${item.role}">${esc(item.content)}</div>`).join("") : `<div class="empty">可以试试：今天有哪些预约？、李雷最近有没有预约？、护理后多久可以洗头？</div>`;
    return `<section class="panel"><div class="panel-header"><h2>员工查询助手</h2><span>只读查询</span></div><div class="message-list" id="assistant-messages">${messages}</div><form class="assistant-form" id="assistant-form"><label class="sr-only" for="assistant-input">输入员工问题</label><input id="assistant-input" name="message" required placeholder="输入你想查询的门店信息" autocomplete="off" /><button class="btn" type="submit">查询</button></form></section>`;
  }

  async function loadData() {
    const [user, schedule, customers, members, refunds, audits, reminders, birthdays] = await Promise.all([
      api("/api/auth/me"),
      safeGet(`/api/staff/schedule?date=${encodeURIComponent(state.scheduleDate)}`, []),
      safeGet("/api/customers", []),
      safeGet("/api/members", []),
      safeGet("/api/refunds", []),
      safeGet("/api/audit-logs", []),
      safeGet("/api/retention/reminders?status=pending", []),
      safeGet("/api/marketing/birthdays", []),
    ]);
    if (!["stylist", "admin"].includes(user.role)) throw new Error("当前账号不是员工账号");
    state.user = user;
    state.data = { schedule, customers, members, refunds, audits, reminders, birthdays };
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

  document.addEventListener("submit", (event) => {
    if (event.target.id === "login-form") { event.preventDefault(); login(event.target); }
    if (event.target.id === "assistant-form") { event.preventDefault(); askAssistant(event.target); }
    if (event.target.id === "change-form") { event.preventDefault(); proposeAppointmentChange(event.target); }
  });

  document.addEventListener("click", (event) => {
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) { state.view = viewButton.dataset.view; renderShell(); return; }
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "logout") { state.token = ""; localStorage.removeItem(TOKEN_KEY); state.user = null; renderLogin(); return; }
    if (action === "refresh") { refresh(); return; }
    if (action === "refresh-schedule") { refresh("schedule"); return; }
    if (action === "run-retention") { runRetentionAnalysis(); return; }
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
