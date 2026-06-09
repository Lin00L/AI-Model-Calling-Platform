# Great Mind - Memory Console

一个基于 Flask 的多模型 AI 对话平台，拥有完整的**记忆管理系统**，支持临时记忆、永久记忆、记忆压缩与多模型协作讨论。

## 功能特性

### 核心能力

- **多厂商 LLM 接入** — 统一接口支持 Google Gemini、OpenAI、SiliconFlow、ModelScope、LongCat 五大平台
- **双层级记忆系统** — 临时记忆（会话级上下文）+ 永久记忆（跨会话持久化知识）
- **记忆压缩引擎** — 基于 LLM 的递归摘要压缩，支持多种预设模板（通用/编程/角色扮演）
- **多模型协作讨论** — 多个 AI 模型按轮次接力对话，支持自定义角色名与思考模式
- **思考/推理模式** — 自动检测模型能力，支持 DeepSeek R1、Gemini Thinking、QwQ 等推理模型
- **流式响应 (SSE)** — 实时流式输出，含思考过程与正文分离展示
- **多模态附件** — 支持图片上传与文本文件内联，自动转 Base64 发送

### 安全机制

- 文件名严格校验（防路径穿越 / Windows 保留名 / 控制字符）
- 附件大小与数量限制（默认 10MB / 文件，最多 8 个）
- 原子写入（临时文件 + `os.replace`），防止断电数据损坏
- 线程安全（读写锁 + 全局锁），支持并发访问

### 会话管理

- 多会话独立存储（每个会话一个 JSON 文件）
- 会话重命名 / 删除
- 消息级别记忆开关（可逐条启用/遗忘）
- 永久记忆实时编辑与新增
- 单条 AI 回复重新生成

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | Flask (Python) |
| AI SDK | google-genai, openai, requests |
| 前端 | 原生 HTML/CSS/JS (SPA) |
| 代码高亮 | highlight.js |
| 数学公式 | KaTeX |
| 图标 | Font Awesome |
| 字体 | Inter + JetBrains Mono |

## 项目结构

```
AIUse/
├── app.py              # 主应用入口 (Flask 路由 + 业务逻辑)
├── llm_providers.py    # 多厂商 LLM 抽象层 (Provider 接口 + Key 管理)
├── templates/
│   └── index.html      # 前端单页应用
├── chats_data/         # 对话数据存储 (JSON)
├── uploads/            # 附件文件存储
└── README.md
```

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/your-username/AIUse.git
cd AIUse
```

### 2. 安装依赖

```bash
pip install flask google-genai openai requests
```

### 3. 配置 API Key

编辑 `llm_providers.py`，在 `my_keys` 字典中填入你的 API 密钥：

```python
my_keys = {
    "google": [
        {"name": "Gemini 主号", "key": "YOUR_GOOGLE_API_KEY"},
    ],
    "openai": [
        {"name": "OpenAI 主号", "key": "sk-YOUR_OPENAI_KEY"},
    ],
    "siliconflow": [
        {"name": "硅基流动 主号", "key": "sk-YOUR_SILICONFLOW_KEY"},
    ],
    "modelscope": [
        {"name": "ModelScope 主号", "key": "YOUR_MODELSCOPE_TOKEN"},
    ],
    "longcat": [
        {"name": "LongCat 主号", "key": "YOUR_LONGCAT_KEY"},
    ],
}
```

> 支持为每个厂商配置多个 Key，系统会自动轮询（Round-Robin）分配请求。

### 4. 启动服务

```bash
python app.py
```

默认监听 `0.0.0.0:5000`，浏览器访问 http://localhost:5000 即可使用。

## 使用说明

### 记忆系统

- **临时记忆**（默认）：随对话积累，可通过"记忆压缩"归纳为精简摘要
- **永久记忆**：作为 System Instruction 注入每次请求，适合存储角色设定、核心偏好等长期知识
- **记忆压缩**：将临时记忆 + 旧摘要通过 LLM 递归压缩为结构化真值表（档案/定案/任务三段式）

### 多模型讨论

在讨论模式下，可指定多个不同平台/模型的 AI 参与者，设置讨论轮数与初始指令，模型之间可看到彼此的输出并接力回复。

### 思考模式

系统会根据模型 ID 自动检测是否支持思考/推理模式（基于白名单 + 关键词匹配），支持的平台参数格式：

| 平台 | 参数 | 说明 |
|------|------|------|
| Google Gemini | `thinking_config` | 原生思考配置 |
| SiliconFlow | `enable_thinking` | 开关式 |
| LongCat | `enable_thinking` + `thinking_budget` | 开关 + Token 预算 |
| OpenAI | `reasoning_effort` | 推理力度 |

## 环境变量（可选）

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MAX_UPLOAD_BYTES` | `10485760` (10MB) | 单个附件最大字节数 |
| `MAX_ATTACHMENT_COUNT` | `8` | 单次消息最大附件数 |

## 注意事项

> **重要：请勿将包含真实 API Key 的代码推送到公开仓库。**  
> 建议在提交前将 `llm_providers.py` 中的密钥替换为占位符，或使用环境变量管理密钥。

## License

MIT
