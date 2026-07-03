from infoq_watchlist.config import load_config
from infoq_watchlist.models import Talk
from infoq_watchlist.scoring import score_talk


def test_scoring_uses_terms_and_thresholds_from_config(tmp_path):
    # The made-up term keeps the test independent from any built-in defaults.
    config_path = tmp_path / "watchlist.toml"
    config_path.write_text(
        """
[thresholds]
watch = 6
skim = 5
transcript = 3
background = 1

[[signals]]
name = "custom_control_plane_signal"
weight = 5
terms = ["quorum zebra"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    talk = Talk(
        url="https://www.infoq.com/presentations/quorum-zebra/",
        title="Operating the Quorum Zebra control plane",
        summary="A production story about quorum zebra rollouts.",
        topics=[],
        tags=[],
    )

    scored = score_talk(talk, config)

    # A matching configurable term should affect both score and decision.
    assert scored.score == 5
    assert scored.decision == "skim"
    assert "custom_control_plane_signal" in scored.tags
    assert "quorum zebra" in scored.reason.lower()


def test_scoring_decision_changes_when_thresholds_change(tmp_path):
    # Same weighted signal as the previous test, but a lower watch threshold.
    config_path = tmp_path / "watchlist.toml"
    config_path.write_text(
        """
[thresholds]
watch = 5
skim = 4
transcript = 3
background = 1

[[signals]]
name = "custom_control_plane_signal"
weight = 5
terms = ["quorum zebra"]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)
    talk = Talk(
        url="https://www.infoq.com/presentations/quorum-zebra/",
        title="Operating the Quorum Zebra control plane",
        summary="A production story about quorum zebra rollouts.",
        topics=[],
        tags=[],
    )

    scored = score_talk(talk, config)

    # This confirms thresholds are loaded from config rather than hard-coded.
    assert scored.score == 5
    assert scored.decision == "watch"
