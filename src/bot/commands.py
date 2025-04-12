from telegram import Update
from telegram.ext import ContextTypes
from src.config.config import ALLOWED_USERS
from src.dune.client import DuneAnalytics
from src.utils.plotting import create_whale_flow_chart, base64_to_buffer
import logging
import pandas as pd
from telegram.ext import Application, CommandHandler
from src.services.cache_service import cache_command
from functools import wraps
import time

logger = logging.getLogger(__name__)

async def check_auth(update: Update) -> bool:
    """Check if user is authorized to use the bot"""
    user_id = str(update.effective_user.id)
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return False
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command"""
    user_id = str(update.effective_user.id)
    
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    await update.message.reply_text(help_text)

def command_handler(func):
    """Wrapper to handle message sending for cached commands"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = await func(update, context)
        if result:
            if isinstance(result, dict) and 'message' in result and 'chart_base64' in result:
                # Send text message
                await update.message.reply_text(
                    result['message'],
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                # Convert base64 back to buffer and send photo
                chart_buffer = base64_to_buffer(result['chart_base64'])
                await update.message.reply_photo(chart_buffer)
            else:
                # Handle text-only messages as before
                await update.message.reply_text(
                    result,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
    return wrapper

def format_whale_message(df: pd.DataFrame) -> str:
    """Format whale analysis data into a message"""
    # Convert numeric columns to float
    numeric_columns = ['current_price', 'total_supply', 'token_balance', 'total_bought_usd', 
                      'usd_value', 'unrealized_pnl', 'net_position_7d_usd', 
                      'net_position_30d_usd', 'net_position_90d_usd']
    
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    current_price = float(df['current_price'].iloc[0])
    total_whales = len(df)
    token_symbol = df['token_symbol'].iloc[0]
    total_supply = float(df['total_supply'].iloc[0])
    current_mcap = float(current_price * total_supply)
    
    message = f"🐋 Whale Analysis for ${token_symbol}\n\n"
    message += f"💰 Price: ${current_price:.4f}\n"
    message += f"🏦 MCap: ${current_mcap:,.0f}\n"
    message += f"📊 Total Whales: {total_whales}\n\n"
    
    # Sort by current holdings (usd_value) for top 5 display
    # Filter to only include current holders (token_balance > 0) first
    current_holders = df[df['token_balance'] > 0].sort_values('usd_value', ascending=False)
    top_5_holders = current_holders.head(5)
    
    # Add top 5 whales with HTML formatting
    message += "Top 5 Current Holders:\n"
    for idx, (_, whale) in enumerate(top_5_holders.iterrows(), 1):
        addr_short = f"{whale['address'][:6]}...{whale['address'][-4:]}"
        solscan_link = f"https://solscan.io/account/{whale['address']}"
        supply_pct = float(str(whale['supply_owned']).replace('%', ''))
        
        # Calculate average cost basis and equivalent marketcap
        token_balance = float(whale['token_balance'])
        capital_invested = float(whale['total_bought_usd'])
        avg_cost_per_token = capital_invested / token_balance if token_balance > 0 else 0
        cost_basis_mcap = float(avg_cost_per_token * total_supply)
        
        # Format position status
        position_status = f"💰 Value: ${float(whale['usd_value']):,.0f}"
        
        message += (
            f"{idx}. <a href='{solscan_link}'>{addr_short}</a> ({supply_pct:.2f}%)\n"
            f"   {position_status}\n"
            f"   💵 PnL: ${float(whale['unrealized_pnl']):,.0f}\n"
            f"   💎 Cost Basis MCap: ${cost_basis_mcap:,.0f}\n"
            f"   📊 Status: {whale['behavior_pattern']}\n"
            f"   7d: ${float(whale['net_position_7d_usd']):,.0f} | "
            f"30d: ${float(whale['net_position_30d_usd']):,.0f} | "
            f"90d: ${float(whale['net_position_90d_usd']):,.0f}\n\n"
        )
    
    # Add behavior summary
    behavior_counts = df['behavior_pattern'].value_counts()
    message += "📈 Behavior Summary:\n"
    for pattern, count in behavior_counts.items():
        emoji = {
            'STRONG_ACCUMULATING': '🟢',
            'ACCUMULATING': '🔵',
            'STRONG_DISTRIBUTING': '🔴',
            'DISTRIBUTING': '🟡',
            'HOLDING': '⚪️',
            'MIXED': '🟣',
            'ALPHA_ACCUMULATING': '💎',
            'ALPHA_DISTRIBUTING': '⚠️',
            'ALPHA_NEUTRAL': '🔷',
            'EXITED': '📤'
        }.get(pattern, '⚪️')
        message += f"{emoji} {pattern}: {count} whales\n"
        
    return message

@command_handler
@cache_command(expire_minutes=60)
async def whales_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get whale analysis for a specific token"""
    if not await check_auth(update):
        return
        
    if not context.args:
        await update.message.reply_text("Please provide a contract address.\nUsage: /whales <contract_address>")
        return
        
    contract_address = context.args[0]
    try:
        start_time = time.time()  # Add timing
        await update.message.reply_text(f"📊 Analyzing whales for: <code>{contract_address}</code>...\nPlease wait...", parse_mode='HTML')
        
        dune = DuneAnalytics()
        df = await dune.get_whale_analysis(contract_address)
        
        if df.empty:
            return "❌ No whale data found for this token."
            
        # Generate the text message
        message = format_whale_message(df)
        
        # Generate the flow chart
        token_symbol = df['token_symbol'].iloc[0]
        base64_str, chart_buffer = create_whale_flow_chart(df, token_symbol)
        
        execution_time = time.time() - start_time  # Calculate execution time
        logger.info(f"Whales command executed in {execution_time:.2f} seconds")  # Log timing
        
        # Return message and base64 string for caching
        return {
            'message': message,
            'chart_base64': base64_str
        }
        
    except Exception as e:
        logger.error(f"Error in whales command: {e}")
        return "❌ Error occurred while analyzing whales. Please try again later."

@command_handler
async def heatmap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get heatmap analysis"""
    if not await check_auth(update):
        return
        
    try:
        # Parse mode from arguments
        mode = 'elite'  # default to elite mode
        if context.args:
            if context.args[0].lower() == 'all':
                mode = 'all'
            elif context.args[0].lower() != 'elite':
                return "❌ Invalid mode. Usage: /heatmap [elite|all]"

        # Call the appropriate cached function based on mode
        if mode == 'all':
            return await _heatmap_all(update, context)
        else:
            return await _heatmap_elite(update, context)
        
    except Exception as e:
        logger.error(f"Error in heatmap command: {e}")
        return "❌ Error occurred while analyzing alpha activity. Please try again later."

@cache_command(expire_minutes=15)
async def _heatmap_elite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get heatmap analysis for elite traders only"""
    await update.message.reply_text("🔍 Analyzing alpha activity...\nPlease wait...")
    
    dune = DuneAnalytics()
    # Use the elite-only query that filters out "Other" category
    df = await dune.get_heatmap_analysis(query_id=4830441)
    
    if df is None or df.empty:
        return "❌ No data found. Please try again later."
    
    message = await format_heatmap(df, is_elite_mode=True)
    message = "Mode: Elite Traders Only\n\n" + message
    return message

@cache_command(expire_minutes=15)
async def _heatmap_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get heatmap analysis for all traders"""
    await update.message.reply_text("🔍 Analyzing alpha activity...\nPlease wait...")
    
    dune = DuneAnalytics()
    # Use the original query that includes all traders
    df = await dune.get_heatmap_analysis(query_id=4723009)
    
    if df is None or df.empty:
        return "❌ No data found. Please try again later."
    
    message = await format_heatmap(df, is_elite_mode=False)
    message = "Mode: All Traders\n\n" + message
    return message

async def test_alpha_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test alpha tracker functionality"""
    if not await check_auth(update):
        return
        
    try:
        await update.message.reply_text("🔄 Testing alpha tracker...")
        await context.application.alpha_tracker.update_alpha_addresses()
        num_addresses = len(context.application.alpha_tracker.alpha_addresses)
        await update.message.reply_text(f"✅ Successfully loaded {num_addresses} alpha addresses")
    except Exception as e:
        logger.error(f"Error testing alpha tracker: {e}")
        await update.message.reply_text("❌ Error testing alpha tracker")

def format_token_info(row, timeframe='1h', is_elite_mode=False):
    flow = row[f'flow_{timeframe}']
    flow_abs = abs(flow)
    
    # Format dollar amount with K/M suffix
    if flow_abs >= 1_000_000:
        flow_str = f"${flow_abs/1_000_000:.1f}M"
    elif flow_abs >= 1000:
        flow_str = f"${flow_abs/1000:.1f}K"
    else:
        flow_str = f"${flow_abs:.0f}"
    
    alpha_count = row['active_alphas']
    
    # Format average market cap at entry if available
    mcap_str = ""
    if 'avg_mcap_at_entry' in row and row['avg_mcap_at_entry'] is not None:
        mcap = float(row['avg_mcap_at_entry'])
        if mcap >= 1_000_000_000:  # Billions
            mcap_str = f" | MCap: ${mcap/1_000_000_000:.1f}B"
        elif mcap >= 1_000_000:    # Millions
            mcap_str = f" | MCap: ${mcap/1_000_000:.1f}M"
        elif mcap >= 1000:         # Thousands
            mcap_str = f" | MCap: ${mcap/1000:.0f}K"
        else:
            mcap_str = f" | MCap: ${mcap:.0f}"
    
    # Format timestamp
    last_trade_str = ""
    if 'last_trade' in row and row['last_trade'] is not None:
        last_trade_str = f"\nLast Trade: {row['last_trade']}"
    
    # Format wallet list with GMGN links
    wallet_str = ""
    if 'involved_wallets' in row and row['involved_wallets']:
        wallets = row['involved_wallets'].split(',')
        wallet_links = []
        for wallet in wallets:
            wallet = wallet.strip()
            short_wallet = f"{wallet[:4]}...{wallet[-4:]}"
            gmgn_link = f"https://gmgn.io/wallet/{wallet}"
            wallet_links.append(f"<a href='{gmgn_link}'>{short_wallet}</a>")
        wallet_str = f"\nWallets: {' | '.join(wallet_links)}"
    
    # Format with copyable CA at the end, include market cap, timestamp and wallets
    return (
        f"⚡️ ${row['symbol']}: {flow_str} "
        f"({'🟢' if flow > 0 else '🔴'}) "
        f"[{alpha_count}w{mcap_str}] | "
        f"<code>{row['token_address']}</code>"
        f"{last_trade_str}"
        f"{wallet_str}"
    )

async def format_heatmap(df: pd.DataFrame, is_elite_mode: bool = False) -> str:
    """Format heatmap data for clear alpha signals"""
    
    if df.empty:
        return "🔍 No significant alpha activity detected in the last 24h"
    
    # Start with explanation of how to copy CAs
    message = [
        "💡 Click on the contract address to copy it\n"
    ]
    
    # Set thresholds based on mode
    high_alpha_threshold = 2 if is_elite_mode else 10
    medium_alpha_threshold = 1 if is_elite_mode else 5
    
    # 1H Activity
    active_1h_df = df.copy()
    message.append("⚡️ Live Alpha Activity (1H)")
    if not active_1h_df.empty:
        sorted_1h = active_1h_df.sort_values(
            by=['active_alphas', 'flow_1h'], 
            ascending=[False, False]
        ).head(10)
        for _, row in sorted_1h.iterrows():
            formatted = format_token_info(row, '1h', is_elite_mode)
            if formatted:
                message.append(formatted)
    else:
        message.append("No immediate alpha activity")
    
    # 4H Activity
    active_4h_df = df.copy()
    message.append("\n🔥 Recent Alpha Activity (4H)")
    if not active_4h_df.empty:
        sorted_4h = active_4h_df.sort_values(
            by=['active_alphas', 'flow_4h'], 
            ascending=[False, False]
        ).head(10)
        for _, row in sorted_4h.iterrows():
            formatted = format_token_info(row, '4h', is_elite_mode)
            if formatted:
                message.append(formatted)
    else:
        message.append("No recent alpha activity")
    
    # 24H Activity
    active_24h_df = df.copy()
    if not active_24h_df.empty:
        message.append("\n📊 24H Alpha Activity")
        
        sorted_df = active_24h_df.sort_values(
            by=['active_alphas', 'flow_24h'],
            ascending=[False, False]
        )
        
        # High Alpha (2+ alphas for elite mode, 10+ for all mode)
        high_alpha = sorted_df[sorted_df['active_alphas'] >= high_alpha_threshold]
        if not high_alpha.empty:
            message.append("\n🔥 High Alpha Interest:")
            for _, row in high_alpha.head(10).iterrows():
                formatted = format_token_info(row, '24h', is_elite_mode)
                if formatted:
                    message.append(formatted)
        
        # Medium Alpha (1 alpha for elite mode, 5-9 for all mode)
        medium_alpha = sorted_df[
            (sorted_df['active_alphas'] >= medium_alpha_threshold) & 
            (sorted_df['active_alphas'] < high_alpha_threshold)
        ]
        if not medium_alpha.empty:
            message.append("\n📈 Medium Alpha Interest:")
            for _, row in medium_alpha.head(8).iterrows():
                formatted = format_token_info(row, '24h', is_elite_mode)
                if formatted:
                    message.append(formatted)
    
    return "\n".join(message)

welcome_message = (
    "🔍 Welcome to CA Scanner Bot!\n\n"
    "Available commands:\n"
    "/whales <contract_address> - Get whale analysis\n"
    "/heatmap [elite|all] - View live alpha wallet activity\n"
    "/help - Show this help message\n"
    "/testalpha - Test alpha tracker functionality"
)

help_text = (
    "🤖 CA Scanner Bot Commands:\n\n"
    "/whales <contract_address>\n"
    "- Get detailed whale analysis for a token\n\n"
    "/heatmap [elite|all]\n"
    "- View live alpha wallet activity\n"
    "- Use 'elite' for elite traders only (default)\n"
    "- Use 'all' to include all traders\n\n"
    "/testalpha\n"
    "- Test alpha tracker functionality\n\n"
    "/help\n"
    "- Show this help message"
)

