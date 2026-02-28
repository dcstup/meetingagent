from src.services.deduper import compute_dedupe_hash


def test_dedupe_hash_deterministic():
    h1 = compute_dedupe_hash("session-1", "email-bob")
    h2 = compute_dedupe_hash("session-1", "email-bob")
    assert h1 == h2


def test_dedupe_hash_different_sessions():
    h1 = compute_dedupe_hash("session-1", "email-bob")
    h2 = compute_dedupe_hash("session-2", "email-bob")
    assert h1 != h2


def test_dedupe_hash_different_keys():
    h1 = compute_dedupe_hash("session-1", "email-bob")
    h2 = compute_dedupe_hash("session-1", "email-alice")
    assert h1 != h2
