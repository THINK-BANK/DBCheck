# SQL Server JDBC 插件的 Java 环境要求（Docker / Windows 打包版）

## 背景

DBCheck 的 SQL Server JDBC 插件（`sqlserver_jdbc`）通过 **JPype 直连 JVM** 运行：在 Python 进程中启动一个 JVM，把 `mssql-jdbc-*.jar` 加入 classpath，再通过 JDBC 驱动访问 SQL Server（见 `plugins/available/sqlserver_jdbc/jdbc_jvm.py` 的 `ensure_jvm()`）。

因此它**依赖目标环境存在可用的 Java 运行时（JVM）**，与 ODBC 路径（`pyodbc` + 系统 ODBC 驱动）不同——ODBC 不需要 Java，而 JDBC 必须有 JVM。

本文档说明两种常见部署形态下的 Java 环境要求：
- Docker 部署（官方镜像，Java 已内置）；
- Windows 打包版（`build/build_windows.bat` 产物，**未内置** JRE）。

---

## 一、Docker 部署

### 1. 镜像已内置 Java，无需手动安装、无需设置 JAVA_HOME

官方镜像 `jackge12345/dbcheck` 在构建时已安装 Java：

- **builder 阶段**（`deploy/Dockerfile` 第 41 行）安装 `default-jdk`（用于构建期编译）；
- **final 运行镜像**（`deploy/Dockerfile` 第 108 行）安装 `default-jre-headless`，即 **OpenJDK 17 JRE**，包含 `libjvm.so`。

JPype 在 Linux 下使用 `LinuxJVMFinder`，会自动在 `/usr/lib/jvm` 下探测 `libjvm.so` 并启动 JVM。`ensure_jvm()` 调用 `jpype.startJVM()` 时**未显式传 `jvm_path`**，走 `getDefaultJVMPath()` 自动探测，因此：

> 容器内**不需要**安装 Java，也**不需要**设置 `JAVA_HOME` 环境变量。

### 2. 真正决定 JDBC 能否使用的前提：驱动 jar 必须挂载进容器

Docker 里 JDBC 路径是否可用，取决于 **`drivers/sqlserver/mssql-jdbc-*.jar` 是否存在于容器内**：

- `deploy/docker-compose.yml` 通过只读挂载把宿主机 `drivers` 目录映射进容器：

```yaml
volumes:
  - ../drivers:/app/drivers:ro
```

- `modules/entrypoints/main_sqlserver_dual.py` 的 `_jdbc_available()`（88-114 行）要求：
  1. `jpype` 可导入；
  2. `drivers/sqlserver/mssql-jdbc-*.jar` 存在；
  3. 插件 `main_plugin.py` 可加载。

三者全部满足，`_jdbc_available()` 才返回 `True`。

**前提条件**：宿主机 `drivers/sqlserver/` 目录下必须存在 `mssql-jdbc-13.4.0.jre11.jar`（项目根目录 `drivers/sqlserver/` 已包含该文件），并随上述挂载进入容器。

### 3. 示例：docker run / docker compose

**docker run**（挂载 `drivers` 目录）：

```bash
docker run -d -p 5003:5003 \
  -v dbcheck_data:/app/data \
  -v dbcheck_pro_data:/app/data/pro_data \
  -v dbcheck_reports:/app/data/reports \
  -v /绝对路径/drivers:/app/drivers:ro \
  --name dbcheck \
  jackge12345/dbcheck:latest
```

**docker compose**（`deploy/docker-compose.yml` 已默认配置，确认 volumes 包含）：

```yaml
services:
  dbcheck:
    image: jackge12345/dbcheck:latest
    ports:
      - "5003:5003"
    volumes:
      - dbcheck_data:/app/data
      - dbcheck_pro_data:/app/data/pro_data
      - dbcheck_reports:/app/data/reports
      - ../drivers:/app/drivers:ro
```

