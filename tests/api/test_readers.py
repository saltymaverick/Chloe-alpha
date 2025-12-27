"""
Unit tests for Chloe Alpha API readers.
"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from engine_alpha.api.readers import SafeFileReader, get_health_status


class TestSafeFileReader:
    """Test SafeFileReader functionality."""

    def test_whitelist_enforcement(self):
        """Test that only whitelisted files can be accessed."""
        # This should fail
        data, error = SafeFileReader.read_json_file("some/random/file.json")
        assert data is None
        assert "not in whitelist" in error

    def test_nonexistent_file(self):
        """Test handling of nonexistent files."""
        data, error = SafeFileReader.read_json_file("reports/nonexistent.json")
        assert data is None
        assert "not found" in error

    @patch('engine_alpha.api.readers.REPO_ROOT', Path('/tmp'))
    def test_valid_json_file(self):
        """Test reading valid JSON files."""
        # Create a temporary JSON file
        test_data = {"test": "value", "number": 42}

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_data, f)
            temp_path = Path(f.name)

        try:
            # Mock the whitelist to include our temp file
            with patch.object(SafeFileReader, 'WHITELISTED_FILES', {f.name}):
                data, error = SafeFileReader.read_json_file(f.name)
                assert error is None
                assert data == test_data
        finally:
            temp_path.unlink()

    @patch('engine_alpha.api.readers.REPO_ROOT', Path('/tmp'))
    def test_invalid_json_file(self):
        """Test handling of invalid JSON files."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content {")
            temp_path = Path(f.name)

        try:
            with patch.object(SafeFileReader, 'WHITELISTED_FILES', {f.name}):
                data, error = SafeFileReader.read_json_file(f.name)
                assert data is None
                assert "Invalid JSON" in error
        finally:
            temp_path.unlink()


class TestHealthStatus:
    """Test health status retrieval."""

    @patch('engine_alpha.api.readers.SafeFileReader.read_json_file')
    def test_health_from_primary_file(self, mock_read):
        """Test getting health from primary file."""
        mock_data = {"ok": True, "last_tick_ts": "2025-01-01T00:00:00Z"}
        mock_read.return_value = (mock_data, None)

        data, error = get_health_status()
        assert error is None
        assert data == mock_data

    @patch('engine_alpha.api.readers.SafeFileReader.read_json_file')
    def test_health_fallback_to_secondary(self, mock_read):
        """Test fallback to secondary health file."""
        mock_read.side_effect = [
            (None, "not found"),  # Primary fails
            ({"ok": False}, None)  # Secondary succeeds
        ]

        data, error = get_health_status()
        assert error is None
        assert data == {"ok": False}

    @patch('engine_alpha.api.readers.SafeFileReader.read_json_file')
    def test_health_no_data_available(self, mock_read):
        """Test when no health data is available."""
        mock_read.return_value = (None, "not found")

        data, error = get_health_status()
        assert data is None
        assert "No health data available" in error


if __name__ == "__main__":
    pytest.main([__file__])
