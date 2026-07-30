# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

import logging
import sys
from pathlib import Path

# 保证从任意位置运行时都能 import core.paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import paths  # noqa: E402


def getlogger():
    # logger
    #logger = logging.getLogger(__name__)
    logger = logging.getLogger()
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        # create console handler and set level to debug
        #ch = logging.StreamHandler()
        ch = logging.FileHandler(str(paths.LOG_DIR / 'autoDoc.log'))
        ch.setLevel(logging.DEBUG)
    # create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    # add formatter to ch
        ch.setFormatter(formatter)
    # add ch to logger
        logger.addHandler(ch)
    return logger