> 注意：`-v /绝对路径/drivers:/app/drivers:ro` 中的宿主机路径需为绝对路径；`drivers` 以**只读**方式挂载即可，JDBC 插件只读取 jar，不需要写权限。

### 4. 排查：容器内验证 JDBC 是否就绪

```bash
docker exec dbcheck python -c "from modules.entrypoints.main_sqlserver_dual import _jdbc_available; print(_jdbc_available())"
```

- 输出 `True`：JDBC 已就绪，可正常走 JDBC 连接 SQL Server；
- 输出 `False`：JDBC 不可用，见下文。

### 5. `_jdbc_available()` = False 时的处理

`False` 的常见原因是 **`drivers/sqlserver/mssql-jdbc-*.jar` 未挂载进容器**（不是 Java 缺失）：

1. 确认宿主机 `drivers/sqlserver/mssql-jdbc-13.4.0.jre11.jar` 存在；
2. 确认 compose / `docker run` 的 `../drivers:/app/drivers:ro`（或对应绝对路径）挂载已生效；
3. 在容器内检查挂载与 jar 是否可见：

```bash
docker exec dbcheck ls -l /app/drivers/sqlserver/
```

当 `_jdbc_available()` = False 时：
- 连接模式为 `auto` 时会**回退到 ODBC**（`pyodbc`）；
- 但官方镜像**未安装 MS ODBC Driver 18**（`deploy/Dockerfile` 注释明确说明：`pyodbc` 通过 pip 安装，真正的 ODBC 驱动 `msodbcsql18` 需在运行时自行安装，才能支持 SQL Server；Dockerfile 注释中提及的 `docs/enable-sqlserver.md` 当前仓库中不存在，请勿依赖该文档）；
- 因此若需在 Docker 中使用 SQL Server，优先保证 JDBC 路径可用（挂载 jar）；若确实要走 ODBC，需自行在容器内安装 `msodbcsql18`（例如在容器启动脚本中安装，或基于官方镜像扩展新镜像）。

---

## 二、Windows 打包版（build/build_windows.bat）

### 1. 打包版不内置 JRE

`build/dbcheck_windows.spec` 的配置：

- `data_dirs` 中包含 `'drivers'`：仅把 `mssql-jdbc-*.jar` 作为**数据文件**打进包；
- `binaries=[]`：**不携带任何 Java 运行时（JVM）**。

因此，打包后的 `DBCheck-Windows` 目录**不含 JRE**。运行 JDBC 连接时，`jdbc_jvm.ensure_jvm()` → `jpype.startJVM()` 未传 `jvm_path`，Windows 下 JPype 走 `WindowsJVMFinder`，只会按以下顺序查找 JVM：

1. 环境变量 `JAVA_HOME`；
2. Windows 注册表；
3. 常见安装目录。

目标机器**没装 Java、或没配置 `JAVA_HOME`** 时，JPype 会抛出：

```
JVMNotFoundException: No JVM shared library file (jvm.dll) found.
Try setting up the JAVA_HOME environment variable properly.
```

这正是用户看到的提示，属于**预期行为**：打包版不负责携带 JVM，需要目标机器自行提供。

### 2. 目标机器要求

- 安装 **JRE 11+（或 JDK）**。`mssql-jdbc-13.4.0.jre11.jar` 的后缀 `jre11` 表示要求 **Java 11 及以上**；官方镜像内置的是 OpenJDK 17，建议目标机器安装 **JRE 17（或更高）** 与镜像保持一致；
- 配置 **系统或用户环境变量 `JAVA_HOME`**，指向 JRE/JDK 的**根目录**（不是 `bin` 目录），例如：

```
C:\Program Files\Java\jdk-17
```

### 3. Windows 配置 JAVA_HOME 的操作步骤

