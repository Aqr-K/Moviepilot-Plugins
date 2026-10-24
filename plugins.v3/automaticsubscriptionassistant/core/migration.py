"""把存量历史记录从插件 KV 搬进自有表。

只在 KV 里还留着 ``history`` 时执行一次。导入按 unique 去重且逐条隔离：坏记录跳过并
计数，不阻断其余记录。导入成功后原 KV 值不直接删除，而是改存到备份键，留一条可回溯
的退路；同时写下带时间与条数的标记，供排查与幂等判断。
"""
from __future__ import annotations

from datetime import datetime
import json
from typing import Callable, Optional

from .history import HISTORY_KEY
from .models import HistoryRecord

# 迁移完成标记，值形如 {"migrated_at": "...", "imported": 12, "skipped": 0, "source_total": 12}。
MIGRATION_KEY = "history_migration"

# 迁移后原样留档的 KV 键，出问题时可据此复原。
BACKUP_KEY = "history_migrated_backup"


class MigrationResult:
    """一次迁移的结果。"""

    def __init__(self, performed: bool, imported: int = 0, skipped: int = 0,
                 source_total: int = 0, error: Optional[str] = None):
        self.performed = performed        # 本次是否真的搬了数据
        self.imported = imported          # 成功写入表的条数
        self.skipped = skipped            # 跳过的坏记录条数
        self.source_total = source_total  # KV 中原有的条数
        self.error = error                # 整体失败时的原因

    def summary(self) -> str:
        """人类可读的一句话结果。"""
        if self.error:
            return f"迁移失败：{self.error}"
        if not self.performed:
            return "无需迁移"
        text = f"已迁移 {self.imported} 条历史记录到插件自有表"
        if self.skipped:
            text += f"，跳过 {self.skipped} 条无法解析的记录"
        return text


def migrate_history_from_kv(store, get_data: Callable, save_data: Callable,
                            del_data: Callable, logger=None) -> MigrationResult:
    """把 KV 中的历史记录导入 ``store``，完成后把原值挪到备份键。

    :param store: 目标 :class:`~.history.HistoryStore`
    :param get_data: 读插件 KV，签名 ``get_data(key)``
    :param save_data: 写插件 KV，签名 ``save_data(key, value)``
    :param del_data: 删插件 KV，签名 ``del_data(key)``
    :param logger: 可选日志器
    :return: 迁移结果
    """
    try:
        legacy = get_data(HISTORY_KEY)
    except Exception as exc:  # noqa: BLE001 - 读不到就当没有存量，不阻断插件启动
        if logger:
            logger.warning(f"读取存量历史失败，跳过迁移: {exc}")
        return MigrationResult(performed=False, error=str(exc))

    if not isinstance(legacy, list) or not legacy:
        # 键不存在、已迁走、或本来就是空历史：都无需搬运。空列表一并清掉，
        # 免得每次启动都再走一遍这个判断。
        if isinstance(legacy, list):
            _safe(del_data, HISTORY_KEY, logger)
        return MigrationResult(performed=False)

    # 归档必须先完成；失败时绝不删除原键或写完成标记。
    try:
        backup = get_data(BACKUP_KEY)
        archived = list(backup) if isinstance(backup, list) else []
        seen = {json.dumps(raw, sort_keys=True, ensure_ascii=False) for raw in archived}
        for raw in legacy:
            identity = json.dumps(raw, sort_keys=True, ensure_ascii=False)
            if identity not in seen:
                archived.append(raw)
                seen.add(identity)
        if save_data(BACKUP_KEY, archived) is False:
            raise RuntimeError("历史备份写入失败")
    except Exception as exc:  # noqa: BLE001 - 保留原始数据供后续重试
        if logger:
            logger.error(f"历史迁移备份失败，原始数据已保留: {exc}")
        return MigrationResult(performed=False, source_total=len(legacy), error=str(exc))

    imported = 0
    skipped = 0
    retry = []
    for raw in legacy:
        if not isinstance(raw, dict) or not raw.get("unique"):
            skipped += 1
            continue
        try:
            # 收尾失败后重跑，不用旧 KV 覆盖已更新的数据库记录。
            if store.get(raw["unique"]) is None:
                store.record(HistoryRecord.from_dict(raw, migrate_legacy=True))
            imported += 1
        except Exception as exc:  # noqa: BLE001 - 单条坏数据不该毁掉整次迁移
            skipped += 1
            retry.append(raw)
            if logger:
                logger.warning(f"迁移历史记录 {raw.get('unique')} 失败，已跳过: {exc}")

    if imported == 0:
        # 一条都没搬进去，原值原地保留，等修复后重试，不写完成标记。
        error = "存量历史全部无法解析，已原样保留待排查"
        if logger:
            logger.error(f"{error}（共 {len(legacy)} 条）")
        return MigrationResult(performed=False, skipped=skipped,
                               source_total=len(legacy), error=error)

    marker = {
        "migrated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "imported": imported,
        "skipped": skipped,
        "source_total": len(legacy),
    }
    try:
        if retry:
            # 可解析但暂时写入失败的记录继续留在迁移源；坏记录已在备份中留档。
            if save_data(HISTORY_KEY, retry) is False:
                raise RuntimeError("保存待重试历史失败")
        else:
            if save_data(MIGRATION_KEY, marker) is False:
                raise RuntimeError("保存迁移标记失败")
            if del_data(HISTORY_KEY) is False:
                raise RuntimeError("删除已迁移历史失败")
    except Exception as exc:  # noqa: BLE001 - 已导入部分保留，原始数据可重试
        if logger:
            logger.warning(f"历史迁移收尾失败: {exc}")
        return MigrationResult(performed=True, imported=imported, skipped=skipped,
                               source_total=len(legacy), error=str(exc))

    result = MigrationResult(performed=True, imported=imported, skipped=skipped,
                             source_total=len(legacy))
    if logger:
        logger.info(result.summary())
    return result


def _safe(func: Callable, key: str, logger, *args) -> None:
    """执行 KV 操作，失败只告警。"""
    try:
        func(key, *args)
    except Exception as exc:  # noqa: BLE001 - KV 收尾失败不该让已完成的导入前功尽弃
        if logger:
            logger.warning(f"历史迁移收尾操作 {key} 失败: {exc}")
