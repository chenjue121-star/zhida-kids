from app.services.outfits.scoring import (
    child_age_months,
    current_season,
    recommended_thickness,
)


def test_recommended_thickness_buckets():
    assert recommended_thickness(30) in {"thin", "normal", "thick", "fleece"}
    assert recommended_thickness(-5) in {"thin", "normal", "thick", "fleece"}


def test_current_season_returns_valid_season():
    assert current_season() in {"spring", "summer", "autumn", "winter"}


def test_child_age_months_positive(seed, db_session):
    from app.models import Child
    child = db_session.get(Child, seed["child_id"])
    assert child_age_months(child) > 0
