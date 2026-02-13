from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_OUTPUT_INTENT_KEYWORDS = (
    "write",
    "create",
    "generate",
    "save",
    "บันทึก",
    "สร้าง",
    "เขียน",
    "เขียนผลลัพธ์",
    "เขียนผลลง",
    "เขียนลง",
    "ลงไฟล์",
)

_COMMON_OUTPUT_EXTENSIONS = {
    "txt",
    "md",
    "json",
    "csv",
    "html",
    "htm",
    "xml",
    "yaml",
    "yml",
    "log",
    "py",
    "js",
    "ts",
    "jsx",
    "tsx",
    "css",
    "scss",
    "sql",
    "sh",
    "bash",
    "zsh",
    "bat",
    "ps1",
    "ini",
    "cfg",
    "conf",
    "toml",
    "lock",
    "env",
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "bmp",
    "webp",
    "tif",
    "tiff",
    "zip",
    "gz",
    "tar",
    "parquet",
    "pkl",
    "pickle",
}


@dataclass
class TaskContract:
    required_outputs: list[str]
    source_inputs: list[str]
    hinted_directories: list[str]
    required_absent: list[str]
    required_python_modules: list[str]
    expected_text_markers: list[str]


class TaskContractParser:
    def parse(self, task: str, enforce_web_intel_contract: bool = False) -> TaskContract:
        text = (task or "").strip()
        if not text:
            return TaskContract(
                required_outputs=[],
                source_inputs=[],
                hinted_directories=[],
                required_absent=[],
                required_python_modules=[],
                expected_text_markers=[],
            )

        candidates = re.findall(r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)", text)
        source_refs = self._infer_input_file_refs_from_task(text=text, candidates=candidates)

        outputs: list[str] = []
        has_output_intent = any(k in text.lower() for k in _OUTPUT_INTENT_KEYWORDS)
        for token in candidates:
            normalized = self._normalize_file_token(token)
            if not normalized:
                continue
            if self._looks_like_code_member_call(text=text, token=normalized):
                continue
            if normalized in source_refs:
                continue
            if normalized.endswith(".py") and self._looks_like_skill_script_input_ref(text, normalized):
                continue
            if not self._looks_like_workspace_output_candidate(normalized):
                continue
            if has_output_intent or enforce_web_intel_contract:
                outputs.append(normalized)

        if enforce_web_intel_contract:
            outputs.extend(["web_intel/summary.md", "web_intel/meta.json"])

        sources = [self._normalize_file_token(x) for x in sorted(source_refs)]
        source_inputs = [x for x in sources if x]
        hinted_dirs = self._infer_hinted_directories(text=text, source_inputs=source_inputs, outputs=outputs)
        required_absent = self._infer_required_absent_files(
            text=text,
            source_inputs=source_inputs,
            candidates=candidates,
        )
        required_python_modules = self._infer_required_python_modules(text)
        expected_text_markers = self._infer_expected_text_markers(text)
        return TaskContract(
            required_outputs=self._dedup(outputs),
            source_inputs=self._dedup(source_inputs),
            hinted_directories=self._dedup(hinted_dirs),
            required_absent=self._dedup(required_absent),
            required_python_modules=self._dedup(required_python_modules),
            expected_text_markers=self._dedup(expected_text_markers),
        )

    def _normalize_file_token(self, token: str) -> str:
        value = (token or "").strip().replace("\\", "/")
        if not value:
            return ""
        if value.startswith("./"):
            value = value[2:]
        if value.startswith("/"):
            return ""
        if "://" in value or value.startswith("www."):
            return ""
        if value.count(".") > 1 and "/" not in value:
            return ""
        return value

    def _infer_input_file_refs_from_task(self, text: str, candidates: list[str]) -> set[str]:
        lowered = (text or "").lower()
        has_output_intent = any(k in lowered for k in _OUTPUT_INTENT_KEYWORDS)
        source_exts = {
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
            ".gif",
            ".bmp",
        }

        source_refs: set[str] = set()
        for token in candidates:
            normalized = self._normalize_file_token(token)
            if not normalized:
                continue
            escaped = re.escape(token)
            quoted = rf"[\"'“”‘’]?\s*{escaped}\s*[\"'“”‘’]?"
            input_patterns = (
                rf"(?:from|read|use|using|input|source|extract(?:ed)?\s+from)\s+{quoted}",
                rf"(?:จาก|อ่าน|ใช้|อินพุต|ไฟล์ต้นฉบับ|จากไฟล์)\s*{quoted}",
            )
            if any(re.search(p, text, flags=re.IGNORECASE) for p in input_patterns):
                source_refs.add(normalized)
                continue

            if has_output_intent and Path(normalized).suffix.lower() in source_exts:
                source_refs.add(normalized)
        return source_refs

    def _looks_like_workspace_output_candidate(self, token: str) -> bool:
        value = (token or "").strip().lower()
        if not value:
            return False
        ext = Path(value).suffix.lower().lstrip(".")
        if not ext:
            return False
        if "/" not in value:
            return ext in _COMMON_OUTPUT_EXTENSIONS
        return True

    def _looks_like_skill_script_input_ref(self, task: str, token: str) -> bool:
        lowered_token = (token or "").strip().lower().replace("\\", "/")
        if not lowered_token:
            return False
        if lowered_token.startswith(("skillpacks/", "examples/skills/", ".softnix_skill_exec/")):
            return True
        escaped = re.escape(token)
        if re.search(rf"(?:^|\s)python(?:3)?\s+{escaped}(?:\s|$)", task, flags=re.IGNORECASE):
            return True
        return False

    def _infer_hinted_directories(self, text: str, source_inputs: list[str], outputs: list[str]) -> list[str]:
        rows: list[str] = []
        for value in source_inputs + outputs:
            parent = str(Path(value).parent).replace("\\", "/")
            if parent and parent != ".":
                rows.append(parent)

        for match in re.finditer(r"\b(?:in|from|under|inside)\s+([A-Za-z0-9_/-]{2,})", text, flags=re.IGNORECASE):
            candidate = str(match.group(1) or "").strip().strip("/").replace("\\", "/")
            if "/" in candidate or candidate.endswith(("input", "inputs", "output", "outputs", "tmp", "data")):
                rows.append(candidate)

        for match in re.finditer(r"(?:โฟลเดอร์|ในโฟลเดอร์)\s*([A-Za-z0-9_/-]{2,})", text, flags=re.IGNORECASE):
            candidate = str(match.group(1) or "").strip().strip("/").replace("\\", "/")
            if candidate:
                rows.append(candidate)
        return rows

    def _dedup(self, rows: list[str]) -> list[str]:
        seen: set[str] = set()
        uniq: list[str] = []
        for item in rows:
            value = str(item or "").strip().replace("\\", "/")
            if not value or value in seen:
                continue
            seen.add(value)
            uniq.append(value)
        return uniq

    def _infer_required_absent_files(self, text: str, source_inputs: list[str], candidates: list[str]) -> list[str]:
        lowered = (text or "").lower()
        delete_markers = ("delete", "remove", "rm ", "ลบ", "ลบทิ้ง")
        if not any(marker in lowered for marker in delete_markers):
            return []
        rows: list[str] = []
        for token in source_inputs:
            if token:
                rows.append(token)
        for token in candidates:
            normalized = self._normalize_file_token(token)
            if not normalized:
                continue
            if self._looks_like_code_member_call(text=text, token=normalized):
                continue
            if normalized.endswith(".py") and self._looks_like_skill_script_input_ref(text, normalized):
                continue
            if not self._looks_like_workspace_output_candidate(normalized):
                continue
            rows.append(normalized)
        return rows

    def _looks_like_code_member_call(self, text: str, token: str) -> bool:
        candidate = (token or "").strip()
        if not candidate or "/" in candidate:
            return False
        escaped = re.escape(candidate)
        return bool(re.search(rf"(?<![A-Za-z0-9_]){escaped}\s*\(", text))

    def _infer_required_python_modules(self, text: str) -> list[str]:
        rows: list[str] = []
        for m in re.finditer(r"\bpip(?:3)?\s+install\s+([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE):
            rows.append(str(m.group(1) or "").strip().lower())
        for m in re.finditer(r"(?:ติดตั้ง\s+package|ติดตั้งแพ็กเกจ)\s+([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE):
            rows.append(str(m.group(1) or "").strip().lower())
        for m in re.finditer(r"\bimport\s+([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE):
            rows.append(str(m.group(1) or "").strip().lower())
        for m in re.finditer(
            r"(?:print|พิมพ์).{0,30}(?:version|เวอร์ชัน)\s+([A-Za-z0-9_.-]+)",
            text,
            flags=re.IGNORECASE,
        ):
            rows.append(str(m.group(1) or "").strip().lower())
        for m in re.finditer(r"(?:ใช้|use)\s+([A-Za-z][A-Za-z0-9_.-]{1,40})", text, flags=re.IGNORECASE):
            rows.append(str(m.group(1) or "").strip().lower())

        stopwords = {"python", "pip", "script", "ไฟล์", "file", "version", "เวอร์ชัน"}
        return [x for x in rows if x and x not in stopwords]

    def _infer_expected_text_markers(self, text: str) -> list[str]:
        rows: list[str] = []
        for m in re.finditer(
            r"(?:ข้อความ|มีข้อความ|contains?|must contain|มีคำว่า)\s*[\"'“”‘’]([^\"'“”‘’]{1,120})[\"'“”‘’]",
            text,
            flags=re.IGNORECASE,
        ):
            rows.append(str(m.group(1) or "").strip())
        for m in re.finditer(
            r"(?:print|พิมพ์).{0,30}(?:version|เวอร์ชัน)\s+([A-Za-z0-9_.-]+)",
            text,
            flags=re.IGNORECASE,
        ):
            rows.append(str(m.group(1) or "").strip())
        return [x for x in rows if x]


class PathDiscoveryPolicy:
    def find_candidates(
        self,
        workspace: Path,
        missing_path: str,
        hinted_directories: list[str] | None = None,
        limit: int = 3,
    ) -> list[str]:
        root = workspace.resolve()
        text = (missing_path or "").strip().replace("\\", "/")
        if not text:
            return []
        src = Path(text)
        basename = src.name.lower()
        if not basename:
            return []
        hinted = [str(x).strip().replace("\\", "/").strip("/") for x in (hinted_directories or []) if str(x).strip()]
        parent_parts = [p.lower() for p in src.parent.parts if p and p != "."]
        missing_ext = src.suffix.lower()

        scored: list[tuple[int, str]] = []
        try:
            for child in root.rglob("*"):
                if not child.is_file():
                    continue
                rel = str(child.relative_to(root)).replace("\\", "/")
                if rel.startswith(".softnix/"):
                    continue
                if child.name.lower() != basename:
                    continue
                score = 100
                rel_lower = rel.lower()
                if missing_ext and child.suffix.lower() == missing_ext:
                    score += 20
                if parent_parts and all(part in rel_lower for part in parent_parts):
                    score += 30
                if any(rel_lower.startswith(f"{hint.lower()}/") or rel_lower == hint.lower() for hint in hinted):
                    score += 60
                depth = len(Path(rel).parts)
                score += max(0, 10 - depth)
                scored.append((score, rel))
        except Exception:
            return []

        scored.sort(key=lambda x: (-x[0], x[1]))
        return [rel for _, rel in scored[: max(1, int(limit))]]
