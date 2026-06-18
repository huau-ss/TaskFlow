#!/bin/bash
# Flutter 移动端测试运行脚本

echo "======================================"
echo "TaskFlow 移动端测试"
echo "======================================"

# 进入移动端目录
cd "$(dirname "$0")/.." || exit

# 检查Flutter环境
if ! command -v flutter &> /dev/null; then
    echo "错误: 未找到 flutter 命令"
    echo "请确保 Flutter SDK 已安装并配置到 PATH"
    exit 1
fi

# 显示Flutter版本
echo "Flutter 版本:"
flutter --version

# 获取依赖
echo ""
echo "获取依赖..."
flutter pub get

# 分析代码（可选）
echo ""
echo "运行静态分析..."
flutter analyze

# 运行测试
echo ""
echo "======================================"
echo "运行测试..."
echo "======================================"
flutter test

echo ""
echo "======================================"
echo "测试完成"
echo "======================================"

# 询问是否生成覆盖率报告
read -p "是否生成覆盖率报告? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "生成覆盖率报告..."
    flutter test --coverage
    echo "覆盖率报告生成完成"
fi
