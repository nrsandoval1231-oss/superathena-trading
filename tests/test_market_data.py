from athena_trading.market_data.alpaca_corporate_actions import canonical_symbols

def test_symbols_are_canonicalized():
    assert canonical_symbols(["msft", "AAPL", "aapl"]) == ("AAPL", "MSFT")
