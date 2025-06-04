from dune_client.client import DuneClient
from dune_client.types import QueryParameter
from dune_client.query import QueryBase
import os
from dotenv import load_dotenv
import pandas as pd
import logging
import asyncio

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
                query_id=4780669,
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

    async def get_heatmap_analysis(self, query_id: int = 4723009) -> pd.DataFrame:
        """Execute query for heatmap analysis of alpha wallet activity"""
        try:
            # Create query object
            query = QueryBase(
                name="Heatmap Analysis",
                query_id=query_id
            )
            
            # Execute query
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
            logger.error(f"Error executing heatmap analysis query: {e}")
            raise 

    async def scan_ca(self, contract_address: str) -> pd.DataFrame:
        """Execute query to scan a specific token"""
        try:
            query = QueryBase(
                name="CA Scan",
                query_id=5088772,
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
            logger.error(f"Error executing CA scan query: {str(e)}")
            logger.error(f"Query parameters: Contract Address={contract_address}")
            raise 

    async def get_inflows(self, hours_interval: int = 24, top_n: int = 50) -> pd.DataFrame:
        """Execute query for inflows/outflows for all tokens"""
        try:
            query = QueryBase(
                name="Token Inflows/Outflows",
                query_id=5232825,
                params=[
                    QueryParameter.number_type(
                        name="hours_interval",
                        value=hours_interval
                    ),
                    QueryParameter.number_type(
                        name="top_n",
                        value=top_n
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
            logger.error(f"Error executing inflows query: {e}")
            raise 