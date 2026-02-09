# Softnix Agentic Agent Roadmap

เอกสารนี้สรุปแผนงานถัดไป โดยเรียงตามลำดับความสำคัญ (สูง -> ต่ำ)

## สถานะล่าสุด (อัปเดต 2026-02-08)

### เสร็จแล้ว

1. Core Memory design (Spec + Contracts) - Phase 1/2
- ส่งมอบแล้ว:
  - markdown-first memory (`memory/PROFILE.md`, `memory/SESSION.md`, global `POLICY.md`)
  - precedence + resolve (`Policy > Profile > Session`)
  - explicit memory commands (`จำไว้ว่า...`, tone/style/language, forget)
  - inferred memory แบบ pending + confirm/reject ผ่าน task text
  - confidence gating (`SOFTNIX_MEMORY_INFERRED_MIN_CONFIDENCE`)
  - memory audit log (`.softnix/runs/<run_id>/memory_audit.jsonl`)
  - pending inspection endpoint: `GET /runs/{run_id}/memory/pending`
  - one-click test script: `scripts/test_core_memory_oneclick.sh`
- เอกสารอ้างอิง: `docs/core-memory-spec.md`

2. Core Memory hardening (Phase 3A)
- ส่งมอบแล้ว:
  - policy guard enforcement ตาม `policy.allow.tools` ใน execution loop
  - explicit pending decision API:
    - `POST /runs/{id}/memory/confirm`
    - `POST /runs/{id}/memory/reject`
  - Web UI flow สำหรับ confirm/reject pending memory
  - memory observability endpoint:
    - `GET /runs/{id}/memory/metrics`
  - admin policy reload endpoint:
    - `POST /admin/memory/policy/reload` (admin key)
  - backlog alert และ compact failure audit/event logging

3. Execution reliability + Timeline UX clarity
- ส่งมอบแล้ว:
  - ปรับสถานะ run เมื่อจบด้วย `max_iters` ให้เป็น `failed` (ไม่แสดงเป็น `completed`)
  - เพิ่ม Final Summary Card ใน Web UI เพื่อสรุปผล run แบบอ่านง่าย (`Success/Failed/Canceled`)
  - ปรับข้อความ timeline จาก event ดิบเป็นข้อความเชิงความหมาย (human-readable)
  - รองรับ `python3 -> python` alias ทั้ง executor/loop/planner guardrail
  - ขยาย `run_safe_command` ให้รองรับ structured params:
    - `args`
    - `stdout_path` / `stderr_path`
    - legacy compatibility: `redirect_output` / `output_file`
  - เพิ่ม/ปรับ tests สำหรับ structured command execution และ status semantics
  - เพิ่ม no-progress detector (หยุด run เมื่อวนซ้ำไม่คืบหน้า ด้วย `stop_reason=no_progress`)
  - เพิ่ม no-progress telemetry (`signature` + `actions`) เพื่อช่วย debug สาเหตุลูปซ้ำ
  - ลด artifact noise: ไม่ snapshot ไฟล์จาก `list_dir` output โดยตรง
  - เพิ่ม container pip dependency cache ข้าม run ผ่าน `SOFTNIX_EXEC_CONTAINER_CACHE_DIR`
  - เพิ่ม prebuilt image profile strategy (`auto|base|web|data`) และ mapping image ตาม profile
  - ขยาย image profile catalog (`auto|base|web|data|scraping|ml|qa`)
  - เพิ่ม Run Diagnostics panel ใน Web UI สำหรับ runtime selection + no-progress trace

## P0 (ต้องทำก่อน)

1. Core Memory hardening (Phase 3B)
- เป้าหมาย: ปิดงาน hardening ฝั่ง admin control plane ให้พร้อม production
- งานหลัก:
  - admin policy control plane ที่รองรับ key rotation/secret store integration
  - นโยบายสิทธิ์และ audit สำหรับ admin operations (reload/changes)
- ผลลัพธ์: memory governance พร้อมใช้งาน production โดยมี admin boundary ชัดเจน

2. Autonomous code execution framework (No special-purpose tools)
- เป้าหมาย: ให้ Agent วิเคราะห์ วางแผน เขียนโค้ด และรันโค้ดแบบอิสระเพื่อทำงานจนจบ โดยไม่เพิ่ม tool เฉพาะ domain
- งานหลัก:
  - สร้าง execution runtime/sandbox สำหรับรันโค้ด (resource limits: cpu/memory/timeout/disk)
    - ความคืบหน้า:
      - เพิ่ม runtime abstraction `host|container` และ container sandbox baseline (docker run + cpu/memory/pids/network limits)
      - เพิ่ม container lifecycle `per_run` (run-scoped persistent container + docker exec + shutdown เมื่อ run จบ)
      - เพิ่ม structured command execution (`run_safe_command: command+args+stdout/stderr file`) รองรับงานอัตโนมัติที่ซับซ้อนขึ้น
    - แผนถัดไป:
      - ทำ benchmark เปรียบเทียบ profile/image แต่ละแบบ (duration/success rate/cost)
  - นิยาม action กลางสำหรับวงจร `generate -> run -> validate -> refine`
    - ความคืบหน้า: เพิ่ม objective validation baseline ใน loop (ตรวจเงื่อนไขก่อนยอม `done=true`)
  - เพิ่ม workspace governance (input/working/output zones + artifact snapshot)
    - ความคืบหน้า: มี artifact snapshot baseline แล้ว แต่ยังต้องลด noise (ไม่ snapshot ไฟล์เดิมที่ไม่เกี่ยวกับ task)
  - เพิ่ม safety policy สำหรับคำสั่งอิสระ (allow/deny + approval gate)
  - เพิ่ม structured logs/traces สำหรับแผน โค้ด คำสั่ง และผลลัพธ์ต่อ iteration
  - เพิ่ม objective validation checks และ stop conditions แบบ no-progress detection
    - ความคืบหน้า: มี objective validation baseline แล้ว แต่ยังต้องเพิ่ม no-progress detector เพื่อกันวนรอบจน `max_iters`
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
