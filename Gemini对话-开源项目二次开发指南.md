# 开源项目二次开发指南

> **来源：** Google Gemini 共享对话  
> **链接：** https://gemini.google.com/share/c886af31ea19  
> **模型：** Gemini 3.1 Flash-Lite  
> **创建时间：** 2026年6月16日 23:20  
> **发布时间：** 2026年6月16日 23:30  

---

## 目录

1. [第一轮：语音驱动的自动化任务协同系统](#第三轮语音驱动的自动化任务协同系统)
2. [第二轮：打包为 APK 的技术方案](#第四轮打包为-apk-的技术方案)
3. [第三轮：系统架构设计](#第五轮系统架构设计)
4. [第四轮：数据库设计与 Agent 框架](#第六轮数据库设计与-agent-框架)

---


## 第一轮：语音驱动的自动化任务协同系统

### 👤 用户提问

> 在 app 里添加一个录音的功能，音频可以先保存到本地，然后调用一个 ai 进行声纹分析，随后这个音频可以上传到公司服务器的 nas 存储中。在 ai 进行声纹分析后，可以划分不同的人群所说的话。声纹分析采用公司服务器的内置模型语音转写 (ASR): http://192.168.10.11:8001 (Whisper) 或 8002 (/api/transcribe,带声纹分离)。
>
> 同时对会议纪要进行分析，哪些人需要在什么时候完成什么事情，可以发送邮箱给那个人，同时员工需要进行回复，接受还是拒绝，并且在任务快到期时，再次对员工进行催促，如果员工回复已完成，那么则流程结束，如果员工回复未完成，则需要员工给出未完成的原因，同时将未完成的员工名称和未完成的任务以及原因再次整理成一个邮件发送给上一级领导，这个权限设定将由我来决定。同时这一整个邮件推送的过程流是否需要接入一个 agent。

### 🤖 Gemini 回答

这是一个非常完整且具有实际商业价值的业务场景——**"基于语音驱动的自动化任务协同系统"**。

#### 1. 架构方案拆解

**前端 (App)：** 负责录音、本地持久化存储、调用后端 API 及展示任务状态。

**后端 API 服务 (核心调度)：**
- 处理音频：调用 `http://192.168.10.11:8002` 进行声纹分离和语音转写
- 语义解析 (NLP)：提取会议纪要中的"任务、责任人、截止时间"
- 任务管理与状态机：记录任务 ID、执行人、截止时间、当前状态
- 通知与反馈引擎：负责邮件发送、催促逻辑、向上级汇报

#### 2. 这个流程需要 Agent 吗？

**结论：非常需要，且推荐将其设计为系统的大脑。**

- **动态任务提取：** LLM 能比正则表达式更准确地识别非结构化语言
- **智能催办与对话上下文：** 分析员工回复是否合理，自动调整任务状态
- **灵活的汇报逻辑：** 根据设定的权限自动总结汇总邮件

#### 3. 系统逻辑实现关键点

**A. 权限与关系映射**
- 维护组织架构表，对接公司 LDAP 或钉钉/企微
- `Map<Task_ID, Executor>` → `Map<Executor, Manager>`

**B. 邮件推送与闭环流程**
- 邮件中嵌入"确认完成"和"申请延期/未完成"的 Action Buttons (URL Link)
- 员工点击链接后触发 API 调用回写状态
- 设置 Cron Job 定时扫描任务数据库触发催促邮件

#### 4. 推荐技术开发路线

| 层级 | 技术选型 |
|------|----------|
| **后端** | FastAPI (Python) |
| **AI 处理** | LangChain 或 LlamaIndex 编排 Agent |
| **数据存储** | NAS（音频）+ PostgreSQL（任务/权限/状态） |
| **Agent 框架** | LangGraph（适合状态转移业务逻辑） |

> **后续建议：** 你可以先从"语音转文字并自动提取任务"这个最小闭环开始做。

---

## 第二轮：打包为 APK 的技术方案

### 👤 用户提问

> 这可以做成一个 app 吗，打包成 apk 文件

### 🤖 Gemini 回答

当然可以，建议采用 **Hybrid（混合）开发模式**——前端用跨平台框架实现，后端通过 API 与服务器交互。

#### 1. 技术架构选型

| 层级 | 推荐方案 |
|------|----------|
| **前端开发框架** | **Flutter**（处理音频录制、文件流式传输和跨平台 UI 适配表现优秀） |
| **后端开发** | FastAPI (Python) |
| **构建工具** | Gradle（配合 Flutter 原生构建流程） |

#### 2. 实现 APK 的核心步骤

**第一步：App 端功能实现**
- 录音：使用 `record` (Flutter) 或 `expo-av` (React Native) 插件
- 文件存储：通过 `dio` 或 `http` 库上传到公司服务器后端，处理断点续传
- API 交互：发起 HTTP POST 请求到 `http://192.168.10.11:8002`

**第二步：服务器端处理逻辑**
- 接收 App 音频，保存至 NAS 挂载路径
- 调用公司 AI 接口进行声纹分离与转写
- Agent 利用 LLM 提取 JSON 结构化数据，写入数据库并通过 SMTP 发送邮件
- 员工点击邮件内链接完成任务时更新数据库状态

**第三步：打包成 APK**
- 安装 Android Studio 和 Flutter SDK
- 配置权限（`RECORD_AUDIO`, `INTERNET`, `WRITE_EXTERNAL_STORAGE`）
- 生成签名密钥（Keystore）
- 运行构建命令：`flutter build apk --release`
- 生成文件：`build/app/outputs/flutter-apk/app-release.apk`

#### 3. 避坑指南

- **不要把核心代码放在 App 里：** 所有声纹分析、ASR 转写、邮件推送逻辑全部放在公司服务器侧，App 只负责"录音"、"上传"和"展示任务看板"
- **网络权限：** 服务器是局域网地址 (192.168.10.x)，App 必须在公司 Wi-Fi 或 VPN 环境下才能工作
- **安全性：** 在后端 API 层增加 JWT 鉴权

#### 4. 下一步行动计划

1. **先跑通后端：** 写 Python 脚本测试能否调用 `http://192.168.10.11:8002`
2. **再做前端：** 找 Flutter 的"录音并上传到服务器"开源模板
3. **最后集成 Agent：** 基础流程通了再加入 Agent 逻辑

---

## 第三轮：系统架构设计

### 👤 用户提问

> 你先帮我给出这个项目的架构

### 🤖 Gemini 回答

采用**"端侧瘦、服务端厚"**的原则，确保手机端仅作为交互入口。

#### 项目架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                  1. 终端应用层 (Mobile App)                   │
│   ┌──────────┐  ┌──────────┐  ┌────────────────────────┐  │
│   │ 录音组件  │  │ 本地存储  │  │      交互看板          │  │
│   │ (原生API) │  │ (SQLite) │  │ (任务/通知/确认按钮)    │  │
│   └────┬─────┘  └────┬─────┘  └───────────┬────────────┘  │
└────────┼──────────────┼────────────────────┼───────────────┘
         │              │                    │
         ▼              ▼                    ▼
┌─────────────────────────────────────────────────────────────┐
│              2. 业务逻辑网关层 (FastAPI Backend)              │
│   ┌─────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│   │  鉴权中心    │  │  任务状态机       │  │  通知引擎     │  │
│   │ (账号体系)   │  │ (待处理→进行中→   │  │ (邮件/催办/   │  │
│   │             │  │  完成/延期)       │  │  权限判断)    │  │
│   └─────────────┘  └────────┬─────────┘  └──────┬───────┘  │
└──────────────────────────────┼──────────────────┼───────────┘
                               │                  │
                               ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│              3. AI 处理引擎层 (AI Pipeline)                   │
│   ┌──────────────────────────────────────────────┐          │
│   │  语音转写与分离 (ASR + Diarization)          │          │
│   │  → http://192.168.10.11:8002                 │          │
│   └────────────────────┬─────────────────────────┘          │
│   ┌────────────────────▼─────────────────────────┐          │
│   │  智能分析 Agent (LLM 任务提取)                │          │
│   │  责任人 / 任务描述 / 截止时间 → JSON           │          │
│   └──────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│            4. 数据与基础设施层 (Storage & Infra)               │
│   ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│   │ NAS 存储  │  │  PostgreSQL  │  │  邮件服务 (SMTP)      │  │
│   │ (原始音频) │  │ (任务/权限)  │  │  (公司内部邮件接口)   │  │
│   └──────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

#### 架构优势说明

| 特点 | 说明 |
|------|------|
| **AI 处理隔离** | 核心 AI 计算留在公司服务器，APK 体积小巧、运行流畅 |
| **模块化解耦** | 声纹模型升级或更换邮件服务商时只需修改后端 API 层 |
| **权限透明** | 权限判断由后端统一控制，无法被绕过 |

#### 架构关键交互流程

```
移动端录音 → 本地缓存 → 上传至后端 → 后端保存到 NAS
    → 调用 192.168.10.11:8002 声纹分离+ASR转写
    → LLM Agent 提取任务 → 存入 PostgreSQL
    → SMTP 发送任务邮件 → 员工回复
    → 逾期监控 → 催促 → 未完成汇报上级
```

---

## 第四轮：数据库设计与 Agent 框架

### 👤 用户提问

> 需要

### 🤖 Gemini 回答

#### 1. 数据库表结构设计 (SQL Schema)

**员工表 (employees)**
```sql
CREATE TABLE employees (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(255) UNIQUE,
    manager_id INT -- 上级领导ID
);
```

**任务表 (tasks)**
```sql
CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    title TEXT,
    description TEXT,
    deadline TIMESTAMP,
    status VARCHAR(20), -- 'pending', 'in_progress', 'completed', 'rejected', 'overdue'
    executor_id INT REFERENCES employees(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**任务回复与催促日志表 (task_updates)**
```sql
CREATE TABLE task_updates (
    id SERIAL PRIMARY KEY,
    task_id INT REFERENCES tasks(id),
    reason TEXT, -- 未完成原因
    update_type VARCHAR(20), -- 'reply', 'reminder_log'
    status_snapshot VARCHAR(20) -- 记录回复时的状态
);
```

#### 2. Agent 任务提取逻辑框架 (Python)

使用 LangChain 构建 Agent，将 ASR 转写文本转化为结构化 JSON：

```python
from langchain.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.output_parsers import ResponseSchema, StructuredOutputParser

# 1. 定义解析结构
response_schemas = [
    ResponseSchema(name="task", description="任务名称"),
    ResponseSchema(name="executor", description="责任人姓名"),
    ResponseSchema(name="deadline", description="截止日期/时间"),
]
output_parser = StructuredOutputParser.from_response_schemas(response_schemas)

# 2. 定义 Agent Prompt
prompt = PromptTemplate(
    template="分析以下会议纪要，提取出任务、责任人和截止时间。\n{format_instructions}\n会议纪要内容：{context}",
    input_variables=["context"],
    partial_variables={"format_instructions": output_parser.get_format_instructions()}
)

# 3. 模拟逻辑
def extract_tasks_agent(transcribed_text):
    # 此处调用你的 LLM 服务（如 Qwen 或 DeepSeek）
    # response = llm(prompt.format(context=transcribed_text))
    # return output_parser.parse(response)
    pass
```

#### 3. 邮件流转与 Agent 的结合

| 步骤 | 描述 |
|------|------|
| **步骤 1：触发** | 任务创建时，Agent 调用 SMTP 发送邮件，含操作链接 |
| **步骤 2：交互** | 员工点击链接，状态更新为 `completed` |
| **步骤 3：逾期监控** | 后端脚本每天运行，检查 `status == 'pending'` 且已逾期的任务，发送催促邮件；收到未完成原因后，Agent 汇总报告给上级领导 |

#### 4. 给你的行动建议

1. **先跑通"AI 提取"：** 手动把几段录音转写的文字丢进 LLM 测试，看看能否准确提取出任务、人名和时间
2. **配置公司局域网权限：** 确保公司服务器的 8002 端口允许 App 所在网段进行 POST 请求
3. **App 原型：** 如果使用 Flutter 开发，先从"录音并保存文件"这个简单的 Demo 入手

---

> *本对话由 Google Gemini (3.1 Flash-Lite) 生成，内容仅供参考。Gemini 显示的信息（包括与人相关的信息）不一定准确，请注意核查。*
