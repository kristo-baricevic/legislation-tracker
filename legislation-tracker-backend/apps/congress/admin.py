from django.contrib import admin
from .models import Representative, Vote, VoteRecord

admin.site.register(Representative)
admin.site.register(Vote)
admin.site.register(VoteRecord)
