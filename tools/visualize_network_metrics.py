#!/usr/bin/env python3
"""
Visualization script for network metrics data
"""

import matplotlib.pyplot as plt
import pandas as pd

# Load the CSV file
csv_path = "tmp/linux_runs/metrics/network_metrics_20251130_201446.csv"

# Read the data
df = pd.read_csv(csv_path)

# Convert timestamp to datetime
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Convert session duration to hours
df['session_duration_hours'] = df['session_duration_seconds'] / 3600

# Apply rolling average for smooth curves with larger window
df['dropped_smooth'] = df['dropped_packets'].rolling(window=150, center=True).mean()
df['ooo_smooth'] = df['out_of_order_packets'].rolling(window=150, center=True).mean()

# Create a figure with single subplot
fig, ax2 = plt.subplots(figsize=(12, 6))
fig.suptitle('Network Metrics Analysis', fontsize=16, fontweight='bold')

# 2. Dropped and Out-of-Order Packets
#ax2.plot(df['session_duration_hours'], df['dropped_packets'], label='Dropped (raw)', linewidth=1, color='#A23B72', alpha=0.3)
ax2.plot(df['session_duration_hours'], df['dropped_smooth'], label='Dropped', linewidth=2.5, color='#A23B72')
#ax2.plot(df['session_duration_hours'], df['out_of_order_packets'], label='Out of Order (raw)', linewidth=1, color='#F18F01', alpha=0.3)
ax2.plot(df['session_duration_hours'], df['ooo_smooth'], label='Out of Order', linewidth=2.5, color='#F18F01')
ax2.set_title('Dropped vs Out-of-Order Packets', fontweight='bold')
ax2.set_xlabel('Session Duration (hours)')
ax2.set_ylabel('Packets')
ax2.legend()
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:.1f}'))

plt.tight_layout()

# Save the figure
output_path = "network_metrics_visualization.png"
plt.savefig(output_path, dpi=300, bbox_inches='tight')
print(f"✓ Visualization saved to: {output_path}")

# Print some basic statistics
print("\n=== Network Metrics Summary ===")
print(f"Time Range: {df['timestamp'].min()} to {df['timestamp'].max()}")
print(f"Total Samples: {len(df)}")
print("\nTotal Packets:")
print(f"  Min: {df['total_packets'].min()}")
print(f"  Max: {df['total_packets'].max()}")
print(f"  Mean: {df['total_packets'].mean():.1f}")
print("\nDropped Packets:")
print(f"  Total: {df['dropped_packets'].sum()}")
print(f"  Max in single sample: {df['dropped_packets'].max()}")
print("\nOut-of-Order Packets:")
print(f"  Total: {df['out_of_order_packets'].sum()}")
print(f"  Max in single sample: {df['out_of_order_packets'].max()}")
print("\nSession Duration:")
print(f"  Total: {df['session_duration_seconds'].sum():.1f} seconds")
print(f"  Final: {df['session_duration_seconds'].iloc[-1]:.1f} seconds")

plt.show()
