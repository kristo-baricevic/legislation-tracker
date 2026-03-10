from django.contrib import admin
from .models import Topic, Bill, BillDocument, BillContract, EvidenceSpan, BillTopic, BillSimilarity

admin.site.register(Topic)
admin.site.register(Bill)
admin.site.register(BillDocument)
admin.site.register(BillContract)
admin.site.register(EvidenceSpan)
admin.site.register(BillTopic)
admin.site.register(BillSimilarity)
