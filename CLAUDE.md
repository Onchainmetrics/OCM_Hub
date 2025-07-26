# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Development
- `python main.py` - Start the Telegram bot application
- `python -m pytest` - Run tests (pytest framework)
- `pip install -r requirements.txt` - Install dependencies

### Type Checking and Linting
- Type checking is configured via `pyrightconfig.json` with Python path at `python_env/bin/python`
- The project includes type checking warnings for missing imports

## Architecture Overview

This is a **Telegram bot for cryptocurrency market analysis** that provides real-time alpha trader tracking and token analysis. The system follows a layered architecture:

### Core Components

**Data Layer (`src/dune/`)**
- `DuneAnalytics` class interfaces with Dune Analytics API for blockchain queries
- Key queries: whale analysis (4780669), heatmap analysis (4723009), CA scanning (5088772), inflows (5232825)
- All operations are async with proper error handling

**Service Layer (`src/services/`)**
- `AlphaTracker`: Real-time monitoring using Helius webhooks, maintains trader profiles
- `PatternDetector`: Analyzes transaction patterns for market signals (alpha patterns, sequence patterns, diversity patterns)
- `CacheService`: Redis-based caching with Prometheus metrics and automatic failover

**Bot Layer (`src/bot/`)**
- `TelegramBot`: Main bot class with factory pattern initialization
- Commands: `/whales`, `/heatmap`, `/scan`, `/flows` with caching decorators
- Authorization system using `ALLOWED_USERS` environment variable

**Utilities (`src/utils/`)**
- `plotting.py`: Creates whale flow visualizations using matplotlib/seaborn with base64 caching

### Key Patterns

**Async Operations**: All external API calls (Dune, Helius, Redis) are async
**Caching Strategy**: Function-level caching decorator with Redis backend, includes cache keys with parameters
**Error Handling**: Comprehensive logging and graceful degradation
**Authorization**: User-based access control for bot commands
**Real-time Processing**: Webhook-based transaction monitoring with pattern detection

### Environment Configuration

Required environment variables:
- `TELEGRAM_TOKEN`: Bot authentication
- `DUNE_API_KEY`: Dune Analytics API access
- `ALLOWED_USERS`: Comma-separated user IDs for authorization
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`: Cache configuration

### Data Flow

1. **Real-time**: Helius webhooks → AlphaTracker → PatternDetector → Telegram notifications
2. **On-demand**: Telegram commands → Cached queries → Dune API → Formatted responses
3. **Visualization**: Raw data → Plotting utilities → Base64 charts → Telegram photos

### Cache Management

- Command results cached for 15-120 minutes depending on data volatility
- Cache keys include parameters to ensure unique entries
- Automatic fallback when Redis is unavailable
- Prometheus metrics for monitoring cache performance

### Message Handling

- Messages split automatically if exceeding Telegram's 4096 character limit
- HTML formatting with clickable links for contract addresses and wallet links
- Rich formatting with emojis and structured data presentation

## Framework Directory

The `Framework/` directory contains analytical tools and queries that complement the main Telegram bot functionality. These provide deep on-chain analysis capabilities using R and SQL.

### R Analysis Scripts

**`improved_sleuth_fixed.R`** - Main clustering analysis framework
- **Purpose**: Comprehensive insider/early buyer network analysis
- **Features**: 
  - Descendant tracing using transfer networks
  - Community detection (Louvain clustering)
  - Insider vs Early Buyer vs Late Buyer classification
  - Cluster and individual holder visualization
  - Late buyer clustering analysis (complementary to insider analysis)
- **Outputs**: 
  - Network visualizations with supply-weighted nodes
  - Combined cluster + individual entity rankings
  - CSV exports with cluster metadata
- **Data Sources**: USELESS_insiders.csv, USELESS_all_balances.csv, USELESS_all_transfers.csv

**`insider_activity_analysis.R`** - Trading behavior analysis
- **Purpose**: Analyze trading patterns of clustered vs individual entities
- **Features**:
  - Behavior classification (Accumulating/Distributing/Holding)
  - Flow analysis across multiple timeframes (7d/30d/90d)
  - Cluster dominance patterns and heatmaps
  - Individual vs cluster comparison metrics
- **Outputs**: 
  - Behavior distribution visualizations
  - Trading activity heatmaps
  - Summary tables for entity comparison
- **Data Sources**: USELESS_insiders_activity_clean.csv (from Dune Analytics)

**`address_transfer_checker.R`** - Individual address investigation tool  
- **Purpose**: Debug and trace why specific addresses got classified as insiders/descendants
- **Features**:
  - Transfer history analysis (incoming/outgoing)
  - Descendant path tracing (multi-degree connections)
  - Direct vs indirect insider connection detection
  - Classification validation and debugging
- **Use Case**: Investigate unexpected classifications or validate algorithm results

### SQL Queries (Dune Analytics)

**`insider_flows_query.sql`** - Flow analysis for insider wallets
- **Purpose**: Calculate trading flows and behavior patterns for insider addresses
- **Features**:
  - Net flows across 7d/30d/90d timeframes using actual USD values from trades
  - Behavior classification (STRONG_ACCUMULATING, DISTRIBUTING, etc.)
  - Cluster/Individual entity classification from R analysis
  - Current holdings valuation with price calculation
- **Input**: `dune.latecapdao.dataset_useless_insiders` (exported from R analysis)
- **Parameters**: `{{Contract Address}}` for token-specific analysis

**`early_holders_with_transfers.sql`** - Legacy whale analysis query
- **Purpose**: Identify significant holders and their trading patterns
- **Features**:
  - Historical whale activity analysis
  - Position changes over multiple timeframes
  - PnL calculations and unrealized gains
  - Smart money wallet integration
- **Use Case**: Broader market participant analysis beyond insider networks

### Framework Workflow

1. **Data Collection**: Export insider/descendant addresses from R clustering analysis
2. **Upload to Dune**: Create datasets for SQL-based flow analysis  
3. **Behavior Analysis**: Use R scripts to analyze trading patterns and visualize networks
4. **Investigation**: Use address checker for detailed connection tracing
5. **Integration**: Results feed back into Telegram bot commands for real-time insights

### Key Concepts

- **Descendant Tracing**: Recursive algorithm to find wallets connected through token transfers
- **Cluster Detection**: Community detection algorithms to identify coordinated wallet groups  
- **Flow Analysis**: USD-denominated trading flow calculations using historical trade data
- **Entity Classification**: Combined approach using both network topology and trading behavior