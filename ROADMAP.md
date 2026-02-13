# Softnix Agentic Agent Roadmap

เอกสารนี้สรุปแผนงานที่ยังต้องทำ โดยเรียงตามลำดับความสำคัญ (สูง -> ต่ำ)

## P0 (ต้องทำก่อน)

0. Run history retention governance (Phase 1)
- เป้าหมาย: คุมขนาดข้อมูลใน `.softnix/runs` ไม่ให้โตเกินจำเป็น
- สถานะปัจจุบัน (เสร็จแล้ว):
  - เพิ่ม retention policy จาก env (`keep_finished_days`, `max_runs`, `max_bytes`, `interval_sec`)
  - เพิ่ม background retention worker (ลบเฉพาะ run ที่จบแล้ว)
  - เพิ่ม admin APIs สำหรับ report/run cleanup แบบ dry-run และ apply จริง
- สถานะอัปเดต (Phase 2 เสร็จแล้ว):
  - เพิ่ม retention policy สำหรับ `.softnix/experience` และ `.softnix/skill-builds`
  - worker เดียวกัน cleanup แบบอัตโนมัติครอบคลุมทั้ง 3 ส่วน (`runs`, `skill-builds`, `experience`)
- งานถัดไป (Phase 3):
  - เพิ่ม metrics/alert เมื่อ cleanup error หรือใกล้ชนเพดานบ่อย

1. Core Memory hardening (Phase 3B)
- เป้าหมาย: ปิดงาน hardening ฝั่ง admin control plane ให้พร้อม production
- งานหลัก:
  - [ ] secret store integration (เช่น Vault/KMS/Secrets Manager)
  - [ ] role-based authorization (แยกสิทธิ์ read/rotate/revoke/reload)
- ผลลัพธ์: memory governance พร้อมใช้งาน production โดยมี admin boundary ชัดเจน

2. Autonomous code execution framework (No special-purpose tools)
- เป้าหมาย: ให้ Agent วิเคราะห์ วางแผน เขียนโค้ด และรันโค้ดแบบอิสระเพื่อทำงานจนจบ โดยไม่เพิ่ม tool เฉพาะ domain
- สถานะปัจจุบัน (เสร็จแล้ว):
  - execution runtime/sandbox พร้อมใช้ทั้ง `host` และ `container` (`per_action`/`per_run`)
  - action กลางสำหรับวงจร `generate -> run -> validate -> refine`
  - workspace governance + artifact snapshot ใน run storage
  - safety policy พื้นฐานสำหรับ command/action allowlist
  - objective validation + no-progress detection + guard เพิ่มเติม (`planner_parse_error streak`, capability failure streak, wall-time limit)
  - skill selector คัดเฉพาะ skill ที่เกี่ยวข้องกับ task (ลด context noise / ลดการเรียก skill ที่ไม่จำเป็น)
  - execution gate สำหรับงานเชิงปฏิบัติการ (กันลูป preparatory-only เช่น read/calc วนโดยไม่ execute จริง)
  - skill contract ระบุ `success_artifacts` และใช้เป็น objective requirement อัตโนมัติใน loop
- งานคงเหลือ (ต้องทำต่อ):
  - benchmark เปรียบเทียบ profile/image แต่ละแบบ (duration/success rate/cost) โดยใช้ harness ที่มีแล้ว (`scripts/benchmark_success_rate.sh`)
  - เพิ่ม cold-start/warm-start metrics สำหรับ `per_run` เพื่อตัดสินใจ optimize lifecycle
  - เพิ่ม fallback planner/degraded planning path ให้ robust มากขึ้นสำหรับงานยาวและบริบทใหญ่ (เริ่มต้นแล้ว: retry-on-parse-error)
- ผลลัพธ์: Agent ทำงาน data/code transformation แบบ end-to-end ได้ด้วยโค้ดที่สร้างเองอย่างปลอดภัยและตรวจสอบย้อนหลังได้

### สถานะล่าสุด: Success-rate improvement (หยุดไว้ก่อนชั่วคราว)

