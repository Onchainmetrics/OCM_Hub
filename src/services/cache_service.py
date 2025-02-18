import redis
import json
from datetime import timedelta
import logging
import os
from functools import wraps
import pandas as pd
from typing import Any, Callable
from prometheus_client import Counter, Histogram  # For monitoring
import time

logger = logging.getLogger(__name__)

class CacheService:
    # Monitoring metrics
    CACHE_HITS = Counter('cache_hits_total', 'Number of cache hits', ['command'])
    CACHE_MISSES = Counter('cache_misses_total', 'Number of cache misses', ['command'])
    CACHE_ERRORS = Counter('cache_errors_total', 'Number of cache errors', ['operation'])
    CACHE_LATENCY = Histogram('cache_operation_latency_seconds', 'Cache operation latency', ['operation'])

    def __init__(self):
        try:
            host = os.getenv('REDIS_HOST')
            port = os.getenv('REDIS_PORT')
            password = os.getenv('REDIS_PASSWORD')

            logger.info(f"Attempting Redis connection with:")
            logger.info(f"Host: {host}")
            logger.info(f"Port: {port}")
            logger.info(f"Password: {'*' * len(password) if password else 'None'}")

            logger.info("Creating Redis connection with TLS...")
            
            self.redis = redis.Redis(
                host=host,
                port=int(port) if port else 6379,
                password=password,
                decode_responses=True,
                socket_timeout=15.0,
                socket_connect_timeout=15.0,
                retry_on_timeout=True,
                health_check_interval=30,
                ssl=True,
                ssl_cert_reqs="none",
                ssl_ca_certs=None,
                ssl_check_hostname=False
            )
            
            logger.info("Redis connection object created, attempting to ping...")
            
            # Test connection with timeout and retry
            retry_count = 3
            while retry_count > 0:
                try:
                    logger.info(f"Ping attempt {4-retry_count}/3...")
                    self.redis.ping()
                    logger.info("Successfully connected to Redis!")
                    break
                except redis.TimeoutError as e:
                    retry_count -= 1
                    if retry_count == 0:
                        logger.error(f"All ping attempts failed. Last error: {str(e)}")
                        raise
                    logger.warning(f"Redis connection timeout, retrying in 2 seconds... ({retry_count} attempts left)")
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"Unexpected error during ping: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Redis initialization failed: {str(e)}")
            raise
            
    async def get(self, key: str) -> Any:
        """Get value from cache with monitoring"""
        with self.CACHE_LATENCY.labels('get').time():
            try:
                data = self.redis.get(key)
                if data:
                    self.CACHE_HITS.labels(key.split(':')[0]).inc()
                    return json.loads(data)
                self.CACHE_MISSES.labels(key.split(':')[0]).inc()
                return None
            except redis.RedisError as e:
                self.CACHE_ERRORS.labels('get').inc()
                logger.error(f"Redis error getting key {key}: {e}")
                return None
            except json.JSONDecodeError as e:
                self.CACHE_ERRORS.labels('json_decode').inc()
                logger.error(f"JSON decode error for key {key}: {e}")
                return None
            
    async def set(self, key: str, value: Any, expire_minutes: int):
        """Set value in cache with monitoring"""
        with self.CACHE_LATENCY.labels('set').time():
            try:
                self.redis.setex(
                    key,
                    timedelta(minutes=expire_minutes),
                    json.dumps(value)
                )
            except (redis.RedisError, json.JSONEncodeError) as e:
                self.CACHE_ERRORS.labels('set').inc()
                logger.error(f"Error setting cache for key {key}: {e}")
                
    async def invalidate(self, key: str):
        """Invalidate a cache key"""
        try:
            self.redis.delete(key)
            logger.info(f"Invalidated cache key: {key}")
        except redis.RedisError as e:
            self.CACHE_ERRORS.labels('invalidate').inc()
            logger.error(f"Error invalidating key {key}: {e}")

    async def health_check(self) -> bool:
        """Check if Redis is healthy"""
        try:
            return bool(self.redis.ping())
        except redis.RedisError:
            return False
            
def cache_command(expire_minutes: int):
    """Decorator for caching command results"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache = CacheService()
            
            # Generate cache key
            if func.__name__ == 'heatmap_command':
                cache_key = "heatmap"  # No parameters needed
            else:
                # For commands with contract address
                cache_key = f"{func.__name__}:"
                if len(args) > 1 and hasattr(args[1], 'args') and args[1].args:
                    cache_key += args[1].args[0].lower()  # Contract address in lowercase
            
            # Try to get from cache
            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                logger.info(f"Cache hit for {cache_key}")
                return cached_result
            
            # If not in cache, execute function
            result = await func(*args, **kwargs)
            
            # Cache the result
            if result:  # Only cache if we got a valid result
                await cache.set(cache_key, result, expire_minutes)
            
            return result
        return wrapper
    return decorator 