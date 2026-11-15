"""Opt-in real browser checks: INDEXTTS_UI_TESTS=1, no PyTorch required."""

import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
import wave
import zipfile

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INDEXTTS_UI_TESTS") != "1",
    reason="Set INDEXTTS_UI_TESTS=1 to run browser checks with the UI-only backend",
)
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("version", ["2", "2.5"])
def test_batch_upload_generate_download_in_browser(version, tmp_path):
    httpx = pytest.importorskip("httpx")
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    log_path = tmp_path / "server.log"
    env = {**os.environ, "GRADIO_ANALYTICS_ENABLED": "False", "PYTHONUTF8": "1",
           "NO_PROXY": "localhost,127.0.0.1", "no_proxy": "localhost,127.0.0.1"}
    prompt = tmp_path / "prompt.wav"
    with wave.open(str(prompt), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(b"\x00\x00" * 22050)

    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "webui.py", "--ui-only", "--version", version,
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(trust_env=False) as client:
                deadline = time.monotonic() + 50
                while True:
                    if process.poll() is not None:
                        pytest.fail(log_path.read_text(encoding="utf-8"))
                    try:
                        if client.get(url + "/config", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        pytest.fail("WebUI startup timeout: " + log_path.read_text(encoding="utf-8"))
                    time.sleep(0.2)

            with playwright.sync_playwright() as pw:
                channel = os.environ.get("INDEXTTS_BROWSER_CHANNEL", "msedge" if sys.platform == "win32" else "chromium")
                browser = pw.chromium.launch(headless=True, channel=channel)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url, wait_until="domcontentloaded")
                    playwright.expect(page.get_by_text("UI TEST MODE", exact=False)).to_be_visible()
                    page.locator("#batch_texts textarea").fill("你好\n\n你好\nA/B:测试?")
                    page.locator("#batch_generate").click()
                    playwright.expect(page.get_by_text("Upload a voice reference first", exact=False)).to_be_visible(timeout=15000)
                    page.locator("#prompt_audio_compact input[type=file]").set_input_files(prompt)
                    # Wait for Gradio to finish uploading and expose a playable reference.
                    playwright.expect(page.locator("#prompt_audio_compact audio[src]").first).to_have_attribute("src", re.compile(r".+"), timeout=15000)
                    page.locator("#batch_generate").click()
                    status = page.get_by_label("Progress / 进度", exact=True)
                    playwright.expect(status).to_have_value("Finished / 已结束: 3/3; success / 成功 3, failed / 失败 0", timeout=30000)
                    results = page.locator("#batch_results")
                    playwright.expect(results).to_contain_text("你好.wav")
                    playwright.expect(results).to_contain_text("你好 (2).wav")
                    playwright.expect(results).to_contain_text("A_B_测试_.wav")
                    download_link = page.locator("#batch_archive a[download]")
                    with page.expect_download() as download_info:
                        download_link.click()
                    archive = tmp_path / "download.zip"
                    download_info.value.save_as(archive)
                    with zipfile.ZipFile(archive) as bundle:
                        assert set(bundle.namelist()) == {"你好.wav", "你好 (2).wav", "A_B_测试_.wav", "tasks.json"}
                        manifest = json.loads(bundle.read("tasks.json"))
                        assert [row["text"] for row in manifest] == ["你好", "你好", "A/B:测试?"]
                        assert all(row["status"] == "completed" for row in manifest)
                        for name in bundle.namelist():
                            if name.endswith(".wav"):
                                assert bundle.read(name).startswith(b"RIFF")
                    # Exercise a second submission, proving results are reset per batch.
                    page.locator("#batch_texts textarea").fill("第二批")
                    page.locator("#batch_generate").click()
                    playwright.expect(status).to_have_value("Finished / 已结束: 1/1; success / 成功 1, failed / 失败 0", timeout=30000)
                    playwright.expect(results).to_contain_text("第二批.wav")
                    playwright.expect(results).not_to_contain_text("你好.wav")
                    (ROOT / "outputs").mkdir(exist_ok=True)
                    page.screenshot(path=str(ROOT / "outputs" / f"webui-batch-v{version}.png"), full_page=True)
                    assert errors == []
                except Exception:
                    page.screenshot(path=str(tmp_path / "failure.png"), full_page=True)
                    raise
                finally:
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
