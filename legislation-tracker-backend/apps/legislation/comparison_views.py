from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from config.api import StrictQuerySerializer

from .comparison import (
    compare_contracts,
    compare_document_section,
    compare_document_sections,
)
from .models import Bill, BillContract, BillDocument


class ComparisonQuerySerializer(StrictQuerySerializer):
    before = serializers.IntegerField(min_value=1)
    after = serializers.IntegerField(min_value=1)


class DocumentSectionQuerySerializer(ComparisonQuerySerializer):
    section_key = serializers.CharField(max_length=255)


class BillContractComparisonView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, bill_id):
        query = ComparisonQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        bill = get_object_or_404(Bill, pk=bill_id)
        before = get_object_or_404(BillContract, pk=query.validated_data["before"], bill=bill)
        after = get_object_or_404(BillContract, pk=query.validated_data["after"], bill=bill)
        diff = compare_contracts(before=before, after=after)
        return Response(
            {
                "before": before.id,
                "after": after.id,
                "changes": [
                    {
                        "path": change.path,
                        "operation": change.operation,
                        "before": change.before,
                        "after": change.after,
                    }
                    for change in diff.changes
                ],
                "total_change_count": diff.total_change_count,
                "returned_change_count": diff.returned_change_count,
                "truncated": diff.truncated,
            }
        )


class BillDocumentComparisonView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, bill_id):
        query = ComparisonQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        bill = get_object_or_404(Bill, pk=bill_id)
        before = get_object_or_404(BillDocument, pk=query.validated_data["before"], bill=bill)
        after = get_object_or_404(BillDocument, pk=query.validated_data["after"], bill=bill)
        diff = compare_document_sections(before=before, after=after)
        return Response(
            {
                "before": before.id,
                "after": after.id,
                "sections": [
                    {
                        "section_key": item.section_key,
                        "operation": item.operation,
                        "before_hash": item.before_hash,
                        "after_hash": item.after_hash,
                    }
                    for item in diff.sections
                ],
                "total_change_count": diff.total_change_count,
                "returned_change_count": diff.returned_change_count,
                "truncated": diff.truncated,
                "fallback": diff.fallback,
                "truncation_reasons": list(diff.truncation_reasons),
            }
        )


class BillDocumentSectionComparisonView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, bill_id):
        query = DocumentSectionQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        bill = get_object_or_404(Bill, pk=bill_id)
        before = get_object_or_404(BillDocument, pk=query.validated_data["before"], bill=bill)
        after = get_object_or_404(BillDocument, pk=query.validated_data["after"], bill=bill)
        diff = compare_document_section(
            before=before,
            after=after,
            section_key=query.validated_data["section_key"],
        )
        return Response(
            {
                "section_key": diff.section_key,
                "operations": list(diff.operations),
                "truncated": diff.truncated,
                "truncation_reasons": list(diff.truncation_reasons),
            }
        )
