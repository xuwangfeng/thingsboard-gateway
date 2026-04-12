#!/bin/bash
# ThingsBoard Gateway 存储配置修复脚本

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     ThingsBoard Gateway 存储配置修复工具                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# 查找配置文件
CONFIG_FILE=""

for path in \
    "/etc/thingsboard-gateway/config/tb_gateway.json" \
    "/var/lib/thingsboard-gateway/config/tb_gateway.json" \
    "$HOME/.thingsboard-gateway/config/tb_gateway.json" \
    "$(pwd)/tb_gateway.json"
do
    if [ -f "$path" ]; then
        CONFIG_FILE="$path"
        break
    fi
done

if [ -z "$CONFIG_FILE" ]; then
    echo "❌ 错误：未找到配置文件"
    echo ""
    echo "请手动指定配置文件路径："
    echo "  $0 /path/to/tb_gateway.json"
    exit 1
fi

echo "📁 找到配置文件: $CONFIG_FILE"
echo ""

# 备份配置文件
BACKUP_FILE="${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$CONFIG_FILE" "$BACKUP_FILE"
echo "✓ 已备份配置到: $BACKUP_FILE"
echo ""

# 显示当前配置
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "当前存储配置："
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python3 << PYEOF
import json

with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)

storage = config.get('storage', {})

# 显示关键配置
print(f"  max_file_count:           {storage.get('max_file_count', 'N/A')}")
print(f"  max_records_per_file:     {storage.get('max_records_per_file', 'N/A')}")
print(f"  max_read_records_count:   {storage.get('max_read_records_count', 'N/A')}")

# 检查问题
max_read = storage.get('max_read_records_count', 1000)
if max_read < 100:
    print(f"\n🔴 问题：max_read_records_count 设置过小 ({max_read})")
    print(f"   建议设置为 500-1000")
else:
    print(f"\n✓ max_read_records_count 配置正常")

PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 询问是否修复
read -p "是否自动修复配置？(y/n): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 修复配置
echo ""
echo "正在修复配置..."

python3 << 'PYEOF'
import json
import sys

config_file = '$CONFIG_FILE'

with open(config_file, 'r') as f:
    config = json.load(f)

# 修复存储配置
if 'storage' not in config:
    print("错误：配置文件中没有 storage 部分")
    sys.exit(1)

storage = config['storage']

# 推荐的配置
recommendations = {
    'max_read_records_count': 1000,      # 从 10 增加到 1000
    'max_records_per_file': 5000,       # 从 10000 减少到 5000（可选）
    'read_records_count': 500,          # 增加
}

changes = []

for key, value in recommendations.items():
    old_value = storage.get(key)
    if old_value != value:
        storage[key] = value
        changes.append(f"  {key}: {old_value} → {value}")

if not changes:
    print("✓ 配置已经是推荐的值，无需修改")
else:
    print("应用的修改：")
    for change in changes:
        print(change)

    # 保存修改后的配置
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    print("\n✓ 配置已保存")

PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "修复完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "下一步："
echo "  1. 重启网关服务："
echo "     sudo systemctl restart thingsboard-gateway"
echo ""
echo "  2. 监控 CPU 使用情况："
echo "     watch -n 1 'ps aux | grep tb_gateway'"
echo ""
echo "  3. 如果需要回滚："
echo "     cp $BACKUP_FILE $CONFIG_FILE"
echo ""
