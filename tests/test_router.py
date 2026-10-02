from agent.router import route_ci_failure


def test_high_confidence_flaky_auto_reruns():
    decision = route_ci_failure("flaky", 0.92)
    assert decision.action == "rerun"


def test_low_confidence_flaky_holds_for_human():
    decision = route_ci_failure("flaky", 0.5)
    assert decision.action == "hold_for_human"


def test_regression_always_holds_for_human_regardless_of_confidence():
    decision = route_ci_failure("regression", 0.99)
    assert decision.action == "hold_for_human"


def test_infra_escalates():
    decision = route_ci_failure("infra", 0.9)
    assert decision.action == "escalate"
