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
        
        # Cache
        self.price_cache = {}  # Cache token data for 30 seconds
        self.sol_price_cache = None
        self.sol_price_timestamp = None
        
    async def get_token_data(self, token_address: str) -> Optional[Dict]:
        """Get comprehensive token data using Helius getAsset method"""
        try:
            cache_key = f"token_data_{token_address}"
            if cache_key in self.price_cache:
                cached_data, timestamp = self.price_cache[cache_key]
                if datetime.now() - timestamp < timedelta(seconds=30):
                    return cached_data
            
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getAsset",
                "params": {
                    "id": token_address,
                    "displayOptions": {
                        "showFungibleTokens": True
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
                        logger.info(f"Helius API response for {token_address[:8]}...: {data}")
                        
                        if "result" in data and data["result"]:
                            result = data["result"]
                            
                            # Extract token information
                            token_info = result.get("token_info", {})
                            content = result.get("content", {})
                            
                            token_data = {
                                "address": token_address,
                                "symbol": token_info.get("symbol", content.get("metadata", {}).get("symbol", "Unknown")),
                                "name": content.get("metadata", {}).get("name", "Unknown"),
                                "decimals": token_info.get("decimals", 9),
                                "supply": token_info.get("supply"),
                                "price_per_token": None,
                                "market_cap": None
                            }
                            
                            # Extract price information if available
                            price_info = token_info.get("price_info")
                            if price_info:
                                token_data["price_per_token"] = price_info.get("price_per_token")
                                
                                # Calculate market cap if we have both price and supply
                                if token_data["price_per_token"] and token_data["supply"]:
                                    # Convert supply to actual tokens (accounting for decimals)
                                    actual_supply = float(token_data["supply"]) / (10 ** token_data["decimals"])
                                    token_data["market_cap"] = token_data["price_per_token"] * actual_supply
                            
                            # Cache the result
                            self.price_cache[cache_key] = (token_data, datetime.now())
                            return token_data
                        else:
                            logger.warning(f"No asset data found for token {token_address}")
                            return None
                    else:
                        logger.error(f"Helius getAsset API error: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching token data: {e}")
            return None
            
    async def get_token_price(self, token_address: str) -> Optional[float]:
        """Get token price"""
        token_data = await self.get_token_data(token_address)
        return token_data.get("price_per_token") if token_data else None
        
    async def get_token_market_cap(self, token_address: str) -> Optional[float]:
        """Get token market cap"""
        token_data = await self.get_token_data(token_address)
        return token_data.get("market_cap") if token_data else None
        
    async def get_sol_price(self) -> Optional[float]:
        """Get SOL price using Jupiter (more reliable for SOL)"""
        try:
            # Check cache first
            if (self.sol_price_cache and self.sol_price_timestamp and
                datetime.now() - self.sol_price_timestamp < timedelta(seconds=30)):
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
                            
                            # Cache the result
                            self.sol_price_cache = price
                            self.sol_price_timestamp = datetime.now()
                            return price
                            
        except Exception as e:
            logger.error(f"Error fetching SOL price: {e}")
            
        return None
        
    async def calculate_usd_value(self, sol_amount: float, token_amount: float, token_address: str) -> Dict[str, float]:
        """Calculate USD values for both SOL and token amounts"""
        try:
            # Get SOL price and token price in parallel
            sol_price_task = self.get_sol_price()
            token_price_task = self.get_token_price(token_address)
            
            sol_price, token_price = await asyncio.gather(sol_price_task, token_price_task)
            
            result = {
                "sol_usd_value": 0.0,
                "token_usd_value": 0.0,
                "total_usd_value": 0.0,
                "sol_price": sol_price,
                "token_price": token_price
            }
            
            if sol_price:
                result["sol_usd_value"] = sol_amount * sol_price
                
            if token_price:
                result["token_usd_value"] = token_amount * token_price
                
            result["total_usd_value"] = result["sol_usd_value"] + result["token_usd_value"]
            
            return result
            
        except Exception as e:
            logger.error(f"Error calculating USD values: {e}")
            return {
                "sol_usd_value": 0.0,
                "token_usd_value": 0.0,
                "total_usd_value": 0.0,
                "sol_price": None,
                "token_price": None
            }
            
    async def get_multiple_token_data(self, token_addresses: List[str]) -> Dict[str, Dict]:
        """Get data for multiple tokens"""
        try:
            tasks = [self.get_token_data(addr) for addr in token_addresses]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            token_data = {}
            for i, result in enumerate(results):
                if isinstance(result, dict) and not isinstance(result, Exception):
                    token_data[token_addresses[i]] = result
                    
            return token_data
            
        except Exception as e:
            logger.error(f"Error fetching multiple token data: {e}")
            return {}
            
    def clear_cache(self):
        """Clear all cached data"""
        self.price_cache.clear()
        self.sol_price_cache = None
        self.sol_price_timestamp = None
        
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        return {
            "price_cache_size": len(self.price_cache),
            "sol_price_cached": self.sol_price_cache is not None,
            "sol_price_age_seconds": (
                (datetime.now() - self.sol_price_timestamp).total_seconds()
                if self.sol_price_timestamp else None
            )
        }