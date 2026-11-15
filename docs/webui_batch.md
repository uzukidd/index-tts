# Batch generation in the WebUI

[中文说明](#中文说明)

Upload a voice reference on the audio generation page, then enter **one task per line** in **Batch generation**. Blank lines are ignored; line breaks separate independent audio files. Choose the shared language, duration (v2.5), emotion, preset and advanced generation settings, then click **Generate batch**.

Tasks run sequentially on the same model. The table shows waiting, running, completed and failed tasks; the latest completed audio can be previewed. A failed task records its error and the remaining tasks continue. Successful WAV files can be downloaded individually or together using **Download all (ZIP)**. The ZIP also includes `tasks.json`, which maps the original text to filenames and records errors. If every task fails, no ZIP is offered.

Audio names use the task text. Invalid Windows filename characters are replaced with underscores, reserved names are prefixed, long names are shortened, and duplicates (including case-insensitive collisions) get ` (2)`, ` (3)`, etc. Each batch has its own directory under `outputs/tasks/batch_*`; the original text passed to the model is unaffected by filename cleaning. Batch files remain on disk until you remove them.

The existing single-text workflow remains available. Single and batch generation share a serialized Gradio queue and an inference lock because model caches are shared. `lang` and `duration_factor` are forwarded only to IndexTTS 2.5; both versions use their existing non-streaming `infer` API.

## Verify without PyTorch

The `indextts` Conda environment can contain only Python 3.11 and the UI dependencies for this check. If it does not exist, create it first; do not use the base environment:

```bash
conda create -n indextts python=3.11 pip -y
conda run -n indextts python -m pip install -r scripts/requirements-webui-test.txt
```

Launch with `scripts/webui_ui_only.bat` (Windows) or `bash scripts/webui_ui_only.sh` (Linux/macOS), then open <http://127.0.0.1:7861>. Extra arguments are accepted, for example `--version 2` or `--port 7862`. You can also run:

```bash
conda run --no-capture-output -n indextts python webui.py --ui-only --host 127.0.0.1 --port 7861
```

**UI-only mode creates silent WAV fixtures. It does not synthesize speech, import PyTorch, or download model checkpoints/example audio.** A banner identifies this mode. Reference uploads are still required so the real upload and validation flow can be exercised. Token previews use a simple character splitter, so they do not validate model tokenization. Normal model inference uses the original startup command without `--ui-only` and requires the normal project dependencies and checkpoints.

Run `scripts/test_webui.bat` or `bash scripts/test_webui.sh` for batch logic, filename handling, error recovery, source checks and model API contract checks. Add `--browser` to exercise uploading a WAV, submitting two batches, checking statuses, downloading a ZIP and inspecting its contents in a real browser for both model versions. These checks start and stop their own temporary local WebUI processes.

Browser checks use installed Microsoft Edge on Windows and Playwright Chromium on Linux/macOS. Override with `INDEXTTS_BROWSER_CHANNEL=chrome` if appropriate. For Chromium, install it with `conda run -n indextts python -m playwright install chromium`. Screenshots are written to `outputs/webui-batch-v2.png` and `outputs/webui-batch-v2.5.png`.

## 中文说明

在“音频生成”页上传音色参考音频，然后在“批量生成”中输入文本，**每行一条任务**，空行会忽略。每条任务独立生成一个音频；换行即表示新任务。设置本页共用的语言、时长系数（2.5）、情感、预设和高级参数后，点击“开始批量生成”。

任务按输入顺序逐条执行。表格显示等待、生成中、完成或失败，可试听最近完成的音频。单条任务失败会记录错误并继续后续任务。成功的 WAV 可以逐个下载，也可以点击“全部打包下载”获取 ZIP。压缩包同时附带 `tasks.json`，记录原文、实际文件名、任务状态和错误。全部失败时不会提供空压缩包。

文件名采用对应文本，自动替换 Windows 非法字符、处理保留名称、截短过长文本，并为重名或大小写冲突追加 ` (2)`、` (3)`。每批生成到独立的 `outputs/tasks/batch_*` 目录，清理文件名不会改变传给模型的文本。生成文件保留在磁盘，可自行清理。

原有单条生成入口仍可使用。单条和批量共用串行队列及模型推理锁，避免共享缓存冲突。语言 `lang` 和时长 `duration_factor` 仅传给 2.5，两版均使用已有的非流式 `infer` API。

### 不安装 PyTorch 的验证方法

使用 Python 3.11 的独立 `indextts` Conda 环境。不存在时先运行上方创建环境命令，再通过 `scripts/requirements-webui-test.txt` 安装界面测试依赖，不需要安装项目全部依赖。

Windows 运行 `scripts/webui_ui_only.bat`，Linux/macOS 运行 `bash scripts/webui_ui_only.sh`，打开 <http://127.0.0.1:7861>。可追加 `--version 2` 或 `--port 7862`。也可以使用上方带 `--ui-only` 的 Python 命令。

**测试模式只生成静音 WAV，不合成语音、不导入 PyTorch、不下载模型及示例音频。** 页面顶部会明确标示测试模式。仍需上传参考音频，以验证真实上传和校验流程；分句预览使用字符切分，不能用于验证模型分词效果。实际模型运行时使用原有启动命令，去掉 `--ui-only`，并准备正常模型依赖与权重。

运行 `scripts/test_webui.bat` 或 `bash scripts/test_webui.sh` 检查批处理、命名、异常恢复、源码及两版模型接口契约。追加 `--browser` 可在真实浏览器中验证两版界面的上传、连续提交两批任务、状态更新、ZIP 下载及包内内容。测试会自动启动并关闭临时 WebUI。

Windows 默认使用已安装的 Edge，Linux/macOS 默认使用 Playwright Chromium。可通过环境变量 `INDEXTTS_BROWSER_CHANNEL=chrome` 改用 Chrome。使用 Chromium 前运行上方 Playwright 安装命令。浏览器截图保存在 `outputs/webui-batch-v2.png` 和 `outputs/webui-batch-v2.5.png`。
