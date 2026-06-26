# TaskFlow — 录音驱动任务协同系统

Monorepo containing a FastAPI backend and a Flutter mobile app。系统自动转写会议录音、通过声纹识别说话人、提取可执行任务、分析会议关联关系，并主动推送通知。

---

## 目录结构

```
app/
├── backend/               # FastAPI + Celery + LangGraph
│   ├── app/
│   │   ├── agents/       # LangGraph AI 智能体
│   │   │   ├── meeting_workflow.py      # 会议完整处理流水线
│   │   │   ├── task_extract.py          # 任务提取（含声纹融合）
│   │   │   ├── meeting_relation.py       # 会议关联分析
│   │   │   ├── task_notification.py      # 任务通知
│   │   │   └── escalation.py             # 任务升级
│   │   ├── routers/      # API 路由
│   │   │   ├── auth.py               # JWT 登录认证
│   │   │   ├── meetings.py           # 会议上传、列表、转写、任务提取、关联分析
│   │   │   ├── transcripts.py         # 转写文本 LLM 优化、HTML 导出
│   │   │   ├── tasks.py              # 任务管理（接受/拒绝/完成/标记不完）
│   │   │   ├── voiceprints.py        # 声纹注册、验证、会议说话人识别
│   │   │   ├── messages.py           # 站内消息通知
│   │   │   └── employees.py          # 员工 CRUD、管理员功能
│   │   ├── services/     # 业务逻辑服务
│   │   ├── tasks/        # Celery 异步任务
│   │   ├── models.py      # SQLAlchemy 数据模型
│   │   ├── schemas.py     # Pydantic 请求/响应模型
│   │   ├── main.py        # FastAPI 入口
│   │   ├── config.py      # 环境配置
│   │   ├── auth.py        # JWT 认证
│   │   ├── deps.py        # 依赖注入
│   │   └── database.py    # 数据库连接
│   ├── alembic/           # 数据库迁移
│   ├── tests/             # 单元测试
│   ├── scripts/           # 工具脚本
│   └── requirements.txt
├── mobile/                # Flutter 移动端（iOS + Android）
│   ├── lib/
│   │   ├── main.dart
│   │   ├── screens/       # 12 个页面
│   │   │   ├── login_screen.dart
│   │   │   ├── home_screen.dart
│   │   │   ├── meeting_detail_screen.dart
│   │   │   ├── record_screen.dart
│   │   │   ├── upload_queue_screen.dart
│   │   │   ├── tasks_screen.dart
│   │   │   ├── messages_screen.dart
│   │   │   ├── meeting_graph_screen.dart
│   │   │   ├── voice_print_management_screen.dart
│   │   │   ├── employee_management_screen.dart
│   │   │   └── me_screen.dart
│   │   └── services/
│   │       ├── api_service.dart       # Dio REST 客户端
│   │       ├── recording_service.dart # 录音服务
│   │       └── upload_queue.dart      # 离线上传队列
│   ├── pubspec.yaml
│   ├── ios/
│   └── android/
├── funasr_service/        # FunASR 语音识别服务
└── docker-compose.yml
```

---

## 系统架构

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  Flutter 移动端  │────▶│    FastAPI 后端      │────▶│   PostgreSQL    │
│  (Dio + Record) │     │  (Pydantic + LangGraph)│     │  (SQLAlchemy)  │
└─────────────────┘     └──────────┬───────────┘     └─────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
        ┌─────▼─────┐        ┌────▼────┐          ┌─────▼──────┐
        │ Celery +  │        │  FunASR  │          │  LLM API   │
        │  Redis    │        │ Service  │          │  (Qwen3)   │
        └───────────┘        └──────────┘          └────────────┘
```

---

## 快速启动

### 1. 环境准备

```bash
cp .env.example .env
# 编辑 .env，填入数据库、Redis、LLM、FunASR 等配置
docker compose up -d postgres redis
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
python scripts/seed.py              # 初始化种子数据

# 终端 1：API 服务
uvicorn app.main:app --reload --port 8000

