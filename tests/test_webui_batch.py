"""Model-free behavior and real-signature contracts for WebUI batch synthesis."""

import ast
import copy
import importlib.util
import json
import os
import re
import sys
import threading
import types
import uuid
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADVANCED = {
    "do_sample": True, "top_p": 0.73, "top_k": 17, "temperature": 0.91,
    "length_penalty": 1.2, "num_beams": 3, "repetition_penalty": 2.7,
    "max_mel_tokens": 321,
}
ADVANCED_INPUT = [True, "0.73", "17", "0.91", "1.2", 3, "2.7", "321"]


@pytest.fixture(scope="module")
def batch():
    name = "_webui_batch_under_test"
    spec = importlib.util.spec_from_file_location(name, ROOT / "indextts/utils/webui_batch.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("text, expected", [
    (None, []), ("", []), (" \t\r\n \n", []),
    ("  first  \r\n\n\t第二条\t\n \nlast\n", ["first", "第二条", "last"]),
    ("same\nsame", ["same", "same"]),
])
def test_parse_filters_blank_lines_without_reordering(batch, text, expected):
    assert batch.parse_batch_text(text) == expected


@pytest.mark.parametrize("text", [None, "", " \t\n\r\n"])
def test_empty_batch_has_no_side_effects(batch, tmp_path, text):
    root = tmp_path / "not-created"
    calls = []
    with pytest.raises(ValueError, match="non-empty|非空"):
        list(batch.run_batch(text, lambda *args: calls.append(args), root))
    assert calls == []
    assert not root.exists()


def test_sync_order_and_detached_snapshots(batch, tmp_path):
    calls = []

    def synthesize(text, path):
        calls.append((text, path))
        Path(path).write_bytes(b"RIFF" + text.encode())

    stream = batch.run_batch(" first \n\n second ", synthesize, tmp_path)
    initial = next(stream)
    assert calls == []
    assert initial.rows == [[1, "first", "first.wav", "queued", ""],
                            [2, "second", "second.wav", "queued", ""]]
    assert (initial.completed, initial.failed, initial.total, initial.running) == (0, 0, 2, True)
    first_running = next(stream)
    assert calls == []
    assert [r[3] for r in first_running.rows] == ["running", "queued"]
    first_done = next(stream)
    assert [t for t, _ in calls] == ["first"]
    assert [r[3] for r in first_done.rows] == ["completed", "queued"]
    second_running = next(stream)
    assert [t for t, _ in calls] == ["first"]
    assert [r[3] for r in second_running.rows] == ["completed", "running"]
    second_done = next(stream)
    assert [t for t, _ in calls] == ["first", "second"]
    final = next(stream)
    with pytest.raises(StopIteration):
        next(stream)
    assert (final.completed, final.failed, final.total, final.running) == (2, 0, 2, False)
    assert final.archive and Path(final.archive).is_file()
    assert all(s.archive is None for s in [initial, first_running, first_done, second_running, second_done])
    assert [r[3] for r in initial.rows] == ["queued", "queued"]
    assert initial.files == [] and len(first_done.files) == 1
    final.rows[0][3] = "consumer mutation"
    final.files.clear()
    assert second_done.rows[0][3] == "completed"
    assert len(second_done.files) == 2


def test_failure_continues_and_zip_contains_only_successes_and_manifest(batch, tmp_path):
    calls = []

    def synthesize(text, path):
        calls.append(text)
        if text == "bad":
            Path(path).write_bytes(b"partial must not be archived")
            raise RuntimeError("deliberate failure")
        Path(path).write_bytes(("audio:" + text).encode())

    updates = list(batch.run_batch("成功\nbad\nlast", synthesize, tmp_path))
    final = updates[-1]
    assert calls == ["成功", "bad", "last"]
    assert (final.completed, final.failed, final.total, final.running) == (2, 1, 3, False)
    assert [r[3] for r in final.rows] == ["completed", "failed", "completed"]
    assert final.rows[1][4] == "deliberate failure"
    with zipfile.ZipFile(final.archive) as archive:
        assert set(archive.namelist()) == {final.rows[0][2], final.rows[2][2], "tasks.json"}
        assert archive.read(final.rows[0][2]) == "audio:成功".encode()
        assert archive.read(final.rows[2][2]) == b"audio:last"
        manifest = json.loads(archive.read("tasks.json"))
    assert manifest == [dict(zip(("index", "text", "filename", "status", "error"), row))
                        for row in final.rows]
    failed_snapshot = next(s for s in updates if s.failed == 1)
    assert failed_snapshot.completed == 1 and failed_snapshot.running
    assert failed_snapshot.rows[2][3] == "queued"


