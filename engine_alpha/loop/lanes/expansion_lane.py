"""
Expansion Lane - Post-Break Continuation Trading

Catches post-break continuation moves that begin inside chop, without converting CORE into a scalper.
Trades only when: expansion impulse + pullback confirmation + re-acceleration.
"""

from __future__ import annotations

from typing import Tuple, Optional, Dict, Any, List, Literal
from datetime import datetime, timezone, timedelta
from enum import Enum
from .base import Lane, LaneContext, LaneResult, LaneDecision


class ExpansionState(Enum):
    """State machine for expansion entry tracking"""
    IDLE = "idle"
    IMPULSE_DETECTED = "impulse_detected"
    PULLBACK_TRACKING = "pullback_tracking"
    ARMED = "armed"
    IN_POSITION = "in_position"


class ExpansionLane(Lane):
    """Expansion lane for post-break continuation trading"""

    LANE_ID = "expansion"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.default_risk_mult = config.get("default_risk_mult", 0.05)

        # CORE-safe risk: 0.25x CORE risk until proven
        self.core_risk_mult = config.get("core_risk_mult", 0.10)
        self.risk_mult = 0.25  # 25% of CORE risk

        # Entry parameters
        self.impulse_strength_min = 1.3  # Expansion impulse threshold
        self.pullback_atr_min = 0.3  # Minimum pullback ATR
        self.pullback_atr_max = 0.8  # Maximum pullback ATR
        self.reaccel_window_bars = 8  # Max bars for B+C confirmation
        self.invalidation_atr = 0.6  # Pullback invalidation line
        
        # Event-gated entry (for chop regime with expansion_event)
        self.EXP_EVENT_MIN_CONF = 0.58  # Lower threshold for event-gated entries
        self.EXP_EVENT_MIN_STRENGTH = 1.30  # Minimum strength for event-only entry
        self.EXP_EVENT_REQUIRE_FOLLOW_THROUGH = False  # Allow strength-only if >= 1.5

        # Cost sanity check
        self.expected_move_atr = 0.8  # Conservative continuation expectation
        self.cost_buffer_pct = 2.5  # Require expected_move_pct >= 2.5 * cost_pct

        # Guardrails (CORE-safe by construction)
        self.min_hold_minutes = 20  # Never behave like scalper
        self.cooldown_minutes = 60  # Cooldown after exit
        self.max_positions_per_symbol = 1  # One position per symbol

        # Exit parameters
        self.tp1_atr = 1.0  # Take 30-50% off at +1.0 ATR
        self.atr_trail_mult = 1.2  # Trail remaining with 1.2 ATR
        self.momentum_decay_bars = 2  # 2 consecutive closes against direction
        self.atr_decay_ratio = 0.9  # ATR contraction threshold
        self.time_stop_hours = 24  # Exit if bars_open >= 24 (1 day on 1h)

        # State tracking per symbol
        self.symbol_states: Dict[str, Dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "Expansion"

    @property
    def description(self) -> str:
        return "Post-break continuation trading (CORE-safe)"

    def is_allowed(self, ctx: LaneContext) -> Tuple[bool, str]:
        """
        Check if expansion lane is allowed.
        Require explicit allow_expansion permission.
        """
        allow_expansion = ctx.policy_state.get("allow_expansion", False)
        if not allow_expansion:
            return False, "expansion_requires_explicit_allow_expansion_permission"

        # Allow quarantined symbols - expansion can be an earn-back mechanism
        return True, "expansion_allowed"

    def execute_tick(self, ctx: LaneContext) -> Optional[LaneResult]:
        """
        Execute expansion trading logic for post-break continuation.
        """
        from engine_alpha.loop.lanes.base import LaneResult, LaneDecision

        # Check if we can trade based on permissions and guardrails
        permission_check = self.is_allowed(ctx)
        if not permission_check[0]:
            print(f"EXPANSION_BLOCKED_PERMISSION: {ctx.symbol} {permission_check[1]}")
            return LaneResult(
                decision=LaneDecision.SKIP,
                reason=permission_check[1],
                risk_mult=self.default_risk_mult,
                tags=["expansion", "blocked", "permission"],
                metadata={"blocked_reason": "permission"}
            )

        print(f"EXPANSION_EXECUTE_TICK_START: {ctx.symbol} permission_ok, checking guardrails")

        # Check guardrails (position limits, cooldowns, etc.)
        guardrail_check = self._check_guardrails(ctx)
        if not guardrail_check[0]:
            print(f"EXPANSION_BLOCKED_GUARDRAIL: {ctx.symbol} {guardrail_check[1]}")
            return LaneResult(
                decision=LaneDecision.SKIP,
                reason=guardrail_check[1],
                risk_mult=self.default_risk_mult,
                tags=["expansion", "blocked", f"blocked_reason={guardrail_check[2]}"],
                metadata={"blocked_reason": guardrail_check[2]}
            )

        print(f"EXPANSION_EXECUTE_TICK_START: {ctx.symbol} guardrails_ok, evaluating entry")

        # Check global allowance
        allowed, reason = self.is_allowed(ctx)
        if not allowed:
            return LaneResult(
                decision=LaneDecision.SKIP,
                reason=reason,
                risk_mult=self.default_risk_mult,
                tags=["expansion", "blocked", "blocked_reason=permission"],
                metadata={"blocked_reason": "permission"}
            )

        # Check guardrails
        guardrail_check = self._check_guardrails(ctx)
        if not guardrail_check[0]:
            return LaneResult(
                decision=LaneDecision.SKIP,
                reason=guardrail_check[1],
                risk_mult=self.default_risk_mult,
                tags=["expansion", "blocked", f"blocked_reason={guardrail_check[2]}"],
                metadata={"blocked_reason": guardrail_check[2]}
            )

        # Check if we have an existing position
        if ctx.position:
            return self._evaluate_position_exit(ctx)

        # No position - check for entry
        return self._evaluate_entry_opportunity(ctx)

    def _evaluate_entry_opportunity(self, ctx: LaneContext) -> Optional[LaneResult]:
        """
        Evaluate if expansion lane should open a position using state machine.

        Entry Logic: "Expansion → Pullback → Re-Accel"
        State machine: IDLE → IMPULSE_DETECTED → PULLBACK_TRACKING → ARMED → IN_POSITION
        """
        from engine_alpha.loop.lanes.base import LaneResult, LaneDecision

        symbol = ctx.symbol
        current_state = self._get_symbol_state(symbol)

        # Get required data
        signal_vector = ctx.signal_vector
        market_data = ctx.market_data
        regime_data = ctx.regime or {}

        atr = signal_vector.get("atr", 0)
        if atr <= 0:
            return None

        # Handle regime_data being either a string or dict
        if isinstance(regime_data, str):
            micro_regime = ""  # String regime doesn't have micro_regime
            regime_str = regime_data
        elif isinstance(regime_data, dict):
            micro_regime = regime_data.get("micro_regime", "")
            regime_str = regime_data.get("regime", "")
        else:
            micro_regime = ""
            regime_str = ""
        expansion_event = market_data.get("expansion_event", False)

        print(f"EXPANSION_STATE_MACHINE: {symbol} state={current_state['state'].value}, micro_regime={micro_regime}, expansion_event={expansion_event}")

        # State machine transitions
        if current_state["state"] == ExpansionState.IDLE:
            # Trigger A: Expansion impulse
            impulse_strength = self._calculate_impulse_strength(ctx)
            print(f"EXPANSION_STATE_CHECK: {symbol} impulse_strength={impulse_strength:.2f}, micro_regime={micro_regime}, min_required={self.impulse_strength_min}")
            if (impulse_strength >= self.impulse_strength_min and
                micro_regime != "dead_chop"):
                self._update_symbol_state(symbol, ExpansionState.IMPULSE_DETECTED,
                                        impulse_ts=datetime.now(timezone.utc),
                                        impulse_strength=impulse_strength,
                                        break_level=self._get_break_level(ctx))
                print(f"EXPANSION_TRIGGER_A: {symbol} impulse_strength={impulse_strength:.2f}")
            else:
                print(f"EXPANSION_BLOCKED_IDLE: {symbol} impulse_too_weak_or_dead_chop")

        elif current_state["state"] == ExpansionState.IMPULSE_DETECTED:
            # Wait for Trigger B: Pullback confirmation
            pullback_ok = self._check_pullback_confirmation(ctx, current_state)
            print(f"EXPANSION_PULLBACK_CHECK: {symbol} pullback_ok={pullback_ok}")
            if pullback_ok:
                self._update_symbol_state(symbol, ExpansionState.PULLBACK_TRACKING,
                                        pullback_low=self._get_current_price(ctx),
                                        pullback_ts=datetime.now(timezone.utc))
                print(f"EXPANSION_TRIGGER_B: {symbol} pullback confirmed")

        elif current_state["state"] == ExpansionState.PULLBACK_TRACKING:
            # Wait for Trigger C: Re-acceleration within window
            reaccel_ok = self._check_reacceleration(ctx, current_state)
            print(f"EXPANSION_REACCEL_CHECK: {symbol} reaccel_ok={reaccel_ok}")
            if reaccel_ok:
                # Check cost sanity
                cost_ok = self._check_cost_sanity(ctx)
                print(f"EXPANSION_COST_CHECK: {symbol} cost_ok={cost_ok}")
                if cost_ok:
                    self._update_symbol_state(symbol, ExpansionState.ARMED,
                                            reaccel_trigger=self._get_reaccel_type(ctx))
                    print(f"EXPANSION_TRIGGER_C: {symbol} re-acceleration confirmed, cost sanity passed")
                else:
                    print(f"EXPANSION_COST_BLOCK: {symbol} failed cost sanity check")
                    self._reset_symbol_state(symbol)
                    return None

        elif current_state["state"] == ExpansionState.ARMED:
            # Execute entry when all conditions met
            return self._execute_entry(ctx, current_state)

        return None

    def _get_symbol_state(self, symbol: str) -> Dict[str, Any]:
        """Get or initialize state tracking for a symbol"""
        if symbol not in self.symbol_states:
            self.symbol_states[symbol] = {
                "state": ExpansionState.IDLE,
                "impulse_ts": None,
                "impulse_strength": 0.0,
                "break_level": 0.0,
                "pullback_low": 0.0,
                "pullback_ts": None,
                "reaccel_trigger": None,
                "max_wait_bars": self.reaccel_window_bars
            }
        return self.symbol_states[symbol]

    def _update_symbol_state(self, symbol: str, new_state: ExpansionState, **updates):
        """Update symbol state with new values"""
        state = self._get_symbol_state(symbol)
        state["state"] = new_state
        state.update(updates)
        self.symbol_states[symbol] = state

    def _reset_symbol_state(self, symbol: str):
        """Reset symbol state to IDLE"""
        self.symbol_states[symbol] = {
            "state": ExpansionState.IDLE,
            "impulse_ts": None,
            "impulse_strength": 0.0,
            "break_level": 0.0,
            "pullback_low": 0.0,
            "pullback_ts": None,
            "reaccel_trigger": None,
            "max_wait_bars": self.reaccel_window_bars
        }

    def _calculate_impulse_strength(self, ctx: LaneContext) -> float:
        """Calculate expansion impulse strength"""
        signal_vector = ctx.signal_vector
        market_data = ctx.market_data

        # Use expansion_strength if available, otherwise calculate
        expansion_strength = market_data.get("expansion_strength", 0.0)
        if expansion_strength > 0:
            return expansion_strength

        # Calculate from return_last_N / ATR
        atr = signal_vector.get("atr", 0)
        if atr <= 0:
            return 0.0

        closes = market_data.get("closes", [])
        if len(closes) < 2:
            return 0.0

        # Simple return calculation (can be made more sophisticated)
        recent_return = abs((closes[-1] - closes[-2]) / closes[-2])
        return recent_return / atr

    def _get_break_level(self, ctx: LaneContext) -> float:
        """Get the impulse break level (high for long, low for short)"""
        direction = ctx.signal_vector.get("direction", 0)
        current_price = self._get_current_price(ctx)

        # For simplicity, use current price as break level
        # In full implementation, this would be the actual impulse high/low
        return current_price

    def _get_current_price(self, ctx: LaneContext) -> float:
        """Get current price from context"""
        return ctx.signal_vector.get("close", 0)

    def _check_pullback_confirmation(self, ctx: LaneContext, state: Dict[str, Any]) -> bool:
        """Check if price has pulled back within acceptable ATR range"""
        current_price = self._get_current_price(ctx)
        break_level = state.get("break_level", 0)
        atr = ctx.signal_vector.get("atr", 0)

        if break_level <= 0 or atr <= 0:
            return False

        direction = ctx.signal_vector.get("direction", 0)
        if direction == 0:
            return False

        # Calculate retracement from break level
        if direction > 0:  # Long: check pullback from high
            retracement_atr = (break_level - current_price) / atr
            invalidation_line = break_level - (self.invalidation_atr * atr)
            pullback_ok = (current_price >= invalidation_line and
                          self.pullback_atr_min <= retracement_atr <= self.pullback_atr_max)
        else:  # Short: check pullback from low
            retracement_atr = (current_price - break_level) / atr
            invalidation_line = break_level + (self.invalidation_atr * atr)
            pullback_ok = (current_price <= invalidation_line and
                          self.pullback_atr_min <= retracement_atr <= self.pullback_atr_max)

        return pullback_ok

    def _check_reacceleration(self, ctx: LaneContext, state: Dict[str, Any]) -> bool:
        """Check for re-acceleration confirmation within time window"""
        impulse_ts = state.get("impulse_ts")
        if not impulse_ts:
            return False

        # Check time window
        now = datetime.now(timezone.utc)
        bars_elapsed = (now - impulse_ts).total_seconds() / 3600.0 * (24.0 / self._get_timeframe_hours(ctx))
        if bars_elapsed > self.reaccel_window_bars:
            self._reset_symbol_state(ctx.symbol)
            return False

        # Check re-acceleration triggers (any one)
        reaccel_type = self._get_reaccel_type(ctx)
        return reaccel_type is not None

    def _get_reaccel_type(self, ctx: LaneContext) -> Optional[str]:
        """Get re-acceleration trigger type"""
        signal_vector = ctx.signal_vector
        market_data = ctx.market_data
        direction = signal_vector.get("direction", 0)

        if direction == 0:
            return None

        # 1. Close crosses above EMA(9) after pullback
        ema9 = signal_vector.get("ema9", 0)
        current_close = self._get_current_price(ctx)
        if ema9 > 0:
            prev_close = market_data.get("closes", [])[-2] if len(market_data.get("closes", [])) >= 2 else 0
            if direction > 0 and prev_close <= ema9 and current_close > ema9:
                return "ema9_cross"
            elif direction < 0 and prev_close >= ema9 and current_close < ema9:
                return "ema9_cross"

        # 2. RSI(7) crosses above 50 after pullback
        rsi7 = signal_vector.get("rsi7", 50)
        if ((direction > 0 and rsi7 > 50) or (direction < 0 and rsi7 < 50)):
            return "rsi50_cross"

        # 3. Bar return > 0.25*ATR in breakout direction
        atr = signal_vector.get("atr", 0)
        if atr > 0:
            closes = market_data.get("closes", [])
            if len(closes) >= 2:
                bar_return = abs(current_close - closes[-2]) / closes[-2]
                if bar_return > (0.25 * atr / current_close):  # Normalized
                    return "bar_return_atr"

        return None

    def _check_cost_sanity(self, ctx: LaneContext) -> bool:
        """Check if expected move justifies trading costs"""
        atr = ctx.signal_vector.get("atr", 0)
        current_price = self._get_current_price(ctx)

        if atr <= 0 or current_price <= 0:
            return False

        # Calculate expected move
        expected_move_pct = (self.expected_move_atr * atr) / current_price * 100

        # Estimate costs (simplified)
        fees_bps = 0.1  # 0.1%
        slip_bps = 0.2  # 0.2%
        spread_bps = 0.1  # 0.1%
        cost_pct = (fees_bps + slip_bps + spread_bps) / 100

        return expected_move_pct >= (self.cost_buffer_pct * cost_pct)

    def _check_guardrails(self, ctx: LaneContext) -> Tuple[bool, str, str]:
        """Check CORE-safe guardrails"""
        # Min hold time check
        last_trade_time = self._get_last_expansion_trade_time(ctx.symbol)
        if last_trade_time:
            now = datetime.now(timezone.utc)
            minutes_since_trade = (now - last_trade_time).total_seconds() / 60.0
            if minutes_since_trade < self.min_hold_minutes:
                return False, f"expansion_cooldown_{minutes_since_trade:.1f}_min", "min_hold"

        # Cooldown check
        if last_trade_time:
            now = datetime.now(timezone.utc)
            cooldown_end = last_trade_time + timedelta(minutes=self.cooldown_minutes)
            if now < cooldown_end:
                return False, f"expansion_cooldown_active_{self.cooldown_minutes}_min", "cooldown"

        # Max positions per symbol
        if self._count_open_positions(ctx.symbol) >= self.max_positions_per_symbol:
            return False, f"expansion_max_positions_{self.max_positions_per_symbol}", "max_positions"

        return True, "", ""

    def _execute_entry(self, ctx: LaneContext, state: Dict[str, Any]) -> Optional[LaneResult]:
        """Execute the actual entry"""
        from engine_alpha.loop.lanes.base import LaneResult, LaneDecision

        direction = ctx.signal_vector.get("direction", 0)
        confidence = ctx.signal_vector.get("confidence", 0.0)

        if direction == 0:
            return None

        # Transition to IN_POSITION
        self._update_symbol_state(ctx.symbol, ExpansionState.IN_POSITION)

        return LaneResult(
            decision=LaneDecision.OPEN,
            reason=f"expansion_entry: impulse={state['impulse_strength']:.2f}, pullback_atr={self._calculate_pullback_atr(ctx, state):.2f}, reaccel={state.get('reaccel_trigger', 'unknown')}",
            risk_mult=self.risk_mult,
            tags=["expansion", f"expansion_state={ExpansionState.IN_POSITION.value}",
                  f"impulse_strength={state['impulse_strength']:.2f}",
                  f"pullback_atr={self._calculate_pullback_atr(ctx, state):.2f}",
                  f"reaccel_trigger={state.get('reaccel_trigger', 'unknown')}"],
            metadata={
                "entry_price": self._get_current_price(ctx),
                "direction": direction,
                "break_level": state["break_level"],
                "impulse_strength": state["impulse_strength"],
                "pullback_atr": self._calculate_pullback_atr(ctx, state),
                "reaccel_trigger": state.get("reaccel_trigger"),
                "atr_at_entry": ctx.signal_vector.get("atr", 0),
                "min_hold_seconds": self.min_hold_minutes * 60,
                "cooldown_minutes": self.cooldown_minutes
            }
        )

    def _calculate_pullback_atr(self, ctx: LaneContext, state: Dict[str, Any]) -> float:
        """Calculate pullback distance in ATR units"""
        current_price = self._get_current_price(ctx)
        break_level = state.get("break_level", 0)
        atr = ctx.signal_vector.get("atr", 0)

        if break_level <= 0 or atr <= 0:
            return 0.0

        return abs(current_price - break_level) / atr

    def _get_timeframe_hours(self, ctx: LaneContext) -> float:
        """Get timeframe in hours for bar calculations"""
        timeframe = ctx.timeframe
        if timeframe.endswith("h"):
            return float(timeframe[:-1])
        elif timeframe.endswith("m"):
            return float(timeframe[:-1]) / 60.0
        elif timeframe.endswith("d"):
            return float(timeframe[:-1]) * 24.0
        return 1.0  # Default to 1h

    def _evaluate_strict_expansion_entry(self, ctx: LaneContext, direction: float,
                                       confidence: float) -> Optional[LaneResult]:
        """
        Strict expansion entry: Original logic requiring full regime transition.
        """
        from engine_alpha.loop.lanes.base import LaneResult, LaneDecision

        # Determine prev_regime and current regime
        prev_regime = self._get_prev_regime(ctx)
        current_regime = ctx.regime

        # Require transition: prev_regime == "chop" AND current_regime in expansion regimes
        allowed_expansion_regimes = {"trend_up", "trend_down", "high_vol"}
        if prev_regime != "chop" or current_regime not in allowed_expansion_regimes:
            return None

        # Break detection: compute range from prior 20 bars
        break_detected, break_level = self._detect_break(ctx, direction)
        if not break_detected:
            return None

        # Confirmation signals (at least one must pass)
        confirmation_type = self._check_confirmation(ctx, direction, break_level)
        if not confirmation_type:
            return None

        # Late entry block: distance_from_break <= 0.6 ATR (stricter for breakout mode)
        distance_ok = self._check_late_entry_distance(ctx, direction, break_level)
        if not distance_ok:
            return None

        # Get ATR for position sizing (required)
        atr = ctx.signal_vector.get("atr", 0.02)
        if atr <= 0:
            return None

        # Calculate risk for strict expansion entry
        risk_mult = self._calculate_expansion_risk_mult(ctx, confidence, continuation_mode=False)

        return LaneResult(
            decision=LaneDecision.TRADE,
            reason=f"expansion_breakout: regime_transition={prev_regime}->{current_regime}, direction={direction:.2f}, confirmation={confirmation_type}",
            risk_mult=risk_mult,
            tags=["expansion", "breakout", "strict"],
            metadata={
                "entry_mode": "strict",
                "prev_regime": prev_regime,
                "current_regime": current_regime,
                "break_level": break_level,
                "confirmation_type": confirmation_type,
                "direction": direction,
                "confidence": confidence,
                "atr": atr
            }
        )

        # Get ATR for position sizing (required)
        atr = signal_vector.get("atr", 0.02)
        if atr <= 0:
            return None  # Cannot trade without ATR

        # Calculate risk
        risk_mult = self.risk_multiplier * self.core_risk_mult  # 0.35x CORE risk

        print(f"EXPANSION_ENTRY: transition={prev_regime}->{current_regime}, break={break_level:.4f}, confirm={confirmation_type}, dist_atr={self._calculate_distance_atr(ctx, direction, break_level):.2f}")

        return LaneResult(
            decision=LaneDecision.OPEN,
            reason=f"expansion_post_break_dir_{direction}_confirm_{confirmation_type}",
            risk_mult=risk_mult,
            tags=["expansion", "continuation", "post_breakout"],
            metadata={
                "break_level": break_level,
                "atr_at_entry": atr,
                "atr_peak_since_entry": atr,  # Initialize
                "trailing_stop": self._calculate_initial_trailing_stop(direction, break_level, atr),
                "regime_at_entry": current_regime,
                "lane_id": "expansion",
                "confirmation_type": confirmation_type
            }
        )

    def _evaluate_position_exit(self, ctx: LaneContext) -> Optional[LaneResult]:
        """
        Evaluate if expansion position should exit.
        Exit logic: invalidation SL, TP1, ATR trail, momentum decay, time stop.
        """
        from engine_alpha.loop.lanes.base import LaneResult, LaneDecision

        position = ctx.position
        if not position:
            return None

        entry_price = position.get("entry_px", 0)
        current_price = self._get_current_price(ctx)
        direction = position.get("dir", 0)

        if entry_price <= 0 or current_price <= 0 or direction == 0:
            return None

        # Calculate current P&L percentage and ATR
        if direction > 0:  # Long
            pnl_pct = (current_price - entry_price) / entry_price
        else:  # Short
            pnl_pct = (entry_price - current_price) / entry_price

        atr_at_entry = position.get("atr_at_entry", 0.02)
        current_atr = ctx.signal_vector.get("atr", atr_at_entry)

        # 1. INVALIDATION STOP: Initial stop loss
        pullback_low = position.get("pullback_low", entry_price)
        invalidation_sl = min(pullback_low - (0.2 * atr_at_entry), entry_price - (0.9 * atr_at_entry))
        if direction > 0 and current_price <= invalidation_sl:
            self._reset_symbol_state(ctx.symbol)
            return LaneResult(
                decision=LaneDecision.CLOSE,
                reason="expansion_invalidation_sl",
                risk_mult=self.default_risk_mult,
                tags=["expansion", "stop_loss", "invalidation"],
                metadata={
                    "exit_reason": "invalidation_sl",
                    "pnl_pct": pnl_pct,
                    "sl_level": invalidation_sl
                }
            )

        # 2. TAKE-PROFIT 1: At +1.0 ATR (take 30-50% off)
        tp1_level = entry_price + (direction * self.tp1_atr * atr_at_entry)
        if ((direction > 0 and current_price >= tp1_level) or
            (direction < 0 and current_price <= tp1_level)):
            # Take partial profit and switch to trailing mode
            partial_metadata = position.copy()
            partial_metadata["tp1_hit"] = True
            partial_metadata["trailing_stop"] = self._calculate_initial_trail_stop(direction, current_price, current_atr)

            return LaneResult(
                decision=LaneDecision.CLOSE,  # Close partial position
                reason=f"expansion_tp1_at_{self.tp1_atr}_atr",
                risk_mult=self.default_risk_mult,
                tags=["expansion", "take_profit", "tp1", "partial_close"],
                metadata={
                    "exit_reason": "tp1",
                    "pnl_pct": pnl_pct,
                    "tp1_level": tp1_level,
                    "remaining_position": True,
                    "trailing_stop": partial_metadata["trailing_stop"]
                }
            )

        # 3. ATR TRAILING STOP (after TP1)
        if position.get("tp1_hit", False):
            trailing_stop = position.get("trailing_stop", 0)
            new_trailing_stop = self._update_trailing_stop(direction, current_price, trailing_stop, current_atr)

            if ((direction > 0 and current_price <= new_trailing_stop) or
                (direction < 0 and current_price >= new_trailing_stop)):
                self._reset_symbol_state(ctx.symbol)
                return LaneResult(
                    decision=LaneDecision.CLOSE,
                    reason="expansion_atr_trail",
                    risk_mult=self.default_risk_mult,
                    tags=["expansion", "trailing_stop", "atr_trail"],
                    metadata={
                        "exit_reason": "atr_trail",
                        "pnl_pct": pnl_pct,
                        "trailing_stop": new_trailing_stop
                    }
                )

        # 4. MOMENTUM DECAY EXIT (after TP1)
        if position.get("tp1_hit", False) and self._check_momentum_decay(ctx, position):
            self._reset_symbol_state(ctx.symbol)
            return LaneResult(
                decision=LaneDecision.CLOSE,
                reason="expansion_momentum_decay",
                risk_mult=self.default_risk_mult,
                tags=["expansion", "momentum_decay", "continuation_failed"],
                metadata={
                    "exit_reason": "momentum_decay",
                    "pnl_pct": pnl_pct
                }
            )

        # 5. TIME STOP: Exit if bars_open >= 24 (1 day on 1h)
        bars_open = position.get("bars_open", 0)
        if bars_open >= self.time_stop_hours:
            self._reset_symbol_state(ctx.symbol)
            return LaneResult(
                decision=LaneDecision.CLOSE,
                reason=f"expansion_time_stop_{self.time_stop_hours}h",
                risk_mult=self.default_risk_mult,
                tags=["expansion", "time_stop"],
                metadata={
                    "exit_reason": "time_stop",
                    "pnl_pct": pnl_pct,
                    "bars_open": bars_open
                }
            )

        # Hold position
        updated_metadata = position.copy()
        if position.get("tp1_hit", False):
            updated_metadata["trailing_stop"] = self._update_trailing_stop(
                direction, current_price, position.get("trailing_stop", 0), current_atr)

        return LaneResult(
            decision=LaneDecision.HOLD,
            reason=f"expansion_holding_pnl_{pnl_pct:.4f}_atr_{current_atr:.4f}",
            risk_mult=self.default_risk_mult,
            tags=["expansion", "holding"],
            metadata=updated_metadata
        )

    def _calculate_initial_trail_stop(self, direction: int, current_price: float, current_atr: float) -> float:
        """Calculate initial trailing stop level"""
        trail_distance = self.atr_trail_mult * current_atr
        if direction > 0:
            return current_price - trail_distance
        else:
            return current_price + trail_distance

    def _update_trailing_stop(self, direction: int, current_price: float, current_trailing: float, current_atr: float) -> float:
        """Update trailing stop to follow price"""
        trail_distance = self.atr_trail_mult * current_atr
        if direction > 0:
            return max(current_trailing, current_price - trail_distance)
        else:
            return min(current_trailing, current_price + trail_distance)

    def _check_momentum_decay(self, ctx: LaneContext, position: Dict[str, Any]) -> bool:
        """Check for momentum decay after TP1"""
        impulse_strength = position.get("impulse_strength", 0)
        if impulse_strength < self.impulse_strength_min:
            return False

        market_data = ctx.market_data
        closes = market_data.get("closes", [])

        # Check 2 consecutive closes against direction
        if len(closes) < 3:
            return False

        direction = position.get("dir", 0)
        recent_closes = closes[-3:]  # Last 3 closes

        consecutive_against = 0
        for i in range(1, len(recent_closes)):
            if direction > 0 and recent_closes[i] < recent_closes[i-1]:
                consecutive_against += 1
            elif direction < 0 and recent_closes[i] > recent_closes[i-1]:
                consecutive_against += 1

        if consecutive_against >= 2:
            return True

        # Check ATR contraction
        atr_at_entry = position.get("atr_at_entry", 0.02)
        current_atr = ctx.signal_vector.get("atr", atr_at_entry)
        atr_ratio = current_atr / atr_at_entry if atr_at_entry > 0 else 1.0

        return atr_ratio < self.atr_decay_ratio

    def _check_guardrails(self, ctx: LaneContext) -> Tuple[bool, str, str]:
        """Check CORE-safe guardrails"""
        # Min hold time check
        last_trade_time = self._get_last_expansion_trade_time(ctx.symbol)
        if last_trade_time:
            now = datetime.now(timezone.utc)
            minutes_since_trade = (now - last_trade_time).total_seconds() / 60.0
            if minutes_since_trade < self.min_hold_minutes:
                return False, f"expansion_cooldown_{minutes_since_trade:.1f}_min", "min_hold"

        # Cooldown check
        if last_trade_time:
            now = datetime.now(timezone.utc)
            cooldown_end = last_trade_time + timedelta(minutes=self.cooldown_minutes)
            if now < cooldown_end:
                return False, f"expansion_cooldown_active_{self.cooldown_minutes}_min", "cooldown"

        # Max positions per symbol
        if self._count_open_positions(ctx.symbol) >= self.max_positions_per_symbol:
            return False, f"expansion_max_positions_{self.max_positions_per_symbol}", "max_positions"

        return True, "", ""

    def _get_last_expansion_trade_time(self, symbol: str) -> Optional[datetime]:
        """Get timestamp of last expansion trade for this symbol"""
        try:
            import json
            from pathlib import Path

            trades_file = Path("reports/trades.jsonl")
            if not trades_file.exists():
                return None

            last_expansion_time = None
            with trades_file.open("r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trade = json.loads(line)
                        if (trade.get("symbol", "").upper() == symbol.upper() and
                            trade.get("lane_id") == "expansion"):
                            ts_str = trade.get("ts") or trade.get("entry_ts")
                            if ts_str:
                                if isinstance(ts_str, str):
                                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                else:
                                    dt = ts_str
                                if last_expansion_time is None or dt > last_expansion_time:
                                    last_expansion_time = dt
                    except Exception:
                        continue

            return last_expansion_time
        except Exception:
            return None

    def _count_open_positions(self, symbol: str) -> int:
        """Count open expansion positions for this symbol"""
        # This would need to be implemented based on your position tracking system
        # For now, return 0 (simplified)
        return 0


    def get_risk_profile(self, ctx: LaneContext) -> Dict[str, Any]:
        """Get risk profile for expansion lane"""
        return {
            "risk_mult": self.risk_mult,
            "max_positions_per_symbol": self.max_positions_per_symbol,
            "min_hold_minutes": self.min_hold_minutes,
            "cooldown_minutes": self.cooldown_minutes,
            "evaluation_metric": "r_multiple",
            "target_r_multiple": 2.0,  # Conservative target for continuation trades
            "entry_logic": "impulse_pullback_reaccel",
            "exit_logic": "invalidation_sl_tp1_atr_trail_momentum_decay_time_stop"
        }

    def get_measurement_params(self) -> Dict[str, Any]:
        """Get measurement requirements for expansion lane"""
        return {
            "evaluation_metric": "r_multiple",
            "regime_required": ["trend_up", "trend_down", "high_vol"],
            "min_regime_age_minutes": self.min_regime_age_minutes,
            "structural_break_types": ["range_break", "vwap_flip", "atr_expansion"],
            "confirmation_signals": ["retest_hold", "consecutive_closes", "volume_expansion"]
        }

    def __str__(self) -> str:
        return f"ExpansionLane(lane_id={self.lane_id}, risk_mult={self.risk_mult}, impulse_min={self.impulse_strength_min}, pullback_atr={self.pullback_atr_min}-{self.pullback_atr_max})"
