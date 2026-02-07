# Core Memory Spec (Markdown-first)

สถานะ: Draft v1
ขอบเขต: Agent Core memory behavior + file contract + security boundary

## 1. Objectives

- ผู้ใช้สั่งแบบธรรมชาติได้ เช่น "จำไว้ว่า..." แล้วระบบบันทึกให้อัตโนมัติ
- รองรับ preference ระยะยาว (tone/style/language) และบริบทเฉพาะงาน
- แยก policy ระดับระบบออกจาก user memory อย่างชัดเจน
- มี precedence, conflict resolution, ttl และ audit trail ที่ตรวจสอบได้

## 2. Memory Model

1. `Profile Memory`
- วัตถุประสงค์: ความชอบถาวรของผู้ใช้
- ตัวอย่าง: tone, style, ภาษา, รูปแบบ output
- ที่เก็บ: `<workspace>/PROFILE.md`

2. `Session Memory`
- วัตถุประสงค์: บริบทชั่วคราวของงาน/บทสนทนาปัจจุบัน
- ตัวอย่าง: เป้าหมายรอบนี้, ข้อจำกัดชั่วคราว, ข้อมูลที่ใช้เฉพาะ run
- ที่เก็บ: `<workspace>/SESSION.md`

3. `Policy Memory`
- วัตถุประสงค์: กติการะดับระบบ
- ที่เก็บ: `<global_config>/POLICY.md` (admin-managed only)
- สิทธิ์: user และ planner/action ปกติห้ามอ่าน/เขียน

## 3. Precedence / Merge Rule

ลำดับความสำคัญ: `Policy > Profile > Session`

การตัดสินเมื่อ key ซ้ำ:
1. ใช้ scope precedence ก่อน
2. ถ้า scope เท่ากัน ใช้ `priority` สูงกว่า
3. ถ้า `priority` เท่ากัน ใช้ `updated_at` ล่าสุด
4. ถ้ายังเท่ากัน ใช้ last-write-wins และบันทึกเหตุผลใน audit

## 4. Logical Schema (สำหรับ parser/validator)

แม้ source of truth เป็น markdown แต่ทุก entry ต้อง map ได้เป็นโครงสร้างนี้:

- `scope`: `policy|profile|session`
- `kind`: `preference|constraint|fact|instruction`
- `key`: string (canonical key)
- `value`: string
- `priority`: integer (default 50)
- `ttl`: `none|<duration>|<absolute-iso-time>`
- `updated_at`: ISO-8601
- `source`: `user_explicit|user_inferred|system|admin`

## 5. Markdown File Contract

## 5.1 PROFILE.md

ไฟล์ผู้ใช้มองเห็นและแก้ได้

```md
# PROFILE

## Preferences
- key:response.tone | value:professional-friendly | priority:70 | ttl:none | source:user_explicit | updated_at:2026-02-07T11:00:00Z
- key:response.language | value:th | priority:80 | ttl:none | source:user_explicit | updated_at:2026-02-07T11:00:00Z
- key:response.format.default | value:bullet-summary | priority:60 | ttl:none | source:user_inferred | updated_at:2026-02-07T11:05:00Z
```

## 5.2 SESSION.md

ไฟล์ผู้ใช้มองเห็นและแก้ได้ (ผูกกับ session/run ปัจจุบัน)

```md
# SESSION

## Context
- key:task.current_goal | value:ออกแบบ Core Memory Spec ให้ใช้งานได้จริง | priority:80 | ttl:session_end | source:system | updated_at:2026-02-07T11:10:00Z
- key:response.verbosity | value:concise | priority:75 | ttl:8h | source:user_explicit | updated_at:2026-02-07T11:10:00Z
```

## 5.3 POLICY.md

ไฟล์ global/admin-only ไม่ expose ใน user workspace/API ปกติ

