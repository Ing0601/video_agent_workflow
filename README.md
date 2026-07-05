# Video Agent Console

`Video Agent Console` 是一个轻量级的视频处理后端与控制台项目，支持视频高光分析、解说词/广告文案生成、以及会话历史存储与摘要管理。

## 项目简介

本项目提供以下核心能力：

- 视频高光分析与结果输出
- 解说词/广告文案生成与 TTS 时间轴支持
- 会话历史保存与摘要归档
- 简洁前端控制台用于触发工作流和查看执行进度

## 目录结构

```text
frontend/               # 前端静态页面与交互逻辑
src/                    # 后端业务代码
  api/                  # FastAPI 接口与请求定义
  config/               # 环境配置与云存储初始化
  logger/               # 日志初始化与输出配置
  memory/               # 兼容旧引用路径的会话存储层
  session_store/        # 会话存储核心实现
  model/                # ASR、TTS、LLM 等模型服务封装
  workflow/             # 高光与解说词工作流实现
  utils/                # 辅助工具函数
main.py                 # 后端入口模块
README.md               # 项目说明文档
.gitignore              # 本地忽略文件配置
```

## 功能说明

### 高光分析

通过 `POST /highlight_sse` 发起视频高光分析工作流。

该工作流会接收视频输入，执行语音识别、帧分析、片段筛选等步骤，并采用 SSE 实时返回执行进度和结果。

### 解说词生成

通过 `POST /commentary_sse` 发起解说词/广告文案生成工作流。

该流程支持结构化 `demo_info` 输入、用户需求定制、语音合成策略等，并采用 SSE 实时返回执行进度与结果。

### 会话存储与摘要

项目中的会话存储实现位于 `src/session_store`，用于：

- 保存对话消息到数据库
- 检查会话 token 使用阈值
- 将对话历史压缩为摘要并写回存储

该实现更像“会话历史存储与摘要服务”，而不是通用语义向量记忆库。

## 环境变量

项目支持通过 `.env` 文件读取环境变量。示例：

```env
DASHSCOPE_API_KEY=your_dashscope_api_key
TOS_ACCESS_KEY=your_tos_access_key
TOS_SECRET_KEY=your_tos_secret_key
TOS_BUCKET_NAME=your_tos_bucket_name
TOS_ENDPOINT=tos-cn-beijing.volces.com
TOS_REGION=cn-beijing
OPENAI_API_KEY=your_openai_api_key
OPENAI_BASE_URL=https://api.your-openai-proxy.com/v1
```

> 请勿将实际密钥提交到公共仓库。

如果不使用 `.env`，也可以直接在 shell 中导出环境变量。

## 依赖安装

建议使用虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果使用 conda：

```bash
conda create -n video_agent python=3.11 -y
conda activate video_agent
pip install -r requirements.txt
```

## 启动后端

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

或：

```bash
python -m src.api.server
```

启动后可以访问：

```bash
curl http://127.0.0.1:8000/healthz
```

## API 参考

### 健康检查

- `GET /healthz`
- `GET /health`

返回示例：

```json
{ "msg": "OK" }
```

### 高光分析

- `POST /highlight_sse`
- 请求示例：

```json
{
  "input_videos": ["/path/to/video.mp4"],
  "output_base_dir": "/tmp/video_agent/highlight",
  "fps": 1.0,
  "max_workers": 3,
  "save_intermediate": true,
  "generate_draft": false
}
```

### 解说词生成

- `POST /commentary_sse`
- 请求示例：

```json
{
  "input_videos": [],
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
  "output_dir": "/tmp/video_agent/commentary",
  "draft_name": "解说前贴",
  "voice_type": "BV411_streaming",
  "speed_ratio": 1.2
}
```

## 前端使用

前端静态页面文件位于：

```text
frontend/index.html
frontend/styles.css
frontend/app.js
```

前端通过 SSE 调用后端接口，展示实时执行进度和结果。

如果需要单独启动前端静态服务：

```bash
cd frontend
python -m http.server 5173
```

然后访问：

```text
http://127.0.0.1:5173/
```
