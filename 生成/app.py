import hashlib
import mimetypes
import os
import json
import threading
from contextlib import contextmanager

from flask import Response, stream_with_context
from flask import Flask, render_template, request, jsonify, abort
import re


import base64 # 新增引用
app = Flask(__name__)

# --- 配置区 ---
# 新增：多厂商 Provider
from llm_providers import ProviderType, PROVIDER_SPECS, get_provider, key_manager

# =========================
# 记忆压缩提示词预设（可扩展）
# =========================

MEMORY_SUMMARY_PRESETS = {
    "truth_table": {
        "name": "旧通用：真值记忆表（长期记忆引擎）",
        "template": """# Role: 长期记忆保存与递归专家 (Memory Engine)

# Task:
合并【存量记忆】与【增量对话】，输出唯一、最新的“真值记忆表”。

# Logic:
1. **识别**：
   - **Base (存量)**：匹配以 `- **档案(Profile)**`、`- **定案(Decisions)**`、`- **任务(Actions)**` 开头的块。
   - **Delta (增量)**：所有非结构化对话或原始日志。
2. **处理**：
   - **覆写**：增量信息若与存量冲突，直接删除旧记录，保留最新态。
   - **聚合**：按主体归类，单行陈述。格式：`[主体] -> [属性1; 属性2]`。
   - **剪枝**：移除已完成任务、失效推测、修饰词，仅保留“实体+动作/状态”。

# Output Format (严格遵循):
- **档案(Profile)**: [主体] -> [长期属性/技术栈/环境/偏好]
- **定案(Decisions)**: [核心事实/共识结论/关键代码]
- **任务(Actions)**: [状态: 待办/进行中] [执行人] [任务项] [时间点]

# Constraints:
- 禁言：严禁解释、开场白或结束语。
- 隐藏：若某模块无内容，不显示标题。
- 精度：精准保留代码变量、路径、配置参数。

# Input:
<<INPUT>>
"""
    },
    "newtruth_table": {
        "name": "新通用：真值记忆表（长期记忆引擎）",
        "template": """# Role: Memory Compressor

# Task
从输入中合并【既有记忆表】与【新增对话/日志】，输出唯一、最新、尽可能短的“真值记忆表”。

# Parse
Base = 输入内出现的 **档案(Profile)** / **定案(Decisions)** / **任务(Actions)** 块；其余为 Delta。

# Keep (minimum sufficient set)
只保留“下一轮仍可能被用到”的信息：
- Profile：会影响后续输出的稳定偏好/约束/环境
- Decisions：已确认结论/规则/契约/不可逆事实
- Actions：待办/进行中/阻塞（可执行、能推进）

# Drop
删除：客套/情绪/修饰描写/重复陈述/无结论讨论/一次性细节/长代码或长日志全文。
敏感明文（key/token/password/验证码等）不入记忆：仅可记录“已配置/已提供/存在”之类的非明文状态。

# Update (conflict-safe)
- 只有当 Delta “明确 + 可执行/可验证”时才覆写 Base；含糊/无证据 => 不覆写，转为 Actions 的“待确认”
- 可并存（不同环境/角色/阶段）=> 并存并加最短限定词
- 去重合并：同义合并；同主体同属性只留最新；属性用 “;” 聚合

# Adaptive compression (attention-like, no fixed line limit)
硬要求：输出必须显著短于输入；输入越长 => 压缩越激进。
保留优先级（高→低）：
硬约束/契约/不可逆事实 > 当前阻塞与下一步任务 > 稳定环境信息 > 其他。
对过长清单：提炼为“规则/摘要 + 少量关键名词”，仅保留未来会被引用的名称/键/路径。

# Idempotence & ordering
输出应可反复压缩而不膨胀：不创造新别名/新分类；同一主体只出现一次；按优先级排序后再按主体名排序。

# Fidelity
必须原样保留关键标识：变量/函数/类/字段/路径/配置键；错误信息最多2行关键句。
禁止粘贴长代码：只能写“契约级摘要”。

# Output (strict; omit empty)
- **档案(Profile)**:
  - [主体] -> [属性; 属性...]
- **定案(Decisions)**:
  - [范围] -> [结论/规则/契约...]
- **任务(Actions)**:
  - [状态: 待办/进行中/阻塞/待确认] [执行人: 用户/助手/未知] [任务项] [时间点: 可空]

# Hard
只输出记忆表；禁止解释；禁止编造。

# Input:
<<INPUT>>
"""
    },

    "coding_patchlog": {
        "name": "代码/项目：变更日志 + TODO（适合开发协作）",
        "template": """# Role: Memory Compressor (Programming)

# Task
合并既有记忆表(Base) + 新增对话/日志/代码(Delta)，输出最短可用的工程真值记忆表。

# Parse
Base = **档案(Profile)**/**定案(Decisions)**/**任务(Actions)**；其余为 Delta。

# Keep (only what helps next step)
- 约束：输出/改动限制、工程规范（会影响后续实现）
- 契约：API/协议/字段名/数据结构/关键配置键/文件路径与职责
- Bug：报错关键句(<=2行)+定位(文件/模块/行号)+已确认原因/结论
- Actions：待办/进行中/阻塞/待确认（可执行，含文件/字段/预期）

# Drop
大段代码/长日志全文/重复讨论/一次性细节；敏感明文(密钥/口令/token)不入记忆，仅保留非明文状态。

# Update & conflict rules
- 新信息仅在“明确且可验证/可执行”时覆写旧；否则保持旧并生成“待确认”任务
- 允许并存：用最短标签标注（dev/prod、host/client、provider=xxx）
- 去重合并：同模块同主题只留一条；属性用 “;” 聚合

# Compression (attention-like)
输出必须显著短于输入；输入越长压缩越激进。
保留优先级：硬约束/接口契约 > 当前阻塞与下一步 > 已确认bug结论 > 必要环境信息。
对长列表：改写为“摘要规则 + 少量关键名词/键/路径”。

# Idempotence & ordering
不创造新别名；同一模块/主体只出现一次；按优先级→模块名排序。

# Fidelity
原样保留：函数/变量/字段/路径/配置键；错误<=2行；只写契约级摘要，不贴长代码。

# Output (strict; omit empty)
- **档案(Profile)**:
  - [项目/用户] -> [技术栈; 环境; 关键约束...]
- **定案(Decisions)**:
  - [模块/范围] -> [契约/规则/关键结论...]
- **任务(Actions)**:
  - [状态: 待办/进行中/阻塞/待确认] [执行人] [任务项] [时间点: 可空]

# Hard
只输出记忆表；禁止解释；禁止编造。

# Input:
<<INPUT>>
"""
    },

    "roleplay_cards": {
        "name": "角色扮演：世界卡/角色卡/线索卡（适合文字游戏）",
        "template": """# Role: Memory Compressor (Roleplay)

# Task
合并既有记忆表(Base) + 新增剧情对话(Delta)，输出最短可用的“世界真值记忆表”。

# Parse
Base = **档案(Profile)**/**定案(Decisions)**/**任务(Actions)**；其余为 Delta。

# Keep (only what affects continuity)
- Profile：玩家硬偏好/禁忌/玩法约束；关键人物/地点的稳定状态（仅保留可复用）
- Decisions：已发生且不可逆的事件与后果；已确认线索/已解谜结论/已排除项
- Actions：下一步目标/待调查线索/阻塞原因/待确认（可执行）

# Drop
对白复述、氛围描写、重复信息、一次性细节；未确认推测不写死（转“待确认/待调查”任务）。

# Update & truth rules
- 既定事实仅在“明确确认反转/伪证/修正”时改写；否则保持旧并生成待确认任务
- 命名归一：同一角色/地点别名合并；同主体只出现一次
- 去重合并：属性用 “;” 聚合；能并存则加最短限定词

# Compression (attention-like)
输出必须显著短于输入；输入越长压缩越激进。
保留优先级：不可逆后果/当前矛盾与场景锚点 > 关键线索进度 > 玩家硬约束与关系网 > 其他。
对长清单：提炼为“摘要规则 + 少量关键名词”。

# Idempotence & ordering
不创造新称谓；按优先级→主体名排序，保证反复压缩不膨胀。

# Output (strict; omit empty)
- **档案(Profile)**:
  - [玩家/关键角色/地点] -> [属性; 状态...]
- **定案(Decisions)**:
  - [事件/线索/谜题] -> [已确认事实/结论/后果...]
- **任务(Actions)**:
  - [状态: 待办/进行中/阻塞/待确认/待调查] [执行人: 玩家/叙事者/未知] [下一步] [时间点: 可空]

# Hard
只输出记忆表；禁止解释；禁止编造。

# Input
<<INPUT>>
"""
    },
#
#     "study_review": {
#         "name": "学习/考试：复习要点 + 易错点（适合课程总结）",
#         "template": """# Role: 学习复盘与知识点压缩专家
#
# # Task:
# 把对话压缩成“复习清单”，包含：概念、公式/步骤、常见坑、必练题型与检查点。
#
# # Output Format (严格遵循):
# - **要点(Key Points)**:
#   - [概念] -> [一句话定义] -> [典型用法/场景]
# - **步骤/模板(Procedures)**:
#   - [任务] -> [步骤1/2/3...]
# - **易错点(Pitfalls)**:
#   - [错误] -> [为什么错] -> [如何避免]
# - **必练题型(Drills)**:
#   - [题型] -> [考察点] -> [自测标准]
#
# # Constraints:
# - 禁言：不解释过程、不寒暄。
# - 删掉闲聊与重复，只保留可复习内容。
# - 不确定就标注“未确认”。
#
# # Input:
# <<INPUT>>
# """
#     },
}

