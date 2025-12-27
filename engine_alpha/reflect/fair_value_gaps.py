#!/usr/bin/env python3
"""
Fair Value Gap Detection and Tracking - Market Microstructure Intelligence

Detects and tracks Fair Value Gaps (FVGs) - structural price dislocations where
aggressive order flow creates imbalances that price often revisits to fill.

Observer-only initially: detects, classifies, and tracks FVGs for meta-analysis.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple, NamedTuple
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from pathlib import Path
import json
import math

from engine_alpha.core.regime import classify_regime
from engine_alpha.config.feature_flags import get_feature_registry


class FairValueGap(NamedTuple):
    """A detected Fair Value Gap"""
    timestamp: datetime
    symbol: str
    direction: str  # 'bullish' or 'bearish'
    upper_bound: float  # Upper price boundary of the gap
    lower_bound: float  # Lower price boundary of the gap
    gap_size: float  # Size of the gap (absolute price difference)
    gap_size_pct: float  # Size as percentage
    impulse_strength: float  # Strength of the initiating move (0.0-1.0)
    volume_spike: float  # Volume relative to recent average
    regime_at_creation: str  # Market regime when gap was created
    creation_candles: Dict[str, Any]  # The three candles that created the gap
    filled_percentage: float = 0.0  # How much of the gap has been filled (0.0-1.0)
    time_to_first_fill: Optional[int] = None  # Candles until first price touch
    fully_filled_at: Optional[datetime] = None  # When gap was completely filled
    status: str = "active"  # 'active', 'partially_filled', 'filled', 'expired'


@dataclass
class FVGDetector:
    """Detects and tracks Fair Value Gaps in real-time"""

    gap_log_file: Path = field(default_factory=lambda: Path("reports/fair_value_gaps.jsonl"))
    min_gap_size_pct: float = 0.1  # Minimum gap size (0.1% of price)
    max_gap_size_pct: float = 5.0  # Maximum gap size to avoid outliers
    lookback_candles: int = 50  # How many candles to keep for analysis
    gap_expiry_candles: int = 200  # Candles after which unfilled gap expires

    def __post_init__(self):
        self.gap_log_file.parent.mkdir(parents=True, exist_ok=True)
        self.recent_candles: Dict[str, List[Dict[str, Any]]] = {}
        # Track already logged gaps to prevent duplicate logging
        self._logged_gaps: Set[str] = set()
        # Rate limiting: last log timestamp per symbol+timeframe
        self._last_log_per_symbol: Dict[str, datetime] = {}
        # Cache of gap states for change detection
        self._gap_states: Dict[str, Dict[str, Any]] = self._load_gap_states()

    def _load_gap_states(self) -> Dict[str, Dict[str, Any]]:
        """Load gap states cache from disk"""
        cache_file = self.gap_log_file.parent / "fair_value_gaps_index.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text())
            except Exception:
                pass
        return {}

    def _save_gap_states(self) -> None:
        """Save gap states cache to disk"""
        cache_file = self.gap_log_file.parent / "fair_value_gaps_index.json"
        try:
            cache_file.write_text(json.dumps(self._gap_states, indent=2))
        except Exception:
            pass

    def detect_fvgs(self, symbol: str, candles: List[Dict[str, Any]],
                   current_regime: str) -> List[FairValueGap]:
        """
        Detect Fair Value Gaps in the latest candle data.

        Args:
            symbol: Trading symbol
            candles: Recent OHLCV candles (latest first)
            current_regime: Current market regime

        Returns:
            List of newly detected FVGs
        """
        if len(candles) < 3:
            return []

        # Update recent candles cache
        if symbol not in self.recent_candles:
            self.recent_candles[symbol] = []

        # Add new candles (avoid duplicates)
        existing_timestamps = {c.get('timestamp') for c in self.recent_candles[symbol]}
        new_candles = [c for c in candles if c.get('timestamp') not in existing_timestamps]

        self.recent_candles[symbol].extend(new_candles)
        self.recent_candles[symbol] = self.recent_candles[symbol][-self.lookback_candles:]

        # Sort by timestamp (oldest first for analysis)
        sorted_candles = sorted(self.recent_candles[symbol], key=lambda x: x.get('timestamp', 0))

        if len(sorted_candles) < 3:
            return []

        detected_gaps = []

        # Scan for FVGs in recent candles
        for i in range(len(sorted_candles) - 2):
            # Check for FVG at positions i, i+1, i+2
            gap = self._detect_fvg_at_position(sorted_candles, i, symbol, current_regime)
            if gap:
                detected_gaps.append(gap)

        # Update existing gaps with fill status
        self._update_gap_fill_status(symbol, sorted_candles)

        return detected_gaps

    def _detect_fvg_at_position(self, candles: List[Dict[str, Any]], position: int,
                              symbol: str, regime: str) -> Optional[FairValueGap]:
        """Detect FVG at specific candle position"""
        if position + 2 >= len(candles):
            return None

        c1 = candles[position]      # i-1 (first candle)
        c2 = candles[position + 1]  # i (middle candle)
        c3 = candles[position + 2]  # i+1 (third candle)

        # Extract OHLC
        c1_high = c1.get('high', 0)
        c1_low = c1.get('low', 0)
        c3_high = c3.get('high', 0)
        c3_low = c3.get('low', 0)

        # Check for bullish FVG: low(i+1) > high(i-1)
        if c3_low > c1_high:
            gap_size = c3_low - c1_high
            gap_size_pct = (gap_size / c1_high) * 100

            if self.min_gap_size_pct <= gap_size_pct <= self.max_gap_size_pct:
                return self._create_fvg(
                    symbol=symbol,
                    direction="bullish",
                    upper_bound=c3_low,
                    lower_bound=c1_high,
                    gap_size=gap_size,
                    gap_size_pct=gap_size_pct,
                    candles=[c1, c2, c3],
                    regime=regime,
                    timestamp=datetime.fromtimestamp(c3.get('timestamp', 0), tz=timezone.utc)
                )

        # Check for bearish FVG: high(i+1) < low(i-1)
        elif c3_high < c1_low:
            gap_size = c1_low - c3_high
            gap_size_pct = (gap_size / c1_low) * 100

            if self.min_gap_size_pct <= gap_size_pct <= self.max_gap_size_pct:
                return self._create_fvg(
                    symbol=symbol,
                    direction="bearish",
                    upper_bound=c1_low,
                    lower_bound=c3_high,
                    gap_size=gap_size,
                    gap_size_pct=gap_size_pct,
                    candles=[c1, c2, c3],
                    regime=regime,
                    timestamp=datetime.fromtimestamp(c3.get('timestamp', 0), tz=timezone.utc)
                )

        return None

    def _create_fvg(self, symbol: str, direction: str, upper_bound: float, lower_bound: float,
                   gap_size: float, gap_size_pct: float, candles: List[Dict[str, Any]],
                   regime: str, timestamp: datetime) -> FairValueGap:
        """Create a FairValueGap object with impulse strength analysis"""

        # Calculate impulse strength (size and momentum of the move)
        impulse_candle = candles[1]  # Middle candle (the dislocation)
        impulse_range = impulse_candle.get('high', 0) - impulse_candle.get('low', 0)
        impulse_body = abs(impulse_candle.get('close', 0) - impulse_candle.get('open', 0))

        # Relative to previous candle
        if len(candles) >= 2:
            prev_candle = candles[0]
            prev_range = prev_candle.get('high', 0) - prev_candle.get('low', 0)
            impulse_multiplier = impulse_range / prev_range if prev_range > 0 else 1.0
        else:
            impulse_multiplier = 1.0

        # Combine factors for impulse strength (0.0-1.0)
        range_factor = min(1.0, impulse_range / (upper_bound * 0.01))  # Relative to price
        body_factor = min(1.0, impulse_body / impulse_range) if impulse_range > 0 else 0.0
        multiplier_factor = min(1.0, impulse_multiplier / 3.0)  # Cap at 3x normal

        impulse_strength = (range_factor * 0.5) + (body_factor * 0.3) + (multiplier_factor * 0.2)

        # Volume spike analysis
        volume_spike = self._calculate_volume_spike(candles)

        return FairValueGap(
            timestamp=timestamp,
            symbol=symbol,
            direction=direction,
            upper_bound=upper_bound,
            lower_bound=lower_bound,
            gap_size=gap_size,
            gap_size_pct=gap_size_pct,
            impulse_strength=impulse_strength,
            volume_spike=volume_spike,
            regime_at_creation=regime,
            creation_candles={
                'candle_minus_1': candles[0],
                'candle_0': candles[1],
                'candle_plus_1': candles[2]
            }
        )

    def _calculate_volume_spike(self, candles: List[Dict[str, Any]]) -> float:
        """Calculate volume spike relative to recent average"""
        if len(candles) < 5:
            return 1.0

        # Use middle candle volume
        current_volume = candles[1].get('volume', 0)
        if current_volume == 0:
            return 1.0

        # Average of surrounding candles
        surrounding_volumes = []
        for i, c in enumerate(candles):
            if i != 1:  # Skip the middle candle
                vol = c.get('volume', 0)
                if vol > 0:
                    surrounding_volumes.append(vol)

        if not surrounding_volumes:
            return 1.0

        avg_surrounding_volume = sum(surrounding_volumes) / len(surrounding_volumes)
        return current_volume / avg_surrounding_volume if avg_surrounding_volume > 0 else 1.0

    def _update_gap_fill_status(self, symbol: str, candles: List[Dict[str, Any]]) -> None:
        """Update fill status for existing FVGs"""
        # Load existing gaps
        existing_gaps = self._load_existing_gaps(symbol)

        for gap in existing_gaps:
            if gap.status in ['filled', 'expired']:
                continue

            # Check if gap has been filled by recent price action
            filled_pct, time_to_fill, fully_filled = self._check_gap_fill_status(gap, candles)

            if fully_filled and not gap.fully_filled_at:
                # Update the gap as filled
                updated_gap = gap._replace(
                    filled_percentage=1.0,
                    time_to_first_fill=time_to_fill,
                    fully_filled_at=datetime.now(timezone.utc),
                    status="filled"
                )
                self._update_gap_in_log(gap, updated_gap)
            elif filled_pct > gap.filled_percentage:
                # Update partial fill
                updated_gap = gap._replace(
                    filled_percentage=filled_pct,
                    time_to_first_fill=time_to_fill if not gap.time_to_first_fill else gap.time_to_first_fill
                )
                self._update_gap_in_log(gap, updated_gap)

            # Check for expiry
            candles_since_creation = len([c for c in candles
                                        if c.get('timestamp', 0) > gap.timestamp.timestamp()])
            if candles_since_creation > self.gap_expiry_candles and gap.status == "active":
                updated_gap = gap._replace(status="expired")
                self._update_gap_in_log(gap, updated_gap)

    def _check_gap_fill_status(self, gap: FairValueGap,
                             candles: List[Dict[str, Any]]) -> Tuple[float, Optional[int], bool]:
        """Check how much of a gap has been filled by price action"""
        filled_pct = 0.0
        time_to_fill = None
        fully_filled = False

        gap_range = gap.upper_bound - gap.lower_bound

        for i, candle in enumerate(candles):
            high = candle.get('high', 0)
            low = candle.get('low', 0)

            # Check if candle overlaps with gap
            overlap_high = min(high, gap.upper_bound)
            overlap_low = max(low, gap.lower_bound)
            overlap_size = max(0, overlap_high - overlap_low)

            candle_fill_pct = overlap_size / gap_range if gap_range > 0 else 0
            filled_pct = max(filled_pct, candle_fill_pct)

            # Track time to first fill
            if time_to_fill is None and candle_fill_pct > 0:
                time_to_fill = i + 1  # +1 because we want candles after creation

            # Check for complete fill
            if filled_pct >= 1.0:
                fully_filled = True
                break

        return filled_pct, time_to_fill, fully_filled

    def _load_existing_gaps(self, symbol: str) -> List[FairValueGap]:
        """Load existing FVGs for a symbol"""
        gaps = []
        if not self.gap_log_file.exists():
            return gaps

        with self.gap_log_file.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("symbol") == symbol:
                        # Reconstruct FairValueGap from stored data
                        gap = FairValueGap(
                            timestamp=datetime.fromisoformat(record["timestamp"]),
                            symbol=record["symbol"],
                            direction=record["direction"],
                            upper_bound=record["upper_bound"],
                            lower_bound=record["lower_bound"],
                            gap_size=record["gap_size"],
                            gap_size_pct=record["gap_size_pct"],
                            impulse_strength=record["impulse_strength"],
                            volume_spike=record["volume_spike"],
                            regime_at_creation=record["regime_at_creation"],
                            creation_candles=record["creation_candles"],
                            filled_percentage=record.get("filled_percentage", 0.0),
                            time_to_first_fill=record.get("time_to_first_fill"),
                            fully_filled_at=datetime.fromisoformat(record["fully_filled_at"]) if record.get("fully_filled_at") else None,
                            status=record.get("status", "active")
                        )
                        gaps.append(gap)
                except (json.JSONDecodeError, KeyError):
                    continue

        return gaps

    def _update_gap_in_log(self, old_gap: FairValueGap, new_gap: FairValueGap) -> None:
        """Update a gap in the log file (simplified - would need proper file editing in production)"""
        # For now, just append the updated version
        # In production, you'd need to update the existing record
        record = {
            "timestamp": new_gap.timestamp.isoformat(),
            "symbol": new_gap.symbol,
            "direction": new_gap.direction,
            "upper_bound": new_gap.upper_bound,
            "lower_bound": new_gap.lower_bound,
            "gap_size": new_gap.gap_size,
            "gap_size_pct": new_gap.gap_size_pct,
            "impulse_strength": new_gap.impulse_strength,
            "volume_spike": new_gap.volume_spike,
            "regime_at_creation": new_gap.regime_at_creation,
            "creation_candles": new_gap.creation_candles,
            "filled_percentage": new_gap.filled_percentage,
            "time_to_first_fill": new_gap.time_to_first_fill,
            "fully_filled_at": new_gap.fully_filled_at.isoformat() if new_gap.fully_filled_at else None,
            "status": new_gap.status,
            "updated": True
        }

        with self.gap_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_fvg(self, gap: FairValueGap, current_timeframe: str = "15m") -> None:
        """Log a detected FVG with rate limiting and change detection"""
        # Create unique key for this gap
        gap_key = f"{gap.symbol}_{current_timeframe}_{gap.direction}_{gap.upper_bound}_{gap.lower_bound}_{gap.timestamp.isoformat()}"

        # Rate limiting: max 1 log per symbol+timeframe per candle timestamp
        rate_limit_key = f"{gap.symbol}_{current_timeframe}"
        current_time = datetime.now(timezone.utc)

        # Check rate limit (allow logging once per symbol+timeframe)
        if rate_limit_key in self._last_log_per_symbol:
            last_log_time = self._last_log_per_symbol[rate_limit_key]
            # Allow logging if it's been more than 1 second (avoids per-tick spam)
            if (current_time - last_log_time).total_seconds() < 1.0:
                return
        self._last_log_per_symbol[rate_limit_key] = current_time

        # Check if this is a new gap or significant status change
        should_log = False
        previous_state = self._gap_states.get(gap_key, {})

        if not previous_state:
            # New gap - always log
            should_log = True
        else:
            # Check for meaningful fill status changes
            prev_fill = previous_state.get("filled_percentage", 0)
            current_fill = gap.filled_percentage

            # Log on significant fill thresholds: 0%→25%, 25%→50%, 50%→75%, 75%→100%
            fill_thresholds = [(0, 25), (25, 50), (50, 75), (75, 100)]
            for min_fill, max_fill in fill_thresholds:
                if prev_fill < min_fill and current_fill >= min_fill:
                    should_log = True
                    break
                if prev_fill < max_fill and current_fill >= max_fill:
                    should_log = True
                    break

            # Also log if gap becomes fully filled
            if current_fill >= 100 and prev_fill < 100:
                should_log = True

        if not should_log:
            return

        # Update cache with current state
        self._gap_states[gap_key] = {
            "filled_percentage": gap.filled_percentage,
            "status": gap.status,
            "last_updated": current_time.isoformat()
        }
        self._save_gap_states()

        # Create log record
        record = {
            "timestamp": gap.timestamp.isoformat(),
            "symbol": gap.symbol,
            "timeframe": current_timeframe,
            "direction": gap.direction,
            "upper_bound": gap.upper_bound,
            "lower_bound": gap.lower_bound,
            "gap_size": gap.gap_size,
            "gap_size_pct": gap.gap_size_pct,
            "impulse_strength": gap.impulse_strength,
            "volume_spike": gap.volume_spike,
            "regime_at_creation": gap.regime_at_creation,
            "creation_candles": gap.creation_candles,
            "filled_percentage": gap.filled_percentage,
            "time_to_first_fill": gap.time_to_first_fill,
            "fully_filled_at": gap.fully_filled_at.isoformat() if gap.fully_filled_at else None,
            "status": gap.status,
            "log_reason": "new_gap" if not previous_state else f"fill_{int(prev_fill)}_to_{int(current_fill)}"
        }

        with self.gap_log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def get_fvg_statistics(self, symbol: str, days_back: int = 30) -> Dict[str, Any]:
        """Get comprehensive FVG statistics for analysis"""
        gaps = self._load_existing_gaps(symbol)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        recent_gaps = [g for g in gaps if g.timestamp >= cutoff]

        if not recent_gaps:
            return {"status": "no_data", "symbol": symbol}

        # Basic counts
        total_gaps = len(recent_gaps)
        bullish_gaps = len([g for g in recent_gaps if g.direction == "bullish"])
        bearish_gaps = len([g for g in recent_gaps if g.direction == "bearish"])

        # Fill statistics
        filled_gaps = [g for g in recent_gaps if g.status == "filled"]
        fill_rate = len(filled_gaps) / total_gaps if total_gaps > 0 else 0

        avg_time_to_fill = None
        if filled_gaps:
            fill_times = [g.time_to_first_fill for g in filled_gaps if g.time_to_first_fill]
            if fill_times:
                avg_time_to_fill = sum(fill_times) / len(fill_times)

        # Size statistics
        gap_sizes = [g.gap_size_pct for g in recent_gaps]
        avg_gap_size = sum(gap_sizes) / len(gap_sizes) if gap_sizes else 0

        # Impulse strength
        impulse_strengths = [g.impulse_strength for g in recent_gaps]
        avg_impulse = sum(impulse_strengths) / len(impulse_strengths) if impulse_strengths else 0

        # Regime distribution
        regime_counts = {}
        for gap in recent_gaps:
            regime = gap.regime_at_creation
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        return {
            "symbol": symbol,
            "analysis_period_days": days_back,
            "total_gaps": total_gaps,
            "bullish_gaps": bullish_gaps,
            "bearish_gaps": bearish_gaps,
            "fill_rate": fill_rate,
            "avg_time_to_fill_candles": avg_time_to_fill,
            "avg_gap_size_pct": avg_gap_size,
            "avg_impulse_strength": avg_impulse,
            "regime_distribution": regime_counts,
            "gaps_by_status": {
                "active": len([g for g in recent_gaps if g.status == "active"]),
                "partially_filled": len([g for g in recent_gaps if g.status == "partially_filled"]),
                "filled": len([g for g in recent_gaps if g.status == "filled"]),
                "expired": len([g for g in recent_gaps if g.status == "expired"])
            }
        }


# Global FVG detector instance
fvg_detector = FVGDetector()


def detect_and_log_fvgs(symbol: str, candles: List[Dict[str, Any]],
                       current_regime: str, timeframe: str = "15m") -> List[FairValueGap]:
    """Convenience function to detect and log FVGs"""
    registry = get_feature_registry()
    if registry.is_off("fvg_detector"):
        return []

    gaps = fvg_detector.detect_fvgs(symbol, candles, current_regime)

    # Log detected gaps with rate limiting and change detection
    for gap in gaps:
        fvg_detector.log_fvg(gap, timeframe)

    return gaps


if __name__ == "__main__":
    # Example usage
    print("Fair Value Gap Detector initialized")

    # Test with sample candle data
    sample_candles = [
        {"timestamp": 1640995200, "open": 100, "high": 105, "low": 95, "close": 102, "volume": 1000},
        {"timestamp": 1640995260, "open": 102, "high": 110, "low": 101, "close": 108, "volume": 1500},
        {"timestamp": 1640995320, "open": 108, "high": 112, "low": 106, "close": 110, "volume": 1200},
        # This creates a bullish FVG: low(candle3) > high(candle1) → 106 > 105
    ]

    gaps = detect_and_log_fvgs("TESTUSD", sample_candles, current_regime="chop", timeframe="15m")
    print(f"Detected {len(gaps)} FVGs")
    if gaps:
        print(f"Gap: {gaps[0].direction} {gaps[0].gap_size_pct:.2f}%")

    stats = fvg_detector.get_fvg_statistics("TESTUSD")
    print(f"Statistics: {stats}")
