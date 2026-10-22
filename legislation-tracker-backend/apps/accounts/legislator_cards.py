"""Batch-load saved profile facts, without starting research or fetching donors."""
from django.db.models import F, Prefetch
from apps.legislation.models import Bill
from apps.research.models import RepresentativeBiography, RepresentativePortrait
from apps.research.portraits import may_serve_portrait


def with_card_facts(queryset):
    return queryset.prefetch_related(
        Prefetch("representative__representativebiography_set",
                 queryset=RepresentativeBiography.objects.select_related("source").order_by("-id")[:1],
                 to_attr="card_bios"),
        Prefetch("representative__representativeportrait_set",
                 queryset=RepresentativePortrait.objects.select_related("source").order_by("-id")[:1],
                 to_attr="card_photos"),
        Prefetch("representative__sponsored_bills",
                 queryset=Bill.objects.filter(introduced_at__isnull=False).order_by(F("introduced_at").desc(), "-id")[:1],
                 to_attr="card_bills"),
    )


def card_facts(rep):
    bio = next(iter(getattr(rep, "card_bios", [])), None)
    photo = next(iter(getattr(rep, "card_photos", [])), None)
    bill = next(iter(getattr(rep, "card_bills", [])), None)
    def source(item):
        return {"url": item.source.url, "attribution": item.source.attribution, "license": item.source.license}
    return {
        "biography": {"text": bio.text, "source": source(bio)} if bio else None,
        "portrait": {"url": f"/api/representatives/{rep.pk}/portraits/{photo.pk}/" if photo.object_key and may_serve_portrait(photo) else photo.image_url, "source": source(photo)} if photo else None,
        "latest_bill": {"id": bill.pk, "title": bill.title, "bill_number": bill.bill_number, "introduced_at": bill.introduced_at, "session": bill.session} if bill else None,
    }
