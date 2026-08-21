from django.core.checks import Error, register

from .llm_credentials import llm_feature_configuration_errors


@register()
def check_llm_feature_configuration(app_configs, **kwargs):
    from django.conf import settings

    return [
        Error(
            f"Invalid LLM enhancement configuration: {code}",
            id=f"accounts.E{index:03d}",
        )
        for index, code in enumerate(
            llm_feature_configuration_errors(
                production=getattr(
                    settings,
                    "LLM_ENHANCEMENT_PRODUCTION_SECURITY_REQUIRED",
                    False,
                )
            ),
            start=1,
        )
    ]
