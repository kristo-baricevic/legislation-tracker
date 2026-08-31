from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.legislation.enhancements.provider_registry import get_provider
from apps.legislation.enhancements.providers.base import ProviderError

from .llm_credentials import (
    CredentialDecryptionError,
    decrypt_credential,
    llm_feature_available,
)
from .llm_serializers import LLMCredentialUpdateSerializer
from .models import LLMCredential


class PrivateNoStoreMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


class LLMValidationThrottle(UserRateThrottle):
    scope = "llm_validation"


class PublicCapabilitiesView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request):
        response = Response({"llm_enhancements": llm_feature_available()})
        response["Cache-Control"] = "no-store"
        return response


def _configured_provider() -> str:
    return settings.LLM_ENHANCEMENT_PROVIDER.strip().lower()


def _effective_validation_status(credential: LLMCredential | None) -> str:
    if credential is None:
        return LLMCredential.ValidationStatus.UNVERIFIED
    if (
        credential.validation_status != LLMCredential.ValidationStatus.UNVERIFIED
        and credential.validated_revision == credential.revision
        and credential.validated_provider == credential.provider
        and credential.validated_model == settings.LLM_ENHANCEMENT_MODEL
        and credential.provider == _configured_provider()
    ):
        return credential.validation_status
    return LLMCredential.ValidationStatus.UNVERIFIED


def _settings_payload(credential: LLMCredential | None) -> dict:
    return {
        "feature_available": llm_feature_available(),
        "configured": credential is not None,
        "provider": credential.provider if credential else _configured_provider(),
        "key_suffix": credential.key_suffix if credential else None,
        "revision": credential.revision if credential else None,
        "enabled": credential.enabled if credential else False,
        "validation_status": _effective_validation_status(credential),
        "validated_revision": credential.validated_revision if credential else None,
        "validated_at": credential.validated_at if credential else None,
        "requested_model": settings.LLM_ENHANCEMENT_MODEL,
    }


@method_decorator(sensitive_post_parameters("api_key"), name="dispatch")
class LLMSettingsView(PrivateNoStoreMixin, APIView):
    permission_classes = (IsAuthenticated,)

    def _credential(self, request):
        return LLMCredential.objects.filter(user=request.user).first()

    def get(self, request):
        return Response(_settings_payload(self._credential(request)))

    def put(self, request):
        serializer = LLMCredentialUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        api_key = values.get("api_key")
        requested_enabled = values.get("enabled")

        if not llm_feature_available() and (
            api_key is not None or requested_enabled is True
        ):
            return Response(
                {"error": "feature_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        with transaction.atomic():
            credential = (
                LLMCredential.objects.select_for_update()
                .filter(user=request.user)
                .first()
            )
            provider = values.get(
                "provider",
                credential.provider if credential else _configured_provider(),
            )
            if provider != _configured_provider():
                return Response(
                    {"provider": ["This provider is not available."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if credential is None and api_key is None:
                return Response(
                    {"api_key": ["An API key is required."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if (
                credential is not None
                and provider != credential.provider
                and api_key is None
            ):
                return Response(
                    {"api_key": ["Replacing the provider requires the API key."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if api_key is not None:
                credential = LLMCredential.objects.create_for_key(
                    user=request.user,
                    provider=provider,
                    api_key=api_key,
                    enabled=(
                        requested_enabled if requested_enabled is not None else True
                    ),
                )
            if (
                requested_enabled is not None
                and credential.enabled != requested_enabled
            ):
                credential.enabled = requested_enabled
                credential.save(update_fields=["enabled", "updated_at"])

        return Response(_settings_payload(credential))

    def delete(self, request):
        LLMCredential.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LLMSettingsValidateView(PrivateNoStoreMixin, APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (LLMValidationThrottle,)

    def post(self, request):
        if not llm_feature_available():
            return Response(
                {"error": "feature_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        credential = LLMCredential.objects.filter(user=request.user).first()
        if credential is None:
            return Response(
                {"error": "credential_not_configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if credential.provider != _configured_provider():
            return Response(
                {"error": "provider_changed"},
                status=status.HTTP_409_CONFLICT,
            )

        snapshot = {
            "pk": credential.pk,
            "user": request.user,
            "revision": credential.revision,
            "provider": credential.provider,
            "encrypted_envelope": credential.encrypted_envelope,
        }
        try:
            api_key = decrypt_credential(credential)
        except CredentialDecryptionError:
            return Response(
                {"validation_status": "unverified", "error": "credential_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            check = get_provider(snapshot["provider"]).validate_credential(
                api_key=api_key,
                requested_model=settings.LLM_ENHANCEMENT_MODEL,
                timeout_seconds=settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS,
            )
        except ProviderError as exc:
            updated = LLMCredential.objects.filter(**snapshot).update(
                validation_status=LLMCredential.ValidationStatus.UNVERIFIED,
                validated_revision=None,
                validated_provider="",
                validated_model="",
                validated_at=None,
            )
            if updated == 0:
                return Response(
                    {"error": "credential_changed"},
                    status=status.HTTP_409_CONFLICT,
                )
            response_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.retry_allowed
                else status.HTTP_400_BAD_REQUEST
            )
            return Response(
                {"validation_status": "unverified", "error": exc.category},
                status=response_status,
            )

        validation_status = (
            LLMCredential.ValidationStatus.VALID
            if check.valid
            else LLMCredential.ValidationStatus.INVALID
        )
        updated = LLMCredential.objects.filter(**snapshot).update(
            validation_status=validation_status,
            validated_revision=snapshot["revision"],
            validated_provider=snapshot["provider"],
            validated_model=settings.LLM_ENHANCEMENT_MODEL,
            validated_at=timezone.now(),
        )
        if updated == 0:
            return Response(
                {"error": "credential_changed"},
                status=status.HTTP_409_CONFLICT,
            )
        credential.refresh_from_db()
        return Response(_settings_payload(credential))
