from athena_trading.position_management.apde import APDEState, ORDER

def test_apde_order_is_canonical():
    assert ORDER == (APDEState.EXPLORE, APDEState.PROTECT, APDEState.HARVEST, APDEState.DEFEND, APDEState.EXIT)
