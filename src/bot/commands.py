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
/holders <contract_address> - Get holder analysis for a specific token
/several - Get tokens held by multiple top wallets
/whales <contract_address> - Get detailed whale analysis and behavior patterns
/testalpha - Test alpha tracker functionality
"""
    await update.message.reply_text(help_text)

async def several_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /several command - Get tokens held by several top wallets"""
    try:
        await update.message.reply_text("🔍 Fetching tokens held by several top wallets...\nPlease wait...")
        
        dune = DuneAnalytics()
        df = await dune.get_several_top_wallets()
        
        if df.empty:
            await update.message.reply_text("No results found.")
            return
        
        # Format the results into a nice message
        message = "🏆 Tokens held by several top wallets:\n\n"
        
        for _, row in df.iterrows():
            # Format each row with a copyable contract address
            message += (
                f"<code>{row['token_mint_address']}</code>\n"
                f"${row['symbol']} | {row['num_top_traders']} traders | "
                f"{row['trader_types']} | "
                f"Min: {row['min_percentage']}% | Max: {row['max_percentage']}%\n\n"
            )
        
        await update.message.reply_text(
            message,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error in several command: {e}")
        await update.message.reply_text("❌ Error occurred while fetching data. Please try again later.")

async def holders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /holders command - Analyze holder distribution by trader category"""
    if not context.args:
        await update.message.reply_text("Please provide a contract address.\nUsage: /holders <contract_address>")
        return
    
    contract_address = context.args[0]
    try:
        await update.message.reply_text(f"📊 Analyzing holders for: <code>{contract_address}</code>...\nPlease wait...", parse_mode='HTML')
        
        dune = DuneAnalytics()
        df = await dune.get_holder_analysis(contract_address)
        
        if df.empty:
            await update.message.reply_text("No top traders found holding this token.")
            return
        
        # Format the results into a nice message
        message = f"📊 Holder Analysis for <code>{contract_address}</code>\n\n"
        message += "Top PnL Traders Breakdown:\n"
        
        total_holders = df['holders_count'].sum()
        
        for _, row in df.iterrows():
            percentage = (row['holders_count'] / total_holders) * 100
            message += (
                f"• {row['trader_category']}: {row['holders_count']} holders "
                f"({percentage:.1f}%)\n"
            )
        
        message += f"\nTotal Top Traders: {total_holders}"
        
        await update.message.reply_text(
            message,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error in holders command: {e}")
        await update.message.reply_text("❌ Error occurred while analyzing holders. Please try again later.")

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
    
    # Add top 5 whales with HTML formatting
    message += "Top 5 by USD Value:\n"
    for i, whale in df.head(5).iterrows():
        addr_short = f"{whale['address'][:6]}...{whale['address'][-4:]}"
        solscan_link = f"https://solscan.io/account/{whale['address']}"
        supply_pct = float(str(whale['supply_owned']).replace('%', ''))
        
        # Calculate average cost basis and equivalent marketcap
        token_balance = float(whale['token_balance'])
        capital_invested = float(whale['capital_invested'])
        avg_cost_per_token = capital_invested / token_balance if token_balance > 0 else 0
        cost_basis_mcap = float(avg_cost_per_token * total_supply)
        
        message += (
            f"{i+1}. <a href='{solscan_link}'>{addr_short}</a> ({supply_pct:.2f}%)\n"
            f"   💰 Value: ${float(whale['usd_value']):,.0f}\n"
            f"   💵 PnL: ${float(whale['unrealized_pnl']):,.0f}\n"
            f"   💎 Cost Basis MCap: ${cost_basis_mcap:,.0f}\n"
            f"   📊 Status: {whale['behavior_pattern']}\n"
            f"   7d: ${float(whale['net_position_7d_usd']):,.0f} | "
            f"30d: ${float(whale['net_position_30d_usd']):,.0f}\n\n"
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
            'ALPHA_NEUTRAL': '🔷'
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
@cache_command(expire_minutes=15)
async def heatmap_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get heatmap analysis"""
    if not await check_auth(update):
        return
        
    try:
        await update.message.reply_text("🔍 Analyzing alpha activity...\nPlease wait...")
        
        dune = DuneAnalytics()
        df = await dune.get_heatmap_analysis()
        
        if df is None or df.empty:
            return "❌ No data found. Please try again later."
            
        message = await format_heatmap(df)
        return message  # Return for caching
        
    except Exception as e:
        logger.error(f"Error in heatmap command: {e}")
        return "❌ Error occurred while analyzing alpha activity. Please try again later."

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
        f"[{alpha_count}w] | "  # Changed from α to w
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
    "/several - Get tokens held by multiple top wallets\n"
    "/holders <contract_address> - Analyze holder distribution\n"
    "/whales <contract_address> - Get whale analysis\n"
    "/heatmap - View live alpha wallet activity\n"
    "/help - Show this help message"
)

help_text = (
    "🤖 CA Scanner Bot Commands:\n\n"
    "/several\n"
    "- Get list of tokens held by multiple top wallets\n\n"
    "/holders <contract_address>\n"
    "- Analyze holder distribution and concentration\n\n"
    "/whales <contract_address>\n"
    "- Get whale analysis\n\n"
    "/heatmap\n"
    "- View live alpha wallet activity\n\n"
    "/help\n"
    "- Show this help message"
)