@app.route('/api/memory_summary_presets', methods=['GET'])
def memory_summary_presets():
    """给前端动态加载：只返回 key + name（不下发模板）"""
    items = [{"key": k, "name": v.get("name", k)} for k, v in MEMORY_SUMMARY_PRESETS.items()]
    # 可按需排序：让通用排第一
    items.sort(key=lambda x: (0 if x["key"] == "truth_table" else 1, x["name"]))
    return jsonify({"presets": items})


@app.route('/api/get_providers', methods=['GET'])
def get_providers():
    providers = []
    for _, spec in PROVIDER_SPECS.items():
        providers.append({
            "id": spec.id,
            "display": spec.display,
            "default_model": spec.default_model,
        })
    return jsonify({"providers": providers})


# [Fix] 使用相对路径，而非硬编码 D 盘路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHATS_DIR = os.path.join(BASE_DIR, "chats_data")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

if not os.path.exists(CHATS_DIR):
    os.makedirs(CHATS_DIR)
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# =========================
# Security helpers (P0 fix)
# =========================

# Windows 文件名非法字符 + 控制字符（防止路径/文件名注入）
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Windows 保留名（CON/PRN/...），避免创建/访问异常
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_UPLOAD_NAME_RE = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9]{1,10}$")  # 32位md5 + 简单后缀

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))  # 单个附件最大 10MB（可调）
MAX_BASE64_CHARS = int(MAX_UPLOAD_BYTES * 4 / 3) + 32
MAX_ATTACHMENT_COUNT = int(os.environ.get("MAX_ATTACHMENT_COUNT", 8))  # 单次最多附件数（可调）

