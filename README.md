# General Video LangGraph Backend

LangGraph-based backend for video highlight extraction and commentary/ad video generation workflows.

这个目录是独立重构项目，不修改原来的 `General_Video_Agent`。

## 当前实现范围

### 1. 高光视频片段批量剪辑

LangGraph 节点：

```text
init_task
  -> collect_videos
  -> asr_transcribe
  -> content_clip
  -> split_and_group
  -> vlm_analyze
  -> select_highlights
  -> save_highlight_result
  -> maybe_generate_draft
  -> finish
```

高光线复用了原项目已有能力：

```text
VideoCollector
ASRTranscriber
ContentClipper
VideoSplitter
SubtitleGrouper
SegmentAnalyzer
ShortDramaProcessor
```

### 2. 解说词 / 信息流广告二次创作

LangGraph 节点：

```text
init_task
  -> analyze_material
  -> generate_script
  -> synthesize_tts
  -> check_tts_duration
  -> align_video_info
  -> generate_bgm
  -> generate_overlay
  -> generate_sound
  -> create_jianying_draft
  -> finish
```

第一版支持 `demo_info/template` 模式。直接输入视频后自动做 ASR/VLM 素材理解的模式还没有接入。

为了先跑通 LangGraph 后端链路，解说词线里的 TTS 和剪映草稿生成目前是 stub：

```text
synthesize_tts_stub: 生成可预测 timestamps 和占位音频文件
create_commentary_draft_stub: 生成 draft_manifest.json
```

后续接真实字节 TTS / CosyVoice / Jianying converter 时，只需要替换 service，不需要改 graph 结构。

## 目录结构

```text
src/
  api/
    app.py
    schemas.py
    server.py

  services/
    highlight_service.py
    commentary_service.py
    draft_service.py

  workflow/
    graphs/
      highlight_graph.py
      commentary_graph.py
    nodes/
      highlight_nodes.py
      commentary_nodes.py
    runtime/
      storage.py
      events.py
    states/
      base_state.py
      highlight_state.py
      commentary_state.py
    runners.py
```

## 启动

```bash
cd /Users/lxh/codebase/crengine/general_video_agent_v2/General_Video_LangGraph
conda activate video_agent
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

也可以使用：

```bash
python -m src.api.server
```

## API

### 健康检查

```bash
curl http://127.0.0.1:8000/healthz
```

### 高光分析

```bash
curl -N -X POST http://127.0.0.1:8000/highlight_sse \
  -H "Content-Type: application/json" \
  -d '{
    "input_videos": ["/path/to/video.mp4"],
    "output_base_dir": "/tmp/general_video_langgraph/highlight",
    "fps": 1.0,
    "max_workers": 3,
    "save_intermediate": true
  }'
```

输出目录结构：

```text
output_base_dir/
  tasks/
    {task_id}/
      config.json
      state.latest.json
      intermediates/
      outputs/
        highlight_results.json
```

### 解说词 / 信息流广告

```bash
curl -N -X POST http://127.0.0.1:8000/commentary_sse \
  -H "Content-Type: application/json" \
  -d '{
    "demo_info": [
      {
        "start": 0,
        "end": 3,
        "folder": "开头素材",
        "subtitle": "她刚推开门，就发现气氛不对"
      },
      {
        "start": 3,
        "end": 8,
        "folder": "冲突素材",
        "subtitle": "丈夫的沉默让她意识到事情没有那么简单"
      }
    ],
    "user_demand": "请用第三人称解说，突出冲突和反转",
    "output_dir": "/tmp/general_video_langgraph/commentary",
    "draft_name": "解说前贴",
    "voice_type": "BV411_streaming",
    "speed_ratio": 1.2
  }'
```

第一版会生成：

```text
tasks/{task_id}/intermediates/material_summary.json
tasks/{task_id}/intermediates/script_result.json
tasks/{task_id}/intermediates/tts_result.json
tasks/{task_id}/intermediates/video_info.json
{output_dir}/{draft_name}/draft_manifest.json
```

## 前端页面

静态前端位于：

```text
frontend/index.html
frontend/styles.css
frontend/app.js
```

启动后端：

```bash
cd /Users/lxh/codebase/crengine/general_video_agent_v2/General_Video_LangGraph
conda activate video_agent
uvicorn main:app --host 127.0.0.1 --port 8010
```

启动前端静态服务：

```bash
cd /Users/lxh/codebase/crengine/general_video_agent_v2/General_Video_LangGraph/frontend
python -m http.server 5173
```

浏览器打开：

```text
http://127.0.0.1:5173/
```

页面功能：

```text
高光分析：填写 input_videos、output_base_dir、fps、max_workers，调用 /highlight_sse。
解说词生成：填写 demo_info、user_demand、voice、speed，调用 /commentary_sse。
实时事件：展示 LangGraph 节点进度和 SSE 日志。
最终结果：展示 final result，可复制。
```

## 验证状态

已经执行：

```bash
python -m compileall src main.py
conda run -n video_agent python -c "from src.api.app import app; from src.workflow.graphs import build_highlight_graph, build_commentary_graph; build_highlight_graph(); build_commentary_graph(); print('ok')"
```

结果：语法编译和应用导入通过。

已用 `video_agent` 环境完成 commentary stub graph smoke test，完整跑通：

```text
init_task
  -> analyze_material
  -> generate_script
  -> synthesize_tts
  -> check_tts_duration
  -> align_video_info
  -> generate_bgm
  -> generate_overlay
  -> generate_sound
  -> create_jianying_draft
  -> finish
```

并已启动服务验证：

```bash
conda run -n video_agent uvicorn main:app --host 127.0.0.1 --port 8010
curl http://127.0.0.1:8010/healthz
```

返回：

```json
{"msg":"OK"}
```

## 后续建议

优先级：

```text
P0: 安装依赖并启动服务，验证 /healthz 和 /commentary_sse stub 链路。
P1: 用真实短视频验证 /highlight_sse。
P2: 将 commentary 的 synthesize_tts_stub 替换为真实 TTSService。
P3: 将 create_commentary_draft_stub 替换为真实 Jianying converter。
P4: 增加 LangGraph conditional edge，实现 TTS 时长过长/过短后的文案重写闭环。
P5: 增加直接输入视频的素材理解节点 analyze_video_material。
```
