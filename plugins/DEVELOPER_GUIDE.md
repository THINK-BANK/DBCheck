# DBCheck 插件开发指南

## 概述

DBCheck 插件是一个包含 `plugin.json` 清单和 `__init__.py` 入口的文件夹，放在 DBCheck 的 `plugins/` 目录下即可被自动加载。

## 目录结构

```
my-plugin/
├── plugin.json      # 插件清单（必需）
├── __init__.py       # 入口，调用 register() （必需）
└── README.md         # 说明文档（推荐）
```

## plugin.json 规范

```json
{
  "name": "my-plugin",            // 唯一 ID（kebab-case）
  "version": "1.0.0",            // 语义化版本
  "title": "我的插件",            // 显示名称
  "description": "插件描述",
  "author": {
    "name": "你的名字",
    "email": "you@example.com",
    "url": "https://github.com/you"
  },
  "license": "Apache-2.0",
  "keywords": ["oracle", "asm"],
  "categories": ["inspection"],
  "dbcheck": {
    "minVersion": "2.5.0"
  },
  "capabilities": {
    "inspections": ["check_key_1", "check_key_2"]
  },
  "permissions": ["database:*:read"],
  "entry": "__init__.py"
}
```

## __init__.py 模板

```python
"""
我的 DBCheck 巡检插件
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from plugin_core import InspectionPlugin, InspectionQuery, RiskItem, register

class MyChecker(InspectionPlugin):
    id = "my-plugin"
    name = "我的插件"
    version = "1.0.0"  
    db_types = ["mysql"]          # 适用数据库，空=全部
    author = "你的名字"

    def get_queries(self):
        """返回需要执行的 SQL"""
        return [
            InspectionQuery(
                key="my_check",
                sql="SELECT COUNT(*) AS cnt FROM information_schema.tables",
                desc_zh="统计表数量",
                db_type="mysql"
            )
        ]

    def analyze(self, context):
        """分析结果，返回 RiskItem 列表"""
        data = context.get("my_check", {})
        rows = data.get("rows", []) if isinstance(data, dict) else []
        cnt = int((rows[0] or [0])[0]) if rows else 0
        
        if cnt > 10000:
            return [RiskItem(
                level="MEDIUM",
                title=f"表数量过多 ({cnt})",
                suggestion="建议拆分数据库或分区"
            )]
        return []

# 注册插件
register(MyChecker())
```

## 可用权限

| 权限 | 说明 |
|------|------|
| `database:*:read` | 读取所有数据库 |
| `database:*:write` | 写入所有数据库（高危） |
| `database:mysql:read` | 只读 MySQL |
| `file:report:write` | 写报告文件 |
| `network:outbound` | 发起网络请求 |

## 上架流程

1. Fork [fiyo/dbcheck-plugins](https://github.com/fiyo/dbcheck-plugins)
2. 在 `plugins/` 下创建你的插件目录
3. 在你自己仓库创建 Release，上传 `.zip` 包
4. 编辑 `registry.json`，在 `plugins` 数组中追加你的条目：
   ```json
   {
     "id": "my-plugin",
     "name": "我的插件",
     "version": "1.0.0",
     "author": "你的名字",
     "author_type": "community",
     "description": "插件描述",
     "download": "https://github.com/你的用户名/仓库/releases/download/v1.0.0/xxx.zip",
     "category": "inspection",
     "keywords": ["oracle"],
     "db_types": ["oracle"],
     "min_dbcheck_version": "2.5.0",
     "license": "Apache-2.0",
     "verified": false
   }
   ```
5. 提 PR → CI 自动验证 → 等待审核合并 🎉

## 官方插件 vs 社区插件

| 字段 | 官方 | 社区 |
|------|------|------|
| `author_type` | `"official"` | `"community"` |
| `verified` | `true` | `false`（审核通过后可改 `true`） |
| 维护方 | DBCheck Team | 插件作者 |
| 代码仓库 | `fiyo/dbcheck-plugins` | 开发者自己的仓库 |
| Release | 官方 Release | 你自己的 GitHub Release |
| 前端标识 | 🟢 **✅ 官方** | 🟠 **👤 社区**（未验证）/ 🔵 **✅ 已验证**（已审核） |

**社区插件变更为已验证**：插件质量稳定、用户反馈良好后，由 DBCheck Team 审核并将 `verified` 改为 `true`，前端标识自动变为 🔵「✅ 已验证」。

## 本地测试

```bash
# 把插件文件夹复制到 DBCheck 的 plugins/ 目录
cp -r my-plugin /path/to/DBCheck/plugins/

# 启动 DBCheck，查看控制台输出确认加载
python web_ui.py
# 输出: [插件] 已加载 1 个插件
```