def sanitize_chat_id(chat_id: str) -> str:
    """
    允许中文/空格/大部分可见字符作为对话名，但要：
    - 禁止路径穿越（/ \\ .. NUL 控制字符）
    - 禁止 Windows 不允许的文件名字符
    - 禁止 Windows 保留名
    """
    if not isinstance(chat_id, str):
        raise ValueError("非法 chat_id")

    s = chat_id.strip()

    # 兼容用户误填 "xxx.json"
    if s.lower().endswith(".json"):
        s = s[:-5].strip()

    # Windows 不允许以空格/点结尾
    s = s.rstrip(" .")

    if not s:
        raise ValueError("非法 chat_id")

    # 限长（避免奇怪超长文件名）
    if len(s) > 80:
        raise ValueError("chat_id 过长")

    # 禁止路径分隔符/空字节/控制字符/非法文件名字符
    if _ILLEGAL_FILENAME_CHARS.search(s):
        raise ValueError("非法 chat_id")

    # 再保险：禁止 ..（即使没有 / 也别给机会）
    if ".." in s:
        raise ValueError("非法 chat_id")

    # 再保险：禁止 os.sep / altsep
    if os.sep in s or (os.altsep and os.altsep in s):
        raise ValueError("非法 chat_id")

    # Windows 保留名检测：CON / CON.txt 都算
    base = s.split(".")[0].upper()
    if base in _WIN_RESERVED:
        raise ValueError("非法 chat_id")

    return s


def sanitize_upload_fp(fp: str) -> str:
    """
    只允许我们自己生成的 uploads 文件名（md5.ext），并确保归一化后仍在 UPLOAD_FOLDER 内
    """
    if not isinstance(fp, str) or not _UPLOAD_NAME_RE.match(fp):
        raise ValueError("非法 file_path")
    abs_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, fp))
    base = os.path.abspath(UPLOAD_FOLDER) + os.sep
    if not abs_path.startswith(base):
        raise ValueError("路径越界")
    return fp

def parse_index(v, field_name="index") -> int:
    try:
        iv = int(v)
    except Exception:
        raise ValueError(f"非法 {field_name}")
    return iv

file_lock = threading.Lock()
from flask import send_from_directory

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    # 仅允许 md5.ext 形式的文件名，防止异常访问
    try:
        filename = sanitize_upload_fp(filename)
    except Exception:
        abort(404)
    return send_from_directory(UPLOAD_FOLDER, filename)

def save_chat_data(chat_id, data):
    """加锁写入，防止并发冲突"""
    path = get_chat_path(chat_id)
    with file_lock: # 关键：加锁
        # 写入临时文件再重命名，实现原子写入，防止断电导致文件损坏
        temp_path = path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

def save_chat_data_safe(chat_id, data):
    """线程安全的写入"""
    path = get_chat_path(chat_id)
    with file_lock:
        temp_path = path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)


def save_attachment_to_disk(base64_data, mime_type):
    """将前端传来的 base64 数据落盘，返回相对文件名（hash.ext）。"""
    try:
        if not isinstance(base64_data, str) or not isinstance(mime_type, str):
            return None

        # 兼容 data URL
        if base64_data.startswith("data:"):
            comma = base64_data.find(",")
            if comma != -1:
                base64_data = base64_data[comma + 1 :]

        # 粗略限制：base64 字符串过大直接拒绝
        if len(base64_data) > MAX_BASE64_CHARS:
            return None

        # 严格 base64 校验（非法字符会抛异常）
        file_bytes = base64.b64decode(base64_data, validate=True)

        # 限制单文件大小
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            return None

        # 使用标准库获取后缀
        ext = mimetypes.guess_extension(mime_type)
        if not ext:
            ext = "." + mime_type.split('/')[-1].replace('+xml', '')

        # 后缀清洗（极端 mime 避免注入奇怪字符）
        ext = re.sub(r"[^A-Za-z0-9.]", "", ext)
        if not ext.startswith("."):
            ext = "." + ext
        if len(ext) > 11:
            ext = ext[:11]

        file_hash = hashlib.md5(file_bytes).hexdigest()
        filename = f"{file_hash}{ext}"

        file_path = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(file_path):
            with open(file_path, 'wb') as f:
                f.write(file_bytes)
        return filename
    except Exception as e:
        print(f"Save file error: {e}")
        return None


# --- 核心逻辑：档案管理 ---
# --- 改进：基于 Chat ID 的读写锁 ---

# --- 改进：基于 Chat ID 的读写锁 ---

chat_locks = {}
global_lock = threading.Lock()
from contextlib import contextmanager
@contextmanager
def get_chat_lock(chat_id):
    chat_id = sanitize_chat_id(chat_id)  # ✅ 防止路径穿越 + 锁字典被滥用
    with global_lock:
        if chat_id not in chat_locks:
            chat_locks[chat_id] = threading.Lock()
    with chat_locks[chat_id]:
        yield

def get_chat_path(chat_id):
    """获取具体对话文件的绝对路径（已做 chat_id 校验）"""
    chat_id = sanitize_chat_id(chat_id)
    return os.path.join(CHATS_DIR, f"{chat_id}.json")

def load_chat_data(chat_id):
    """读取对话内容，若不存在则返回空列表；若 JSON 损坏则隔离并返回空列表"""
    path = get_chat_path(chat_id)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            try:
                os.replace(path, path + ".corrupt")
            except Exception:
                pass
            return []
    return []


# --- 路由接口 ---

@app.route('/')
def index():
    """主页面"""
    return render_template('index.html')

@app.route('/api/list_chats', methods=['GET'])
def list_chats():
    """获取所有已保存的对话列表（左侧侧边栏使用）"""
    files = [f[:-5] for f in os.listdir(CHATS_DIR) if f.endswith('.json')]

    return jsonify({"chats": files})
