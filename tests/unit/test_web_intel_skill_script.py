from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_script_module(path: Path):
    spec = importlib.util.spec_from_file_location("web_intel_fetch_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_web_intel_script_sufficient(monkeypatch, tmp_path: Path) -> None:
    script = Path("skillpacks/web-intel/scripts/web_intel_fetch.py").resolve()
    mod = _load_script_module(script)

    html = "<html><body>" + ("Softnix AI " * 400) + "</body></html>"
    monkeypatch.setattr(mod, "_fetch_html", lambda url, timeout_sec: html)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--url",
            "https://example.com",
            "--out-dir",
            str(tmp_path / "web_intel"),
            "--min-chars",
            "100",
        ],
    )
    code = mod.main()
    assert code == 0
    assert (tmp_path / "web_intel" / "raw.html").exists()
    assert (tmp_path / "web_intel" / "extracted.txt").exists()
    assert (tmp_path / "web_intel" / "summary.md").exists()
    assert (tmp_path / "web_intel" / "meta.json").exists()


def test_web_intel_script_fallback_required(monkeypatch, tmp_path: Path) -> None:
    script = Path("skillpacks/web-intel/scripts/web_intel_fetch.py").resolve()
    mod = _load_script_module(script)

    html = "<html><body>tiny</body></html>"
    monkeypatch.setattr(mod, "_fetch_html", lambda url, timeout_sec: html)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--url",
            "https://example.com",
            "--out-dir",
            str(tmp_path / "web_intel"),
            "--min-chars",
            "1000",
        ],
    )
    code = mod.main()
    assert code == 0
    assert (tmp_path / "web_intel" / "meta.json").exists()
    meta_text = (tmp_path / "web_intel" / "meta.json").read_text(encoding="utf-8")
    assert "fallback_required" in meta_text
