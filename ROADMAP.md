# Softnix Agentic Agent Roadmap

เอกสารนี้สรุปแผนงานที่ยังต้องทำ โดยเรียงตามลำดับความสำคัญ (สูง -> ต่ำ)

## P0 (ต้องทำก่อน)

1. Core Memory hardening (Phase 3B)
- เป้าหมาย: ปิดงาน hardening ฝั่ง admin control plane ให้พร้อม production
- งานหลัก:
  - [ ] secret store integration (เช่น Vault/KMS/Secrets Manager)
  - [ ] role-based authorization (แยกสิทธิ์ read/rotate/revoke/reload)
- ผลลัพธ์: memory governance พร้อมใช้งาน production โดยมี admin boundary ชัดเจน

2. Autonomous code execution framework (No special-purpose tools)
- เป้าหมาย: ให้ Agent วิเคราะห์ วางแผน เขียนโค้ด และรันโค้ดแบบอิสระเพื่อทำงานจนจบ โดยไม่เพิ่ม tool เฉพาะ domain
- งานหลัก:
  - สร้าง execution runtime/sandbox สำหรับรันโค้ด (resource limits: cpu/memory/timeout/disk)
    - แผนถัดไป:
      - ทำ benchmark เปรียบเทียบ profile/image แต่ละแบบ (duration/success rate/cost)
      - เพิ่ม cold-start/warm-start metrics สำหรับ `per_run` เพื่อตัดสินใจ optimize lifecycle
  - นิยาม action กลางสำหรับวงจร `generate -> run -> validate -> refine`
  - เพิ่ม workspace governance (input/working/output zones + artifact snapshot)
  - เพิ่ม safety policy สำหรับคำสั่งอิสระ (allow/deny + approval gate)
  - เพิ่ม structured logs/traces สำหรับแผน โค้ด คำสั่ง และผลลัพธ์ต่อ iteration
  - เพิ่ม objective validation checks และ stop conditions แบบ no-progress detection
    - แผนถัดไป:
      - เพิ่ม semantic success criteria (เช่น command exit expectations, artifact freshness per iteration)
      - เพิ่ม objective contract จาก task parser ให้เข้มขึ้นสำหรับ task เชิงโปรแกรม
- ผลลัพธ์: Agent ทำงาน data/code transformation แบบ end-to-end ได้ด้วยโค้ดที่สร้างเองอย่างปลอดภัยและตรวจสอบย้อนหลังได้

## P1 (ทำต่อหลัง P0)

3. External Channel Integration: Telegram Command Gateway
- เป้าหมาย: ให้ผู้ใช้สั่งงาน agent และรับผลลัพธ์ผ่าน Telegram ได้ โดยไม่ต้องเข้า Web UI
- ขอบเขต:
  - รับคำสั่งจาก Telegram chat แล้ว trigger run ผ่าน Agent Core/API
  - ส่งความคืบหน้าและผลลัพธ์กลับไปที่ chat เดิม
  - รองรับการควบคุม run ขั้นพื้นฐาน (`start/status/cancel/resume`)
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

5. CI/CD pipeline
- เป้าหมาย: คุมคุณภาพอัตโนมัติทุก PR/Push
- งานหลัก:
  - backend: `pytest`
  - frontend: `npm run build`
  - deployment: `docker compose config`
- ผลลัพธ์: ลด regression ก่อน merge

6. Monitoring/alerts for long-running runs
- เป้าหมาย: มองเห็นปัญหา run ค้าง/timeout/provider error ได้เร็ว
- งานหลัก:
  - timeout threshold
  - stuck-run detection
  - provider error counter
  - alert output (เริ่มจาก log/webhook)
- ผลลัพธ์: ดูแลระบบง่ายขึ้นและลดเวลาตรวจ incident

7. Authentication model for production
- เป้าหมาย: ยกระดับจาก static API key ไป session/token
- งานหลัก:
  - token/session lifecycle
  - secure storage strategy
  - rotate/revoke flow
- ผลลัพธ์: พร้อมใช้งาน production มากขึ้น

## P2 (เสริมความแข็งแรง)

8. Security hardening phase 2
- เป้าหมาย: เพิ่ม defense-in-depth
- งานหลัก:
  - rate limiting
  - audit log
  - request id tracing
- ผลลัพธ์: สืบสวนปัญหาและป้องกัน abuse ได้ดีขึ้น

9. Release package and runbook
- เป้าหมาย: ทำให้ทีม deploy/operate ได้มาตรฐาน
- งานหลัก:
  - versioning + changelog
  - smoke tests (dev/staging/prod)
  - operational runbook
- ผลลัพธ์: release ซ้ำได้และลด human error

## ลำดับแนะนำถัดไป (Next 3)

1. Scheduled Runs / Cron Workflow (Phase 2: Hardening)
- เพิ่ม idempotency guard กัน dispatch ซ้ำใน due slot เดียวกัน
- เพิ่ม retry/backoff พร้อม error classification
- เพิ่ม scheduling metrics + audit events

2. Telegram Gateway Phase 2 (Hardening)
- เพิ่ม rate limit / cooldown ต่อ chat เพื่อกัน abuse
- เพิ่ม idempotency + dedup กัน Telegram update ซ้ำ
- เพิ่ม audit mapping `telegram_chat_id <-> run_id` พร้อม query/debug endpoint

3. Execution benchmark + observability hardening
- วัดผล `per_action` vs `per_run` และ image profiles (`base/web/data/ml`) ด้วย task ชุดมาตรฐาน
- เก็บ metrics: success rate, median duration, iteration count, dependency install time

## Definition of Done (ทุกหัวข้อ)

- มี test coverage ที่เกี่ยวข้อง
- อัปเดต README/เอกสาร deploy
- ผ่าน backend + frontend build/test
- มี rollback plan หรือ mitigation สำหรับการ deploy
