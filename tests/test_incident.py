from types import SimpleNamespace

from agent.incident import IncidentDecision, decide
from agent.router import route_incident


def test_offer_rollback_only_when_model_and_code_agree():
    route = route_incident("bad_deploy", True, 0.9, new_revision_in_window=True)
    assert route.action == "offer_rollback"


def test_bad_deploy_without_recent_rollout_holds():
    route = route_incident("bad_deploy", True, 0.99, new_revision_in_window=False)
    assert route.action == "hold_for_human"


def test_low_confidence_holds():
    route = route_incident("bad_deploy", True, 0.5, new_revision_in_window=True)
    assert route.action == "hold_for_human"


def test_other_root_causes_only_ticket():
    for cause in ("db_outage", "oom", "image_pull", "traffic_spike", "unknown"):
        assert route_incident(cause, True, 0.99, new_revision_in_window=True).action == "ticket_only"


def test_no_decision_holds():
    assert route_incident(None, False, 0.0, new_revision_in_window=True).action == "hold_for_human"


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _fake_client(response):
    return SimpleNamespace(messages=_FakeMessages(response))


def test_decide_clamps_and_uses_typed_output():
    parsed = IncidentDecision(
        root_cause="bad_deploy", severity=42, rollback_likely_fixes=True,
        confidence=1.7, evidence=["v2 rolled out 3 min before alarm"], summary="v2 broke the DB config.",
    )
    client = _fake_client(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed))
    decision = decide("evidence", model="anthropic.claude-haiku-5-5", client=client)
    assert decision.severity == 10 and decision.confidence == 1.0
    assert client.messages.kwargs["output_format"] is IncidentDecision
    assert client.messages.kwargs["output_config"] == {"effort": "low"}


def test_decide_refusal_returns_none():
    client = _fake_client(SimpleNamespace(stop_reason="refusal", parsed_output=None))
    assert decide("evidence", model="m", client=client) is None