# 终端 2：Celery Worker
celery -A app.tasks.celery_app worker --loglevel=info
```

### 3. 启动移动端

```bash
cd mobile
flutter pub get
flutter run
```

登录页配置 API 地址（Android 模拟器用 `10.0.2.2:8000`）。

### 4. 验证连接

```bash
python scripts/verify_connectivity.py
```

检测 FunASR 服务（`192.168.10.8:8005`）、LLM 接口、数据库健康状态。

---

## 核心处理流程

```
用户上传录音
    ↓
Celery: transcribe_meeting (FunASR VAD + ASR + 说话人分割 + CAM++ embedding)
    ↓
声纹匹配：Cosine Similarity 识别说话人身份
    ↓
LangGraph 流水线 (ProcessPoolExecutor 并行)
    ├─ LLM 优化转写文本（去口头禅、修正误差）
    ├─ 任务提取（声纹融合 + 姓名匹配双重路由）
    ├─ 会议关联分析（follow_up / related / prerequisite）
    ├─ HTML 报告生成
    └─ 任务通知推送
    ↓
Celery 定时任务
    ├─ 每小时：到期提醒
    ├─ 每 2 小时：逾期状态更新
    ├─ 每 4 小时：升级超期任务
    └─ 每 3 天：全局会议关联分析
```

---

## API 路由总览

### 认证 `/auth`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 邮箱密码登录，返回 JWT Token |

### 会议 `/meetings`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/meetings/upload` | 上传录音到 NAS | 登录用户 |
| GET | `/meetings` | 会议列表 | 登录用户（普通用户仅返回自己上传的，管理员返回全部） |
| GET | `/meetings/{id}` | 会议详情 | 登录用户（仅创建者或管理员） |
| GET | `/meetings/{id}/transcript` | 获取转写片段 | 登录用户（仅创建者或管理员） |
| POST | `/meetings/{id}/extract-tasks` | 触发任务提取 | 登录用户（仅创建者或管理员） |
| GET | `/meetings/{id}/tasks` | 获取会议任务列表 | 登录用户（仅创建者或管理员） |
| POST | `/meetings/{id}/retranscribe` | 重新转写 | 登录用户（仅创建者或管理员） |
| POST | `/meetings/relations/analyze` | 触发关联分析 | 登录用户（普通用户仅分析自己上传的会议） |
| GET | `/meetings/relations` | 关联列表 | 登录用户（仅与可访问会议相关的关联） |
| DELETE | `/meetings/relations/{id}` | 删除关联 | 登录用户（需持有关联中至少一个会议） |
| GET | `/meetings/graph` | 图谱数据 | 登录用户（普通用户仅看自己会议的图谱） |

### 转写 `/transcripts`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/transcripts/{id}/optimize` | LLM 优化转写文本 | 登录用户（仅创建者或管理员） |
| GET | `/transcripts/{id}/export/html` | 导出 HTML | 登录用户（仅创建者或管理员） |
| GET | `/transcripts/{id}/segments` | 获取转写片段（含说话人映射） | 登录用户（仅创建者或管理员） |

### 任务 `/tasks`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tasks` | 我的任务列表 |
| GET | `/tasks/counts` | 各状态任务数量 |
| GET | `/tasks/{id}` | 任务详情 |
| POST | `/tasks/{id}/accept` | 接受任务 |
| POST | `/tasks/{id}/reject` | 拒绝任务 |
| POST | `/tasks/{id}/complete` | 完成任务 |
| POST | `/tasks/{id}/incomplete` | 标记不完（触发升级流程） |

### 声纹 `/voiceprints`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/voiceprints/register/file` | 上传音频注册声纹 |
| POST | `/voiceprints/register/base64` | Base64 音频注册声纹 |
| POST | `/voiceprints/verify/file` | 声纹验证（文件） |
| POST | `/voiceprints/verify/base64` | 声纹验证（Base64） |
| POST | `/voiceprints/recognize-meeting/{id}` | 会议说话人重识别 |

