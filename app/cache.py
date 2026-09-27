"""Optional Redis cache for the fleet catalogue, never for scheduling decisions."""

import hashlib
import logging
from functools import lru_cache
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from app.config import settings
from app.schemas import ShipOut

logger = logging.getLogger(__name__)
ships_adapter = TypeAdapter(list[ShipOut])


class ShipCache:
    def __init__(self, client: Redis | None, namespace: str, ttl: int = 300):
        self.client = client
        self.namespace = namespace
        self.ttl = ttl

    @property
    def generation_key(self) -> str:
        return f"{self.namespace}:generation"

    def read(self) -> tuple[list[ShipOut] | None, str | None]:
        if self.client is None:
            return None, None
        try:
            generation = self.client.get(self.generation_key)
            if generation is None:
                self.client.set(self.generation_key, uuid4().hex, nx=True)
                generation = self.client.get(self.generation_key)
                if generation is None:
                    return None, None
            key = f"{self.namespace}:{generation}"
            value = self.client.get(key)
        except (RedisError, UnicodeError):
            logger.warning("Ship cache unavailable; using PostgreSQL")
            return None, None
        if value is not None:
            try:
                return ships_adapter.validate_json(value), key
            except (ValidationError, ValueError):
                logger.warning("Invalid ship cache data; refreshing from PostgreSQL")
        return None, key

    def write(self, key: str | None, ships: list[ShipOut]) -> None:
        if key is None or self.client is None:
            return
        try:
            self.client.set(key, ships_adapter.dump_json(ships), ex=self.ttl)
        except RedisError:
            logger.warning("Could not populate ship cache; response still comes from PostgreSQL")

    def invalidate(self) -> None:
        if self.client is None:
            return
        try:
            # Rotate the generation AFTER the database commit. An in-flight old
            # reader can fill only the old key, which expires and is no longer read.
            self.client.set(self.generation_key, uuid4().hex)
        except RedisError:
            logger.warning("Ship cache invalidation failed; existing entries expire by TTL")

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


@lru_cache
def get_ship_cache() -> ShipCache:
    client = (
        Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            retry=Retry(NoBackoff(), 0),
            max_connections=20,
        )
        if settings.redis_url
        else None
    )
    # Include the database identity so different local databases do not share data.
    identity = hashlib.sha256(settings.database_url.encode()).hexdigest()[:16]
    return ShipCache(
        client, f"{settings.redis_key_prefix}:{identity}:ships:v1", settings.ships_cache_ttl_seconds
    )
