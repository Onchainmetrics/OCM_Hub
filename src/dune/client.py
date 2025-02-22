from dune_client.client import DuneClient
from dune_client.types import QueryParameter
from dune_client.query import QueryBase
import os
from dotenv import load_dotenv
import pandas as pd
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta
from collections import defaultdict

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class DuneAnalytics:
    def __init__(self):
        self.client = DuneClient.from_env()
        
    async def get_whale_analysis(self, contract_address: str) -> pd.DataFrame:
        """Execute query for whale analysis of a specific token"""
        try:
            query = QueryBase(
                name="Whale Analysis",
                query_id=4557213,
                params=[
                    QueryParameter.text_type(
                        name="Contract Address",
                        value=contract_address
                    )
                ]
            )
            
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.client.run_query(
                    query=query,
                    performance="large"
                )
            )
            return pd.DataFrame(results.result.rows)
        except Exception as e:
            logger.error(f"Error executing whale analysis query: {str(e)}")
            logger.error(f"Query parameters: Contract Address={contract_address}")
            raise 

    async def get_heatmap_analysis(self) -> pd.DataFrame:
        """Execute query for heatmap analysis of alpha wallet activity"""
        try:
            # Create query object
            query = QueryBase(
                name="Heatmap Analysis",
                query_id=4723009
            )
            
            # Execute query
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, 
                lambda: self.client.run_query(
                    query=query,
                    performance="medium" 
                )
            )
            return pd.DataFrame(results.result.rows)
        except Exception as e:
            logger.error(f"Error executing heatmap analysis query: {e}")
            raise 

async def get_token_activity(token_address: str) -> dict:
    """Get comprehensive token activity from Helius"""
    helius_key = os.getenv('HELIUS_API_KEY')
    
    url = f"https://api.helius.xyz/v1/token-transactions?api-key={helius_key}"
    params = {
        "mintAccount": token_address,
        "type": "SWAP",
        "limit": 100
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                logger.error(f"Helius API error: {await response.text()}")
                return None
                
            transactions = await response.json()
            
            # Process transactions
            buyers = defaultdict(lambda: {
                'first_buy_time': None,
                'total_bought': 0,
                'total_sold': 0,
                'buy_count': 0,
                'sell_count': 0
            })
            
            # Track timestamps for time-based analysis
            first_tx_time = None
            recent_trades = []
            
            for tx in transactions:
                timestamp = datetime.fromisoformat(tx['timestamp'])
                wallet = tx['accountData']['account']
                is_buy = tx['type'] == 'buy'  # Adjust based on actual Helius response
                
                if not first_tx_time:
                    first_tx_time = timestamp
                
                # Update buyer stats
                if is_buy:
                    if not buyers[wallet]['first_buy_time']:
                        buyers[wallet]['first_buy_time'] = timestamp
                    buyers[wallet]['total_bought'] += tx['amount']
                    buyers[wallet]['buy_count'] += 1
                else:
                    buyers[wallet]['total_sold'] += tx['amount']
                    buyers[wallet]['sell_count'] += 1
                
                # Track recent activity (last 4h)
                if (datetime.now() - timestamp).total_seconds() < 14400:  # 4 hours
                    recent_trades.append({
                        'timestamp': timestamp,
                        'wallet': wallet,
                        'is_buy': is_buy,
                        'amount': tx['amount']
                    })
            
            return {
                'buyers': buyers,
                'recent_trades': recent_trades,
                'token_age': datetime.now() - first_tx_time if first_tx_time else None
            } 