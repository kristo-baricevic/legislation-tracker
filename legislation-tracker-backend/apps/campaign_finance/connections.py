from datetime import date
from django.db.models import Q, Sum, Min
from apps.legislation.models import Bill
from apps.congress.models import BillCosponsor, VoteRecord
from .models import FinanceSnapshot, FinanceTransaction, ContributorIdentity


def get_connections(representative_id, period, cursor=0, contributor=None, donor_cursor=0, related_cursor=0):
    start, end = date(period - 1, 1, 1), date(period + 1, 1, 1)
    cosponsors = BillCosponsor.objects.filter(representative_id=representative_id, sponsorship_date__gte=start, sponsorship_date__lt=end)
    votes = VoteRecord.objects.filter(representative_id=representative_id, vote__vote_date__date__gte=start, vote__vote_date__date__lt=end).exclude(vote__bill=None)
    bills = Bill.objects.filter(Q(sponsor_id=representative_id, introduced_at__gte=start, introduced_at__lt=end) | Q(pk__in=cosponsors.values("bill_id")) | Q(pk__in=votes.values("vote__bill_id"))).distinct().order_by("-introduced_at", "id")
    count = bills.count()
    selected = list(bills.prefetch_related("bill_topics__topic")[cursor:cursor + 10])
    ids = [bill.pk for bill in selected]
    cosponsor_map = {row.bill_id: row for row in cosponsors.filter(bill_id__in=ids)}
    vote_map = {}
    for row in votes.filter(vote__bill_id__in=ids).select_related("vote").order_by("vote__vote_date", "id"):
        vote_map.setdefault(row.vote.bill_id, []).append({"vote_id": row.vote_id, "position": row.position, "question": row.vote.question, "source_url": row.vote.source_url})
    snapshot = FinanceSnapshot.objects.filter(representative_id=representative_id, period=period, active=True).first()
    results = []
    for bill in selected:
        relations = []
        if bill.sponsor_id == representative_id and bill.introduced_at and start <= bill.introduced_at < end:
            relations.append("Sponsored")
        if bill.pk in cosponsor_map:
            relations.append("Cosponsored (withdrawn)" if cosponsor_map[bill.pk].withdrawn_at else "Cosponsored")
        if bill.pk in vote_map:
            relations.append("Recorded vote — see question and position")
        results.append({"id": bill.pk, "number": bill.bill_number, "title": bill.title, "relations": relations, "votes": vote_map.get(bill.pk, []), "topics": [{"id": row.topic_id, "name": row.topic.name} for row in bill.bill_topics.all()]})
    verified = ContributorIdentity.objects.filter(verified=True, contributor__kind="committee").values("contributor_id")
    receipts = FinanceTransaction.objects.filter(snapshot__active=True, snapshot__period=period, effective=True, kind="contribution", contributor_id__in=verified)
    donors = receipts.filter(snapshot=snapshot).values("contributor_id", "contributor__name").annotate(amount=Sum("amount"), source=Min("source_url")).order_by("-amount", "contributor_id") if snapshot else receipts.none().values("contributor_id", "contributor__name").annotate(amount=Sum("amount"), source=Min("source_url"))
    donor_count = donors.count()
    related = []
    related_count = 0
    if contributor and snapshot and receipts.filter(snapshot=snapshot, contributor_id=contributor).exists():
        related_rows = receipts.filter(contributor_id=contributor).values("snapshot__representative_id", "snapshot__representative__name").annotate(amount=Sum("amount"), source=Min("source_url")).order_by("snapshot__representative_id")
        related_count = related_rows.count()
        related = [{"id": row["snapshot__representative_id"], "name": row["snapshot__representative__name"], "amount": str(row["amount"]), "source_url": row["source"]} for row in related_rows[related_cursor:related_cursor + 20]]
    return {"notice": "This shows recorded legislative activity and does not establish donor endorsement of a topic or influence over a vote.", "finance_status": snapshot.coverage if snapshot else "not_researched", "count": count, "next_cursor": cursor + 10 if cursor + 10 < count else None, "bills": results, "donors": [{"id": row["contributor_id"], "name": row["contributor__name"], "amount": str(row["amount"]), "source_url": row["source"]} for row in donors[donor_cursor:donor_cursor + 20]], "donor_count": donor_count, "next_donor_cursor": donor_cursor + 20 if donor_cursor + 20 < donor_count else None, "related_representatives": related, "related_count": related_count, "next_related_cursor": related_cursor + 20 if related_cursor + 20 < related_count else None}