### 消息 `/messages`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/messages` | 消息列表 |
| GET | `/messages/unread-count` | 未读数 |
| GET | `/messages/{id}` | 消息详情 |
| POST | `/messages/{id}/read` | 标记已读 |
| GET | `/messages/{id}/actions` | 消息操作记录 |

### 员工 `/employees`

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/employees` | 员工列表 | 管理员 |
| POST | `/employees` | 创建员工 | 管理员 |
| GET | `/employees/me` | 当前用户信息 | 登录用户 |
| PUT | `/employees/{id}` | 更新员工 | 管理员 |
| DELETE | `/employees/{id}` | 删除员工 | 管理员 |
| GET | `/employees/{id}/subordinates` | 下属列表 | 管理员 |
| POST | `/employees/import-csv` | CSV 批量导入 | 管理员 |

---

## 数据模型

| 模型 | 说明 |
|------|------|
| `Employee` | 员工（支持管理链、is_admin 权限） |
| `Meeting` | 会议（creator_id 记录上传者） |
| `TranscriptSegment` | 转写片段（speaker_label + employee_id 声纹识别结果） |
| `Task` | 任务（executor_id、deadline、status、match_method 声纹/姓名） |
| `TaskUpdate` | 任务状态变更历史 |
| `PermissionRule` | 升级规则（每个员工可单独配置） |
| `VoicePrint` | 声纹向量（CAM++ ecapa-tdnn 192维） |
| `Message` | 站内消息（task_created / task_reminder / task_escalation / task_response） |
| `MessageAction` | 消息操作记录（accept/reject/complete/incomplete） |
| `MeetingRelation` | 会议关联（follow_up / related / prerequisite + confidence） |

---

## Celery 定时任务

| 任务 | 周期 | 说明 |
|------|------|------|
| `transcribe_meeting` | 触发制 | FunASR 转写 + 声纹识别 + 触发 LangGraph 流水线 |
| `check_deadline_reminders` | 每 1 小时 | 24 小时内到期任务发送提醒消息 |
| `check_overdue_tasks` | 每 2 小时 | 将超期任务状态更新为 overdue |
| `escalate_long_overdue_tasks` | 每 4 小时 | 将超期 3 天以上的任务升级至直属经理 |
| `run_global_relation_analysis` | 每 3 天 | 全量会议关联分析 |
| `analyze_single_meeting_relations` | 触发制 | 新会议转写完成后，与历史会议做关联分析 |

---

## 权限模型

系统采用 **RBAC + 数据隔离** 双层权限：

- **管理员（is_admin=True）**：无限制，可访问/操作所有会议、员工、声纹数据
- **普通用户（is_admin=False）**：只能访问自己上传的会议（`creator_id == current_user.id`），其他功能（任务、消息）按 `executor_id` / `recipient_id` 隔离

```
管理员 → 可访问所有数据
普通用户 → 只能看到/操作自己上传的会议、自己被分配的任务、自己收到的消息
```

---

## 环境变量说明

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://user:pass@localhost:5432/taskflow` |
| `REDIS_URL` | Redis 连接串 | `redis://localhost:6379/0` |
| `LLM_URL` | LLM API 地址 | `http://localhost:8001/v1` |
| `LLM_API_KEY` | LLM API Key | `not-needed` |
| `LLM_MODEL` | LLM 模型名 | `Qwen3-8B` |
| `FUNASR_URL` | FunASR 服务地址 | `http://192.168.10.11:8002` |
| `NAS_PATH` | 录音文件存储目录 | `/data/meetings` |
| `JWT_SECRET` | JWT 签名密钥 | `change-me-in-production` |
| `MOCK_ASR` | 模拟 ASR（测试用） | `true` / `false` |

默认管理员账号：`admin@company.com` / `admin123`

---

## Docker 全栈启动

```bash
docker compose up --build
```

---

## 测试

```bash
cd backend
pytest tests/ -v
```

使用 `MOCK_ASR=true` 可在无 FunASR 服务的环境下测试整个 ASR 流水线。
