"""Coordinate Congress API throttling across workers sharing a credential."""

import hashlib
import math
import threading
import time

from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache

_local_lock = threading.Lock()


def cooldown_key(credential):
    return "congress:cooldown:" + hashlib.sha256(credential.encode()).hexdigest()


def wait_for_slot(key):
    """Space starts across production workers, returning any provider cooldown."""
    cache = caches["default"]
    if not isinstance(cache, RedisCache):
        return max(0, math.ceil((cache.get(key) or 0) - time.time()))
    client = cache._cache.get_client(write=True)
    deadline = time.monotonic() + 3
    while True:
        # Check the provider's cooldown and claim the next 300 ms slot together.
        cooldown, wait = client.eval(
            "local c = redis.call('pttl', KEYS[1]); "
            "if c > 0 then return {c, 0} end; "
            "if redis.call('set', KEYS[2], '1', 'PX', 300, 'NX') then return {0, 0} end; "
            "return {0, math.max(1, redis.call('pttl', KEYS[2]))}",
            2,
            cache.make_key(key),
            cache.make_key(key + ":slot"),
        )
        if cooldown or wait <= 0:
            return math.ceil(cooldown / 1000)
        if time.monotonic() + wait / 1000 >= deadline:
            return max(1, math.ceil(wait / 1000))
        time.sleep(wait / 1000)


def defer_requests(key, seconds):
    cache = caches["default"]
    if isinstance(cache, RedisCache):
        # Compare and extend atomically on the primary. A late short 429 must
        # never release another worker's longer cooldown.
        client = cache._cache.get_client(write=True)
        client.eval(
            "if redis.call('pttl', KEYS[1]) < tonumber(ARGV[1]) then "
            "redis.call('psetex', KEYS[1], ARGV[1], '1') end return 1",
            1,
            cache.make_key(key),
            seconds * 1000,
        )
    else:
        # Test/development settings use an in-process cache.
        with _local_lock:
            until = time.time() + seconds
            if (cache.get(key) or 0) < until:
                cache.set(key, until, seconds)
