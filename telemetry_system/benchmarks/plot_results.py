import pandas as pd
import matplotlib.pyplot as plt
import os
import argparse

def plot_benchmarks():
    client_counts = [1, 5, 10, 20, 50]
    throughputs = []
    loss_rates = []
    
    for count in client_counts:
        file_path = f"server_stats_{count}_clients.csv"
        if not os.path.exists(file_path):
            print(f"Skipping {count} clients: file not found.")
            continue
            
        df = pd.read_csv(file_path)
        
        # Calculate derived throughput (recvs roughly per 10s log intervals)
        total_recv = df['received'].sum()
        max_time = df['timestamp_epoch'].max()
        min_time = df['timestamp_epoch'].min()
        
        duration = max_time - min_time if (max_time - min_time) > 0 else 10
        throughput = total_recv / duration
        throughputs.append((count, throughput))
        
        # Average loss rate
        avg_loss = df['loss_pct'].mean()
        loss_rates.append((count, avg_loss))

    if not throughputs:
        print("No data found to plot.")
        return

    x_clients_t = [x[0] for x in throughputs]
    y_throughput = [x[1] for x in throughputs]
    
    x_clients_l = [x[0] for x in loss_rates]
    y_loss = [x[1] for x in loss_rates]

    # Plot Throughput vs Client Count
    plt.figure(figsize=(10, 5))
    plt.subplot(1, 2, 1)
    plt.plot(x_clients_t, y_throughput, marker='o', linestyle='-', color='b')
    plt.title('Throughput vs Client Count')
    plt.xlabel('Number of Clients')
    plt.ylabel('Throughput (packets/sec)')
    plt.grid(True)
    
    # Plot Packet Loss vs Client Count
    # Simulating Packet Rate proxy: higher clients at fixed rate = higher system packet rate
    plt.subplot(1, 2, 2)
    plt.plot(x_clients_l, y_loss, marker='x', linestyle='--', color='r')
    plt.title('Loss Rate vs Client Count')
    plt.xlabel('Number of Clients')
    plt.ylabel('Loss Rate (%)')
    plt.grid(True)
    
    plt.tight_layout()
    plt.savefig('benchmark_results.png')
    print("Saved plots to benchmark_results.png")
    
if __name__ == "__main__":
    plot_benchmarks()
