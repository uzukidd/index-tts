"""Sequential WebUI batch jobs; deliberately independent of model dependencies."""

import json
import re
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


@dataclass
class BatchUpdate:
    rows: list[list]
    files: list[str]
    archive: str | None
    completed: int
    failed: int
    total: int
    running: bool


def parse_batch_text(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _truncate_utf8(text: str, limit: int = 120) -> str:
    return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def audio_filename(text: str, used: set[str]) -> str:
    """Keep readable Unicode names within Windows and Unix filesystem limits."""
    stem = unicodedata.normalize("NFC", text)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", stem)
    stem = _truncate_utf8(stem).strip(" .") or "audio"
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", stem, re.I):
        stem = "_" + stem
    candidate = stem
    suffix = 2
    while (candidate + ".wav").casefold() in used:
        candidate = f"{stem} ({suffix})"
        suffix += 1
    name = candidate + ".wav"
    used.add(name.casefold())
    return name


def run_batch(
    text: str,
    synthesize: Callable[[str, str], object],
    output_root: str | Path = "outputs/tasks",
) -> Iterator[BatchUpdate]:
    """Yield snapshots before/after each job; archive only successfully written WAVs."""
    texts = parse_batch_text(text)
    if not texts:
        raise ValueError("Enter at least one non-empty task / 请至少输入一条非空文本")
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="batch_", dir=root))
    used: set[str] = set()
    rows = [[i, item, audio_filename(item, used), "queued", ""]
            for i, item in enumerate(texts, 1)]
    files: list[str] = []
    completed = failed = 0

    def snapshot(archive=None, running=True):
        return BatchUpdate([row.copy() for row in rows], files.copy(), archive,
                           completed, failed, len(rows), running)

    yield snapshot()
    for row in rows:
        row[3] = "running"
        yield snapshot()
        path = directory / row[2]
        try:
            synthesize(row[1], str(path))
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError("Model did not write an audio file / 模型未写入音频文件")
        except Exception as exc:
            row[3], row[4] = "failed", str(exc)
            failed += 1
        else:
            row[3] = "completed"
            files.append(str(path))
            completed += 1
        yield snapshot()

    archive = None
    if files:
        archive_path = directory / "audio.zip"
        manifest = [{"index": row[0], "text": row[1], "filename": row[2],
                     "status": row[3], "error": row[4]} for row in rows]
        # Keep an exact text-to-filename mapping, including failed jobs.
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for file in files:
                bundle.write(file, arcname=Path(file).name)
            bundle.writestr("tasks.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive = str(archive_path)
    yield snapshot(archive=archive, running=False)
