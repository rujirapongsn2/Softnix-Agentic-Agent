# Scheduling & Cron Workflow Spec (MVP -> Hardening)

เอกสารนี้กำหนดแนวทางพัฒนา feature ตั้งเวลารันงานล่วงหน้าใน Softnix Agentic Agent
โดยรองรับทั้ง one-time schedule และ recurring schedule แบบ cron-like

## 1) Problem Statement

ผู้ใช้ต้องการสั่งงานลักษณะ:
- `วันนี้ 09:00 ช่วยสรุปข้อมูลจาก www.softnix.ai และข่าวประจำวันที่เกี่ยวกับ AI`

และต้องการให้ระบบ:
- ตั้งเวลารันให้อัตโนมัติ
- ไม่ต้องมานั่ง trigger เองทุกครั้ง
- ติดตามผลย้อนหลังได้
- ส่งผลลัพธ์กลับช่องทางเดิม (Web UI / Telegram)

## 2) Goals

1. รองรับงานครั้งเดียว (one-time)
2. รองรับงานซ้ำ (recurring) แบบ cron expression
3. รองรับ timezone ต่อผู้ใช้ (default: `Asia/Bangkok`)
4. แปลงคำสั่งธรรมชาติเป็น schedule payload ได้
5. บันทึก execution history และรองรับ retry policy

## 3) Out of Scope (MVP)

1. Multi-tenant billing/quota ขั้นสูง
2. Calendar UI เต็มรูปแบบ
3. Workflow branching ซับซ้อน (DAG orchestration)

## 4) User Stories

1. ผู้ใช้ตั้งงานวันนี้ 09:00 ให้สรุปเว็บ + ข่าว AI แล้วรับผลใน Telegram
2. ผู้ใช้ตั้งงานทุกวัน 09:00 แบบ recurring
3. ผู้ใช้ pause/resume/delete schedule ได้
4. ผู้ใช้กด run-now เพื่อลองงานทันทีได้
5. ผู้ใช้ดูประวัติ run ต่อ schedule ได้

## 5) Functional Requirements

1. Schedule Types
- `one_time`: มี `run_at`
- `cron`: มี `cron_expr`

2. Trigger & Dispatch
- scheduler ตรวจงาน due แล้วส่งเข้า run pipeline เดิม (`POST /runs` equivalent internally)
- ผูก `schedule_id` กับ `run_id`

3. Delivery
- รองรับ `web_ui` และ `telegram`
- telegram ส่งข้อความสรุป + artifact links/attachments ตามนโยบายเดิม

4. Safety/Validation
- validate cron expression
- validate timezone
- จำกัดจำนวน active schedules ต่อ user/chat (configurable)

5. Observability
- metrics: scheduled, dispatched, success, failed, lag_seconds
- audit log: create/update/pause/resume/delete/run-now

## 6) Data Model (Proposed)

### `schedules`
- `id` (string)
- `owner_type` (`user|chat|system`)
- `owner_id` (string)
- `task_prompt` (text)
- `schedule_type` (`one_time|cron`)
- `run_at` (datetime nullable)
- `cron_expr` (string nullable)
- `timezone` (string, IANA)
- `enabled` (bool)
- `next_run_at` (datetime nullable)
- `delivery_channel` (`web_ui|telegram`)
- `delivery_target` (string nullable)
- `created_at`, `updated_at`

### `schedule_runs`
- `id` (string)
- `schedule_id` (string)
- `run_id` (string nullable)
- `status` (`queued|running|completed|failed|canceled`)
- `started_at`, `finished_at`
- `error` (text nullable)

## 7) API Contract (Draft)

1. `POST /schedules`
- สร้าง schedule ใหม่

2. `GET /schedules`
- list schedules (filter by owner/status)

3. `GET /schedules/{id}`
- อ่านรายละเอียด schedule

4. `PATCH /schedules/{id}`
- แก้ prompt/timezone/cron หรือ enable/disable

5. `POST /schedules/{id}/run-now`
- trigger manual run ทันที

6. `DELETE /schedules/{id}`
- soft delete หรือ disable ถาวรตาม policy

7. `GET /schedules/{id}/runs`
- อ่าน execution history ของ schedule

## 8) Natural Language Parsing (MVP Rule-based)

รองรับ pattern เริ่มต้น:
1. `วันนี้ HH:MM ...` -> one-time วันนี้ตาม timezone
2. `พรุ่งนี้ HH:MM ...` -> one-time พรุ่งนี้
3. `ทุกวัน HH:MM ...` -> recurring daily cron
4. `ทุกวันจันทร์ HH:MM ...` -> recurring weekly cron

หาก parse ไม่ชัดเจน:
- ตอบกลับขอข้อมูลเพิ่ม (วันที่/เวลา/timezone) แทนการเดาผิด

## 9) Scheduler Execution Model

1. background worker loop ทุก N วินาที (เช่น 15s)
2. query งานที่ `enabled=true` และ `next_run_at <= now`
3. lock งาน (idempotency guard)
4. สร้าง run ใหม่ผ่าน orchestration เดิม
5. update `schedule_runs` และคำนวณ `next_run_at`

## 10) Reliability & Idempotency

1. unique dispatch key ต่อ `(schedule_id, due_slot)`
2. retry dispatch เมื่อ transient error (exponential backoff, max attempts configurable)
3. ถ้า worker restart ต้องไม่ยิงซ้ำงานเดิม

## 11) Security

1. access control: เจ้าของ schedule เท่านั้นที่แก้ไขได้
2. Telegram: bind `allowed_chat_ids` + owner mapping
3. audit ทุก action สำคัญ
4. rate limit ต่อ owner/chat

## 12) Configuration (Proposed Env)

- `SOFTNIX_SCHEDULER_ENABLED=true|false`
- `SOFTNIX_SCHEDULER_POLL_INTERVAL_SEC=15`
- `SOFTNIX_SCHEDULER_MAX_DISPATCH_PER_TICK=20`
- `SOFTNIX_SCHEDULER_DEFAULT_TIMEZONE=Asia/Bangkok`
- `SOFTNIX_SCHEDULER_MAX_ACTIVE_PER_OWNER=20`
- `SOFTNIX_SCHEDULER_RETRY_MAX_ATTEMPTS=3`
- `SOFTNIX_SCHEDULER_RETRY_BACKOFF_SEC=5`

## 13) Rollout Plan

Phase 1 (MVP):
1. one-time + cron API
2. scheduler worker
3. run-now + history
4. Telegram delivery reuse ของ pipeline เดิม

Phase 2 (Hardening):
1. idempotency key + distributed lock
2. parser coverage เพิ่ม
3. metrics + dashboards + alerts
4. anti-abuse/rate limit

Phase 3 (UX):
1. Web UI schedule tab
2. template preset (daily summary, news digest)
3. edit wizard + timezone helper

## 14) Test Plan

1. Unit tests
- cron/time parser
- next_run_at calculator
- idempotent dispatcher

2. Integration tests
- create schedule -> due -> run created -> history updated
- telegram delivery path
- retry after transient error

3. E2E tests
- คำสั่งธรรมชาติ -> schedule created -> รันตามเวลา -> ส่งผลสำเร็จ

## 15) Definition of Done

1. ผู้ใช้สร้าง one-time schedule ได้และรันตรงเวลา
2. ผู้ใช้สร้าง recurring cron schedule ได้
3. มี run history ต่อ schedule
4. มี guardrails ขั้นต่ำ (access control + rate limit + idempotency)
5. เอกสาร README/ROADMAP/API อัปเดตครบ
