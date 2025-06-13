import aiohttp
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import asyncio
import json
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class PriceService:
    def __init__(self):
        self.helius_api_key = os.getenv('HELIUS_API_KEY')
        self.helius_rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
        
        # Jupiter for backup prices (especially for SOL)
        self.jupiter_base_url = "https://api.jup.ag"
        
        # Cache strategy:
        # - Token metadata: Cache with cleanup (remove if not accessed for 14 days)
        # - SOL price: 1 hour cache 
        # - Token prices: No cache (calculate from each transaction)
        # - Stablecoins: Hardcoded to $1
        self.token_metadata_cache = {}  # Format: {token_address: {"data": metadata, "last_access": datetime}}
        self.sol_price_cache = None
        self.sol_price_timestamp = None
        self.METADATA_CLEANUP_DAYS = 14  # Remove tokens not accessed for 14 days
        
    async def get_sol_price(self) -> Optional[float]:
        """Get SOL price using Jupiter (more reliable for SOL)"""
        try:
            # Check 1-hour cache first
            if (self.sol_price_cache and self.sol_price_timestamp and
                datetime.now() - self.sol_price_timestamp < timedelta(hours=1)):
                return self.sol_price_cache
            
            sol_address = "So11111111111111111111111111111111111111112"
            url = f"{self.jupiter_base_url}/price/v2"
            params = {"ids": sol_address}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if "data" in data and sol_address in data["data"]:
                            price = float(data["data"][sol_address]["price"])
                            
                            # Cache the result for 1 hour
                            self.sol_price_cache = price
                            self.sol_price_timestamp = datetime.now()
                            return price
                            
        except Exception as e:
            logger.error(f"Error fetching SOL price: {e}")
            
        return None
    
    async def get_token_metadata(self, token_address: str) -> Optional[Dict]:
        """Get token metadata (symbol, name, supply, decimals) - cached with cleanup for stale entries"""
        try:
            # Check cache first and update last access time
            if token_address in self.token_metadata_cache:
                cache_entry = self.token_metadata_cache[token_address]
                cache_entry["last_access"] = datetime.now()  # Update access time
                logger.info(f"Using cached metadata for {token_address[:8]}...")
                return cache_entry["data"]
            
            # Make API call to get complete metadata using getAsset
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getAsset",
                "params": {
                    "id": token_address,
                    "displayOptions": {
                        "showFungible": True
                    }
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.helius_rpc_url,
                    json=payload,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"getAsset response for {token_address[:8]}...: {data}")
                        
                        if "result" in data and data["result"]:
                            result = data["result"]
                            token_info = result.get("token_info", {})
                            content = result.get("content", {})
                            
                            metadata = {
                                "symbol": token_info.get("symbol", content.get("metadata", {}).get("symbol", "Unknown")),
                                "name": content.get("metadata", {}).get("name", "Unknown"),
                                "supply": token_info.get("supply"),
                                "decimals": token_info.get("decimals", 9)
                            }
                            
                            # Cache with access tracking (metadata never changes but we cleanup stale entries)
                            self.token_metadata_cache[token_address] = {
                                "data": metadata,
                                "last_access": datetime.now()
                            }
                            logger.info(f"Cached metadata for {token_address[:8]}...: symbol={metadata['symbol']}, supply={metadata['supply']}")
                            
                            # Trigger cleanup occasionally (every 100th cache addition)
                            if len(self.token_metadata_cache) % 100 == 0:
                                await self._cleanup_stale_metadata()
                            
                            return metadata
                        else:
                            logger.warning(f"No metadata found for token {token_address}")
                            return None
                    else:
                        logger.error(f"getAsset API error: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching token metadata: {e}")
            return None
    
    async def _cleanup_stale_metadata(self):
        """Remove token metadata that hasn't been accessed in METADATA_CLEANUP_DAYS"""
        try:
            cutoff_time = datetime.now() - timedelta(days=self.METADATA_CLEANUP_DAYS)
            stale_tokens = []
            
            for token_address, cache_entry in self.token_metadata_cache.items():
                if cache_entry["last_access"] < cutoff_time:
                    stale_tokens.append(token_address)
            
            # Remove stale entries
            for token_address in stale_tokens:
                del self.token_metadata_cache[token_address]
            
            if stale_tokens:
                logger.info(f"Cleaned up {len(stale_tokens)} stale token metadata entries older than {self.METADATA_CLEANUP_DAYS} days")
            
        except Exception as e:
            logger.error(f"Error during metadata cleanup: {e}")
    
    async def calculate_market_cap_from_transaction(self, token_address: str, 
                                                   sol_amount: float, token_amount: float, 
                                                   sol_price: float) -> Dict[str, float]:
        """Calculate market cap using transaction data and cached metadata"""
        try:
            # Get token metadata (cached if available) - includes symbol, supply, decimals
            metadata = await self.get_token_metadata(token_address)
            if not metadata:
                logger.warning(f"Could not get metadata for {token_address[:8]}...")
                return {"price_per_token": 0, "market_cap": 0, "supply": 0, "decimals": 9, "symbol": "Unknown"}
            
            # Calculate price per token from this transaction
            if token_amount > 0 and sol_amount > 0:
                price_per_token = (sol_amount * sol_price) / token_amount
            else:
                price_per_token = 0
                
            # Calculate market cap
            if price_per_token > 0 and metadata.get("supply"):
                decimals = metadata.get("decimals", 9)
                raw_supply = float(metadata["supply"])
                actual_supply = raw_supply / (10 ** decimals)
                market_cap = price_per_token * actual_supply
                
                logger.info(f"Market cap calculation for {metadata.get('symbol', 'Unknown')} ({token_address[:8]}...): "
                          f"price=${price_per_token:.8f}, supply={actual_supply:,.0f}, mcap=${market_cap:,.2f}")
            else:
                market_cap = 0
                
            return {
                "price_per_token": price_per_token,
                "market_cap": market_cap,
                "supply": metadata.get("supply", 0),
                "decimals": metadata.get("decimals", 9),
                "symbol": metadata.get("symbol", "Unknown")
            }
            
        except Exception as e:
            logger.error(f"Error calculating market cap from transaction: {e}")
            return {"price_per_token": 0, "market_cap": 0, "supply": 0, "decimals": 9, "symbol": "Unknown"}
    
    # Legacy methods for backward compatibility
    async def get_token_data(self, token_address: str) -> Optional[Dict]:
        """Legacy method - use get_token_metadata and calculate_market_cap_from_transaction instead"""
        return await self.get_token_metadata(token_address)
        
    async def get_token_price(self, token_address: str) -> Optional[float]:
        """Legacy method - prices should be calculated from transactions"""
        return None
        
    async def get_token_market_cap(self, token_address: str) -> Optional[float]:
        """Legacy method - market cap should be calculated from transactions"""
        return None
        
    def clear_cache(self):
        """Clear SOL price cache (keep metadata cache)"""
        self.sol_price_cache = None
        self.sol_price_timestamp = None
        
    def force_metadata_cleanup(self):
        """Force cleanup of stale metadata (useful for testing)"""
        import asyncio
        asyncio.create_task(self._cleanup_stale_metadata())
        
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        # Calculate oldest and newest metadata entries
        oldest_access = None
        newest_access = None
        if self.token_metadata_cache:
            access_times = [entry["last_access"] for entry in self.token_metadata_cache.values()]
            oldest_access = min(access_times)
            newest_access = max(access_times)
        
        return {
            "metadata_cache_size": len(self.token_metadata_cache),
            "sol_price_cached": self.sol_price_cache is not None,
            "sol_price_age_seconds": (
                (datetime.now() - self.sol_price_timestamp).total_seconds()
                if self.sol_price_timestamp else None
            ),
            "oldest_metadata_age_days": (
                (datetime.now() - oldest_access).days if oldest_access else None
            ),
            "cleanup_threshold_days": self.METADATA_CLEANUP_DAYS
        }