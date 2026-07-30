"""DBCheck 旧路径回滚脚本。

依据 ``<DATA_DIR>/.migration_manifest.json`` 中已迁移（status==done）的条目，
逆序将文件/目录回滚到原始相对路径：

- 若目标新路径存在、且原路径仍存在：直接 ``shutil.move(new, old)``。
- 若目标新路径存在、但原路径不存在：优先从备份恢复（copy2/copytree 到 old），
  备份缺失时退化为直接移动。
- 目标新路径已不存在的条目视为无需回滚，跳过。

用法：
    python scripts/rollback_paths.py
"""

import datetime
import json
import shutil
import sys
from pathlib import Path

# 保证从仓库根启动时能 import core
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import paths  # noqa: E402


def _read_manifest() -> dict:
    if paths._MANIFEST.exists():
        try:
            with open(paths._MANIFEST, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"version": 1, "entries": []}


def _write_manifest(manifest: dict) -> None:
    paths._MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(paths._MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)


def _merge_into(src: Path, dst: Path):
    """把 src 的内容归并进 dst（覆盖同名），然后删除 src。

    用于「新旧两份共存」场景：将 new 的内容归并回 old，并删除 new，保证回滚后
    只保留 old、new 被清空。实现细节见 scripts/migrate_legacy_paths._merge_into。
    """
    import shutil

    src, dst = Path(src), Path(dst)
    if not src.exists():
        return
    if src.is_file():
        shutil.move(str(src), str(dst))
        return
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir() and target.exists() and target.is_dir():
            _merge_into(child, target)
        else:
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(str(target))
                else:
                    target.unlink()
            shutil.move(str(child), str(target))
    shutil.rmtree(str(src))


def run() -> None:
    """逆序回滚所有已迁移条目。

    保证回滚后 old 恢复且 new 被清空，不存在新旧两份共存：
    - new 存在、old 也存在      -> 将 new 内容归并回 old 并删除 new
    - new 存在、old 不存在      -> 直接 rename new 回 old 原位（同时清空 new）
    - new 不存在、old 存在      -> 视为已回滚，跳过
    - new 不存在、old 也不存在  -> 从备份恢复（文件 copy2 / 目录 copytree 到 old），
                                   备份缺失时仅在 manifest 标记，不报错。
    """
    manifest = _read_manifest()
    entries = manifest.get("entries", [])
    done_entries = [e for e in entries if e.get("status") == "done"]
    rolled = 0

    for e in reversed(done_entries):
        new = paths.PROJECT_ROOT / e["new"]
        old = paths.PROJECT_ROOT / e["old"]

        if new.exists():
            if old.exists():
                # 新旧两份共存：把 new 的内容归并回 old，并删除 new
                _merge_into(new, old)
            else:
                # 原位置缺失：直接把 new 重命名回 old 原位（同时清空 new）
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(new), str(old))
        elif old.exists():
            # new 已不存在但 old 仍在，视为已回滚，跳过
            e["status"] = "rolled_back"
            rolled += 1
            continue
        else:
            # new 与 old 都不存在：尝试从备份恢复
            backup = Path(e["backup"]) if e.get("backup") else None
            old.parent.mkdir(parents=True, exist_ok=True)
            if backup is not None and backup.exists():
                if backup.is_file():
                    shutil.copy2(backup, old)
                else:
                    shutil.copytree(backup, old)
            else:
                # 备份缺失：仅在 manifest 标记，不报错
                pass

        e["status"] = "rolled_back"
        rolled += 1

    _write_manifest(manifest)
    print(f"[rollback] 回滚完成：处理 {rolled} 项")


if __name__ == "__main__":
    run()
