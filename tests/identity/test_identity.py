"""Unit tests for compute_dog_uid and resolve_dog_identity."""

import pytest
from sqlalchemy.exc import IntegrityError

from cucciolofinder.database import compute_dog_uid, resolve_dog_identity
from cucciolofinder.database.models import Dog


# ---- compute_dog_uid ----

def test_uid_is_deterministic():
    a = compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 1)
    b = compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 1)
    assert a == b


def test_uid_length_is_16_hex():
    uid = compute_dog_uid("a", "b", 1)
    assert len(uid) == 16
    assert all(c in "0123456789abcdef" for c in uid)


def test_different_generations_produce_different_uids():
    a = compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 1)
    b = compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 2)
    assert a != b


def test_different_sites_produce_different_uids():
    a = compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 1)
    b = compute_dog_uid("canileoasi", "https://x.com/dogs/bobby", 1)
    assert a != b


def test_different_urls_produce_different_uids():
    a = compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 1)
    b = compute_dog_uid("enpatorino", "https://x.com/dogs/luna", 1)
    assert a != b


# ---- resolve_dog_identity: branch 1 (no active row) ----

def test_resolve_no_active_row_returns_gen_1(session):
    identity = resolve_dog_identity(
        session,
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        image_urls=["https://x.com/img/bobby1.jpg"],
    )
    assert identity.generation == 1
    assert identity.supersede_id is None
    assert identity.dog_uid == compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 1)


# ---- resolve_dog_identity: branch 2 (image overlap = same dog) ----

def test_resolve_image_overlap_reuses_existing_identity(session, make_dog_factory):
    existing = make_dog_factory(
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        name="Bobby",
        dog_uid="aaaaaaaaaaaaaaaa",
        generation=3,
        image_urls=["img1.jpg", "img2.jpg"],
    )
    identity = resolve_dog_identity(
        session,
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        image_urls=["img2.jpg", "img3.jpg"],  # one overlap
    )
    assert identity.dog_uid == existing.dog_uid
    assert identity.generation == existing.generation
    assert identity.supersede_id is None


def test_resolve_full_image_overlap_reuses_existing_identity(session, make_dog_factory):
    existing = make_dog_factory(
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        name="Bobby",
        dog_uid="bbbbbbbbbbbbbbbb",
        image_urls=["img1.jpg", "img2.jpg"],
    )
    identity = resolve_dog_identity(
        session,
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        image_urls=["img1.jpg", "img2.jpg"],
    )
    assert identity.dog_uid == existing.dog_uid
    assert identity.supersede_id is None


# ---- resolve_dog_identity: branch 3 (image disjoint = collision) ----

def test_resolve_image_disjoint_bumps_generation_and_flags_supersede(session, make_dog_factory):
    existing = make_dog_factory(
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        name="Bobby",
        dog_uid="cccccccccccccccc",
        generation=1,
        image_urls=["img1.jpg", "img2.jpg"],
    )
    identity = resolve_dog_identity(
        session,
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        image_urls=["new1.jpg", "new2.jpg"],  # zero overlap
    )
    assert identity.generation == 2
    assert identity.supersede_id == existing.id
    assert identity.dog_uid == compute_dog_uid("enpatorino", "https://x.com/dogs/bobby", 2)
    assert identity.dog_uid != existing.dog_uid


def test_resolve_skips_already_superseded_rows(session, make_dog_factory):
    """A superseded row at the same URL should be ignored: a new scrape
    should treat the URL as fresh (gen=1)."""
    from datetime import datetime, timezone

    make_dog_factory(
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        name="Bobby-old",
        dog_uid="dddddddddddddddd",
        generation=1,
        image_urls=["old1.jpg"],
        superseded_at=datetime.now(timezone.utc),
    )
    identity = resolve_dog_identity(
        session,
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        image_urls=["new1.jpg"],
    )
    assert identity.generation == 1
    assert identity.supersede_id is None


# ---- partial unique index ----

def test_partial_unique_index_blocks_duplicate_active_rows(session, make_dog_factory):
    """Two active rows with the same (site, url) must not coexist."""
    make_dog_factory(
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        name="Bobby",
        dog_uid="eeeeeeeeeeeeeeee",
    )
    with pytest.raises(IntegrityError):
        make_dog_factory(
            source_site="enpatorino",
            source_url="https://x.com/dogs/bobby",
            name="Bobby-dup",
            dog_uid="ffffffffffffffff",
        )


def test_superseded_and_active_rows_can_share_url(session, make_dog_factory):
    """Once the old row is marked superseded, a new active row at the same
    URL is allowed."""
    from datetime import datetime, timezone

    make_dog_factory(
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        name="Bobby-old",
        dog_uid="1111111111111111",
        generation=1,
        superseded_at=datetime.now(timezone.utc),
    )
    # Should NOT raise.
    make_dog_factory(
        source_site="enpatorino",
        source_url="https://x.com/dogs/bobby",
        name="Bobby-new",
        dog_uid="2222222222222222",
        generation=2,
    )
    active = (
        session.query(Dog)
        .filter_by(source_url="https://x.com/dogs/bobby", superseded_at=None)
        .all()
    )
    assert len(active) == 1
    assert active[0].name == "Bobby-new"
