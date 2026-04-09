# 🌐 SDN Bandwidth Measurement and Analysis
### Orange Level Project – Computer Networks (UE24CS252B) | PES University

---

## Problem Statement

Modern networks must handle varying traffic loads across different topologies. This project implements an SDN-based solution using **Mininet** and the **Ryu OpenFlow controller** to:

- Measure and compare bandwidth across **three different network topologies** (Linear, Star, Tree)
- Observe how network structure affects throughput and latency
- Install and monitor OpenFlow flow rules in real-time
- Analyze performance using `iperf` and `ping` with statistics logging

---

## Architecture Overview

```
┌─────────────────────────────────────┐
│         Ryu Controller              │
│  ┌─────────────────────────────┐   │
│  │  Learning Switch Logic      │   │
│  │  + Port Stats Polling (5s)  │   │
│  │  + Bandwidth Calculator     │   │
│  │  + CSV Logger               │   │
│  └─────────────────────────────┘   │
└──────────────┬──────────────────────┘
               │ OpenFlow 1.3
    ┌──────────┴──────────┐
    │   OVS Switches      │
    │  (Mininet Topology) │
    └─────────────────────┘
```

### Topology 1 – Linear
```
h1 ──── s1 ──── s2 ──── h2
         (5ms)  (2ms)
```

### Topology 2 – Star
```
        h1
         │
h3 ───  s1  ─── h2
         │
        h4
```

### Topology 3 – Tree (2-level)
```
            s1 (core)
           /         \
         s2            s3
        /  \          /  \
       h1   h2       h3   h4
```

---

## Flow Rule Design

| Priority | Match Fields         | Action         | Idle Timeout | Hard Timeout |
|----------|----------------------|----------------|--------------|--------------|
| 0        | (any)                | → Controller   | 0 (permanent)| 0            |
| 1        | in_port + eth_src + eth_dst | → out_port | 30s        | 120s         |

- **Table-miss rule** (priority 0): Sends unknown packets to controller (triggers `packet_in`)
- **Learned rule** (priority 1): Installed after MAC learning; expires if idle >30s

---

## Setup & Execution

### Prerequisites
- Ubuntu 20.04/22.04 VM
- Mininet installed (`sudo apt install mininet -y`)
- Ryu framework (`pip3 install ryu`)
- Open vSwitch (`sudo apt install openvswitch-switch -y`)

### Step 1: Install dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install mininet openvswitch-switch iperf wireshark -y
pip3 install ryu
```

### Step 2: Clean any previous Mininet state
```bash
sudo mn -c
```

### Step 3: Start the Ryu Controller (Terminal 1)
```bash
ryu-manager bandwidth_controller.py --observe-links
```
> Controller will listen on port 6633 and begin logging.

### Step 4: Run a Topology (Terminal 2)

**Linear Topology (basic 2-host path):**
```bash
sudo python3 topologies.py --topo linear --bw 10
```

**Star Topology (4 hosts, shared switch):**
```bash
sudo python3 topologies.py --topo star --bw 10
```

**Tree Topology (hierarchical, 4 hosts):**
```bash
sudo python3 topologies.py --topo tree --bw 10
```

---

## Test Scenarios

### Scenario 1 – Connectivity Verification
```bash
mininet> pingall
```
**Expected:** All hosts reach each other. 0% packet loss.

### Scenario 2 – Single-Flow Bandwidth (iperf)
```bash
mininet> h1 iperf -s &
mininet> h2 iperf -c 10.0.1.1 -t 10
```
**Expected:** Throughput close to the configured link bandwidth (e.g., ~9.x Mbps for 10 Mbps cap).

### Scenario 3 – Parallel Flows (Contention)
```bash
mininet> h1 iperf -s -D
mininet> h3 iperf -s -D
mininet> h2 iperf -c 10.0.1.1 -t 10 &
mininet> h4 iperf -c 10.0.1.3 -t 10
```
**Expected (Star):** Total throughput splits across competing flows, each gets ~50% of link bandwidth.

### Scenario 4 – Flow Table Inspection
```bash
mininet> sh ovs-ofctl dump-flows s1
```
**Expected:** Shows installed match-action rules with packet/byte counters.

---

## Expected Output

### Controller Terminal
```
10:23:01 [INFO] ─────────────────────────────────────────────────────────────
10:23:01 [INFO]   Switch 0000000000000001  │  Port Statistics
10:23:01 [INFO]   Port   │ RX (bps)        │ TX (bps)        │ RX Pkts   │ TX Pkts
10:23:01 [INFO]   1      │ 9834201.6       │ 132.0           │ 7823      │ 38
10:23:01 [INFO]   2      │ 131.2           │ 9834190.1       │ 38        │ 7823
```

### bandwidth_log.csv (auto-generated)
```csv
timestamp,datapath_id,port_no,rx_bps,tx_bps,rx_packets,tx_packets
10:23:01,0000000000000001,1,9834201.60,132.00,7823,38
```

---

## Performance Analysis

| Metric       | Linear     | Star (1 flow) | Star (2 flows) | Tree (intra) | Tree (inter) |
|-------------|------------|---------------|----------------|--------------|--------------|
| Throughput  | ~9.5 Mbps  | ~9.5 Mbps     | ~4.7 Mbps each | ~9.5 Mbps   | ~9.5 Mbps    |
| Latency     | ~12ms RTT  | ~4ms RTT      | ~4ms RTT       | ~10ms RTT   | ~11ms RTT    |
| Bottleneck  | Series links| Switch fabric | Shared uplink  | Edge link   | Core link    |

**Key Findings:**
- Linear topology shows cumulative latency from series links
- Star topology demonstrates bandwidth contention when multiple flows share the switch
- Tree topology shows higher throughput for intra-subtree traffic (no core switch traversal)

---

## Repository Structure

```
├── bandwidth_controller.py  # Ryu SDN controller with stats monitoring
├── topologies.py            # Mininet topology definitions + automated tests
├── bandwidth_log.csv        # Auto-generated bandwidth measurements
└── README.md                # This file
```

---

## Validation & Regression Tests

| Test | Expected | Pass Condition |
|------|----------|----------------|
| `pingall` | 0% packet loss | All hosts reachable |
| Single iperf (10 Mbps cap) | ≥9 Mbps throughput | Within 10% of cap |
| Parallel iperf (2 flows, 10 Mbps) | ~5 Mbps each | Sum ≤ cap |
| Flow table after ping | ≥1 rule installed | `ovs-ofctl` shows priority=1 |
| Stats polling | Logs every 5s | CSV grows every 5s |

---

## References

1. Mininet Overview – https://mininet.org/overview/
2. Ryu SDN Framework – https://ryu.readthedocs.io/
3. OpenFlow 1.3 Specification – https://opennetworking.org/
4. Mininet Walkthrough – https://mininet.org/walkthrough/
5. Open vSwitch Docs – https://docs.openvswitch.org/
6. Mininet GitHub – https://github.com/mininet/mininet

---

*Individual Project | PES University | Computer Networks UE24CS252B*
