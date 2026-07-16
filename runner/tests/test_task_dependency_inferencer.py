"""Tests for task_dependency_inferencer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from task_dependency_inferencer import DependencyGraph, TaskDependencyInferencer

def test_graph_add_and_get():
    g = DependencyGraph(); g.add_edge("build", "test", 0.9)
    assert g.get_prerequisites("test") == {"build": 0.9}

def test_graph_no_prereqs():
    assert DependencyGraph().get_prerequisites("x") == {}

def test_graph_nodes():
    g = DependencyGraph(); g.add_edge("a", "b", 1.0)
    assert g.nodes == {"a", "b"}

def test_graph_edge_count():
    g = DependencyGraph(); g.add_edge("a", "b"); g.add_edge("b", "c")
    assert g.edge_count == 2

def test_graph_no_cycle():
    g = DependencyGraph(); g.add_edge("a", "b"); g.add_edge("b", "c")
    assert g.has_cycle() is None

def test_graph_detects_cycle():
    g = DependencyGraph(); g.add_edge("a", "b"); g.add_edge("b", "c"); g.add_edge("c", "a")
    assert g.has_cycle() is not None

def test_build_before_test():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=2)
    for _ in range(5): inf.observe_sequence(["build", "test"])
    assert "build" in inf.predict_dependencies("test")

def test_single_path_chain():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=2)
    for _ in range(3): inf.observe_sequence(["build", "test", "deploy"])
    deps = inf.predict_dependencies("deploy")
    assert len(deps) >= 1

def test_no_dependency_random_order():
    inf = TaskDependencyInferencer(min_confidence=0.7, min_observations=2)
    inf.observe_sequence(["a", "b"]); inf.observe_sequence(["b", "a"])
    assert len(inf.predict_dependencies("a")) == 0

def test_fan_in():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=2)
    for _ in range(3): inf.observe_sequence(["compile", "lint", "merge"])
    assert len(inf.predict_dependencies("merge")) >= 1

def test_fan_out():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=2)
    for _ in range(3):
        inf.observe_sequence(["build", "test-unit"])
        inf.observe_sequence(["build", "test-integration"])
    assert "build" in inf.predict_dependencies("test-unit")
    assert "build" in inf.predict_dependencies("test-integration")

def test_confidence_scores():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=2)
    for _ in range(10): inf.observe_sequence(["build", "test"])
    scores = inf.predict_dependencies_with_confidence("test")
    assert scores["build"] >= 0.9

def test_known_types():
    inf = TaskDependencyInferencer(); inf.observe_sequence(["a", "b", "c"])
    assert inf.known_types == {"a", "b", "c"}

def test_sequence_count():
    inf = TaskDependencyInferencer(); inf.observe_sequence(["a"]); inf.observe_sequence(["b"])
    assert inf.sequence_count == 2

def test_empty_inferencer():
    assert TaskDependencyInferencer().predict_dependencies("x") == set()

def test_single_obs_below_threshold():
    inf = TaskDependencyInferencer(min_observations=2)
    inf.observe_sequence(["build", "test"])
    assert len(inf.predict_dependencies("test")) == 0

def test_predict_unknown_type():
    inf = TaskDependencyInferencer(); inf.observe_sequence(["a", "b"])
    assert inf.predict_dependencies("unknown") == set()

def test_graph_caching():
    inf = TaskDependencyInferencer(min_observations=1); inf.observe_sequence(["a", "b"])
    assert inf.build_graph() is inf.build_graph()

def test_graph_invalidation():
    inf = TaskDependencyInferencer(min_observations=1); inf.observe_sequence(["a", "b"])
    g1 = inf.build_graph(); inf.observe_sequence(["c", "d"])
    assert g1 is not inf.build_graph()

def test_many_task_types():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=2)
    for _ in range(5): inf.observe_sequence(["init", "fetch", "build", "lint", "test", "package", "deploy"])
    assert len(inf.predict_dependencies("deploy")) >= 1

def test_bidirectional_weak():
    inf = TaskDependencyInferencer(min_confidence=0.8, min_observations=2)
    inf.observe_sequence(["a", "b"]); inf.observe_sequence(["a", "b"]); inf.observe_sequence(["b", "a"])
    assert len(inf.predict_dependencies("b")) == 0

def test_strong_signal():
    inf = TaskDependencyInferencer(min_confidence=0.6, min_observations=2)
    for _ in range(20): inf.observe_sequence(["checkout", "build", "test"])
    deps = inf.predict_dependencies("test")
    assert "build" in deps or "checkout" in deps

def test_cycle_in_inferencer():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=1)
    inf.observe_sequence(["a", "b", "c", "a"])
    assert inf.build_graph() is not None

def test_symmetric_observations():
    inf = TaskDependencyInferencer(min_confidence=0.5, min_observations=2)
    for _ in range(5): inf.observe_sequence(["x", "y"])
    for _ in range(5): inf.observe_sequence(["y", "x"])
    # 50/50 = 0.5, just at threshold
    deps = inf.predict_dependencies("y")
    assert isinstance(deps, set)
