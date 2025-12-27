import pytest

import engine_alpha.loop.recovery_lane_v2 as rl


def test_exit_only_when_allow_recovery_trading_false():
    exit_only, reason = rl._should_exit_only(
        allow_recovery_trading_v1=False,
        allow_recovery_lane_v2=True,
        needed_ok_v1=0,
        ok_ticks_v1=0,
    )
    assert exit_only is True
    assert reason == "recovery_disallowed_by_ramp_v1"


def test_exit_only_when_ready_for_normal():
    exit_only, reason = rl._should_exit_only(
        allow_recovery_trading_v1=True,
        allow_recovery_lane_v2=True,
        needed_ok_v1=6,
        ok_ticks_v1=6,
    )
    assert exit_only is True
    assert reason == "recovery_exit_only_ready_for_normal_v1"


def test_exit_only_when_lane_disallowed_v2():
    exit_only, reason = rl._should_exit_only(
        allow_recovery_trading_v1=True,
        allow_recovery_lane_v2=False,
        needed_ok_v1=0,
        ok_ticks_v1=0,
    )
    assert exit_only is True
    assert reason == "recovery_ramp_v2_disallowed"


def test_not_exit_only_when_allows_and_not_ready():
    exit_only, reason = rl._should_exit_only(
        allow_recovery_trading_v1=True,
        allow_recovery_lane_v2=True,
        needed_ok_v1=6,
        ok_ticks_v1=3,
    )
    assert exit_only is False
    assert reason == ""

