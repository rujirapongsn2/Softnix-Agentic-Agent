# Softnix Agentic Agent Roadmap

เอกสารนี้สรุปแผนงานถัดไป โดยเรียงตามลำดับความสำคัญ (สูง -> ต่ำ)

## สถานะล่าสุด (อัปเดต 2026-02-10)

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
  - เพิ่ม objective validation แบบ `python_import` (ตรวจว่าไฟล์ Python import module ที่ task ต้องการจริง)
  - เพิ่ม auto-infer library requirement จาก task (`numpy`/`pandas`/`scipy`) เพื่อกันงาน completed หลอก
  - ปิดช่องโหว่ auto-complete: หากมี action ใด fail ใน iteration ปัจจุบัน จะไม่ auto-complete
  - ปรับ runtime profile auto-selection ให้ `data` มี priority สูงกว่า `web` เมื่อ task ระบุ data libs
  - เพิ่ม prebuilt runtime images สำหรับ `data/ml` และ one-click build script:
    - `deploy/docker/runtime/Dockerfile.data`
    - `deploy/docker/runtime/Dockerfile.ml`
    - `scripts/build_runtime_images.sh`

4. Telegram Gateway MVP (Phase 1 - baseline started)
- ส่งมอบแล้ว:
  - เพิ่ม integration modules:
    - `src/softnix_agentic_agent/integrations/telegram_parser.py`
    - `src/softnix_agentic_agent/integrations/telegram_templates.py`
    - `src/softnix_agentic_agent/integrations/telegram_client.py`
    - `src/softnix_agentic_agent/integrations/telegram_gateway.py`
  - เพิ่ม API endpoints:
    - `POST /telegram/webhook`
    - `POST /telegram/poll`
    - `GET /telegram/metrics`
  - รองรับ command พื้นฐาน:
    - `/run <task>`
    - `/status <run_id>`
    - `/cancel <run_id>`
    - `/resume <run_id>`
    - `/pending <run_id>`
    - `/help`
  - เพิ่ม config/env รองรับ Telegram Gateway และ system config summary
  - เพิ่ม final run notification กลับ Telegram อัตโนมัติเมื่อ run จบ
  - เพิ่ม artifact delivery กลับ Telegram ด้วย `sendDocument` (ล่าสุดสูงสุด 3 ไฟล์)
  - ปรับ Web UI ให้ auto-refresh run list และ auto-follow run ใหม่จาก external trigger (เช่น Telegram) เพื่อให้เห็น Conversation Timeline แบบ near real-time

5. Core Memory hardening (Phase 3B) - started
- ส่งมอบแล้ว:
  - เพิ่ม Memory Admin Control Plane สำหรับจัดการ admin keys แบบหลายแหล่ง:
    - legacy key (`SOFTNIX_MEMORY_ADMIN_KEY`)
    - env key list (`SOFTNIX_MEMORY_ADMIN_KEYS`)
    - local rotated keys (`SOFTNIX_MEMORY_ADMIN_KEYS_PATH`)
  - เพิ่ม admin audit log (`SOFTNIX_MEMORY_ADMIN_AUDIT_PATH`)
  - เพิ่ม admin endpoints:
    - `GET /admin/memory/keys`
    - `POST /admin/memory/keys/rotate`
    - `POST /admin/memory/keys/revoke`
    - `GET /admin/memory/audit`
  - เพิ่ม test coverage สำหรับ rotate/revoke/audit flow

## P0 (ต้องทำก่อน)

1. Core Memory hardening (Phase 3B)
- เป้าหมาย: ปิดงาน hardening ฝั่ง admin control plane ให้พร้อม production
- งานหลัก:
  - [x] admin policy control plane ที่รองรับ key rotation (local keyring + legacy/env keys)
  - [x] audit สำหรับ admin operations (reload/changes/rotate/revoke/read)
  - [ ] secret store integration (เช่น Vault/KMS/Secrets Manager)
  - [ ] role-based authorization (แยกสิทธิ์ read/rotate/revoke/reload)
- ผลลัพธ์: memory governance พร้อมใช้งาน production โดยมี admin boundary ชัดเจน

