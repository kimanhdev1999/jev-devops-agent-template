from agent.prefilter import prefilter_ci_failure


def test_oom_detected_as_infra():
    assert prefilter_ci_failure("process OOMKilled by kubelet") == "infra"


def test_docker_connection_refused_detected_as_infra():
    assert prefilter_ci_failure("docker: connection refused") == "infra"


def test_ambiguous_log_falls_through_to_jev():
    assert prefilter_ci_failure("AssertionError: expected 200, got 500") is None
