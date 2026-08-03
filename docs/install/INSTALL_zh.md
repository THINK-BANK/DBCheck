# DBCheck 快速安装指南

## 方式一：使用依赖检查脚本（推荐）

```bash
cd DBCheck

# 1. 安装所有依赖
pip install -r requirements.txt

# 2. 运行依赖检查
python check_dependencies.py
```

如果检查通过，直接启动：
```bash
python web_ui.py
```

## 方式二：使用虚拟环境（推荐用于开发）

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 运行检查
python check_dependencies.py
```

## 数据库驱动说明

| 数据库 | 驱动 | 额外配置 |
|--------|------|----------|
| MySQL/TiDB | pymysql | 无 |
| PostgreSQL | psycopg2-binary | 无 |
| Oracle | oracledb | 推荐使用，pure Python |
| 达梦 DM8 | dmpython | 无 |
| SQL Server | pyodbc | 需要安装 [ODBC Driver 17](https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) |

## 启动 Web UI

```bash
python web_ui.py
```

默认访问地址：http://localhost:5003
