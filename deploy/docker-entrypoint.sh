#!/bin/bash
# docker-entrypoint.sh
# DBCheck Docker 容器启动脚本

set -e

echo "==> DBCheck v$(cat /app/VERSION.txt 2>/dev/null || echo 'unknown')"

# Check available memory (warn if < 2GB)
if [ -f /proc/meminfo ]; then
    AVAIL_MEM=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo "unknown")
    if [ "$AVAIL_MEM" != "unknown" ] && [ "$AVAIL_MEM" -lt 2097152 ]; then
        echo "==> WARNING: Available memory is less than 2GB (${AVAIL_MEM}KB)"
        echo "    Report generation may fail due to insufficient memory."
        echo "    Consider increasing Docker memory limit (--memory=2g)"
    fi
fi

# Ensure data/ and drivers/ directories exist and are writable
mkdir -p /app/data
chmod 755 /app/data
mkdir -p /app/drivers
chmod 755 /app/drivers
mkdir -p /app/data/pro_data
chmod 755 /app/data/pro_data

# Initialize database tables (create if not exist)
# This ensures inspection_template and other tables exist even on first run
echo "==> Initializing database tables..."
python -c "
from inspection_dal import init_database
init_database()
print('inspection.db tables ready.')
" 2>&1 || echo "WARNING: inspection.db init failed"

# Initialize default inspection templates (skip if already exist)
echo "==> Initializing default inspection templates..."
python /app/inspection/init_db.py 2>&1 || echo "WARNING: inspection_init_db.py failed"

# Check drivers status
DRIVER_COUNT=$(find /app/drivers -type f 2>/dev/null | wc -l)
if [ "$DRIVER_COUNT" -eq 0 ]; then
    echo "==> WARNING: /app/drivers/ is empty."
    echo "    Oracle client libs and YashanDB wheel are not included."
    echo "    To enable these databases, place driver files in /app/drivers/"
    echo "    or use '-v /path/to/drivers:/app/drivers' when running the container."
else
    echo "==> Drivers found: $DRIVER_COUNT file(s) in /app/drivers/"
fi

# Initialize RBAC user management seed data
echo "==> Initializing RBAC user management..."
python -m user_management.seed 2>&1 || echo "WARNING: RBAC seed init failed"

# Auto-enable bundled plugins: plugins/available -> plugins/enabled
# NOTE: uses the local loader API (discover_plugins / enable_plugin), NOT the
# online PluginMarket registry. The old code called PluginMarket.list_available()
# which does not exist -> "PluginMarket has no attribute 'list_available'".
echo "==> Enabling bundled plugins (available -> enabled)..."
timeout 120 python -c "
import sys
sys.path.insert(0, '/app')
try:
    from modules.pluginkit.loader import discover_plugins, enable_plugin
    plugins = discover_plugins()
    pending = sorted({p['name'] for p in plugins if not p.get('enabled')})
    if not pending:
        print('All bundled plugins already enabled.')
    for name in pending:
        try:
            res = enable_plugin(name)
            if isinstance(res, tuple):
                ok, msg = res
            else:
                ok, msg = bool(res), 'done'
            status = '✓' if ok else '✗'
            print(f'  {status} {name}: {msg}')
        except Exception as e:
            print(f'  ✗ {name} enable failed: {e}')
    print('Plugin auto-installation completed.')
except Exception as e:
    print(f'WARNING: Plugin auto-installation failed: {e}')
" 2>&1 || echo "WARNING: Plugin auto-installation timeout or failed"

echo ""
exec python /app/web_ui.py
