# Alpha Tracker Setup Guide

## Overview

The alpha tracker monitors real-time transactions from your list of alpha wallets and detects confluence patterns when multiple alpha wallets perform similar actions on the same token.

## Architecture

1. **Alpha Address Management**: Fetches weekly updated list of alpha traders from Dune Analytics
2. **Helius Webhook**: Receives real-time transaction notifications for tracked wallets
3. **Pattern Detection**: Analyzes transactions on a per-token basis to detect confluence
4. **Telegram Notifications**: Sends alerts when confluence patterns are detected

## Required Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
# Telegram Bot
TELEGRAM_TOKEN=your_bot_token
ALLOWED_USERS=123456789,987654321
ALPHA_NOTIFICATIONS_CHAT_ID=your_chat_id

# Dune Analytics  
DUNE_API_KEY=your_dune_api_key

# Helius (for webhooks)
HELIUS_API_KEY=your_helius_api_key
HELIUS_WEBHOOK_ID=your_webhook_id
WEBHOOK_URL=https://your-domain.com/webhook/helius
WEBHOOK_PORT=8080

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=optional
```

## Setup Steps

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**: Set up your `.env` file with all required variables

3. **Set up Helius Webhook**:
   - Create a webhook in Helius dashboard
   - Set webhook URL to your server: `https://your-domain.com/webhook/helius`
   - The bot will automatically update the webhook with alpha addresses

4. **Start the Bot**:
   ```bash
   python main.py
   ```

## Confluence Detection

The system detects these patterns on a **per-token basis**:

### 1. Alpha Confluence (Primary)
- **Trigger**: 2+ different alpha wallets buying/selling the same token within 30 minutes
- **Example**: Alpha wallet A sells RICO, then Alpha wallet B also sells RICO
- **Notification**: Shows wallets involved and total volume

### 2. Alpha Follow Pattern  
- **Trigger**: Alpha wallet acts first, then 2+ other trader types follow within 2 hours
- **Example**: Alpha buys token X, then Volume Leaders and Position traders also buy

### 3. Diverse Activity Pattern
- **Trigger**: 3+ different trader types active on same token within 1 hour
- **Example**: Alpha, Volume Leaders, and Steady Elite all buying same token

## Testing

Use the built-in test commands:

- `/testalpha` - Test alpha address loading
- `/testconfluence` - Simulate confluence with test data

## Transaction Storage

- Uses Redis for temporary transaction storage (4-hour expiration)
- Stores up to 50 transactions per token to prevent memory issues
- Each token has its own cache key: `token_transactions:{contract_address}`

## Webhook Data Flow

1. **Helius** → Webhook receives transaction data
2. **Parser** → Extracts wallet, token, amounts from transaction
3. **Filter** → Only processes transactions from tracked alpha wallets  
4. **Store** → Saves transaction to Redis with token address as key
5. **Analyze** → Checks for confluence patterns against previous transactions for same token
6. **Notify** → Sends Telegram alert if patterns detected

## Monitoring

- All components include comprehensive logging
- Redis cache handles automatic cleanup
- Pattern detection is optimized for real-time processing
- Webhook server runs on separate port from Telegram bot