@app.route('/api/get_history', methods=['POST'])
def get_history():
    """加载特定对话的历史记录"""
    req_data = request.get_json(silent=True) or {}
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    history = load_chat_data(chat_id)
    return jsonify({"history": history})

@app.route('/api/summarize_memory', methods=['POST'])
def summarize_memory():
    """浓缩逻辑：保护永久记忆，只对 临时记忆+旧浓缩 进行递归浓缩"""
    req_data = request.get_json(silent=True) or {}
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    history = load_chat_data(chat_id)

    to_summary_list = [
        m for m in history
        if m.get('is_memory', True) and (m.get('memory_type', 1) == 1 or m.get('role') == 'summary')
    ]

    text_to_summarize = "\n".join([f"{m['role']}: {m['content']}" for m in to_summary_list])
    if not text_to_summarize:
        return jsonify({"error": "当前没有可浓缩的临时记忆"}), 400

    try:
        # 1) 选择预设
        preset_key = (req_data.get("preset_key") or "truth_table").strip()
        preset = MEMORY_SUMMARY_PRESETS.get(preset_key)
        if not preset:
            return jsonify({
                "error": "非法 preset_key",
                "available_presets": [{"key": k, "name": v.get("name", k)} for k, v in MEMORY_SUMMARY_PRESETS.items()]
            }), 400

        # 2) 构造 prompt（模板不下发给前端，只在后端拼）
        template = preset.get("template", "")
        prompt = template.replace("<<INPUT>>", text_to_summarize)

        # 3) 模型与 provider 选择逻辑保持你原样
        api_type = req_data.get('api_type', 'google')
        api_key_index = req_data.get('api_key_index', None)

        model_name = req_data.get('model')
        if not model_name:
            if api_type == "google":
                model_name = 'gemini-3-flash-preview'
            else:
                model_name = PROVIDER_SPECS[ProviderType.OPENAI].default_model

        provider = get_provider(api_type, int(api_key_index) if api_key_index is not None else None)
        summary_text = provider.generate_text(model=model_name, prompt=prompt)

        return jsonify({
            "summary_proposal": summary_text,
            "used_preset_key": preset_key,
            "used_preset_name": preset.get("name", preset_key),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/confirm_summary', methods=['POST'])
def confirm_summary():
    """确认浓缩：将参与总结的消息设为遗忘(永久记忆除外)，并存入新浓缩"""
    req_data = request.get_json(silent=True) or {}
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    final_summary = req_data.get('summary') or ""
    if not isinstance(final_summary, str) or not final_summary.strip():
        return jsonify({"error": "summary 不能为空"}), 400

    with get_chat_lock(chat_id):
        history = load_chat_data(chat_id)

        for m in history:
            if m.get('memory_type', 1) == 1 or m.get('role') == 'summary':
                m['is_memory'] = False

        history.append({
            "role": "summary",
            "content": f"{final_summary}",
            "is_memory": True,
            "memory_type": 1
        })

        save_chat_data(chat_id, history)

    return jsonify({"success": True, "history": history})

@app.route('/api/get_permanent_memory', methods=['GET'])
def get_permanent_memory():
    chat_id = request.args.get('chat_id')
    if not chat_id:
        return jsonify({"permanent_memory": []})

    try:
        chat_id = sanitize_chat_id(chat_id)
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    history = load_chat_data(chat_id)
    perm_list = [m for m in history if m.get('memory_type') == 2]
    return jsonify({"permanent_memory": perm_list})

@app.route('/api/update_message', methods=['POST'])
def update_message():
    """直接编辑单条消息的内容（用于永久记忆的实时修正）"""
    req_data = request.get_json(silent=True) or {}

    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
        index = parse_index(req_data.get('index'))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

    new_content = req_data.get('content')
    if not isinstance(new_content, str):
        return jsonify({"success": False, "error": "content 必须是字符串"}), 400

    with get_chat_lock(chat_id):
        history = load_chat_data(chat_id)
        if 0 <= index < len(history):
            history[index]['content'] = new_content
            save_chat_data(chat_id, history)
            return jsonify({"success": True})

    return jsonify({"success": False, "error": "Index error"}), 400


@app.route('/api/get_models', methods=['GET'])
def get_models():
    api_type = request.args.get('api_type', 'google')
    api_key_index = request.args.get('api_key_index', None)

    try:
        provider = get_provider(api_type, int(api_key_index) if api_key_index is not None else None)
        return jsonify({"models": provider.list_models()})
    except Exception as e:
        print(f"Model Error: {e}")
        # 保底：返回 provider 的默认模型，避免前端下拉框空白
        try:
            spec = PROVIDER_SPECS[ProviderType(api_type)]
            return jsonify({"models": [{"id": spec.default_model, "display": spec.default_model}]})
        except Exception:
            return jsonify({"models": [{"id": "gemini-2.0-flash-exp", "display": "Gemini (fallback)"}]})


# --- 核心逻辑：档案管理 ---

@app.route('/api/toggle_memory', methods=['POST'])
def toggle_memory():
    req_data = request.get_json(silent=True) or {}

    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
        index = parse_index(req_data.get('index'))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

    mode = req_data.get('mode', 'status')

    with get_chat_lock(chat_id):
        history = load_chat_data(chat_id)
        if 0 <= index < len(history):
            if mode == 'status':
                current_status = history[index].get('is_memory', True)
                new_status = not current_status
                history[index]['is_memory'] = new_status
                if new_status is False and history[index].get('memory_type') == 2:
                    history[index]['memory_type'] = 1
            elif mode == 'type':
                current_type = history[index].get('memory_type', 1)
                history[index]['memory_type'] = 2 if current_type == 1 else 1
                if history[index]['memory_type'] == 2:
                    history[index]['is_memory'] = True
            else:
                return jsonify({"success": False, "error": "非法 mode"}), 400

            save_chat_data(chat_id, history)
            return jsonify({"success": True, "item": history[index]})

    return jsonify({"success": False}), 400



# --- 在路由接口区域添加 ---

@app.route('/api/rename_chat', methods=['POST'])
def rename_chat():
    """重命名对话（实际是重命名 JSON 文件）"""
    req_data = request.get_json(silent=True) or {}
    old_id = req_data.get('old_chat_id')
    new_id = req_data.get('new_chat_id')

    try:
        old_id = sanitize_chat_id(old_id)
        new_id = sanitize_chat_id(new_id)
    except Exception:
        return jsonify({"error": "非法的 chat_id"}), 400

    if old_id == new_id:
        return jsonify({"error": "新旧名称不能相同"}), 400

    # 避免双锁死锁：按字典序加锁
    a, b = sorted([old_id, new_id])

    with get_chat_lock(a):
        with get_chat_lock(b):
            with file_lock:
                old_path = get_chat_path(old_id)
                new_path = get_chat_path(new_id)

                if not os.path.exists(old_path):
                    return jsonify({"error": "原对话不存在"}), 404
                if os.path.exists(new_path):
                    return jsonify({"error": "该名称已存在，请换一个"}), 409

                try:
                    os.replace(old_path, new_path)  # 原子替换（比 rename 更稳）
                    return jsonify({"success": True})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
@app.route('/api/delete_chat', methods=['POST'])
def delete_chat():
    """删除整个对话列表"""
    req_data = request.get_json(silent=True) or {}
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    with get_chat_lock(chat_id):
        with file_lock:
            path = get_chat_path(chat_id)
            if os.path.exists(path):
                try:
                    os.remove(path)
                    return jsonify({"success": True})
                except Exception as e:
                    return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": False}), 404



# --- 在 appnb.py 路由区域添加 ---

@app.route('/api/add_permanent_memory', methods=['POST'])
def add_permanent_memory():
    """直接新增一条永久记忆"""
    req_data = request.get_json(silent=True) or {}
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    content = req_data.get('content')
    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "内容不能为空"}), 400

    with get_chat_lock(chat_id):
        history = load_chat_data(chat_id)
        new_memory = {
            "role": "user",
            "content": content,
            "is_memory": True,
            "memory_type": 2
        }
        history.append(new_memory)
        save_chat_data(chat_id, history)

    return jsonify({"success": True, "history": history})