def test_all_failures_do_not_create_zip(batch, tmp_path):
    calls = []

    def fail(text, path):
        calls.append(text)
        raise ValueError("no audio")

    final = list(batch.run_batch("a\nb", fail, tmp_path))[-1]
    assert calls == ["a", "b"]
    assert (final.completed, final.failed, final.running) == (0, 2, False)
    assert final.files == [] and final.archive is None
    assert not list(tmp_path.rglob("*.zip"))


@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_nonexistent_or_empty_output_is_a_failed_task(batch, tmp_path, kind):
    def synthesize(text, path):
        if kind == "empty":
            Path(path).touch()
        return path

    final = list(batch.run_batch("bad output", synthesize, tmp_path))[-1]
    assert (final.completed, final.failed) == (0, 1)
    assert "audio file" in final.rows[0][4]
    assert final.files == [] and final.archive is None


def test_duplicate_casefold_and_sanitization_collisions(batch):
    used = set()
    texts = ["same", "same", "SAME", "a/b", "a?b", "a_b", "é", "e\u0301"]
    names = [batch.audio_filename(text, used) for text in texts]
    assert names == ["same.wav", "same (2).wav", "SAME (3).wav",
                     "a_b.wav", "a_b (2).wav", "a_b (3).wav", "é.wav", "é (2).wav"]
    assert used == {name.casefold() for name in names}


