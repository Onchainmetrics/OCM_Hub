import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from datetime import datetime
import io
import base64

def create_whale_flow_chart(df: pd.DataFrame, token_symbol: str) -> tuple[str, io.BytesIO]:
    """Create a whale flow chart showing net flows by behavior pattern"""
    # Prepare the data
    whale_summary = df.groupby('behavior_pattern').agg({
        'net_position_90d_usd': 'sum',
        'address': 'count',
        'usd_value': 'sum'
    }).reset_index()
    
    whale_summary = whale_summary.rename(columns={
        'address': 'wallet_count',
        'net_position_90d_usd': 'flow_90d',
        'usd_value': 'total_value'
    })
    
    # Calculate average flow per wallet
    whale_summary['avg_flow_per_wallet'] = whale_summary['flow_90d'] / whale_summary['wallet_count']
    
    # Sort by absolute flow value
    whale_summary = whale_summary.sort_values(by='flow_90d', key=abs, ascending=True)
    
    # Calculate total pressure
    total_flow = whale_summary['flow_90d'].abs().sum()
    net_pressure = whale_summary['flow_90d'].sum() / total_flow * 100
    
    # Set up the plot style
    plt.style.use('classic')
    sns.set_style("whitegrid")
    
    # Create figure with adjusted size and DPI
    fig, ax = plt.subplots(figsize=(14, 8), dpi=100)
    
    # Create horizontal bars
    bars = ax.barh(
        whale_summary['behavior_pattern'],
        whale_summary['flow_90d'] / 1000,  # Convert to thousands
        color=['#00C805' if x > 0 else '#FF4B4B' for x in whale_summary['flow_90d']],
        height=0.6  # Reduce bar height for better spacing
    )
    
    # Add wallet count and average flow annotations with adjusted positioning
    for idx, bar in enumerate(bars):
        row = whale_summary.iloc[idx]
        flow = row['flow_90d']
        wallet_count = row['wallet_count']
        avg_flow = row['avg_flow_per_wallet'] / 1000  # Convert to thousands
        
        # Position the text based on whether the flow is positive or negative
        x_pos = bar.get_x() + (bar.get_width() if flow > 0 else 0)
        ha = 'left' if flow > 0 else 'right'
        x_offset = 0.05 if flow > 0 else -0.05  # Reduced offset
        
        # Add text with background for better readability
        text = f"{wallet_count} wallets\n${abs(avg_flow):,.1f}k/wallet"
        ax.text(
            x_pos + x_offset * max(abs(whale_summary['flow_90d'])) / 1000,
            bar.get_y() + bar.get_height()/2,
            text,
            va='center',
            ha=ha,
            fontsize=9,
            bbox=dict(facecolor='white', alpha=0.8, edgecolor='none', pad=1)
        )
    
    # Get trend indicator
    def get_trend_indicator(pressure):
        if pressure > 40: return "HEAVY ACC."
        if pressure > 20: return "ACC."
        if pressure > -20: return "NEUTRAL"
        if pressure > -40: return "DIST."
        return "HEAVY DIST."
    
    trend = get_trend_indicator(net_pressure)
    trend_color = '#00C805' if net_pressure > 0 else '#FF4B4B' if net_pressure < 0 else '#808080'
    
    # Customize the plot with new title format
    title = (
        f"Whale Flows by Behavior Pattern | {token_symbol.upper()}\n"
        f"90d flows | As of {datetime.now().strftime('%Y-%m-%d')} | "
    )
    
    ax.set_title(title, pad=20, fontsize=12, fontweight='bold')
    
    # Add trend as a separate text element with color
    plt.figtext(
        0.5, 0.95,
        trend,
        color=trend_color,
        fontsize=12,
        fontweight='bold',
        ha='center'
    )
    
    # Add percentage axis on the right with improved spacing
    ax2 = ax.twinx()
    total_flow_k = total_flow / 1000
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks(ax.get_yticks())
    ax2.set_yticklabels([f"{abs(x/total_flow_k*100):.0f}%" for x in whale_summary['flow_90d'] / 1000])
    
    # Format the main axis
    ax.set_xlabel("Net Flow (USD, thousands)")
    ax.grid(True, axis='x', alpha=0.3)
    
    # Add caption with improved positioning
    plt.figtext(
        0.99, 0.01,
        "Bars show 90d net flow | Labels show wallet count and average position size",
        ha='right',
        va='bottom',
        fontsize=8,
        style='italic',
        bbox=dict(facecolor='white', alpha=0.8, edgecolor='none', pad=2)
    )
    
    # Adjust layout with specific spacing
    plt.subplots_adjust(top=0.85, bottom=0.1, left=0.15, right=0.85)
    
    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    # Create base64 string for caching
    base64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    return base64_str, buf

def base64_to_buffer(base64_str: str) -> io.BytesIO:
    """Convert a base64 string back to BytesIO buffer"""
    buf = io.BytesIO(base64.b64decode(base64_str))
    return buf 