from datetime import datetime, timedelta

import pytest

from src.history import Conversation, HistoryStore
from src.web.presenters import display_name, history_groups


@pytest.fixture
def history(tmp_path):
    return HistoryStore(tmp_path / "app.db")


def test_conversation_lifecycle(history):
    cid = history.create_conversation("  What is   the patch SLA? ")
    history.add_message(cid, "user", "What is the patch SLA?")
    history.add_message(cid, "assistant", "7 days", [{"source": "policy.pdf"}])
    assert history.conversation_exists(cid)
    convs = history.conversations()
    assert convs[0].title == "What is the patch SLA?" and convs[0].message_count == 2
    assert history.messages(cid)[1] == {"role": "assistant", "content": "7 days", "sources": [{"source": "policy.pdf"}],
                                        "meta": {}}
    history.add_message(cid, "assistant", "x", meta={"agents": ["researcher"]})
    assert history.messages(cid)[-1]["meta"] == {"agents": ["researcher"]}
    history.delete_conversation(cid)
    assert not history.conversation_exists(cid) and history.messages(cid) == []


def test_long_titles_truncated_and_newest_first(history):
    first = history.create_conversation("x" * 100)
    second = history.create_conversation("second")
    assert len(history.conversations()[1].title) == 60
    assert [c.id for c in history.conversations()] == [second, first]


def test_preferences_documents_uploads(history):
    assert history.get_pref("show_technical", "true") == "true"
    history.set_pref("show_technical", "false")
    assert history.get_pref("show_technical") == "false"

    history.record_document("scan.xlsx", "xlsx", ["SecOps"], 18, ["scan__findings"], [])
    assert history.documents()["scan.xlsx"]["topics"] == ["SecOps"]
    history.forget_document("scan.xlsx")
    assert history.documents() == {}

    history.log_upload("a.exe", "rejected", "blocked")
    assert history.uploads()[0]["outcome"] == "rejected"
    history.clear_uploads()
    assert history.uploads() == []


def test_history_groups():
    now = datetime(2026, 10, 27, 12, 0).astimezone()
    convs = [Conversation(str(i), str(i), now - timedelta(days=d), 1) for i, d in enumerate([0, 1, 3, 30])]
    assert [label for label, _ in history_groups(convs, now)] == ["Today", "Yesterday", "Previous 7 days", "Older"]


@pytest.mark.parametrize(
    "filename, expected",
    [("information_security_policy.pdf", "Information security policy"),
     ("postmortem_INC-2041_payment_api_outage.txt", "Postmortem INC-2041 payment api outage"),
     ("siem_alerts_2026-10.csv", "Siem alerts 2026-10")],
)
def test_display_name(filename, expected):
    assert display_name(filename) == expected


def test_old_database_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, sources TEXT, created_at TEXT NOT NULL);""")
    con.close()
    history = HistoryStore(path)
    cid = history.create_conversation("q")
    history.add_message(cid, "assistant", "a", meta={"mode": "answer"})
    assert history.messages(cid)[0]["meta"] == {"mode": "answer"}
