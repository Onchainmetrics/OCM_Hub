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
    plt.style.use('seaborn')
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Create horizontal bars
    bars = ax.barh(
        whale_summary['behavior_pattern'],
        whale_summary['flow_90d'] / 1000,  # Convert to thousands
        color=['#00C805' if x > 0 else '#FF4B4B' for x in whale_summary['flow_90d']]
    )
    
    # Add wallet count and average flow annotations
    for idx, bar in enumerate(bars):
        row = whale_summary.iloc[idx]
        flow = row['flow_90d']
        wallet_count = row['wallet_count']
        avg_flow = row['avg_flow_per_wallet'] / 1000  # Convert to thousands
        
        # Position the text based on whether the flow is positive or negative
        x_pos = bar.get_x() + (bar.get_width() if flow > 0 else 0)
        ha = 'left' if flow > 0 else 'right'
        x_offset = 0.1 if flow > 0 else -0.1
        
        ax.text(
            x_pos + x_offset * max(abs(whale_summary['flow_90d'])) / 1000,
            bar.get_y() + bar.get_height()/2,
            f"{wallet_count} whales\n${abs(avg_flow):,.1f}k/whale",
            va='center',
            ha=ha,
            fontsize=9
        )
    
    # Customize the plot
    ax.set_title(
        f"Whale Flows by Behavior Pattern 🐋 | {token_symbol.upper()}\n"
        f"90d flows | As of {datetime.now().strftime('%Y-%m-%d')} | "
        f"{'🟢 Heavy Accumulation' if net_pressure > 40 else '🟡 Accumulation' if net_pressure > 20 else '⚪ Neutral/Mixed' if net_pressure > -20 else '🟠 Distribution' if net_pressure > -40 else '🔴 Heavy Distribution'}",
        pad=20,
        fontsize=12,
        fontweight='bold'
    )
    
    # Add percentage axis on the right
    ax2 = ax.twinx()
    total_flow_k = total_flow / 1000
    ax2.set_ylim(ax.get_ylim())
    ax2.set_yticks(ax.get_yticks())
    ax2.set_yticklabels([f"{abs(x/total_flow_k*100):.0f}%" for x in whale_summary['flow_90d'] / 1000])
    
    # Format the main axis
    ax.set_xlabel("Net Flow (USD, thousands)")
    ax.grid(True, axis='x', alpha=0.3)
    
    # Add caption
    plt.figtext(
        0.99, 0.01,
        "Bars show 90d net flow | Labels show wallet count and average position size",
        ha='right',
        va='bottom',
        fontsize=8,
        style='italic'
    )
    
    # Adjust layout and save to buffer
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=300, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    # Create base64 string for caching
    base64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    return base64_str, buf

def base64_to_buffer(base64_str: str) -> io.BytesIO:
    """Convert a base64 string back to BytesIO buffer"""
    buf = io.BytesIO(base64.b64decode(base64_str))
    return buf 