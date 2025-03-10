from telegram import Update
from telegram.ext import ContextTypes
from src.config.config import ALLOWED_USERS
from src.dune.client import DuneAnalytics
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
    help_text = """
Available commands:
/help - Show this help message
/whales <contract_address> - Get detailed whale analysis and behavior patterns
/testalpha - Test alpha tracker functionality
"""
    await update.message.reply_text(help_text)

def command_handler(func):
    """Wrapper to handle message sending for cached commands"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = await func(update, context)
        if result:  # Only send if we got a result
            await update.message.reply_text(
                result,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
    return wrapper

def format_whale_message(df: pd.DataFrame) -> str:
    """Format whale analysis data into a message"""
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
    for i, whale in top_5_holders.iterrows():
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
            f"{i+1}. <a href='{solscan_link}'>{addr_short}</a> ({supply_pct:.2f}%)\n"
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
            
        message = format_whale_message(df)
        execution_time = time.time() - start_time  # Calculate execution time
        logger.info(f"Whales command executed in {execution_time:.2f} seconds")  # Log timing
        return message
        
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
    df = await dune.get_heatmap_analysis()
    
    if df is None or df.empty:
        return "❌ No data found. Please try again later."
        
    # Filter out "Other" category
    df = df[df['trader_type'] != 'Other']
    
    message = await format_heatmap(df)
    message = "Mode: Elite Traders Only\n\n" + message
    return message

@cache_command(expire_minutes=15)
async def _heatmap_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get heatmap analysis for all traders"""
    await update.message.reply_text("🔍 Analyzing alpha activity...\nPlease wait...")
    
    dune = DuneAnalytics()
    df = await dune.get_heatmap_analysis()
    
    if df is None or df.empty:
        return "❌ No data found. Please try again later."
    
    message = await format_heatmap(df)
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

def format_token_info(row, timeframe='1h'):
    flow = row[f'flow_{timeframe}']
    flow_abs = abs(flow)
    
    # Only show tokens with >$10k flow
    if flow_abs < 10000:
        return None
        
    # Format dollar amount with K/M suffix
    if flow_abs >= 1_000_000:
        flow_str = f"${flow_abs/1_000_000:.1f}M"
    elif flow_abs >= 1000:
        flow_str = f"${flow_abs/1000:.1f}K"
    else:
        flow_str = f"${flow_abs:.0f}"
    
    alpha_count = row['active_alphas']
    
    # Format with copyable CA at the end
    return (
        f"⚡️ ${row['symbol']}: {flow_str} "
        f"({'🟢' if flow > 0 else '🔴'}) "
        f"[{alpha_count}w] | "
        f"<code>{row['token_address']}</code>"
    )

async def format_heatmap(df: pd.DataFrame) -> str:
    """Format heatmap data for clear alpha signals"""
    
    if df.empty:
        return "🔍 No significant alpha activity detected in the last 24h"
    
    # Start with explanation of how to copy CAs
    message = [
        "💡 Click on the contract address to copy it\n"
    ]
    
    # 1H Activity
    active_1h_df = df[df['flow_1h'].abs() >= 10000].copy()
    message.append("⚡️ Live Alpha Activity (1H)")
    if not active_1h_df.empty:
        sorted_1h = active_1h_df.sort_values(
            by=['active_alphas', 'flow_1h'], 
            ascending=[False, False]
        ).head(10)
        for _, row in sorted_1h.iterrows():
            formatted = format_token_info(row, '1h')
            if formatted:
                message.append(formatted)
    else:
        message.append("No immediate alpha activity")
    
    # 4H Activity
    active_4h_df = df[df['flow_4h'].abs() >= 10000].copy()
    message.append("\n🔥 Recent Alpha Activity (4H)")
    if not active_4h_df.empty:
        sorted_4h = active_4h_df.sort_values(
            by=['active_alphas', 'flow_4h'], 
            ascending=[False, False]
        ).head(10)
        for _, row in sorted_4h.iterrows():
            formatted = format_token_info(row, '4h')
            if formatted:
                message.append(formatted)
    else:
        message.append("No recent alpha activity")
    
    # 24H Activity
    active_24h_df = df[df['flow_24h'].abs() >= 10000].copy()
    if not active_24h_df.empty:
        message.append("\n📊 24H Alpha Activity")
        
        sorted_df = active_24h_df.sort_values(
            by=['active_alphas', 'flow_24h'],
            ascending=[False, False]
        )
        
        # High Alpha (10+ alphas)
        high_alpha = sorted_df[sorted_df['active_alphas'] >= 10]
        if not high_alpha.empty:
            message.append("\n🔥 High Alpha Interest:")
            for _, row in high_alpha.head(10).iterrows():
                formatted = format_token_info(row, '24h')
                if formatted:
                    message.append(formatted)
        
        # Medium Alpha (5-9 alphas)
        medium_alpha = sorted_df[
            (sorted_df['active_alphas'] >= 5) & 
            (sorted_df['active_alphas'] < 10)
        ]
        if not medium_alpha.empty:
            message.append("\n📈 Medium Alpha Interest:")
            for _, row in medium_alpha.head(8).iterrows():
                formatted = format_token_info(row, '24h')
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

