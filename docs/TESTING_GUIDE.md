# TaskFlow 测试指南

## 快速开始

### 后端测试

```bash
cd backend

# 使用虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Mac/Linux
# venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 运行所有测试
pytest tests/ -v

# 运行指定模块测试
pytest tests/test_auth.py -v
pytest tests/test_tasks.py -v

# 生成覆盖率报告
pytest tests/ --cov=app --cov-report=html
```

### 移动端测试

```bash
cd mobile

# 安装依赖
flutter pub get

# 运行所有测试
flutter test

# 运行指定测试
flutter test test/login_screen_test.dart

# 生成覆盖率
flutter test --coverage
```

---

## 测试文件结构

### 后端 (`backend/tests/`)

| 文件 | 描述 | 用例数 |
|------|------|--------|
| `conftest.py` | pytest配置、fixtures、测试数据库 | - |
| `test_auth.py` | 认证功能测试 | 6 |
| `test_tasks.py` | 任务管理API测试 | 13 |
| `test_employees.py` | 员工管理API测试 | 7 |
| `test_messages.py` | 消息系统API测试 | 7 |
| `test_health.py` | 健康检查测试 | 2 |
| `test_api.py` | API端点测试 | 4 |
| `test_models.py` | 模型和枚举测试 | 10 |
| **总计** | | **49** |

### 移动端 (`mobile/test/`)

| 文件 | 描述 | 用例数 |
|------|------|--------|
| `login_screen_test.dart` | 登录界面测试 | 7 |
| `tasks_screen_test.dart` | 任务列表测试 | 8 |
| `recording_service_test.dart` | 录音服务测试 | 4 |
| **总计** | | **19** |

---

## 测试用例覆盖

### 后端API覆盖

- [x] 登录认证
- [x] JWT Token验证
- [x] 任务CRUD
- [x] 任务状态流转
- [x] 员工管理
- [x] 消息系统
- [x] 健康检查

### 待添加

- [ ] 声纹管理API
- [ ] 会议上传API
- [ ] 定时任务单元测试
- [ ] Celery任务测试

### 移动端覆盖

- [x] 登录界面
- [x] 任务列表界面
- [x] 录音服务

### 待添加

- [ ] 首页界面
- [ ] 录音界面
- [ ] 消息列表界面
- [ ] 员工管理界面
- [ ] 声纹管理界面
- [ ] 上传队列界面

---

## CI/CD 集成

### GitHub Actions 示例

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  backend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
      - name: Run tests
        run: pytest tests/ -v

  mobile-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.16.0'
      - name: Install dependencies
        run: cd mobile && flutter pub get
      - name: Run tests
        run: cd mobile && flutter test
```

---

## 测试最佳实践

1. **单元测试**: 测试单个函数/方法的逻辑
2. **集成测试**: 测试多个组件的协作
3. **E2E测试**: 测试完整的用户流程
4. **Mock外部依赖**: 数据库、外部API等
5. **保持测试独立**: 每个测试可以独立运行
6. **清晰的测试命名**: `test_功能_场景_预期结果`

---

## 常见问题

### Q: 测试数据库如何配置?

使用 `tests/conftest.py` 中的 SQLite 内存数据库，无需额外配置。

### Q: 外部服务不可用怎么办?

后端测试使用 Mock 模式，通过设置 `MOCK_ASR=true` 跳过外部依赖。

### Q: 如何运行特定测试?

```bash
# 后端: 按文件名
pytest tests/test_auth.py::TestAuth::test_login_success -v

# 移动端: 按描述
flutter test --name "登录界面显示正确"
```