@app.route('/api/delete_message', methods=['POST'])
def delete_message():
    """物理删除某条特定的消息/记忆"""
    req_data = request.get_json(silent=True) or {}
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
        index = parse_index(req_data.get('index'))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    with get_chat_lock(chat_id):
        history = load_chat_data(chat_id)
        if 0 <= index < len(history):
            del history[index]
            save_chat_data(chat_id, history)
            return jsonify({"success": True})

    return jsonify({"error": "索引无效"}), 400



@app.route('/api/chat', methods=['POST'])
def chat_endpoint():
    # 流式请求里 Content-Type 可能不稳定：用 silent=True 避免直接抛异常
    req_data = request.get_json(silent=True) or {}

    api_type = req_data.get('api_type', 'google')
    api_key_index_raw = req_data.get('api_key_index', None)
    try:
        api_key_index = int(api_key_index_raw) if api_key_index_raw not in (None, "") else None
    except Exception:
        api_key_index = None

    # 校验 provider，避免 ProviderType(api_type) 直接 500
    try:
        ptype = ProviderType(api_type)
    except Exception:
        return jsonify({
            "error": f"Unsupported api_type: {api_type}",
            "allowed": [e.value for e in ProviderType],
        }), 400

    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    user_input = req_data.get('message') or ""
    attachments = req_data.get('attachments', []) or []

    # 模型：优先用前端传入；否则用该 provider 的默认模型
    model_name = req_data.get('model') or PROVIDER_SPECS[ptype].default_model

    # 1) 处理附件：转存磁盘
    processed_attachments = []

    # 限制附件数量，避免 DoS
    if not isinstance(attachments, list):
        attachments = []
    attachments = attachments[:MAX_ATTACHMENT_COUNT]

    for att in attachments:
        if not isinstance(att, dict):
            continue

        # 新上传：带 data（base64 或 data url）
        if 'data' in att and att.get('mime_type'):
            filename = save_attachment_to_disk(att['data'], att['mime_type'])
            if filename:
                processed_attachments.append({
                    "name": att.get('name', filename),
                    "mime_type": att['mime_type'],
                    "file_path": filename,
                    "size": len(att.get('data') or ""),
                })

        # 历史回放：只带 file_path（必须校验，防止任意文件读取）
        elif 'file_path' in att and att.get('mime_type'):
            try:
                safe_fp = sanitize_upload_fp(att.get('file_path'))
            except Exception:
                continue

            processed_attachments.append({
                "name": att.get("name", safe_fp),
                "mime_type": att.get("mime_type"),
                "file_path": safe_fp,
                "size": att.get("size", 0),
            })

    # 2) 准备上下文（读文件只用于构建 prompt，不改写，所以不加 chat_lock）
    history = load_chat_data(chat_id)

    # 2.1 System Instruction（永久记忆）
    perm_mems = [m for m in history if m.get("is_memory") and m.get("memory_type") == 2]
    system_instruction_text = ""
    if perm_mems:
        system_instruction_text = "以下是核心记忆与设定：\n" + "\n".join(
            [f"- {m.get('content', '')}" for m in perm_mems]
        )

    # 2.2 需要带入的对话（summary + 临时记忆）
    summary_mems = [m for m in history if m.get("is_memory") and m.get("role") == "summary"]
    recent_mems = [
        m for m in history
        if m.get("is_memory") and m.get("memory_type", 1) == 1 and m.get("role") != "summary"
    ]

    # 归一化 messages：交给 Provider 自己转成 Gemini / OpenAI 输入结构
    messages = []
    for m in (summary_mems + recent_mems):
        role = "assistant" if m.get("role") in ("model", "summary") else "user"
        messages.append({
            "role": role,
            "content": m.get("content", ""),
            "attachments": m.get("attachments", []),
        })

    # 当前用户消息（带本轮附件）
    messages.append({
        "role": "user",
        "content": user_input,
        "attachments": processed_attachments,
    })

    provider = get_provider(api_type, api_key_index)

   # ...existing code... (保持不变直到 provider = get_provider 那行)
    
    # 新增：获取思考模式开关
    thinking_enabled = bool(req_data.get('thinking', False))
    
    provider = get_provider(api_type, api_key_index)
    
    # 构建 options
    options = {"thinking": thinking_enabled} if thinking_enabled else None

    def generate():
        full_ai_response = ""
        reasoning_content = ""
        
        try:
            for event in provider.stream_chat(
                model=model_name,
                messages=messages,
                system=system_instruction_text if system_instruction_text else None,
                upload_folder=UPLOAD_FOLDER,
                options=options,
            ):
                # 处理不同类型的事件
                if isinstance(event, dict):
                    evt_type = event.get("type", "")
                    text = event.get("text", "")
                    
                    if evt_type == "content_delta":
                        full_ai_response += text
                        yield f"data: {json.dumps({'type': 'content', 'text': text})}\n\n"
                    elif evt_type == "reasoning_delta":
                        reasoning_content += text
                        yield f"data: {json.dumps({'type': 'reasoning', 'text': text})}\n\n"
                    elif evt_type == "error":
                        yield f"data: {json.dumps({'type': 'error', 'text': text})}\n\n"
                elif isinstance(event, str):
                    # 兼容旧的字符串返回
                    full_ai_response += event
                    yield f"data: {json.dumps({'type': 'content', 'text': event})}\n\n"
                    
        except Exception as e:
            error_msg = f"\n[System Error: {str(e)}]"
            full_ai_response += error_msg
            yield f"data: {json.dumps({'type': 'error', 'text': error_msg})}\n\n"
            
        finally:
            # Atomic Save
            try:
                with get_chat_lock(chat_id):
                    with file_lock:
                        path = get_chat_path(chat_id)
                        current_history = []
                        if os.path.exists(path):
                            try:
                                with open(path, 'r', encoding='utf-8') as f:
                                    current_history = json.load(f)
                            except json.JSONDecodeError:
                                try:
                                    os.replace(path, path + ".corrupt")
                                except Exception:
                                    pass
                                current_history = []

                        # 追加用户消息
                        current_history.append({
                            "role": "user",
                            "content": user_input,
                            "attachments": processed_attachments,
                            "is_memory": True,
                            "api_type": api_type,
                            "model": model_name,
                        })

                        # 追加 AI 回复（包含 reasoning_content）
                        if full_ai_response.strip():
                            ai_msg = {
                                "role": "model",
                                "content": full_ai_response,
                                "is_memory": True,
                                "api_type": api_type,
                                "model": model_name,
                            }
                            if reasoning_content:
                                ai_msg["reasoning_content"] = reasoning_content
                            current_history.append(ai_msg)

                        temp_path = path + ".tmp"
                        with open(temp_path, 'w', encoding='utf-8') as f:
                            json.dump(current_history, f, ensure_ascii=False, indent=2)
                        os.replace(temp_path, path)
            except Exception as e:
                print(f"Save error: {e}")
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(stream_with_context(generate()), content_type='text/event-stream; charset=utf-8')


