from athena_trading.strategies.orb_momentum import OrbLevels, Side, close_breakout, initial_stop, retracement_fraction


def test_close_trigger_ignores_wick():
    levels = OrbLevels(101.0, 99.0)
    assert close_breakout(close=100.9, levels=levels) is None
    assert close_breakout(close=101.01, levels=levels) is Side.LONG
    assert close_breakout(close=98.99, levels=levels) is Side.SHORT


def test_long_stop_uses_tighter_structure_or_atr():
    levels = OrbLevels(101.0, 95.0)
    assert initial_stop(side=Side.LONG, entry=102.0, atr=2.0, levels=levels, min_distance=.05) == 100.0


def test_retracement_is_entry_to_peak():
    assert retracement_fraction(side=Side.LONG, entry=100.0, peak=110.0, current=108.0) == .2
