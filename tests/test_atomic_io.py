"""
Test atomic I/O utilities.
"""

import json
import os
import tempfile
from pathlib import Path
import pytest
from engine_alpha.core.atomic_io import atomic_write_json, atomic_append_jsonl


def test_atomic_write_json():
    """Test that atomic_write_json writes valid JSON and doesn't leave .tmp file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "test.json"
        test_data = {"key": "value", "number": 42, "nested": {"a": 1, "b": 2}}
        
        # Write atomically
        atomic_write_json(test_path, test_data)
        
        # Verify file exists
        assert test_path.exists()
        
        # Verify no .tmp file left behind
        tmp_files = list(Path(tmpdir).glob("*.tmp"))
        assert len(tmp_files) == 0, f"Found temp files: {tmp_files}"
        
        # Verify content is valid JSON
        with test_path.open("r") as f:
            loaded = json.load(f)
        
        assert loaded == test_data
        
        # Verify parent directory was created
        nested_path = Path(tmpdir) / "nested" / "deep" / "test.json"
        atomic_write_json(nested_path, test_data)
        assert nested_path.exists()


def test_atomic_append_jsonl():
    """Test that atomic_append_jsonl appends single-line JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_path = Path(tmpdir) / "test.jsonl"
        
        # Append first entry
        atomic_append_jsonl(test_path, {"ts": "2024-01-01T00:00:00Z", "event": "start"})
        
        # Append second entry
        atomic_append_jsonl(test_path, {"ts": "2024-01-01T00:01:00Z", "event": "end"})
        
        # Verify file exists
        assert test_path.exists()
        
        # Read and verify entries
        with test_path.open("r") as f:
            lines = f.readlines()
        
        assert len(lines) == 2
        
        # Verify each line is valid JSON
        entry1 = json.loads(lines[0].strip())
        entry2 = json.loads(lines[1].strip())
        
        assert entry1["event"] == "start"
        assert entry2["event"] == "end"
        
        # Verify parent directory was created
        nested_path = Path(tmpdir) / "nested" / "deep" / "test.jsonl"
        atomic_append_jsonl(nested_path, {"test": "data"})
        assert nested_path.exists()