# ...existing code... (在 get_api_keys 路由之前添加)

# =========================================================
# 思考模式能力检测接口
# =========================================================
from llm_providers import get_model_capabilities

@app.route('/api/get_model_capabilities', methods=['GET'])
def get_model_capabilities_endpoint():
    """检测指定模型是否支持思考模式"""
    api_type = request.args.get('api_type', 'google')
    model = request.args.get('model', '')
    
    try:
        caps = get_model_capabilities(api_type, model)
        return jsonify(caps)
    except Exception as e:
        return jsonify({
            "supports_thinking": False,
            "supports_reasoning_output": False,
            "thinking_mode": None,
            "reason": str(e)
        })


# =========================================================
# 重新生成单条消息接口
# =========================================================
@app.route('/api/regenerate_message', methods=['POST'])
def regenerate_message():
    """重新生成指定索引的 AI 回复（只使用该消息之前的上下文）"""
    req_data = request.get_json(silent=True) or {}
    
    api_type = req_data.get('api_type', 'google')
    api_key_index_raw = req_data.get('api_key_index', None)
    try:
        api_key_index = int(api_key_index_raw) if api_key_index_raw not in (None, "") else None
    except Exception:
        api_key_index = None
    
    try:
        ptype = ProviderType(api_type)
    except Exception:
        return jsonify({"error": f"Unsupported api_type: {api_type}"}), 400
    
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
        target_index = parse_index(req_data.get('index'))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    
    model_name = req_data.get('model') or PROVIDER_SPECS[ptype].default_model
    thinking_enabled = bool(req_data.get('thinking', False))
    
    # 读取历史
    history = load_chat_data(chat_id)
    
    if target_index < 0 or target_index >= len(history):
        return jsonify({"error": "索引无效"}), 400
    
    target_msg = history[target_index]
    
    # 只能重新生成 AI 消息（model/summary）
    if target_msg.get('role') not in ('model', 'assistant'):
        return jsonify({"error": "只能重新生成 AI 回复"}), 400
    
    # 构建上下文：只取目标索引之前的消息
    context_history = history[:target_index]
    
    # System Instruction（永久记忆）
    perm_mems = [m for m in context_history if m.get("is_memory") and m.get("memory_type") == 2]
    system_instruction_text = ""
    if perm_mems:
        system_instruction_text = "以下是核心记忆与设定：\n" + "\n".join(
            [f"- {m.get('content', '')}" for m in perm_mems]
        )
    
    # 构建消息列表（summary + 临时记忆）
    summary_mems = [m for m in context_history if m.get("is_memory") and m.get("role") == "summary"]
    recent_mems = [
        m for m in context_history
        if m.get("is_memory") and m.get("memory_type", 1) == 1 and m.get("role") != "summary"
    ]
    
    messages = []
    for m in (summary_mems + recent_mems):
        role = "assistant" if m.get("role") in ("model", "summary") else "user"
        messages.append({
            "role": role,
            "content": m.get("content", ""),
            "attachments": m.get("attachments", []),
        })
    
    if not messages:
        return jsonify({"error": "没有足够的上下文来重新生成"}), 400
    
    provider = get_provider(api_type, api_key_index)
    
    # 构建 options
    options = {"thinking": thinking_enabled} if thinking_enabled else None
    
    def generate():
        full_ai_response = ""
        reasoning_content = ""
        
        try:
            for event in provider.stream_chat(
                model=model_name,
                messages=messages,
                system=system_instruction_text if system_instruction_text else None,
                upload_folder=UPLOAD_FOLDER,
                options=options,
            ):
                if isinstance(event, dict):
                    evt_type = event.get("type", "")
                    text = event.get("text", "")
                    
                    if evt_type == "content_delta":
                        full_ai_response += text
                        yield f"data: {json.dumps({'type': 'content', 'text': text})}\n\n"
                    elif evt_type == "reasoning_delta":
                        reasoning_content += text
                        yield f"data: {json.dumps({'type': 'reasoning', 'text': text})}\n\n"
                    elif evt_type == "error":
                        yield f"data: {json.dumps({'type': 'error', 'text': text})}\n\n"
                elif isinstance(event, str):
                    full_ai_response += event
                    yield f"data: {json.dumps({'type': 'content', 'text': event})}\n\n"
                    
        except Exception as e:
            error_msg = f"[Error: {str(e)}]"
            yield f"data: {json.dumps({'type': 'error', 'text': error_msg})}\n\n"
            
        finally:
            # 更新历史记录中的目标消息
            try:
                with get_chat_lock(chat_id):
                    current_history = load_chat_data(chat_id)
                    if 0 <= target_index < len(current_history):
                        # 更新内容
                        current_history[target_index]["content"] = full_ai_response
                        current_history[target_index]["api_type"] = api_type
                        current_history[target_index]["model"] = model_name
                        
                        # 如果有思维内容，也保存
                        if reasoning_content:
                            current_history[target_index]["reasoning_content"] = reasoning_content
                        elif "reasoning_content" in current_history[target_index]:
                            del current_history[target_index]["reasoning_content"]
                        
                        save_chat_data(chat_id, current_history)
                        
            except Exception as e:
                print(f"Save regenerated message error: {e}")
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
    
    return Response(stream_with_context(generate()), content_type='text/event-stream; charset=utf-8')


