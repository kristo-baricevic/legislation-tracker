import pytest
from django.db import IntegrityError, transaction

from apps.congress.models import (
    BillCosponsor,
    Committee,
    CommitteeMembership,
    Representative,
)
from apps.legislation.models import Bill


@pytest.mark.django_db
def test_committee_memberships_and_cosponsors_use_stable_upstream_identities():
    representative = Representative.objects.create(
        bioguide_id="I000001",
        name="Insight Member",
        chamber="house",
        party="Independent",
        state="NY",
    )
    committee = Committee.objects.create(
        system_code="hsii00",
        name="House Rules",
        chamber="house",
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="HR 910",
        title="Relationship bill",
        status="Introduced",
    )
    CommitteeMembership.objects.create(
        committee=committee,
        representative=representative,
        congress=119,
        source_name="house",
        source_code="II00",
    )
    BillCosponsor.objects.create(bill=bill, representative=representative)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CommitteeMembership.objects.create(
                committee=committee,
                representative=representative,
                congress=119,
                source_name="house",
                source_code="II00",
            )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            BillCosponsor.objects.create(bill=bill, representative=representative)
