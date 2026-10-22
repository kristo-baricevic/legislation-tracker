"""Small, typed graph projection; money never propagates to legislative topics."""
from urllib.parse import urlencode
from django.db.models import Sum
from apps.congress.models import Representative
from .models import ContributorIdentity


def connection_graph(representative_id, snapshot, bills, donors, receipts):
    nodes, edges = {}, []
    rep = Representative.objects.get(pk=representative_id)

    def node(kind, identity, label, url):
        key = f"{kind}:{identity}"
        nodes[key] = {"id": key, "kind": kind, "label": label, "url": url}
        return key

    def edge(kind, source, target, label, evidence_url, **extra):
        edges.append({"id": f"{kind}:{source}:{target}:{len(edges)}", "kind": kind, "source": source, "target": target, "label": label, "evidence_url": evidence_url, **extra})

    root = node("representative", rep.pk, rep.name, f"/representatives/{rep.pk}")
    donor_ids = [row["contributor_id"] for row in donors]
    if snapshot and donor_ids:
        identities = dict(ContributorIdentity.objects.filter(contributor_id__in=donor_ids, verified=True, provider_key__startswith="fec:C").values_list("contributor_id", "provider_key"))
        grouped = receipts.filter(snapshot=snapshot, contributor_id__in=donor_ids).values("contributor_id", "contributor__name", "committee_id", "committee__name").annotate(amount=Sum("amount"))
        for row in grouped:
            donor_id = row["contributor_id"]
            source = node("contributor", donor_id, row["contributor__name"], f"https://www.fec.gov/data/committee/{identities[donor_id][4:]}/")
            committee = node("committee", row["committee_id"], row["committee__name"], f"https://www.fec.gov/data/committee/{row['committee_id']}/")
            evidence = "https://www.fec.gov/data/receipts/?" + urlencode({"data_type": "processed", "committee_id": row["committee_id"], "contributor_id": identities[donor_id][4:], "two_year_transaction_period": snapshot.period})
            edge("contributed_to", source, committee, "Contributed to campaign committee", evidence, amount=str(row["amount"]))
        for link in snapshot.committee_links:
            committee = f"committee:{link['committee_id']}"
            if committee in nodes:
                edge("authorized_for", committee, root, "Authorized campaign committee", link["source_url"], candidate_id=link["candidate_id"])
    for bill in bills:
        bill_node = node("bill", bill["id"], f"{bill['number']}: {bill['title']}", f"/bills/{bill['id']}")
        for relation in bill["relations"]:
            if relation == "Sponsored":
                edge("sponsored", root, bill_node, relation, f"/bills/{bill['id']}", date=bill["introduced_at"])
            elif relation.startswith("Cosponsored"):
                edge("cosponsored", root, bill_node, relation, f"/bills/{bill['id']}", withdrawn="withdrawn" in relation, date=bill["cosponsored_at"], withdrawn_at=bill["withdrawn_at"])
        for vote in bill["votes"]:
            edge("recorded_vote", root, bill_node, f"{vote['question']}: {vote['position']}", vote["source_url"] or f"/votes/{vote['vote_id']}", vote_id=vote["vote_id"], date=vote["date"])
        for topic in bill["topics"]:
            topic_node = node("topic", topic["id"], topic["name"], f"/bills?topic_id={topic['id']}")
            edge("bill_tagged_topic", bill_node, topic_node, "Classified under topic", f"/bills/{bill['id']}")
    return {"nodes": list(nodes.values()), "edges": edges}
