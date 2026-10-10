from rest_framework import serializers

from apps.legislation.serializers import BillListSerializer
from config.api import PaginatedQuerySerializer, StrictQuerySerializer

from .profile_sources import vote_source_link


class ProfileQuerySerializer(StrictQuerySerializer):
    congress = serializers.IntegerField(min_value=1, max_value=1000)
    chamber = serializers.ChoiceField(choices=("house", "senate"), required=False)


class ProfileVoteQuerySerializer(PaginatedQuerySerializer):
    congress = serializers.IntegerField(min_value=1, max_value=1000)
    chamber = serializers.ChoiceField(choices=("house", "senate"), required=False)


def recorded_vote_data(record):
    vote = record.vote
    source_url, kind = vote_source_link(vote)
    return {
        "id": record.id,
        "representative_id": record.representative_id,
        "vote_id": vote.id,
        "congress": vote.congress,
        "chamber": vote.chamber,
        "session_number": vote.session_number,
        "roll_number": vote.roll_number,
        "vote_date": vote.vote_date,
        "question": vote.question,
        "position": record.position,
        "raw_position": record.raw_position,
        "bill": BillListSerializer(vote.bill).data if vote.bill else None,
        "source_url": source_url,
        "source_link_kind": kind,
        "source_updated_at": vote.source_updated_at,
    }
