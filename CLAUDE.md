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