from attoswarm.coordinator.merge_queue import MergeQueue


def test_merge_queue_roundtrip() -> None:
    q = MergeQueue()
    q.enqueue("t1", artifacts=["a.py"])
    q.items[0].status = "in_review"
    raw = q.to_list()
    restored = MergeQueue.from_list(raw)
    assert restored.items[0].task_id == "t1"
    assert restored.items[0].candidate_artifacts == ["a.py"]
    assert restored.items[0].status == "in_review"
