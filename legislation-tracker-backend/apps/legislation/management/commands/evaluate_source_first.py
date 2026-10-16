import json
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.legislation.enhancements.provision_pipeline import plan_analysis
from apps.legislation.enhancements.source_graph import build_source_graph
from apps.legislation.evaluation.source_first import (
    evaluation_limits,
    execute_recorded,
    preflight_benchmarks,
    replay,
    review_packet,
)
from apps.legislation.evaluation.whole_bill import load_cases


class Command(BaseCommand):
    help = "Source-first preflight/replay; paid generation requires --execute and the confirmed plan fingerprint."

    def add_arguments(self, parser):
        parser.add_argument("--replay", type=Path)
        parser.add_argument("--case")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--confirm-plan")
        parser.add_argument("--output", type=Path)

    def handle(self, *args, **options):
        if options["execute"] and options["replay"]:
            raise CommandError("Choose execution or replay, not both")
        if options["execute"]:
            cases = {c["id"]: c for c in load_cases()}
            if options["case"] not in cases or not options["output"]:
                raise CommandError(
                    "Execution requires a pinned --case and a new --output path"
                )
            case = cases[options["case"]]
            graph = build_source_graph(case["id"], case["id"], case["text"])
            plan = plan_analysis(graph, evaluation_limits())
            if options["confirm_plan"] != plan.fingerprint:
                raise CommandError(
                    "Current plan confirmation required; rerun preflight and pass --confirm-plan"
                )
            key = getattr(settings, "LLM_ENHANCEMENT_EVALUATION_API_KEY", "")
            if not key:
                raise CommandError(
                    "Configure LLM_ENHANCEMENT_EVALUATION_API_KEY; no requests sent"
                )
            from apps.legislation.enhancements.provider_registry import get_provider
            from apps.legislation.enhancements.providers.base import ProviderError

            provider = get_provider("openai")

            def invoke(call):
                # No answer-key content enters the request or repair stages.
                request = SimpleNamespace(
                    requested_model=plan.model,
                    reasoning_effort=plan.reasoning_effort,
                    request_envelope={"source_first_payload": call.payload},
                )
                method = {
                    "generation": "generate_provisions",
                    "repair": "repair_provisions",
                    "synopsis": "generate_synopsis",
                }[call.stage]
                return getattr(provider, method)(
                    api_key=key,
                    request=request,
                    timeout_seconds=settings.LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS,
                )

            try:
                result = execute_recorded(plan, invoke, options["output"])
            except FileExistsError:
                raise CommandError(
                    "Output exists; refusing overwrite or duplicate charges"
                ) from None
            except ProviderError as error:
                raise CommandError(
                    f"Provider run failed: {error.category}; recording retained"
                ) from None
            finally:
                key = None
            report = review_packet(case, result)
            report.update(
                mode="fresh_generation",
                network_calls=result.call_count,
                recording=str(options["output"]),
            )
            self.stdout.write(json.dumps(report, indent=2))
            return
        if options["replay"]:
            cases = {c["id"]: c for c in load_cases()}
            if options["case"] not in cases:
                raise CommandError("Select a pinned benchmark case")
            case = cases[options["case"]]
            artifact = json.loads(options["replay"].read_text())
            graph = build_source_graph(case["id"], case["id"], case["text"])
            report = replay(
                plan_analysis(
                    graph,
                    artifact.get("limits", {"model": artifact["model"]}),
                    reuse_result=artifact.get("reuse_result"),
                ),
                artifact,
            )
        else:
            report = preflight_benchmarks()
        self.stdout.write(json.dumps(report, indent=2))
