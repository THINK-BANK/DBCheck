# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

# 启动入口 shim：转发到 modules.web.app.main()，保持 `python web_ui.py` 可启动调试
from modules.web.app import *  # noqa: F401,F403

if __name__ == "__main__":
    main()