@app.route('/api/ai_discuss', methods=['POST'])
def ai_discuss():
    req_data = request.get_json(silent=True) or {}

    # 1. 基础校验
    try:
        chat_id = sanitize_chat_id(req_data.get('chat_id'))
    except Exception:
        return jsonify({"error": "非法 chat_id"}), 400

    participants = req_data.get('participants', [])
    if not isinstance(participants, list) or not participants:
        return jsonify({"error": "participants 不能为空"}), 400

    try:
        rounds = int(req_data.get('rounds', 1))
    except Exception:
        rounds = 1
    rounds = max(1, min(rounds, 20))

    thinking_enabled = bool(req_data.get('thinking', False))
    options = {"thinking": True} if thinking_enabled else None

    # 获取 Seed Prompt
    # 核心思想：Seed Prompt 是唯一的指挥棒。
    # 如果用户留空，给一个最中性的默认值。
    seed_prompt = req_data.get("seed_prompt")
    if not isinstance(seed_prompt, str) or not seed_prompt.strip():
        seed_prompt = "请根据上下文继续。"

    # =========================
    # 2. 上下文加载
    # =========================
    history = load_chat_data(chat_id)

    def remembered(m: dict) -> bool:
        return bool(m.get("is_memory", True))

    perm_mems = [m for m in history if remembered(m) and m.get("memory_type") == 2]
    summary_mems = [m for m in history if remembered(m) and m.get("role") == "summary"]
    recent_mems = [
        m for m in history
        if remembered(m) and m.get("role") != "summary" and m.get("memory_type", 1) == 1
    ]

    perm_text = "\n\n".join([m.get("content", "") for m in perm_mems if m.get("content")])

    # =========================
    # 3. 核心优化：System Prompt 归零化 / 中性化
    #    不再植入“协作、纠错、讨论”等预设立场。
    #    只保留永久记忆（World Info / Character Settings）和最基础的身份认知。
    # =========================

    # 基础元指令：只强调上下文连续性，不干涉输出风格
    base_instruction = (
        "你正在参与一个多模型接力任务。\n"
        "请阅读上方的历史记录（包含了用户和其他模型的发言），并严格执行用户最新的指令。"
    )

    if perm_text.strip():
        # 如果有永久记忆（通常是 RPG 的世界观、角色设定），必须放在 System Prompt
        system_instruction_text = f"【核心设定/永久记忆】\n{perm_text.strip()}\n\n{base_instruction}"
    else:
        system_instruction_text = base_instruction

    # 组装基础上下文
    messages_base = []
    for m in (summary_mems + recent_mems):
        raw_role = m.get("role", "user")
        # 保持角色映射，让模型知道哪些是 User 说的，哪些是 AI 队友说的
        role = "assistant" if raw_role in ("model", "summary", "assistant") else "user"
        messages_base.append({
            "role": role,
            "content": m.get("content", ""),
            "attachments": m.get("attachments", []) or []
        })

    # =========================
    # 4. SSE 与 存储逻辑 (保持稳健)
    # =========================
    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def append_message_to_disk(msg_obj: dict):
        with get_chat_lock(chat_id):
            with file_lock:
                path = get_chat_path(chat_id)
                current_history = []
                if os.path.exists(path):
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            current_history = json.load(f)
                    except Exception:
                        current_history = []

                current_history.append(msg_obj)

                temp_path = path + ".tmp"
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(current_history, f, ensure_ascii=False, indent=2)
                os.replace(temp_path, path)

    # =========================
    # 5. 核心优化：User Prompt (中性容器)
    #    只提供必要的元数据（为了防止模型不知道轮到自己了），
    #    然后直接拼接 Seed Prompt。
    # =========================
    def build_iteration_prompt(round_no: int, total_rounds: int, api_type: str, model_name: str) -> str:
        # 使用 XML tag 风格或方括号风格标记元数据，使其与正文指令隔离
        # 这样模型能区分 "我是谁" 和 "我要做什么"
        return (
            f"[System Meta: Current Model: {model_name} | Round: {round_no}/{total_rounds}]\n\n"
            f"{seed_prompt.strip()}"
        )

    def generate():
        total_steps = rounds * len(participants)
        yield sse({
            "type": "ai_discuss_meta",
            "rounds": rounds,
            "total_steps": total_steps,
            "participants": participants
        })

        step_no = 0
        nonlocal_messages_base = messages_base

        for r in range(rounds):
            for p in participants:
                step_no += 1

                api_type = p.get("api_type", "google")
                model_name = p.get("model", "") or ""
                api_key_index = p.get("api_key_index")
                try:
                    if api_key_index not in (None, ""):
                        api_key_index = int(api_key_index)
                    else:
                        api_key_index = None
                except:
                    api_key_index = None

                if not model_name:
                    yield sse({"type": "error", "text": f"Skip: Missing model for {api_type}", "fatal": False})
                    continue

                yield sse({
                    "type": "message_start",
                    "round": r + 1,
                    "step": step_no,
                    "api_type": api_type,
                    "model": model_name
                })

                # 前缀：为了在 UI 上区分是谁在说话（建议保留，否则多模型接力看不出谁是谁）
                prefix = f"**[{model_name}]**\n\n"
                yield sse({"type": "content", "text": prefix})

                # 构建本次请求的消息
                local_msgs = list(nonlocal_messages_base)

                # 【关键】把 Seed 当作当前 User 的最新指令
                local_msgs.append({
                    "role": "user",
                    "content": build_iteration_prompt(r + 1, rounds, api_type, model_name),
                    "attachments": []
                })

                full_text = ""
                reasoning_text = ""

                try:
                    provider = get_provider(api_type, api_key_index)
                    for event in provider.stream_chat(
                            model=model_name,
                            messages=local_msgs,
                            system=system_instruction_text,  # 极简 System Prompt
                            upload_folder=UPLOAD_FOLDER,
                            options=options,
                    ):
                        if isinstance(event, dict):
                            evt_type = event.get("type", "")
                            text = event.get("text", "")
                            if evt_type == "content_delta":
                                full_text += text
                                yield sse({"type": "content", "text": text})
                            elif evt_type == "reasoning_delta":
                                reasoning_text += text
                                yield sse({"type": "reasoning", "text": text})
                            elif evt_type == "error":
                                yield sse({"type": "error", "text": text, "fatal": False})
                        elif isinstance(event, str):
                            full_text += event
                            yield sse({"type": "content", "text": event})

                except Exception as e:
                    err = f"\n[Error: {str(e)}]"
                    full_text += err
                    yield sse({"type": "error", "text": err, "fatal": False})

                # 结果处理
                body = full_text.strip() if full_text.strip() else "[无内容]"
                final_content = prefix + body

                msg_obj = {
                    "role": "model",
                    "content": final_content,
                    "is_memory": True,  # 默认为临时记忆
                    "api_type": api_type,
                    "model": model_name,
                }
                if reasoning_text.strip():
                    msg_obj["reasoning_content"] = reasoning_text

                # 将当前模型输出加入上下文，供下一个模型可见
                # 这样实现了：Model A 讲一段 -> Model B 看到后接着讲 -> Model C 看到后...
                nonlocal_messages_base.append({
                    "role": "assistant",
                    "content": final_content,
                    "attachments": []
                })

                try:
                    append_message_to_disk(msg_obj)
                except Exception as e:
                    yield sse({"type": "error", "text": f"Save Failed: {str(e)}", "fatal": True})
                    return

                yield sse({"type": "message_done"})

        yield sse({"type": "done"})

    resp = Response(stream_with_context(generate()), content_type='text/event-stream; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp

# ...existing code... (get_api_keys 路由)
@app.route('/api/get_api_keys', methods=['GET'])
def get_api_keys():
    api_type = request.args.get('api_type', 'google')

    # 防止传入未知 provider 直接炸
    try:
        ProviderType(api_type)
    except Exception:
        return jsonify({"keys": []})

    try:
        keys = key_manager.list_key_meta(api_type)
        return jsonify({"keys": keys})
    except Exception:
        return jsonify({"keys": []})

if __name__ == '__main__':
    # 允许局域网访问，这样你也可以用电脑浏览器访问手机的 IP
    app.run(host='0.0.0.0', port=5000, debug=True)