```md
# POLICY

## Guardrails
- key:policy.prohibit.secrets_exfiltration | value:true | priority:100 | ttl:none | source:admin | updated_at:2026-02-01T00:00:00Z
- key:policy.allow.tools | value:list_dir,read_file,write_workspace_file,run_safe_command,run_python_code,web_fetch | priority:100 | ttl:none | source:admin | updated_at:2026-02-01T00:00:00Z
```

## 6. Natural-language Memory UX Contract

Trigger สำหรับ create/update memory:
- "จำไว้ว่า..."
- "ตั้งโทนการตอบเป็น..."
- "ต่อไปให้ตอบแบบ..."
- "ลืมสิ่งนี้..."
- "แก้ preference ว่า..."

กติกา:
1. คำสั่ง explicit จากผู้ใช้ต้องเขียน memory ทันที
2. memory ที่ inferred ต้องเขียนเฉพาะเมื่อ confidence สูงพอ (เช่น >= 0.8) หรือมีการยืนยันจากผู้ใช้
3. เมื่อเขียนเสร็จ ต้องส่ง acknowledgement สั้นและสอดคล้องกับ verbosity ที่ตั้งไว้
4. inferred memory ต้องถูก stage เป็น pending ก่อน และ promote เข้า profile เมื่อผู้ใช้ยืนยันเท่านั้น

## 7. Operations (Internal)

คำสั่งเชิงระบบ (ไม่จำเป็นต้อง expose เป็น public tool ช่วงแรก):
- `memory_upsert(scope, kind, key, value, priority?, ttl?, source)`
- `memory_delete(scope, key)`
- `memory_resolve(keys[]) -> effective values + provenance`
- `memory_compact(scope)` (cleanup expired/duplicate entries)

## 8. Security Boundary

- ห้าม planner/action เขียน `POLICY.md` โดยตรง
- API ปกติห้าม route สำหรับอ่าน policy raw
- policy reload ได้ผ่าน admin channel เท่านั้น
- ทุก memory mutation ต้อง append audit entry

## 9. Audit Trail

เก็บใน `.softnix/runs/<run_id>/memory_audit.jsonl`

record example:

```json
{"ts":"2026-02-07T11:12:00Z","op":"upsert","scope":"profile","key":"response.tone","old":"formal","new":"professional-friendly","actor":"user_explicit","reason":"user said: ตั้งโทนการตอบ..."}
```

## 10. Integration Flow (Planner/Executor/Loop)

1. ก่อนวางแผนแต่ละ iteration ให้ load effective memory (Policy+Profile+Session)
2. inject memory summary เข้า planner prompt
3. planner เสนอ actions ตาม memory
4. ถ้าพบคำสั่ง memory จากผู้ใช้ ให้ commit memory ก่อน execute งานหลัก
5. หลังจบ iteration ให้ persist memory changes + audit

## 11. Stop/Validation Rules

- ถ้า task ระบุให้จำสิ่งใด ต้องมีหลักฐานว่า entry ถูกเขียนจริงก่อน `done=true`
- ถ้าผู้ใช้สั่ง "ลืม" ต้อง verify ว่า key ถูกลบ/mark-expired ก่อน `done=true`
- หาก memory write ล้มเหลวซ้ำเกิน threshold ให้ fail-safe: แจ้งผู้ใช้ + หยุด done

## 12. Rollout Plan

Phase 1 (MVP)
- parser/serializer สำหรับ `PROFILE.md` และ `SESSION.md`
- upsert/delete/resolve + precedence
- memory audit log

Phase 2
- natural-language trigger classifier + confidence gating
- inferred memory write with user confirmation flow
 - pending inspection endpoint: `GET /runs/{run_id}/memory/pending`

Phase 3
- admin policy loader + hot reload
- guard enforcement ครบทุก execution path

## 13. Open Decisions

- format ttl มาตรฐานเดียว (`8h` vs ISO absolute) จะเลือกแบบใดเป็น default
- session lifecycle: นิยามจบ session ด้วย run status หรือ inactivity timeout
- threshold สำหรับ inferred memory และ strategy การขอ confirm
