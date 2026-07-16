# 员工代客预约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在员工客户页增加代客预约，并让员工日程、客户 H5 和小程序读取同一预约事实。

**Architecture:** 新增员工受保护的预约创建接口，复用现有 AppointmentService 原子占槽逻辑；前端通过现有 stylists/slots API 选择资源，创建成功后刷新共享数据。通知和审计在接口成功后写入。

**Tech Stack:** FastAPI、SQLAlchemy、Pydantic、原生 JavaScript、pytest、Playwright CLI。

## Global Constraints

- 不创建第二套预约表或第二套时间槽占用逻辑。
- 员工只能为已有客户代约。
- 客户 H5 与小程序继续读取 `/api/appointments`。
- 预约成功前不发送成功通知、不写成功审计。

### Task 1: Backend staff booking contract

**Files:**
- Modify: `backend/api/schemas.py`
- Modify: `backend/api/routers.py`
- Test: `tests/test_staff_booking.py`

- [ ] Write a failing full-chain test for staff booking, shared customer visibility, notification, stylist schedule, and slot conflict.
- [ ] Run `python -m pytest tests/test_staff_booking.py -q` and observe failure because the staff endpoint does not exist.
- [ ] Add `StaffAppointmentCreate` and `StaffAppointmentResponse` schemas.
- [ ] Add `POST /api/staff/appointments` with staff authorization, existing-customer lookup, service validation, `AppointmentService.create_appointment`, notification, and audit.
- [ ] Run the focused test and confirm it passes.

### Task 2: Staff customer booking panel

**Files:**
- Modify: `frontend/staff.js`
- Modify: `frontend/staff.css`
- Modify: `frontend/staff.html`

- [ ] Add a booking panel to the customer view with customer, service, stylist, slot, and notes controls.
- [ ] Load slots only after a stylist is selected and clear stale slot choices when the stylist changes.
- [ ] Submit to the staff endpoint, refresh data, and show the new appointment in the staff schedule.
- [ ] Run `node --check frontend/staff.js`.

### Task 3: Cross-client verification

**Files:**
- Modify: `tests/test_staff_booking.py`
- Create: `output/playwright/staff-assisted-booking.png`

- [ ] Verify the customer endpoint returns the staff-created appointment.
- [ ] Verify a customer notification exists for the same appointment.
- [ ] Verify the staff page shows the booking panel and stylist schedule row.
- [ ] Capture a browser screenshot in `output/playwright/`.

### Task 4: Documentation and regression

**Files:**
- Modify: `开发总结.md`

- [ ] Document data flow, shared API reason, failure behavior, tests, and interview explanation.
- [ ] Run `python -m pytest -q`, compile checks, `node --check frontend/staff.js`, and `git diff --check`.
