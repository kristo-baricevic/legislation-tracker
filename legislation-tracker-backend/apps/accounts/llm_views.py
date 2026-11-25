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

from apps.legislation.enhancements.model_selection import (
    catalog,
    credential_target,
    selectable,
)
from apps.legislation.enhancements.provider_registry import get_provider
from apps.legislation.enhancements.providers.base import ProviderError

from .llm_credentials import (
    CredentialDecryptionError,
    decrypt_credential,
    llm_feature_available,
)
from .llm_serializers import LLMCredentialUpdateSerializer
from .models import LLMCredential, LLMPreference, selected_credentials


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
        and credential.validated_model == credential_target(credential)[1]
        and selectable(credential_target(credential))
    ):
        return credential.validation_status
    return LLMCredential.ValidationStatus.UNVERIFIED


def _settings_payload(credential: LLMCredential | None, user=None) -> dict:
    owner = user if user is not None else credential.user if credential else None
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
        "requested_model": credential_target(credential)[1],
        "models": catalog(),
        "saved_credentials": list(
            LLMCredential.objects.filter(user=owner).values(
                "provider", "selected_model", "key_suffix", "revision"
            )
        ),
    }


def _credential(user, provider):
    if provider is None:
        return selected_credentials(user).first()
    return LLMCredential.objects.filter(user=user, provider=provider).first()


class LLMSelectionView(PrivateNoStoreMixin, APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        credential = selected_credentials(request.user).first()
        if credential is None:
            return Response({"provider": None, "model": None})
        provider, model = credential_target(credential)
        return Response({"provider": provider, "model": model})

    def put(self, request):
        provider, model = request.data.get("provider"), request.data.get("model")
        if not llm_feature_available():
            return Response({"error": "feature_unavailable"}, status=503)
        if not selectable((provider, model)):
            return Response({"error": "unsupported_model"}, status=400)
        with transaction.atomic():
            type(request.user).objects.select_for_update().get(pk=request.user.pk)
            credential = (
                LLMCredential.objects.select_for_update()
                .filter(user=request.user, provider=provider)
                .first()
            )
            if credential is None:
                return Response({"error": "credential_not_configured"}, status=400)
            credential.selected_model = model
            credential.save(update_fields=["selected_model"])
            LLMPreference.objects.update_or_create(
                user=request.user, defaults={"active_credential": credential}
            )
        return Response({"provider": provider, "model": model})


class LLMModelsView(PrivateNoStoreMixin, APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        provider = request.query_params.get("provider")
        return Response(
            {
                "models": [
                    item
                    for item in catalog()
                    if not provider or item["provider"] == provider
                ]
            }
        )


@method_decorator(sensitive_post_parameters("api_key"), name="dispatch")
class LLMSettingsView(PrivateNoStoreMixin, APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, provider=None):
        credential = _credential(request.user, provider)
        payload = _settings_payload(credential, request.user)
        if provider and credential is None:
            choices = [
                item for item in payload["models"] if item["provider"] == provider
            ]
            if not choices:
                return Response(status=404)
            payload.update(provider=provider, requested_model=choices[0]["model"])
        return Response(payload)

    def put(self, request, provider=None):
        serializer = LLMCredentialUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        api_key = values.get("api_key")
        requested_enabled = values.get("enabled")

        if not llm_feature_available() and (
            api_key is not None
            or requested_enabled is True
            or "requested_model" in values
        ):
            return Response(
                {"error": "feature_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        with transaction.atomic():
            type(request.user).objects.select_for_update().get(pk=request.user.pk)
            active = selected_credentials(request.user).first()
            if provider and values.get("provider", provider) != provider:
                return Response({"error": "provider_mismatch"}, status=400)
            scoped = provider is not None
            provider = provider or values.get(
                "provider",
                (
                    _configured_provider()
                    if api_key is not None
                    else credential_target(active)[0]
                ),
            )
            # Older clients submitted only an OpenAI key. Never attach it to
            # whichever third-party provider another settings tab just saved.
            if (
                not scoped
                and api_key is not None
                and "provider" not in values
                and active
                and provider != active.provider
            ):
                return Response(
                    {"error": "credential_changed"}, status=status.HTTP_409_CONFLICT
                )
            credential = (
                LLMCredential.objects.select_for_update()
                .filter(user=request.user, provider=provider)
                .first()
            )
            if (
                api_key
                and credential is None
                and not settings.LLM_MULTI_PROVIDER_WRITES_ENABLED
                and LLMCredential.objects.filter(user=request.user).exists()
            ):
                return Response({"error": "multi_provider_rollout_pending"}, status=409)
            model = values.get("requested_model", credential_target(credential)[1])
            if not selectable((provider, model)) and values != {"enabled": False}:
                return Response(
                    {"provider": ["This provider is not available."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if credential is None and api_key is None:
                return Response(
                    {"api_key": ["An API key is required."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if api_key is not None:
                credential = LLMCredential.objects.create_for_key(
                    user=request.user,
                    provider=provider,
                    api_key=api_key,
                    activate_initial=not scoped,
                    enabled=(
                        requested_enabled
                        if requested_enabled is not None
                        else (
                            active.enabled
                            if not scoped and active is not None
                            else True
                        )
                    ),
                )
            if credential.selected_model != model:
                credential.selected_model = model
                credential.save(update_fields=["selected_model"])
            if (
                requested_enabled is not None
                and credential.enabled != requested_enabled
            ):
                credential.enabled = requested_enabled
                credential.save(update_fields=["enabled", "updated_at"])

            if not scoped:
                LLMPreference.objects.update_or_create(
                    user=request.user, defaults={"active_credential": credential}
                )

        return Response(_settings_payload(credential))

    def delete(self, request, provider=None):
        with transaction.atomic():
            type(request.user).objects.select_for_update().get(pk=request.user.pk)
            credential = _credential(request.user, provider)
            if credential:
                credential.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LLMSettingsValidateView(PrivateNoStoreMixin, APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (LLMValidationThrottle,)

    def post(self, request, provider=None):
        if not llm_feature_available():
            return Response(
                {"error": "feature_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        credential = _credential(request.user, provider)
        if credential is None:
            return Response(
                {"error": "credential_not_configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not selectable(credential_target(credential)):
            return Response(
                {"error": "provider_changed"},
                status=status.HTTP_409_CONFLICT,
            )

        if credential_target(credential) == ("openrouter", "openrouter/free"):
            return Response({"error": "concrete_model_required"}, status=400)

        snapshot = {
            "pk": credential.pk,
            "user": request.user,
            "revision": credential.revision,
            "provider": credential.provider,
            "encrypted_envelope": credential.encrypted_envelope,
            "selected_model": credential.selected_model,
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
                requested_model=credential_target(credential)[1],
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
            validated_model=credential_target(credential)[1],
            validated_at=timezone.now(),
        )
        if updated == 0:
            return Response(
                {"error": "credential_changed"},
                status=status.HTTP_409_CONFLICT,
            )
        credential.refresh_from_db()
        return Response(_settings_payload(credential))
