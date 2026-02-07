# Softnix Agentic Agent Roadmap

เอกสารนี้สรุปแผนงานถัดไป โดยเรียงตามลำดับความสำคัญ (สูง -> ต่ำ)

## สถานะล่าสุด (อัปเดต 2026-02-07)

### เสร็จแล้ว

1. Core Memory design (Spec + Contracts) - Phase 1/2
- ส่งมอบแล้ว:
  - markdown-first memory (`PROFILE.md`, `SESSION.md`, global `POLICY.md`)
  - precedence + resolve (`Policy > Profile > Session`)
  - explicit memory commands (`จำไว้ว่า...`, tone/style/language, forget)
  - inferred memory แบบ pending + confirm/reject ผ่าน task text
  - confidence gating (`SOFTNIX_MEMORY_INFERRED_MIN_CONFIDENCE`)
  - memory audit log (`.softnix/runs/<run_id>/memory_audit.jsonl`)
  - pending inspection endpoint: `GET /runs/{run_id}/memory/pending`
  - one-click test script: `scripts/test_core_memory_oneclick.sh`
- เอกสารอ้างอิง: `docs/core-memory-spec.md`

## P0 (ต้องทำก่อน)

1. Core Memory hardening (Phase 3)
- เป้าหมาย: ปิดช่องว่าง production-grade ของ memory governance และ UX
- งานหลัก:
  - admin policy loader/hot reload ที่แยกสิทธิ์ชัดเจน
  - guard enforcement ครบทุก execution path
  - API/UX สำหรับ confirm/reject pending memory แบบ explicit (ไม่ต้องพึ่ง task text)
  - memory observability เพิ่มเติม (metrics/alerts สำหรับ pending backlog และ compact failures)
- ผลลัพธ์: memory subsystem พร้อมใช้งานจริงใน production และดูแลได้ง่าย

2. Autonomous code execution framework (No special-purpose tools)
- เป้าหมาย: ให้ Agent วิเคราะห์ วางแผน เขียนโค้ด และรันโค้ดแบบอิสระเพื่อทำงานจนจบ โดยไม่เพิ่ม tool เฉพาะ domain
- งานหลัก:
  - สร้าง execution runtime/sandbox สำหรับรันโค้ด (resource limits: cpu/memory/timeout/disk)
  - นิยาม action กลางสำหรับวงจร `generate -> run -> validate -> refine`
  - เพิ่ม workspace governance (input/working/output zones + artifact snapshot)
  - เพิ่ม safety policy สำหรับคำสั่งอิสระ (allow/deny + approval gate)
  - เพิ่ม structured logs/traces สำหรับแผน โค้ด คำสั่ง และผลลัพธ์ต่อ iteration
  - เพิ่ม objective validation checks และ stop conditions แบบ no-progress detection
- ผลลัพธ์: Agent ทำงาน data/code transformation แบบ end-to-end ได้ด้วยโค้ดที่สร้างเองอย่างปลอดภัยและตรวจสอบย้อนหลังได้

## P1 (ทำต่อหลัง P0)

3. External Channel Integration: Telegram Command Gateway
- เป้าหมาย: ให้ผู้ใช้สั่งงาน agent และรับผลลัพธ์ผ่าน Telegram ได้ โดยไม่ต้องเข้า Web UI
- ขอบเขต:
  - รับคำสั่งจาก Telegram chat แล้ว trigger run ผ่าน Agent Core/API
  - ส่งความคืบหน้าและผลลัพธ์กลับไปที่ chat เดิม
  - รองรับการควบคุม run ขั้นพื้นฐาน (`start/status/cancel/resume`)
- งานหลัก (Phase 1: MVP):
  - สร้าง module `telegram_gateway` (adapter ระหว่าง Telegram Bot API กับระบบ run)
  - ออกแบบ command contract เช่น:
    - `/run <task>`
    - `/status <run_id>`
    - `/cancel <run_id>`
    - `/resume <run_id>`
    - `/pending <run_id>` (memory pending)
  - เชื่อมกับ API ภายในที่มีอยู่ (`/runs`, `/runs/{id}`, `/runs/{id}/events`, `/runs/{id}/memory/pending`)
  - ส่งผลลัพธ์กลับ Telegram เป็นข้อความสรุป + ลิงก์/ไฟล์ artifact ที่สำคัญ
  - เพิ่ม env config:
    - `SOFTNIX_TELEGRAM_BOT_TOKEN`
    - `SOFTNIX_TELEGRAM_ALLOWED_CHAT_IDS`
    - `SOFTNIX_TELEGRAM_MODE` (`webhook|polling`)
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

4. CI/CD pipeline
- เป้าหมาย: คุมคุณภาพอัตโนมัติทุก PR/Push
- งานหลัก:
  - backend: `pytest`
  - frontend: `npm run build`
  - deployment: `docker compose config`
- ผลลัพธ์: ลด regression ก่อน merge

5. Monitoring/alerts for long-running runs
- เป้าหมาย: มองเห็นปัญหา run ค้าง/timeout/provider error ได้เร็ว
- งานหลัก:
  - timeout threshold
  - stuck-run detection
  - provider error counter
  - alert output (เริ่มจาก log/webhook)
- ผลลัพธ์: ดูแลระบบง่ายขึ้นและลดเวลาตรวจ incident

6. Authentication model for production
- เป้าหมาย: ยกระดับจาก static API key ไป session/token
- งานหลัก:
  - token/session lifecycle
  - secure storage strategy
  - rotate/revoke flow
- ผลลัพธ์: พร้อมใช้งาน production มากขึ้น

## P2 (เสริมความแข็งแรง)

7. Security hardening phase 2
- เป้าหมาย: เพิ่ม defense-in-depth
- งานหลัก:
  - rate limiting
  - audit log
  - request id tracing
- ผลลัพธ์: สืบสวนปัญหาและป้องกัน abuse ได้ดีขึ้น

8. Release package and runbook
- เป้าหมาย: ทำให้ทีม deploy/operate ได้มาตรฐาน
- งานหลัก:
  - versioning + changelog
  - smoke tests (dev/staging/prod)
  - operational runbook
- ผลลัพธ์: release ซ้ำได้และลด human error

## Definition of Done (ทุกหัวข้อ)

- มี test coverage ที่เกี่ยวข้อง
- อัปเดต README/เอกสาร deploy
- ผ่าน backend + frontend build/test
- มี rollback plan หรือ mitigation สำหรับการ deploy
