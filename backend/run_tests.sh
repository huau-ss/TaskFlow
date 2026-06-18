#!/bin/bash
# 后端测试运行脚本

echo "======================================"
echo "TaskFlow 后端测试"
echo "======================================"

# 进入后端目录
cd "$(dirname "$0")/.." || exit

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    exit 1
fi

# 创建虚拟环境（如果不存在）
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "安装依赖..."
pip install -r requirements.txt

# 运行测试
echo "运行测试..."
pytest tests/ -v --tb=short

echo "======================================"
echo "测试完成"
echo "======================================"
