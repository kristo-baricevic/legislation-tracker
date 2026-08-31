from django.contrib import admin

from .models import (
    Bill,
    BillContract,
    BillDocument,
    BillSimilarity,
    BillTopic,
    EvidenceSpan,
    Topic,
)

admin.site.register(Topic)
admin.site.register(Bill)
admin.site.register(BillDocument)
admin.site.register(BillContract)
admin.site.register(EvidenceSpan)
admin.site.register(BillTopic)
admin.site.register(BillSimilarity)
