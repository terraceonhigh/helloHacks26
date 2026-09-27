from hub.mymathlab import fetch


def test_fetch_is_an_honest_stub():
    # No confirmed page structure exists for MyLab/Mastering (see
    # hub/mymathlab.py's module docstring for what's cited vs. unknown), so
    # fetch() must degrade to "nothing found" rather than guess at a parser.
    # This is the network-free contract every caller (app.py, hub/api.py)
    # relies on: never crash, never fabricate an Item.
    assert fetch() == ([], [])


def test_fetch_takes_no_network_even_with_a_custom_base():
    # Regression guard: fetch() must stay a pure stub no matter what `base`
    # is passed, so it can never accidentally reach the network in tests.
    assert fetch("https://example.invalid/course/123") == ([], [])
