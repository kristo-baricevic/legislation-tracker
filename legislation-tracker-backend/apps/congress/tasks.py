"""Prepare public dashboard data outside interactive requests."""

import logging

from celery import shared_task

from apps.accounts.recommendation_support import RecommendationError

from .topic_activity import representative_activity_catalog

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True, soft_time_limit=25, time_limit=30)
def warm_representative_activity():
    # Keep the current five-minute snapshot available while its replacement is
    # built. The catalog's existing gate prevents overlapping rebuilds; only a
    # complete catalog is published, with unchanged revision/freshness checks.
    try:
        representative_activity_catalog(refresh_before=120)
    except RecommendationError:
        logger.warning("Representative activity refresh deferred; retrying next minute")
