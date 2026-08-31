from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.changelog.models import ChangeLog
from apps.congress.serializers import RepresentativeSerializer
from apps.legislation.serializers import BillListSerializer, TopicSerializer

from .models import TrackedBill, TrackedLegislator, TrackedTopic, UserPreference

User = get_user_model()


class RegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=150)
    password = serializers.CharField(
        max_length=128, trim_whitespace=False, write_only=True
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        candidate = User(username=attrs["email"], email=attrs["email"])
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def register(self):
        email = self.validated_data["email"]
        password = self.validated_data["password"]
        if User.objects.filter(email__iexact=email).exists():
            return
        try:
            with transaction.atomic():
                User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                )
        except IntegrityError:
            # A concurrent request can win after the preflight lookup. The
            # public response intentionally remains identical.
            return


class SessionTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        email_field = self.username_field
        attrs[email_field] = attrs[email_field].strip().lower()
        return super().validate(attrs)


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = ["id", "state", "chamber"]


class TrackedBillSerializer(serializers.ModelSerializer):
    bill = BillListSerializer(read_only=True)

    class Meta:
        model = TrackedBill
        fields = ["id", "bill", "created_at"]


class TrackedTopicSerializer(serializers.ModelSerializer):
    topic = TopicSerializer(read_only=True)

    class Meta:
        model = TrackedTopic
        fields = ["id", "topic", "created_at"]


class TrackedLegislatorSerializer(serializers.ModelSerializer):
    representative = RepresentativeSerializer(read_only=True)

    class Meta:
        model = TrackedLegislator
        fields = ["id", "representative", "created_at"]


class TrackingFeedEntrySerializer(serializers.ModelSerializer):
    bill = BillListSerializer(read_only=True)

    class Meta:
        model = ChangeLog
        fields = [
            "id",
            "bill",
            "change_type",
            "old_value",
            "new_value",
            "created_at",
        ]
