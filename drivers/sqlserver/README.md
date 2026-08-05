# SQL Server Drivers（ODBC + JDBC）

本目录同时承载 **ODBC**（pyodbc 走 msodbcsql）与 **JDBC**（JPype1 走
mssql-jdbc）两套驱动。两套驱动**完全独立、按需使用**，巡检时通过实例的
`connection_mode`（`odbc` / `jdbc` / `auto`）选择。

---

## 1. ODBC 驱动（pyodbc 路径）

由 `main_sqlserver.py`（默认 `connection_mode='odbc'`）使用。

- Windows 64位：`msodbcsql_x64.msi`
- Windows 32位：`msodbcsql_x86.msi`
- Windows arm64：`msodbcsql_arm64.msi`

下载：<https://learn.microsoft.com/zh-cn/sql/connect/odbc/download-odbc-driver-for-sql-server>

## 2. JDBC 驱动（JDBC 路径）

由 `plugins/available/sqlserver_jdbc/`（`connection_mode='jdbc'` 或 `auto`
且探测通过）使用。

- 文件：`mssql-jdbc-13.4.0.jre11.jar`
- 来源：Microsoft 官方，2026-03-13 GA
- 驱动类：`com.microsoft.sqlserver.jdbc.SQLServerDriver`
- URL：`jdbc:sqlserver://host:port;databaseName=xxx;encrypt=true;trustServerCertificate=true`
- 兼容 JDK：1.8 / 11 / 17 / 21 / 25（JPype1 启动时由 `plugins/available/sqlserver_jdbc/jdbc_jvm.py`
  扫描 `drivers/**/*.jar` 全部加载）

下载：<https://learn.microsoft.com/sql/connect/jdbc/download-microsoft-jdbc-driver-for-sql-server>
或 Maven：
```xml
<dependency>
    <groupId>com.microsoft.sqlserver</groupId>
    <artifactId>mssql-jdbc</artifactId>
    <version>13.4.0.jre11</version>
</dependency>
```

> 将 jar 重命名为 `mssql-jdbc-13.4.0.jre11.jar` 后放入本目录即可。

## 3. 许可证

JDBC 驱动本身遵循 **Microsoft Software License Terms**（与 MIT 兼容的开源许可证），
文本见 `LICENSE`。

## 4. 共存说明

- `msodbcsql*.msi`（ODBC）和 `mssql-jdbc-*.jar`（JDBC）是**两套独立的驱动**：
  - ODBC 是 Windows 原生 MSI，pyodbc 通过 Windows ODBC Manager 调用
  - JDBC 是 Java 字节码，JPype1 通过 JVM 调用
- 同一台机器可以**同时安装**两套（互不依赖），按 `connection_mode` 选择路径
- ODBC 路径是默认与向后兼容路径，JDBC 路径用于跨平台 / 简化部署场景
