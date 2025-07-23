"""SQLite 数据库连接与初始化助手。"""
from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Tuple
import re

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
        
        # 只保留最简单的日志，删除详细的表结构输出
        if not exists:
            logger.warning(f"表 '{table_name}' 不存在于数据库")
            
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
        # 简化日志输出，不输出详细的表名列表
        logger.info(f"数据库包含 {len(tables)} 个表")
        return tables
    except Exception as e:
        logger.error(f"列出表失败: {e}")
        return []
    finally:
        conn.close()


# 减少输出详细的表结构，只输出创建了哪些表，而不输出具体结构
def ensure_tables_exist(conn: sqlite3.Connection, schema_scripts: List[str]) -> List[str]:
    """确保必要的表存在，返回缺失的表列表。"""
    cursor = conn.cursor()
    
    # 检查已存在的表
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {row[0] for row in cursor.fetchall()}
    
    missing_tables = []
    
    for script in schema_scripts:
        # 提取表名和CREATE TABLE语句
        table_matches = re.findall(r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?(\w+)", script, re.IGNORECASE)
        if not table_matches:
            continue
            
        table_name = table_matches[0]
        
        if table_name not in existing_tables:
            missing_tables.append(table_name)
            
            try:
                cursor.executescript(script)
                # 减少日志输出，不输出完整SQL语句
                logger.debug("已创建表: %s", table_name)
            except sqlite3.Error as e:
                logger.error("创建表 %s 失败: %s", table_name, e)
    
    conn.commit()
    return missing_tables


__all__ = ["get_db_connection", "initialize_database", "check_table_exists", "list_database_tables"] 