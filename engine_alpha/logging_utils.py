"""
Logging utilities for Chloe Alpha.

Provides dedicated loggers for specific components (e.g., MATIC decisions).
"""

import logging
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
LOGS_DIR = ROOT_DIR / "logs"


def get_matic_logger() -> logging.Logger:
    """
    Get or create the MATIC decisions logger.
    
    Returns a logger that writes to logs/matic_decisions.log with timestamped entries.
    """
    logger = logging.getLogger("matic_decisions")
    
    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False  # Don't propagate to root logger
        
        # Ensure logs directory exists
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create file handler
        log_file = LOGS_DIR / "matic_decisions.log"
        fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        
        # Format: timestamp | message
        fmt = logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        fh.setFormatter(fmt)
        
        logger.addHandler(fh)
    
    return logger