- ทำเสร็จแล้วในรอบนี้:
  - objective contract parser + path discovery policy
  - semantic success criteria (`file_absent`, import/text marker checks, freshness/stale guards)
  - failure strategy memory + repeated-failed-sequence penalty gate
  - repair-loop gate + confidence gate + auto-escalation สำหรับ auth/network/policy
  - benchmark harness (`scripts/benchmark_success_rate.sh`, `scripts/benchmark_tasks.txt`)
- สถานะ: **หยุดพัฒนาต่อไว้ก่อนตามคำขอผู้ใช้**

## P1 (ทำต่อหลัง P0)

3. External Channel Integration: Telegram Command Gateway
- เป้าหมาย: ให้ผู้ใช้สั่งงาน agent และรับผลลัพธ์ผ่าน Telegram ได้ โดยไม่ต้องเข้า Web UI
- ขอบเขต:
  - รับคำสั่งจาก Telegram chat แล้ว trigger run ผ่าน Agent Core/API
  - ส่งความคืบหน้าและผลลัพธ์กลับไปที่ chat เดิม
  - รองรับการควบคุม run ขั้นพื้นฐาน (`start/status/cancel/resume`)
- สถานะปัจจุบัน (MVP เสร็จแล้ว):
  - รองรับ natural mode (ไม่ต้องพิมพ์ `/run` ทุกครั้ง)
  - รองรับงานตั้งเวลา (`/schedule`, `/schedules`, `/schedule_runs`, `/schedule_disable`, `/schedule_delete`)
  - รองรับ skill build jobs (`/skill_build`, `/skill_status`, `/skill_builds`) และส่งผลจบงานอัตโนมัติ
- งานหลัก (Phase 2: Hardening):
  - access control ต่อ chat/user + anti-abuse (rate limit, cooldown, retry)
  - idempotency และ dedup สำหรับ message update ซ้ำ
  - secure webhook verification และ secret rotation
  - audit mapping ระหว่าง `telegram_chat_id <-> run_id`
- งานหลัก (Phase 3: UX/Scale):
  - ส่ง streaming progress แบบ throttled (ลด spam ใน chat)
  - รองรับ artifact delivery แบบ `sendDocument` และ chunk ข้อความยาวอัตโนมัติ
  - template ข้อความผลลัพธ์ที่อ่านง่ายบนมือถือ
- ผลลัพธ์: ผู้ใช้สั่งงานและติดตาม run ผ่าน Telegram ได้ end-to-end อย่างปลอดภัย
- เอกสารอ้างอิงสเปก: `docs/telegram-gateway-spec.md`

4. Scheduled Runs / Cron Workflow
- เป้าหมาย: ให้ผู้ใช้ตั้งเวลารัน task ล่วงหน้าได้ (one-time และ recurring) โดยไม่ต้อง trigger เอง
- ขอบเขต:
  - สร้าง schedule แบบกำหนดเวลา (`วันนี้ 09:00`) และแบบ cron
  - dispatch เข้า run pipeline เดิม และ track ความสัมพันธ์ `schedule_id <-> run_id`
  - รองรับการส่งผลลัพธ์กลับ Web UI / Telegram
- งานหลัก (Phase 2: Hardening):
  - idempotency guard ต่อ due slot
  - retry policy + backoff สำหรับ dispatch fail
  - access control/rate limit ต่อ owner/chat
  - metrics + audit log สำหรับ scheduling
- งานหลัก (Phase 3: UX):
  - Web UI schedule management
  - schedule templates (daily summary/news digest)
- ผลลัพธ์: ระบบรองรับงานอัตโนมัติแบบ cron-like ได้ครบวงจร
- เอกสารอ้างอิงสเปก: `docs/scheduling-spec.md`

5. Web Intelligence Fallback (web_fetch -> browser automation)
- เป้าหมาย: ลดเคสสรุปข้อมูลไม่ครบจากเว็บ dynamic โดยเริ่มจาก `web_fetch` ก่อนเสมอ และ fallback ไป browser automation เมื่อข้อมูลไม่พอ
- ลำดับการ implement:
  - ขั้นที่ 1: Skill adapter + วิธีเดิม (`run_safe_command`/`run_python_code`) เพื่อส่งมอบเร็ว (เสร็จแล้ว)
  - ขั้นที่ 2: ค่อยย้ายไป container runtime profile สำหรับ browser tasks ในเฟส hardening