1. 安装 JRE 17（或 JDK 11+），例如 OpenJDK 发行版（Temurin / Adoptium 等）；
2. 打开「设置 → 系统 → 关于 → 高级系统设置 → 环境变量」；
3. 在「用户变量」（仅当前用户）或「系统变量」中**新建**：
   - 变量名：`JAVA_HOME`
   - 变量值：JRE/JDK 根目录，如 `C:\Program Files\Java\jdk-17`
4. （可选）在 `Path` 变量中追加 `%JAVA_HOME%\bin`，方便在命令行直接使用 `java`；
5. 点「确定」保存后，**重新打开**命令行窗口（环境变量改动不作用于已开启的窗口）；
6. 验证：

```bat
echo %JAVA_HOME%
java -version
```

- `echo %JAVA_HOME%` 应输出上一步设置的根目录路径；
- `java -version` 应正常显示 Java 版本信息（如 `openjdk 17.0.x`），而不是「不是内部或外部命令」。

### 4. 未配置 JAVA_HOME 时的报错及含义

| 报错 | 含义 |
| --- | --- |
| `JVMNotFoundException: No JVM shared library file (jvm.dll) found. Try setting up the JAVA_HOME environment variable properly.` | JPype 在 `JAVA_HOME`、注册表、常见安装目录中均未找到 `jvm.dll`，即目标机器没有可用的 JVM。**不是 DBCheck 的 bug**，而是环境缺少 Java。 |

解决办法：按上文第 3 节安装 JRE 并配置 `JAVA_HOME` 后重启应用即可。

### 5. （可选）不想动系统环境变量时的替代做法

如果不想修改系统/用户环境变量，可以把 JRE 目录放在打包目录旁，启动前临时设置 `JAVA_HOME`：

```bat
set JAVA_HOME=C:\path\to\jre17
"DBCheck-Windows\dbcheck.exe"
```

仅对当前命令行窗口生效，不影响系统全局配置。

---

## 三、常见问题排查表

| 场景 | 现象 | 原因 | 处理 |
| --- | --- | --- | --- |
| Docker 部署 | `_jdbc_available()` 输出 `False` | `drivers/sqlserver/mssql-jdbc-*.jar` 未挂载进容器 | 确认宿主机 jar 存在且 `../drivers:/app/drivers:ro` 挂载生效（见上文「一、5」） |
| Docker 部署 | 报错与 Java 相关（JVM 无法启动） | 极少见；镜像已内置 OpenJDK 17，正常无需处理 | 确认使用官方镜像 `jackge12345/dbcheck`，未在自定义镜像中移除 `default-jre-headless` |
| Windows 打包版 | `JVMNotFoundException: ... Try setting up the JAVA_HOME ...` | 目标机器未装 JRE / 未配置 `JAVA_HOME` | 安装 JRE 11+ 并配置 `JAVA_HOME`（见上文「二、3」） |
| Windows 打包版 | 报错「未找到任何 JDBC 驱动 jar（已扫描 .../drivers）」 | 打包目录 `drivers/sqlserver/` 下缺少 `mssql-jdbc-*.jar`（spec 仅把 jar 作为数据文件打包，误删/丢失会失效） | 从项目 `drivers/sqlserver/` 复制 `mssql-jdbc-13.4.0.jre11.jar` 到打包目录对应位置 |
| 两种形态通用 | JDBC 连接失败，但 `_jdbc_available()` 为 `True` | jar 已就位、JVM 可用，问题在连接参数 / 网络 / 账号权限 | 检查 host/port/user/password/database 与 SQL Server 可达性 |

---

**总结**：

- **Docker**：Java 已内置（OpenJDK 17），无需 `JAVA_HOME`；只需确保 `mssql-jdbc-*.jar` 通过 `drivers` 挂载进容器即可走 JDBC，否则 auto 模式回退 ODBC（而镜像未装 ODBC Driver 18，需另行安装）。
- **Windows 打包版**：不内置 JRE，目标机器必须安装 JRE 11+（推荐 17）并配置 `JAVA_HOME`，否则会看到 `JVMNotFoundException` 提示。
