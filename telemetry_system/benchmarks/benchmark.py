import subprocess
import time
import psutil
import csv
import sys
import threading
import argparse

def measure_server_resources(server_proc, stop_event, output_csv):
    """Periodically write server CPU and Mem out to a CSV"""
    p = psutil.Process(server_proc.pid)
    with open(output_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["time", "cpu_percent", "mem_mb"])
        
        while not stop_event.is_set():
            try:
                cpu = p.cpu_percent(interval=1.0)
                mem = p.memory_info().rss / (1024 * 1024)
                writer.writerow([time.time(), cpu, mem])
            except psutil.NoSuchProcess:
                break

def run_benchmark(num_clients, rate, duration):
    print(f"--- Starting Benchmark: {num_clients} clients at {rate} msg/s for {duration} seconds ---")
    server_metrics = f"server_stats_{num_clients}_clients.csv"
    sys_metrics = f"sys_usage_{num_clients}_clients.csv"
    
    server_cmd = [
        sys.executable, "../server/server.py", 
        "--metrics", server_metrics
    ]
    server_proc = subprocess.Popen(server_cmd)
    
    time.sleep(2) # Give server time to bind and generate contexts
    
    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=measure_server_resources, args=(server_proc, stop_event, sys_metrics))
    monitor_thread.start()
    
    clients = []
    for i in range(1, num_clients + 1):
        c_cmd = [
            sys.executable, "../client/client.py",
            "--client-id", str(i),
            "--rate", str(rate),
            "--duration", str(duration)
        ]
        clients.append(subprocess.Popen(c_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(0.05) # Prevent TCP TLS backlog bursts
        
    for c in clients:
        c.wait()
        
    print(f"Clients finished. Shutting down server...")
    stop_event.set()
    monitor_thread.join()
    
    server_proc.terminate()
    server_proc.wait()
    print(f"Benchmark run complete.\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=15, help="Test duration per step")
    args = parser.parse_args()
    
    client_counts = [1, 5, 10, 20, 50]
    for count in client_counts:
        run_benchmark(count, rate=50.0, duration=args.duration)
        
    print("All benchmarks complete. Use plot_results.py to visualize.")