- หลักการ:
  - fetch-first: พยายาม `web_fetch` ก่อนเพื่อความเร็ว/ต้นทุนต่ำ
  - quality gate: หากคุณภาพข้อมูลต่ำกว่าเกณฑ์ (content too short/missing selectors/validation fail) ให้ยกระดับเป็น browser mode
  - deterministic output: สรุปผลและ evidence กลับมาเป็นไฟล์มาตรฐานใน artifacts
- งานหลัก (Phase 2: Decision Engine):
  - เพิ่มเกณฑ์ตัดสินใจ fallback จากผล `web_fetch` (heuristics + objective validation)
  - เพิ่ม trace/log ว่า fallback เพราะเหตุผลใด เพื่อ debug ได้
  - เพิ่ม per-domain policy (บังคับ browser สำหรับเว็บที่รู้ว่า dynamic)
- งานหลัก (Phase 3: Runtime/Hardening):
  - แยก runtime profile สำหรับ browser tasks (image/deps/cache) และย้ายงาน browser จาก skill-only mode ไป profile นี้
  - เพิ่ม timeout/retry/circuit-breaker สำหรับ browser flow
  - เพิ่ม benchmark เทียบ `web_fetch` vs browser fallback (success rate/latency/cost)
- ผลลัพธ์: ได้ระบบค้นหา/รวบรวมข้อมูลเว็บที่ยืดหยุ่นและแม่นยำขึ้น โดยยังคุมต้นทุนและความปลอดภัย

6. CI/CD pipeline
- เป้าหมาย: คุมคุณภาพอัตโนมัติทุก PR/Push
- งานหลัก:
  - backend: `pytest`
  - frontend: `npm run build`
  - deployment: `docker compose config`
- ผลลัพธ์: ลด regression ก่อน merge

7. Monitoring/alerts for long-running runs
- เป้าหมาย: มองเห็นปัญหา run ค้าง/timeout/provider error ได้เร็ว
- งานหลัก:
  - timeout threshold
  - stuck-run detection
  - provider error counter
  - alert output (เริ่มจาก log/webhook)
- ผลลัพธ์: ดูแลระบบง่ายขึ้นและลดเวลาตรวจ incident

8. Authentication model for production
- เป้าหมาย: ยกระดับจาก static API key ไป session/token
- งานหลัก:
  - token/session lifecycle
  - secure storage strategy
  - rotate/revoke flow
- ผลลัพธ์: พร้อมใช้งาน production มากขึ้น

## P2 (เสริมความแข็งแรง)

9. Security hardening phase 2
- เป้าหมาย: เพิ่ม defense-in-depth
- งานหลัก:
  - rate limiting
  - audit log
  - request id tracing
- ผลลัพธ์: สืบสวนปัญหาและป้องกัน abuse ได้ดีขึ้น

10. Release package and runbook
- เป้าหมาย: ทำให้ทีม deploy/operate ได้มาตรฐาน
- งานหลัก:
  - versioning + changelog
  - smoke tests (dev/staging/prod)
  - operational runbook
- ผลลัพธ์: release ซ้ำได้และลด human error

## ลำดับแนะนำถัดไป (Next 3)

1. Autonomous framework hardening (ต่อจาก P0-2)
- เพิ่ม benchmark + metrics ของ runtime profile/image และ lifecycle `per_run` (ใช้ harness ที่มี)
- ลด planner parse error โดยเพิ่ม retry/degraded planning path ใน loop

2. Scheduled Runs / Cron Workflow (Phase 2: Hardening)
- เพิ่ม idempotency guard กัน dispatch ซ้ำใน due slot เดียวกัน
- เพิ่ม retry/backoff พร้อม error classification
- เพิ่ม scheduling metrics + audit events

3. Telegram Gateway Phase 2 (Hardening)
- เพิ่ม rate limit / cooldown ต่อ chat เพื่อกัน abuse
- เพิ่ม idempotency + dedup กัน Telegram update ซ้ำ
- เพิ่ม audit mapping `telegram_chat_id <-> run_id` พร้อม query/debug endpoint

## Definition of Done (ทุกหัวข้อ)

- มี test coverage ที่เกี่ยวข้อง
- อัปเดต README/เอกสาร deploy
- ผ่าน backend + frontend build/test
- มี rollback plan หรือ mitigation สำหรับการ deploy