@pytest.mark.parametrize("text", [
    'a<>:"/\\|?*\x00\x01\x1f\x7fb', "CON", "con.txt", "PRN", "AUX", "NUL",
    "COM1", "COM9.log", "LPT1", "LPT9.wav", "COM¹", "LPT²", "COM³.txt",
    " ... ", "trailing... ",
])
def test_windows_names_are_safe(batch, text):
    name = batch.audio_filename(text, set())
    stem = name[:-4]
    assert name.endswith(".wav") and stem
    assert not re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', name)
    assert stem == stem.strip(" .")
    assert not re.match(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", stem, re.I)


def test_long_chinese_names_truncate_without_splitting_utf8(batch, tmp_path):
    text = "中文语音" * 100
    used = set()
    names = [batch.audio_filename(text, used), batch.audio_filename(text + "另", used)]
    assert names == [text[:40] + ".wav", text[:40] + " (2).wav"]
    assert len(names[0][:-4].encode("utf-8")) == 120
    for name in names:
        assert "\ufffd" not in name
        path = tmp_path / name
        path.write_bytes(b"wav")
        assert path.is_file()


def test_batches_have_isolated_directories(batch, tmp_path):
    def synthesize(text, path):
        Path(path).write_bytes(b"wav")

    one = list(batch.run_batch("same\nsame", synthesize, tmp_path))[-1]
    two = list(batch.run_batch("same\nsame", synthesize, tmp_path))[-1]
    assert Path(one.archive).parent != Path(two.archive).parent
    assert set(one.files).isdisjoint(two.files)
    for result in [one, two]:
        assert [Path(p).name for p in result.files] == ["same.wav", "same (2).wav"]
        assert Path(result.archive).parent.parent == tmp_path.resolve()
        assert all(Path(p).read_bytes() == b"wav" for p in result.files)


class GrError(Exception):
    pass


class GrProgress:
    def __init__(self):
        self.calls = []

    def __call__(self, value, **kwargs):
        self.calls.append((value, kwargs))


def _extract_function(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return copy.deepcopy(next(node for node in tree.body
                              if isinstance(node, ast.FunctionDef) and node.name == name))


def _strict_infer(version, record):
    path = ROOT / "indextts" / ("infer_v2_5.py" if version else "infer_v2.py")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    method = copy.deepcopy(next(node for cls in tree.body if isinstance(cls, ast.ClassDef)
                                for node in cls.body if isinstance(node, ast.FunctionDef)
                                and node.name == "infer"))
    # Keep the actual signature; explicitly check **generation_kwargs as well.
    method.decorator_list = []
    method.body = ast.parse("return _record(self, locals())").body
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {"_record": record}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["infer"]


@pytest.fixture
def runtime(tmp_path):
    def build(version):
        before = object()
        tts = types.SimpleNamespace(gr_progress=before, calls=[], normalized=[],
                                    fail=None, fail_text=None, return_none=False, write_audio=True)
        mutex = threading.Lock()

        def record(self, arguments):
            arguments = arguments.copy()
            assert arguments.pop("self") is self
            generation = arguments.pop("generation_kwargs")
            assert set(generation) == set(ADVANCED), repr(generation)
            assert arguments["stream_return"] is False
            assert mutex.locked()
            assert self.gr_progress is self.expected_progress
            self.calls.append((arguments, generation.copy()))
            if self.fail is not None:
                raise self.fail
            if arguments["text"] == self.fail_text:
                raise RuntimeError("deliberate inference failure")
            if self.write_audio:
                Path(arguments["output_path"]).write_bytes(b"RIFF fake wav")
            return None if self.return_none else arguments["output_path"]

        def normalize(vector, apply_bias):
            tts.normalized.append((vector, apply_bias))
            return [0.01] * 8

        tts.normalize_emo_vec = normalize
        tts.infer = types.MethodType(_strict_infer(version, record), tts)
        gr = types.SimpleNamespace(Error=GrError, Progress=GrProgress,
                                   update=lambda **kwargs: {"__type__": "update", **kwargs})
        namespace = dict(gr=gr, os=os, uuid=uuid, mutex=mutex,
                         cmd_args=types.SimpleNamespace(verbose=True), IS_V25=version, tts=tts)
        function = _extract_function(ROOT / "webui.py", "gen_single")
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     str(ROOT / "webui.py"), "exec"), namespace)
        prompt = tmp_path / "speaker.wav"
        emotion = tmp_path / "emotion.wav"
        prompt.write_bytes(b"speaker")
        emotion.write_bytes(b"emotion")
        return types.SimpleNamespace(namespace=namespace, tts=tts, mutex=mutex,
                                     before=before, prompt=str(prompt), emotion=str(emotion))
    return build


def _invoke(rt, tmp_path, mode=0, language="EN", emotion_text="", advanced=None,
            progress=None, **overrides):
    rt.tts.expected_progress = progress
    values = dict(prompt=rt.prompt, text="hello", emotion=rt.emotion,
                  output_path=str(tmp_path / "generated.wav"))
    values.update(overrides)
    return rt.namespace["gen_single"](
        mode, values["prompt"], values["text"], language, values["emotion"], 0.65,
        *([0.1] * 8), emotion_text, True, "99", "1.25",
        *(ADVANCED_INPUT if advanced is None else advanced),
        progress=progress, output_path=values["output_path"],
    )


@pytest.mark.parametrize("version", [False, True], ids=["v2", "v2.5"])
@pytest.mark.parametrize("mode", [0, 1, 2, 3])
def test_real_infer_signature_and_advanced_parameter_contract(runtime, tmp_path, version, mode):
    rt = runtime(version)
    result = _invoke(rt, tmp_path, mode=mode, emotion_text="joy", progress=GrProgress())
    assert result == {"__type__": "update", "value": str(tmp_path / "generated.wav"), "visible": True}
    arguments, generation = rt.tts.calls[0]
    assert generation == ADVANCED
    expected = dict(spk_audio_prompt=rt.prompt, text="hello", output_path=str(tmp_path / "generated.wav"),
                    emo_audio_prompt=None if mode == 0 else rt.emotion, emo_alpha=0.65,
                    emo_vector=[0.01] * 8 if mode == 2 else None,
                    use_emo_text=mode == 3, emo_text="joy", use_random=True,
                    interval_silence=200, verbose=True, max_text_tokens_per_segment=99,
                    stream_return=False, more_segment_before=0)
    if version:
        expected.update(lang="EN", duration_factor=1.25, text_normalization=True)
    assert arguments == expected
    assert rt.tts.normalized == ([([0.1] * 8, True)] if mode == 2 else [])
    assert rt.tts.gr_progress is rt.before
    assert not rt.mutex.locked()


