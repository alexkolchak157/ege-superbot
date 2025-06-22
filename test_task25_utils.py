import random
import pytest

from task25.utils import TopicSelector


@pytest.fixture
def sample_topics():
    return [
        {"id": 1, "title": "T1", "block": "History", "difficulty": "easy"},
        {"id": 2, "title": "T2", "block": "History", "difficulty": "medium"},
        {"id": 3, "title": "T3", "block": "Law", "difficulty": "hard"},
        {"id": 4, "title": "T4", "block": "Law", "difficulty": "easy"},
        {"id": 5, "title": "T5", "block": "Economy", "difficulty": "hard"},
    ]


def test_get_random_topic_excludes_recent(monkeypatch, sample_topics):
    selector = TopicSelector(sample_topics)
    user_id = 123

    # deterministic choice
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    seen_ids = []
    for _ in range(len(sample_topics)):
        topic = selector.get_random_topic(user_id)
        seen_ids.append(topic["id"])

    # first five topics should be returned in order without repeats
    assert seen_ids == [1, 2, 3, 4, 5]

    # next call should start over when history exhausted
    topic = selector.get_random_topic(user_id)
    assert topic["id"] == 1


def test_get_recommended_topic(monkeypatch, sample_topics):
    selector = TopicSelector(sample_topics)
    user_id = 555

    # deterministic choice
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    # simulate weak block "Law" with low scores
    user_stats = {
        3: {"scores": [2]},
        4: {"scores": [1]},
        1: {"scores": [5]},
    }
    topic = selector.get_recommended_topic(user_id, user_stats)
    assert topic["block"] == "Law"

    # when no weak blocks, expect hard difficulty
    user_stats = {
        1: {"scores": [5]},
        2: {"scores": [4]},
        3: {"scores": [4]},
    }
    topic = selector.get_recommended_topic(user_id, user_stats)
    assert topic["difficulty"] == "hard"

