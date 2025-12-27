"""
Safe file readers for Chloe Alpha API
Whitelisted file access for dashboard endpoints.
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import dateutil.parser


# Repository root for absolute path resolution
REPO_ROOT = Path(__file__).parent.parent.parent


class SafeFileReader:
    """Safe file reader with whitelisted paths and error handling."""

    # Whitelisted file paths (relative to repo root)
    WHITELISTED_FILES = {
        "reports/loop_health.json",
        "reports/loop/loop_health.json",
        "reports/pf_local.json",
        "reports/position_state.json",
        "reports/risk/symbol_states.json",
        "reports/feature_audit.json",
        "reports/gpt/promotion_advice.json",
        "reports/gpt/shadow_promotion_queue.json",
        "reports/trades.jsonl",
        "reports/meta/counterfactual_ledger.jsonl",
        "reports/meta/inaction_scoring.jsonl",
        "reports/meta/fair_value_gaps.jsonl",
        "reports/meta/opportunity_events.jsonl",
    }

    @classmethod
    def read_json_file(cls, relative_path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Safely read a JSON file.
        Returns (data, error_message) tuple.
        """
        if relative_path not in cls.WHITELISTED_FILES:
            return None, f"Access denied: {relative_path} not in whitelist"

        full_path = REPO_ROOT / relative_path

        if not full_path.exists():
            return None, f"File not found: {relative_path}"

        if not full_path.is_file():
            return None, f"Not a file: {relative_path}"

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data, None
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON in {relative_path}: {str(e)}"
        except Exception as e:
            return None, f"Error reading {relative_path}: {str(e)}"

    @classmethod
    def tail_jsonl_file(cls, relative_path: str, hours: int = 6, limit: int = 200) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        Safely read recent entries from a JSONL file.
        Returns (entries, error_message) tuple.
        """
        if relative_path not in cls.WHITELISTED_FILES:
            return None, f"Access denied: {relative_path} not in whitelist"

        full_path = REPO_ROOT / relative_path

        if not full_path.exists():
            return None, f"File not found: {relative_path}"

        cutoff_time = datetime.now() - timedelta(hours=hours)

        try:
            entries = []
            with open(full_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        entry = json.loads(line)

                        # Check timestamp if present
                        ts_str = entry.get('ts') or entry.get('timestamp')
                        if ts_str:
                            try:
                                # Handle various timestamp formats
                                if ts_str.endswith('Z'):
                                    ts_str = ts_str[:-1] + '+00:00'
                                entry_time = dateutil.parser.parse(ts_str)

                                if entry_time < cutoff_time:
                                    continue  # Skip old entries
                            except:
                                pass  # If timestamp parsing fails, include the entry

                        entries.append(entry)

                        if len(entries) >= limit:
                            break

                    except json.JSONDecodeError:
                        continue  # Skip malformed lines

            return entries, None

        except Exception as e:
            return None, f"Error reading {relative_path}: {str(e)}"

    @classmethod
    def get_file_info(cls, relative_path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Get file information (size, mtime).
        Returns (info_dict, error_message) tuple.
        """
        if relative_path not in cls.WHITELISTED_FILES:
            return None, f"Access denied: {relative_path} not in whitelist"

        full_path = REPO_ROOT / relative_path

        if not full_path.exists():
            return None, f"File not found: {relative_path}"

        try:
            stat = full_path.stat()
            info = {
                "path": relative_path,
                "size_bytes": stat.st_size,
                "modified_timestamp": stat.st_mtime,
                "modified_iso": datetime.fromtimestamp(stat.st_mtime).isoformat()
            }
            return info, None
        except Exception as e:
            return None, f"Error getting info for {relative_path}: {str(e)}"


def get_health_status() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Get the most recent health status from available health files."""
    # Try loop_health.json first (preferred)
    data, error = SafeFileReader.read_json_file("reports/loop_health.json")
    if data:
        return data, None

    # Fallback to loop/loop_health.json
    data, error = SafeFileReader.read_json_file("reports/loop/loop_health.json")
    if data:
        return data, None

    return None, "No health data available"


def get_pf_data() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Get PF data."""
    return SafeFileReader.read_json_file("reports/pf_local.json")


def get_positions() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Get position state."""
    return SafeFileReader.read_json_file("reports/position_state.json")


def get_symbol_states() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Get symbol states."""
    return SafeFileReader.read_json_file("reports/risk/symbol_states.json")


def get_feature_audit() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Get feature audit data."""
    return SafeFileReader.read_json_file("reports/feature_audit.json")


def get_promotion_advice() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Get promotion advice."""
    return SafeFileReader.read_json_file("reports/gpt/promotion_advice.json")


def get_promotion_queue() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Get promotion queue."""
    return SafeFileReader.read_json_file("reports/gpt/shadow_promotion_queue.json")


def get_recent_trades(hours: int = 6, limit: int = 200) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Get recent trades."""
    return SafeFileReader.tail_jsonl_file("reports/trades.jsonl", hours, limit)


def get_meta_log_sizes() -> Dict[str, Any]:
    """Get sizes and metadata for key log files."""
    log_files = {
        "counterfactual": "reports/meta/counterfactual_ledger.jsonl",
        "inaction": "reports/meta/inaction_scoring.jsonl",
        "fvg": "reports/meta/fair_value_gaps.jsonl",
        "opportunity_events": "reports/meta/opportunity_events.jsonl",
    }

    result = {}
    for name, path in log_files.items():
        info, error = SafeFileReader.get_file_info(path)
        if info:
            result[name] = info
        else:
            result[name] = {"error": error or "File not found"}

    return result