@pytest.mark.parametrize("version", [False, True], ids=["v2", "v2.5"])
def test_empty_emotion_language_fallback_disabled_top_k(runtime, tmp_path, version):
    rt = runtime(version)
    advanced = ADVANCED_INPUT.copy()
    advanced[2] = "0"
    _invoke(rt, tmp_path, mode=3, language="", advanced=advanced)
    arguments, generation = rt.tts.calls[0]
    assert arguments["emo_text"] is None
    assert generation == {**ADVANCED, "top_k": None}
    if version:
        assert arguments["lang"] == "ZH"
    else:
        assert "lang" not in arguments and "duration_factor" not in arguments


@pytest.mark.parametrize("version", [False, True], ids=["v2", "v2.5"])
@pytest.mark.parametrize("kind", ["none", "missing", "exception"])
def test_failure_restores_progress_and_releases_lock(runtime, tmp_path, version, kind):
    rt = runtime(version)
    rt.tts.return_none = kind == "none"
    rt.tts.write_audio = kind != "missing"
    failure = RuntimeError("inference exploded")
    rt.tts.fail = failure if kind == "exception" else None
    expected = RuntimeError if kind == "exception" else GrError
    with pytest.raises(expected, match="inference exploded|未返回音频") as caught:
        _invoke(rt, tmp_path, progress=GrProgress())
    if kind == "exception":
        assert caught.value is failure
    assert rt.tts.gr_progress is rt.before
    assert not rt.mutex.locked()
    rt.tts.fail = None
    rt.tts.return_none = False
    rt.tts.write_audio = True
    _invoke(rt, tmp_path, progress=GrProgress())
    assert rt.tts.gr_progress is rt.before


@pytest.mark.parametrize("overrides, mode", [
    ({"prompt": None}, 0), ({"prompt": "does-not-exist.wav"}, 0),
    ({"text": " \t\n"}, 0), ({"emotion": None}, 1),
])
def test_invalid_input_rejected_before_inference(runtime, tmp_path, overrides, mode):
    rt = runtime(False)
    with pytest.raises(GrError):
        _invoke(rt, tmp_path, mode=mode, **overrides)
    assert rt.tts.calls == []
    assert rt.tts.gr_progress is rt.before


@pytest.mark.parametrize("version", [False, True], ids=["v2", "v2.5"])
def test_batch_handler_integrates_with_real_infer_contract(batch, runtime, tmp_path, monkeypatch, version):
    rt = runtime(version)
    rt.tts.expected_progress = None
    rt.tts.fail_text = "bad"
    rt.namespace.update(parse_batch_text=batch.parse_batch_text, run_batch=batch.run_batch)
    function = _extract_function(ROOT / "webui.py", "gen_batch")
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 str(ROOT / "webui.py"), "exec"), rt.namespace)
    monkeypatch.chdir(tmp_path)
    progress = GrProgress()
    updates = list(rt.namespace["gen_batch"](
        0, rt.prompt, "first\nbad\nlast", "JA", rt.emotion, 0.65,
        *([0.1] * 8), "", False, 99, 1.25, *ADVANCED_INPUT, progress=progress,
    ))
    status, rows, files, archive, latest = updates[-1]
    assert "3/3" in status and "成功 2" in status and "失败 1" in status
    assert [arguments["text"] for arguments, _ in rt.tts.calls] == ["first", "bad", "last"]
    assert [row[2] for row in rows] == ["first.wav", "bad.wav", "last.wav"]
    assert "Failed" in rows[1][3] and "deliberate" in rows[1][4]
    assert [Path(path).name for path in files] == ["first.wav", "last.wav"]
    assert latest == files[-1] and Path(archive).is_file()
    assert progress.calls[-1][0] == 1.0
    assert rt.tts.gr_progress is rt.before and not rt.mutex.locked()
