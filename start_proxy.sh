#!/bin/bash

echo "🚀 启动Claude to GCP代理服务器..."

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到Python3，请先安装Python"
    exit 1
fi

# 检查服务账户文件是否存在
KEY_FILE="${GCP_KEY_FILE:-key/key.json}"

if [ ! -f "$KEY_FILE" ]; then
    echo "❌ 错误: 未找到GCP服务账户文件 $KEY_FILE"
    echo "   请将凭据放置于 key/key.json 或设置 GCP_KEY_FILE 环境变量"
    exit 1
fi

# 检查requirements.txt是否存在
if [ ! -f "requirements.txt" ]; then
    echo "❌ 错误: 未找到requirements.txt文件"
    exit 1
fi

# 创建并激活虚拟环境
VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "📦 创建Python虚拟环境..."
    python3 -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "❌ 虚拟环境创建失败"
        exit 1
    fi
fi

echo "🔄 激活虚拟环境..."
source "$VENV_DIR/bin/activate"

# 检查是否需要安装依赖
HASH_FILE="$VENV_DIR/.requirements.hash"
CURRENT_HASH=$(md5sum requirements.txt 2>/dev/null | cut -d' ' -f1 || md5 -q requirements.txt 2>/dev/null)

if [ ! -f "$HASH_FILE" ] || [ "$CURRENT_HASH" != "$(cat "$HASH_FILE" 2>/dev/null)" ]; then
    echo "📦 安装Python依赖包..."
    pip install -q -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ 依赖安装失败，请检查错误信息"
        exit 1
    fi
    echo "$CURRENT_HASH" > "$HASH_FILE"
    echo "✅ 依赖安装完成"
else
    echo "✅ 依赖已就绪"
fi
echo ""
echo "🔧 设置环境变量:"
echo "   export ANTHROPIC_BASE_URL=http://127.0.0.1:8000"
echo ""
echo "🌐 代理服务器将在 http://127.0.0.1:8000 启动"
echo "📋 可用端点:"
echo "   - GET  /health        - 健康检查"
echo "   - GET  /v1/models     - 获取模型列表"
echo "   - POST /v1/messages   - Claude消息API"
echo ""
echo "🏃‍♂️ 启动服务器..."

python main.py