2. Autonomous code execution framework (No special-purpose tools)
- เป้าหมาย: ให้ Agent วิเคราะห์ วางแผน เขียนโค้ด และรันโค้ดแบบอิสระเพื่อทำงานจนจบ โดยไม่เพิ่ม tool เฉพาะ domain
- งานหลัก:
  - สร้าง execution runtime/sandbox สำหรับรันโค้ด (resource limits: cpu/memory/timeout/disk)
    - ความคืบหน้า:
      - เพิ่ม runtime abstraction `host|container` และ container sandbox baseline (docker run + cpu/memory/pids/network limits)
      - เพิ่ม container lifecycle `per_run` (run-scoped persistent container + docker exec + shutdown เมื่อ run จบ)
      - เพิ่ม structured command execution (`run_safe_command: command+args+stdout/stderr file`) รองรับงานอัตโนมัติที่ซับซ้อนขึ้น
      - เพิ่ม prebuilt image สำหรับ `data/ml` เพื่อให้ dependency สำคัญพร้อมใช้ (เช่น `numpy`)
    - แผนถัดไป:
      - ทำ benchmark เปรียบเทียบ profile/image แต่ละแบบ (duration/success rate/cost)
      - เพิ่ม cold-start/warm-start metrics สำหรับ `per_run` เพื่อตัดสินใจ optimize lifecycle
  - นิยาม action กลางสำหรับวงจร `generate -> run -> validate -> refine`
    - ความคืบหน้า: เพิ่ม objective validation baseline + `python_import` checks + inferred library constraints
  - เพิ่ม workspace governance (input/working/output zones + artifact snapshot)
    - ความคืบหน้า: มี artifact snapshot baseline แล้ว และลด noise จาก `list_dir` output แล้ว
  - เพิ่ม safety policy สำหรับคำสั่งอิสระ (allow/deny + approval gate)
  - เพิ่ม structured logs/traces สำหรับแผน โค้ด คำสั่ง และผลลัพธ์ต่อ iteration
  - เพิ่ม objective validation checks และ stop conditions แบบ no-progress detection
    - ความคืบหน้า: มี objective validation + no-progress detector แล้ว
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
- งานหลัก (Phase 1: MVP):
  - [x] สร้าง module `telegram_gateway` (adapter ระหว่าง Telegram Bot API กับระบบ run)
  - [x] รองรับ command contract พื้นฐาน (`/run`, `/status`, `/cancel`, `/resume`, `/pending`, `/help`)
  - [x] เพิ่ม env config หลัก (`BOT_TOKEN`, `ALLOWED_CHAT_IDS`, `MODE`, `WEBHOOK_SECRET`, limits)
  - [x] เพิ่ม artifact delivery (`sendDocument`) + ข้อความสรุปผลท้าย run
  - [x] เพิ่ม command latency/error metrics สำหรับ Telegram flows (`GET /telegram/metrics`)
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

## ลำดับแนะนำถัดไป (Next 3)

1. Telegram Gateway Phase 2 (Hardening)
- เพิ่ม rate limit / cooldown ต่อ chat เพื่อกัน abuse
- เพิ่ม idempotency + dedup กัน Telegram update ซ้ำ
- เพิ่ม audit mapping `telegram_chat_id <-> run_id` พร้อม query/debug endpoint

2. Execution benchmark + observability hardening
- วัดผล `per_action` vs `per_run` และ image profiles (`base/web/data/ml`) ด้วย task ชุดมาตรฐาน
- เก็บ metrics: success rate, median duration, iteration count, dependency install time

3. Objective contract generator
- แปลง task เป็น validation contract อัตโนมัติให้เข้มขึ้น (ไฟล์, เนื้อหา, import/module, freshness)
- ลดเคส completed หลอกในงานเขียน/รันโค้ดหลายขั้นตอน

## Definition of Done (ทุกหัวข้อ)

- มี test coverage ที่เกี่ยวข้อง
- อัปเดต README/เอกสาร deploy
- ผ่าน backend + frontend build/test
- มี rollback plan หรือ mitigation สำหรับการ deploy
