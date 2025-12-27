#!/usr/bin/env python3
"""
Chloe Logic Auditor - Automated consistency checker

Scans Chloe's codebase to identify logic inconsistencies, bugs, and structural issues
that could cause trading problems.

This tool performs static analysis and cross-references logic across modules.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class LogicAuditor:
    """Audits Chloe's codebase for logic consistency issues."""
    
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.issues: List[Dict[str, Any]] = []
        self.imports: Dict[str, Set[str]] = defaultdict(set)
        self.function_calls: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    
    def audit(self) -> Dict[str, Any]:
        """Run full audit and return report."""
        print("=" * 80)
        print("Chloe Logic Auditor")
        print("=" * 80)
        
        # Key files to audit
        key_files = [
            "engine_alpha/loop/autonomous_trader.py",
            "engine_alpha/loop/execute_trade.py",
            "engine_alpha/core/confidence_engine.py",
            "engine_alpha/core/regime.py",
            "engine_alpha/signals/signal_processor.py",
            "tools/backtest_harness.py",
        ]
        
        print(f"\n📂 Scanning {len(key_files)} key files...")
        
        for file_path in key_files:
            full_path = self.repo_root / file_path
            if full_path.exists():
                self._audit_file(full_path, file_path)
        
        # Cross-reference checks
        print(f"\n🔍 Running cross-reference checks...")
        self._check_regime_consistency()
        self._check_threshold_consistency()
        self._check_confidence_consistency()
        self._check_price_extraction()
        self._check_entry_exit_consistency()
        self._check_lab_mode_hacks()
        
        # Build report
        report = {
            "total_issues": len(self.issues),
            "critical": len([i for i in self.issues if i.get("severity") == "critical"]),
            "warnings": len([i for i in self.issues if i.get("severity") == "warning"]),
            "info": len([i for i in self.issues if i.get("severity") == "info"]),
            "issues": self.issues,
        }
        
        return report
    
    def _audit_file(self, file_path: Path, rel_path: str) -> None:
        """Audit a single file."""
        try:
            content = file_path.read_text()
            tree = ast.parse(content, filename=str(file_path))
            
            # Check for problematic patterns
            self._check_patterns(content, rel_path)
            self._check_imports(tree, rel_path)
            self._check_function_calls(tree, rel_path)
            
        except Exception as e:
            self._add_issue("error", rel_path, 0, f"Failed to parse file: {e}")
    
    def _check_patterns(self, content: str, file_path: str) -> None:
        """Check for problematic code patterns."""
        lines = content.split("\n")
        
        # Check for lab/backtest hacks
        lab_patterns = [
            (r"LAB_MODE|IS_LAB_MODE", "LAB_MODE flag found"),
            (r"ANALYSIS_MODE|IS_ANALYSIS_MODE", "ANALYSIS_MODE flag found"),
            (r"BACKTEST_MIN_CONF", "BACKTEST_MIN_CONF override found"),
            (r"BACKTEST_SIMPLE_EXITS", "BACKTEST_SIMPLE_EXITS flag found"),
        ]
        
        for pattern, message in lab_patterns:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line) and not line.strip().startswith("#"):
                    self._add_issue("warning", file_path, i, message, line.strip())
        
        # Check for hardcoded thresholds
        hardcoded_thresholds = [
            (r"0\.5[0-9]", "Possible hardcoded threshold"),
            (r"0\.6[0-9]", "Possible hardcoded threshold"),
            (r"0\.7[0-9]", "Possible hardcoded threshold"),
        ]
        
        # Check for regime gate inconsistencies
        if "regime_allows_entry" in content:
            # Check if it's called correctly
            if "regime_allows_entry" in content and "trend_down" in content:
                # Verify it only allows trend_down and high_vol
                if re.search(r'regime_allows_entry.*trend_up', content):
                    self._add_issue("warning", file_path, 0, "regime_allows_entry may allow trend_up")
        
        # Check for COUNCIL_WEIGHTS vs REGIME_BUCKET_WEIGHTS
        if "COUNCIL_WEIGHTS" in content and "REGIME_BUCKET_WEIGHTS" in content:
            # Check if both are used (inconsistency)
            if re.search(r'COUNCIL_WEIGHTS\[', content):
                self._add_issue("warning", file_path, 0, 
                               "COUNCIL_WEIGHTS used - should use REGIME_BUCKET_WEIGHTS for consistency")
    
    def _check_imports(self, tree: ast.AST, file_path: str) -> None:
        """Check import statements."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[file_path].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.imports[file_path].add(node.module)
    
    def _check_function_calls(self, tree: ast.AST, file_path: str) -> None:
        """Check function call patterns."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    self.function_calls[file_path].append((func_name, str(node.lineno)))
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                    self.function_calls[file_path].append((func_name, str(node.lineno)))
    
    def _check_regime_consistency(self) -> None:
        """Check that regime classification is consistent."""
        # Check if classify_regime is called with same args everywhere
        regime_calls = []
        for file_path, calls in self.function_calls.items():
            for func_name, line in calls:
                if "classify_regime" in func_name.lower():
                    regime_calls.append((file_path, line))
        
        if len(regime_calls) > 1:
            self._add_issue("info", "cross-reference", 0, 
                          f"classify_regime called in {len(regime_calls)} places - verify consistency")
    
    def _check_threshold_consistency(self) -> None:
        """Check threshold usage consistency."""
        # Check if compute_entry_min_conf is used everywhere
        threshold_usage = []
        for file_path, calls in self.function_calls.items():
            for func_name, line in calls:
                if "entry_min_conf" in func_name.lower() or "min_conf" in func_name.lower():
                    threshold_usage.append((file_path, func_name, line))
        
        # Check if entry_thresholds.json is loaded
        config_loaded = False
        for file_path in self.imports.keys():
            if "json" in self.imports[file_path] or "Path" in str(self.imports[file_path]):
                # Check if it reads entry_thresholds.json
                try:
                    content = (self.repo_root / file_path).read_text()
                    if "entry_thresholds.json" in content:
                        config_loaded = True
                except:
                    pass
        
        if not config_loaded:
            self._add_issue("warning", "config", 0, 
                          "entry_thresholds.json may not be loaded - check _load_entry_thresholds()")
    
    def _check_confidence_consistency(self) -> None:
        """Check confidence aggregation consistency."""
        # Check if decide() is called with regime_override
        decide_calls = []
        for file_path, calls in self.function_calls.items():
            for func_name, line in calls:
                if func_name == "decide":
                    decide_calls.append((file_path, line))
        
        # Check if REGIME_BUCKET_WEIGHTS is used
        weights_usage = []
        for file_path in self.imports.keys():
            try:
                content = (self.repo_root / file_path).read_text()
                if "REGIME_BUCKET_WEIGHTS" in content:
                    weights_usage.append(file_path)
            except:
                pass
        
        if len(weights_usage) == 0:
            self._add_issue("warning", "confidence_engine", 0,
                          "REGIME_BUCKET_WEIGHTS may not be used - check confidence aggregation")
    
    def _check_price_extraction(self) -> None:
        """Check that entry_px and exit_px are extracted correctly."""
        price_issues = []
        
        # Check execute_trade.py for price extraction
        execute_trade_path = self.repo_root / "engine_alpha/loop/execute_trade.py"
        if execute_trade_path.exists():
            content = execute_trade_path.read_text()
            if "entry_px" in content:
                # Check if it uses get_live_ohlcv
                if "get_live_ohlcv" not in content:
                    price_issues.append("execute_trade.py: entry_px may not use get_live_ohlcv")
            
            if "exit_px" in content:
                if "get_live_ohlcv" not in content:
                    price_issues.append("execute_trade.py: exit_px may not use get_live_ohlcv")
        
        for issue in price_issues:
            self._add_issue("warning", "execute_trade.py", 0, issue)
    
    def _check_entry_exit_consistency(self) -> None:
        """Check that entry and exit logic are consistent."""
        # Check if _try_open receives correct args
        try_open_calls = []
        for file_path, calls in self.function_calls.items():
            for func_name, line in calls:
                if func_name == "_try_open":
                    try_open_calls.append((file_path, line))
        
        if len(try_open_calls) > 0:
            # Check signature
            autonomous_trader_path = self.repo_root / "engine_alpha/loop/autonomous_trader.py"
            if autonomous_trader_path.exists():
                content = autonomous_trader_path.read_text()
                # Check if _try_open accepts regime parameter
                if "def _try_open" in content:
                    if "regime" not in content.split("def _try_open")[1].split(":")[0]:
                        self._add_issue("warning", "autonomous_trader.py", 0,
                                      "_try_open may not accept regime parameter")
    
    def _check_lab_mode_hacks(self) -> None:
        """Check for any remaining lab/backtest mode hacks."""
        hack_files = []
        
        for file_path in [
            "engine_alpha/loop/autonomous_trader.py",
            "engine_alpha/loop/execute_trade.py",
            "tools/backtest_harness.py",
        ]:
            full_path = self.repo_root / file_path
            if full_path.exists():
                content = full_path.read_text()
                hacks_found = []
                
                if "LAB_MODE" in content or "IS_LAB_MODE" in content:
                    hacks_found.append("LAB_MODE")
                if "ANALYSIS_MODE" in content or "IS_ANALYSIS_MODE" in content:
                    hacks_found.append("ANALYSIS_MODE")
                if "BACKTEST_MIN_CONF" in content:
                    hacks_found.append("BACKTEST_MIN_CONF")
                if "BACKTEST_SIMPLE_EXITS" in content:
                    hacks_found.append("BACKTEST_SIMPLE_EXITS")
                
                if hacks_found:
                    hack_files.append((file_path, hacks_found))
        
        for file_path, hacks in hack_files:
            self._add_issue("warning", file_path, 0,
                          f"Found lab/backtest hacks: {', '.join(hacks)}")
    
    def _add_issue(self, severity: str, file_path: str, line: int, message: str, code: str = "") -> None:
        """Add an issue to the report."""
        self.issues.append({
            "severity": severity,
            "file": file_path,
            "line": line,
            "message": message,
            "code": code,
        })
    
    def print_report(self, report: Dict[str, Any]) -> None:
        """Print human-readable report."""
        print(f"\n" + "=" * 80)
        print("AUDIT REPORT")
        print("=" * 80)
        print(f"\n📊 Summary:")
        print(f"   Total issues:  {report['total_issues']}")
        print(f"   Critical:      {report['critical']}")
        print(f"   Warnings:      {report['warnings']}")
        print(f"   Info:          {report['info']}")
        
        if report['total_issues'] == 0:
            print(f"\n✅ No issues found!")
            return
        
        # Group by severity
        critical = [i for i in report['issues'] if i['severity'] == 'critical']
        warnings = [i for i in report['issues'] if i['severity'] == 'warning']
        info = [i for i in report['issues'] if i['severity'] == 'info']
        
        if critical:
            print(f"\n🔴 CRITICAL ISSUES:")
            for issue in critical:
                print(f"   {issue['file']}:{issue['line']} - {issue['message']}")
                if issue.get('code'):
                    print(f"      Code: {issue['code']}")
        
        if warnings:
            print(f"\n⚠️  WARNINGS:")
            for issue in warnings[:10]:  # Limit to first 10
                print(f"   {issue['file']}:{issue['line']} - {issue['message']}")
                if issue.get('code'):
                    print(f"      Code: {issue['code']}")
            if len(warnings) > 10:
                print(f"   ... and {len(warnings) - 10} more warnings")
        
        if info:
            print(f"\nℹ️  INFO:")
            for issue in info[:5]:  # Limit to first 5
                print(f"   {issue['file']}:{issue['line']} - {issue['message']}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Chloe Logic Auditor")
    parser.add_argument("--repo-root", default=".", help="Repository root directory")
    parser.add_argument("--output", help="Output JSON report path")
    parser.add_argument("--json-only", action="store_true", help="Output only JSON")
    
    args = parser.parse_args()
    
    repo_root = Path(args.repo_root).resolve()
    auditor = LogicAuditor(repo_root)
    report = auditor.audit()
    
    if args.json_only:
        print(json.dumps(report, indent=2))
    else:
        auditor.print_report(report)
        
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w") as f:
                json.dump(report, f, indent=2)
            print(f"\n💾 Report saved to {output_path}")
    
    return 0 if report['critical'] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


