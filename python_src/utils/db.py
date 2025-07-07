"""SQLite 数据库连接与初始化助手。"""
from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Tuple

from python_src.utils.logger import get_logger

logger = get_logger(__name__)


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """获取 SQLite 连接，设置外键约束并返回。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(db_path: str, schema_sql: str) -> None:  # pragma: no cover
    """如果数据库不存在，创建数据库并执行建表 SQL。"""
    if not os.path.exists(db_path):
        logger.info("创建新数据库: %s", db_path)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.executescript(schema_sql)
        conn.commit()
        conn.close()
        logger.info("数据库结构初始化完成: %s", db_path)


def check_table_exists(db_path: str, table_name: str) -> bool:
    """检查指定的表是否存在于数据库中
    
    Args:
        db_path: 数据库路径
        table_name: 表名
        
    Returns:
        bool: 表是否存在
    """
    if not os.path.exists(db_path):
        logger.warning(f"数据库文件不存在: {db_path}")
        return False
        
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        count = cur.fetchone()[0]
        exists = count > 0
        
        if exists:
            logger.info(f"表 '{table_name}' 存在于数据库 {db_path}")
            
            # 显示表结构
            cur.execute(f"PRAGMA table_info({table_name})")
            columns = cur.fetchall()
            logger.info(f"表 '{table_name}' 结构:")
            for col in columns:
                logger.info(f"  - {col[1]} ({col[2]})")
        else:
            logger.warning(f"表 '{table_name}' 不存在于数据库 {db_path}")
            
            # 显示所有表
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]
            logger.info(f"数据库中的表: {', '.join(tables)}")
        
        return exists
    except Exception as e:
        logger.error(f"检查表失败: {e}")
        return False
    finally:
        conn.close()


def list_database_tables(db_path: str) -> List[str]:
    """列出数据库中的所有表
    
    Args:
        db_path: 数据库路径
        
    Returns:
        List[str]: 表名列表
    """
    if not os.path.exists(db_path):
        logger.warning(f"数据库文件不存在: {db_path}")
        return []
        
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        logger.info(f"数据库 {db_path} 包含以下表: {', '.join(tables)}")
        return tables
    except Exception as e:
        logger.error(f"列出表失败: {e}")
        return []
    finally:
        conn.close()


__all__ = ["get_db_connection", "initialize_database", "check_table_exists", "list_database_tables"] 