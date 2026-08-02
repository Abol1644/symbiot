from symbiot.graph import graph


def test_graph_compiles_with_human_gates() -> None:
    assert "validator" in graph.nodes
    assert "escalation" in graph.nodes
    assert "deploy_gate" in graph.nodes
