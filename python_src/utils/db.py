"""SQLite 数据库辅助函数。"""
from __future__ import annotations

import os
import sqlite3

from python_src.utils.logger import get_logger

logger = get_logger(__name__)


def get_db_connection(db_path: str) -> sqlite3.Connection:  # pragma: no cover
    """返回一个新的 SQLite 连接 (autocommit off)。"""
    return sqlite3.connect(db_path)


def initialize_database(db_path: str, schema_sql: str) -> None:  # pragma: no cover
    """若数据库文件不存在则创建并执行 schema_sql。"""
    if os.path.exists(db_path):
        return

    logger.info("数据库 %s 不存在，正在初始化…", os.path.basename(db_path))
    try:
        conn = get_db_connection(db_path)
        conn.executescript(schema_sql)
        conn.commit()
        conn.close()
        logger.info("[成功] 数据库 %s 初始化成功。", os.path.basename(db_path))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("[错误] 数据库初始化失败: %s", exc)
        if os.path.exists(db_path):
            os.remove(db_path)
        raise 