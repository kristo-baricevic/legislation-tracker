import pytest
from apps.congress.models import Representative

pytestmark = pytest.mark.django_db


def test_refresh_updates_generated_biography_and_deduplicates_unchanged_facts(settings):
    from datetime import timedelta
    from django.utils import timezone
    from django.contrib.auth import get_user_model
    from apps.research.services import request_research
    from apps.research.tasks import process_research
    from apps.research.models import RepresentativeBiography
    settings.CONGRESS_API_KEY = ""
    settings.FEC_API_KEY = ""
    settings.LEGISLATOR_WIKIPEDIA_ENABLED = False
    rep = Representative.objects.create(bioguide_id="T000099", name="Test Person", chamber="house", state="NY", district="3", party="D", is_current=True)
    user = get_user_model().objects.create_user(username="refresh")
    def refresh():
        run = request_research(rep.pk, 2026, user.pk)
        work = run.work_item
        work.status = "processing"; work.dispatch_token = "lease"; work.lease_expires_at = timezone.now() + timedelta(minutes=5); work.save()
        process_research(work)
        run.refresh_from_db()
        return RepresentativeBiography.objects.get(pk=run.sections["biography"]["revision"])
    original = refresh()
    rep.is_current = False
    rep.save()
    updated = refresh()
    assert "was a U.S. representative" in updated.text
    assert original.pk != updated.pk
    assert refresh().pk == updated.pk
    rep.is_current = True
    rep.save()
    refresh()
    from apps.research.views import saved_research
    assert "is a U.S. representative" in saved_research(rep, 2026)["biography"]["text"]


def test_official_facts_biography_is_saved_without_external_key():
    from apps.research.biographies import save_official_biography
    from apps.research.models import RepresentativeBiography
    rep = Representative.objects.create(bioguide_id="T000001", name="Test Person", chamber="house", state="NY", district="3", party="Democratic")
    result = save_official_biography(rep)
    assert "Test Person" in result.text
    assert "New York" in result.text
    assert "3" in result.text
    assert RepresentativeBiography.objects.get().source.url == "https://bioguide.congress.gov/search/bio/T000001"


def test_excerpt_preserves_abbreviations_and_reuses_unchanged_revision():
    from apps.research.biographies import save_excerpt
    rep = Representative.objects.create(bioguide_id="T000081", name="Jane Doe", chamber="senate", state="NY")
    excerpt = {"text": "Dr. Jane Doe is a U.S. senator. She served New York. This is an unfinished", "observed_revision_url": "https://en.wikipedia.org/w/index.php?oldid=1", "observed_revision_id": 1, "attribution": "Wikipedia contributors", "license": "CC BY-SA 4.0", "wikidata_id": "Q1"}
    saved = save_excerpt(rep, excerpt)
    assert saved.text == "Dr. Jane Doe is a U.S. senator. She served New York."
    assert save_excerpt(rep, excerpt).pk == saved.pk


@pytest.mark.parametrize("url", ["http://localhost/a.png", "https://congress.gov.evil.test/a", "https://www.congress.gov@evil.test/a", "https://www.congress.gov/img/member/../a", "https://www.congress.gov/img/member/a.svg"])
def test_portrait_rejects_untrusted_urls(url):
    from apps.research.portraits import official_portrait_url
    assert official_portrait_url(url) is None


def test_portrait_accepts_official_member_image_only():
    from apps.research.portraits import official_portrait_url
    assert official_portrait_url("https://www.congress.gov/img/member/t000001_200.jpg") == "https://www.congress.gov/img/member/t000001_200.jpg"


def test_memo_and_unknown_receipts_are_not_presented_as_donations():
    from apps.campaign_finance.normalization import normalize_receipt
    base = dict(sub_id="1", committee_id="C00000001", contributor_name="A", contribution_receipt_amount=100, contribution_receipt_date="2026-01-01", line_number="11C", entity_type="PAC", contributor_id="C00000002")
    assert normalize_receipt(base)["kind"] == "contribution"
    assert normalize_receipt({**base, "memo_code": "X"})["effective"] is False
    loan = normalize_receipt({**base, "line_number": "13A"})
    assert loan["kind"] == "candidate_loan"
    assert loan["effective"] is False
    assert normalize_receipt({**base, "contribution_receipt_amount": -25})["kind"] == "adjustment"


def test_individual_identity_does_not_use_employer_or_merge_by_name():
    from apps.campaign_finance.normalization import normalize_receipt
    row = dict(sub_id="1", committee_id="C00000001", contributor_name="Alex Smith", contributor_employer="Big Company", contribution_receipt_amount=100, line_number="11AI", entity_type="IND")
    first, second = normalize_receipt(row), normalize_receipt({**row, "sub_id": "2"})
    assert first["name"] == "Alex Smith"
    assert first["identity_key"] != second["identity_key"]
