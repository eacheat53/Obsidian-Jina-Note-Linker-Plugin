import logging
import sys
import codecs
import io

def init_logger(level: str = "INFO") -> None:
    """Initialize root logger once per session."""
    # 安全地设置UTF-8编码
    try:
        if hasattr(sys.stdout, 'encoding') and sys.stdout.encoding != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, IOError):
        # 如果出现错误，跳过编码设置
        pass
    
    # 使用文件处理器而非stdout
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(stream=sys.stdout)],
        force=True,
    )


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a module-level logger (default root)."""
    return logging.getLogger(name)