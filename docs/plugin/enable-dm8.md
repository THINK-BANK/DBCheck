# 在 DBCheck 中启用 DM8 达梦数据库连接

DBCheck 的 DM8 测试连接**优先使用纯 Java 的 JDBC 驱动**，无需在运行环境安装达梦客户端
原生库（`libdmcrypt.so` / `dmcrypt.dll`）。这是规避 `-70089 Encryption module failed to load`
报错（dmPython 找不到达梦原生加密库）的最简方案。

## 启用方式（推荐，无需插件）

1. 从达梦官网下载 **DM8 JDBC 驱动**（`DmJdbcDriver18.jar`，开发版/试用版均可）。
2. 将其放入项目根目录的 `drivers/dm8/`：

   ```
   DBCheck/
   └── drivers/
       └── dm8/
           └── DmJdbcDriver18.jar
   ```

3. 重启 DBCheck 服务（开发态 `python web_ui.py` / Docker 重新构建）。

此后「数据源管理 → 添加数据源 → 数据库类型选 DM8」点「测试连接」，会自动走 JDBC 通道，
不再依赖 dmPython / 达梦客户端原生库。

## 工作原理

- 连接测试入口 `test_dm_connection()` / `_ct_dm()` 会先调用 `_find_dm_jdbc_jar()`
  在 `drivers/dm8/` 下查找 `DmJdbcDriver*.jar`。
- **找到 jar** → 通过 `run_jdbc_test_subprocess('dm', ...)` 在**未被 gevent monkey-patch
  的隔离子进程**里用 `jaydebeapi` 连接 `jdbc:dm://host:port`（驱动类
  `dm.jdbc.driver.DmDriver`）。JVM 在子进程内启动，不会钉死 Web 主进程的 gevent hub。
- **未找到 jar** → 回退到 `dmPython`（需本机安装达梦客户端原生库）。若原生库缺失，
  返回可读中文提示（而非天书 `-70089`）。

> 说明：JDBC 依赖 `jaydebeapi` + `JPype1` + 运行环境的 JDK/JRE。Docker 镜像已内置
> `default-jre-headless` 与这两个 Python 包；本地开发环境若未装 JDK，测试会给出明确提示。

## Docker 部署

`drivers/dm8/` 在 `.dockerignore` 中**未被排除**，会随 `COPY . .` 进入镜像构建上下文。
只需在构建前把 `DmJdbcDriver18.jar` 放到 `drivers/dm8/`，重新 `docker build` 即可：
镜像内路径为 `/app/drivers/dm8/DmJdbcDriver18.jar`，运行时自动生效。

```bash
# 1. 放入驱动
mkdir -p drivers/dm8 && cp /path/to/DmJdbcDriver18.jar drivers/dm8/

# 2. 构建（drivers/dm8 会随上下文进入镜像）
docker build -t jackge12345/dbcheck:latest .

# 3. 运行
docker run -d -p 5003:5003 -v dbcheck_data:/app/data jackge12345/dbcheck:latest
```

> 该目录已在 `.gitignore` 中忽略，驱动二进制不会进入 Git 版本库。

## 旧方式（不推荐）：dmPython + 达梦客户端原生库

若坚持用 dmPython（原生 Python 驱动），需在运行本服务的机器安装 DM8 客户端（与数据库同大
版本），并将其 `bin` 目录加入环境：

- Windows：`PATH` 追加 `C:\dmdbms\bin`
- Linux：`export LD_LIBRARY_PATH=/opt/dmdbms/bin:$LD_LIBRARY_PATH`

此方式下 `.dockerignore` 之外还需把客户端原生库打进镜像（专有软件再分发，请自行评估许可），
远不如上面的 JDBC 方案省事，故不再作为默认推荐。
