# 🌐 SDN Bandwidth Measurement and Analysis
### Orange Level Project – Computer Networks (UE24CS252B) | PES University

---

## 📌 Table of Contents

1. [Problem Statement](#problem-statement)
2. [Objectives](#objectives)
3. [System Architecture](#system-architecture)
4. [Network Topologies](#network-topologies)
5. [Controller Design](#controller-design)
6. [Flow Rule Design](#flow-rule-design)
7. [Bandwidth Measurement Methodology](#bandwidth-measurement-methodology)
8. [Setup & Installation](#setup--installation)
9. [Running the Project](#running-the-project)
10. [Test Scenarios](#test-scenarios)
11. [Expected Output](#expected-output)
12. [Performance Analysis & Results](#performance-analysis--results)
13. [Repository Structure](#repository-structure)
14. [Validation & Regression Tests](#validation--regression-tests)
15. [Key Concepts](#key-concepts)
16. [References](#references)

---

## Problem Statement

Modern networks must dynamically handle varying traffic loads across different topologies. Traditional networks rely on static routing tables that cannot adapt in real time, leading to inefficient resource utilization and unpredictable performance.

This project implements a **Software-Defined Networking (SDN)** solution using **Mininet** (network emulator) and the **Ryu OpenFlow controller** to:

- Measure and compare **bandwidth across three distinct network topologies**: Linear, Star, and Tree
- Observe how **network structure affects throughput and latency** under real traffic conditions
- Dynamically **install and monitor OpenFlow flow rules** in real time
- Analyze performance using **iperf** (bandwidth) and **ping** (latency) with structured statistics logging

The core insight being tested: *Does topology shape determine performance, and by how much?*

---

## Objectives

| # | Objective |
|---|-----------|
| 1 | Implement a Ryu-based SDN controller with MAC learning and flow rule installation |
| 2 | Build three Mininet topologies (Linear, Star, Tree) with configurable link bandwidth |
| 3 | Poll OpenFlow port statistics every 5 seconds and compute real-time bandwidth (bps) |
| 4 | Log throughput metrics to `bandwidth_log.csv` for post-experiment analysis |
| 5 | Compare bandwidth, latency, and contention behavior across all three topologies |
| 6 | Demonstrate bandwidth contention in shared-switch (Star) topology using parallel iperf flows |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Ryu Controller                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  BandwidthController (bandwidth_controller.py)       │   │
│  │                                                      │   │
│  │   ┌──────────────────┐  ┌────────────────────────┐  │   │
│  │   │  Learning Switch │  │  Stats Monitor Thread  │  │   │
│  │   │  (packet_in)     │  │  (every 5 seconds)     │  │   │
│  │   └──────────────────┘  └────────────────────────┘  │   │
│  │                                                      │   │
│  │   ┌──────────────────┐  ┌────────────────────────┐  │   │
│  │   │  Flow Rule Mgmt  │  │  CSV Logger            │  │   │
│  │   │  (add/expire)    │  │  bandwidth_log.csv     │  │   │
│  │   └──────────────────┘  └────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │ OpenFlow 1.3 (port 6633)
              ┌────────────┴────────────┐
              │    OVS Kernel Switches  │
              │   (Open vSwitch / OVS)  │
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              │  Mininet Virtual Hosts  │
              │   (h1, h2, h3, h4...)   │
              └─────────────────────────┘
```

**Data Plane:** Open vSwitch (OVS) switches emulated by Mininet, connected using `TCLink` for configurable bandwidth and delay.

**Control Plane:** Ryu controller communicates with switches over OpenFlow 1.3. All forwarding decisions originate from the controller.

**Management Plane:** A background monitoring thread in the controller polls statistics and writes results to a CSV file for analysis.

---

## Network Topologies

Three topologies are implemented in `topologies.py`, each designed to highlight different network behaviours.

---

### Topology 1 – Linear (Single Path)

```
h1 ──(5ms)── s1 ──(2ms)── s2 ──(5ms)── h2
             │                   │
         [Switch 1]          [Switch 2]
```

**Description:** Two hosts connected through two switches in series. Every packet between h1 and h2 must traverse both switches.

**What it tests:**
- Baseline point-to-point throughput
- Cumulative latency from series links (5ms + 2ms + 5ms = 12ms RTT)
- Inter-switch forwarding overhead

**IP Addressing:**
- h1: `10.0.1.1/24`
- h2: `10.0.1.2/24`

---

### Topology 2 – Star (Hub-and-Spoke)

```
          h1 (10.0.1.1)
           │
h3 ─────  s1  ───── h2 (10.0.1.2)
(10.0.1.3) │
          h4 (10.0.1.4)
```

**Description:** Four hosts all connected to a single central switch. All inter-host traffic passes through the same switch fabric.

**What it tests:**
- Shared switch bandwidth
- Multi-client contention: when two flows share the same switch simultaneously, each gets roughly 50% of the link capacity
- Single point of failure / bottleneck behaviour

---

### Topology 3 – Tree (2-Level Hierarchy)

```
                s1  (Core Switch)
               /  \
         (2x bw)  (2x bw)
           /          \
         s2              s3  (Aggregation Switches)
        /  \            /  \
      h1    h2        h3    h4
  10.0.1.1  10.0.1.2  10.0.2.1  10.0.2.2
```

**Description:** A two-level hierarchy with a high-bandwidth core link (2× the edge link bandwidth) connecting two aggregation switches, each serving two hosts.

**What it tests:**
- **Intra-subtree traffic** (h1 ↔ h2): Uses only the aggregation switch (s2), does not traverse the core → higher effective bandwidth
- **Inter-subtree traffic** (h1 ↔ h3): Must traverse s2 → s1 → s3 → potential bottleneck at core link
- Hierarchical routing behaviour

---

## Controller Design

### `BandwidthController` (`bandwidth_controller.py`)

The controller extends `app_manager.RyuApp` and implements two interleaved functions:

#### 1. Learning Switch Logic

When a packet arrives at the controller (via `packet_in`), the controller:

1. **Learns** the source MAC address and associates it with the incoming port
2. **Checks** if the destination MAC is already known
   - If **known**: installs a specific flow rule (match on in_port + eth_src + eth_dst → output to learned port)
   - If **unknown**: floods the packet to all ports
3. **Sends** the packet out (either to specific port or flooded)

This prevents future packets to known destinations from reaching the controller — they are handled directly by the switch.

#### 2. Background Statistics Monitor

A separate `hub.spawn` thread runs `_monitor()` continuously:

```
Every 5 seconds:
  For each connected switch (datapath):
    Send OFPPortStatsRequest
    → Receive OFPPortStatsReply (async)
    → Compute bandwidth: (Δbytes × 8) / Δtime
    → Log to console and bandwidth_log.csv
```

#### Internal State

| Variable | Type | Purpose |
|----------|------|---------|
| `mac_to_port` | `{dpid: {mac: port}}` | MAC learning table |
| `prev_stats` | `{(dpid, port): (rx_bytes, tx_bytes, time)}` | Previous poll snapshot for delta calculation |
| `datapaths` | `{dpid: datapath}` | Registry of connected switches |

---

## Flow Rule Design

| Priority | Match Fields | Action | Idle Timeout | Hard Timeout |
|----------|-------------|--------|-------------|-------------|
| 0 | *(any – table-miss)* | → Controller | 0 (permanent) | 0 (permanent) |
| 1 | `in_port` + `eth_src` + `eth_dst` | → specific `out_port` | 30 seconds | 120 seconds |

**Table-miss rule (priority 0):**
- Installed during switch handshake (`switch_features_handler`)
- Catches all packets not matched by any specific rule
- Sends them to the controller to trigger `packet_in`
- Permanent — never expires

**Learned rule (priority 1):**
- Installed after MAC learning when the destination is known
- Expires after 30 seconds of inactivity (idle timeout) or 120 seconds absolute (hard timeout)
- Prevents the controller from being involved in every forwarding decision

---

## Bandwidth Measurement Methodology

The controller computes bandwidth using **delta byte counters** from OpenFlow port statistics:

```
Bandwidth (bps) = (current_bytes − previous_bytes) × 8
                  ─────────────────────────────────────
                         (current_time − previous_time)
```

- **First poll:** No previous data; bandwidth reported as 0.0 bps
- **Subsequent polls:** Delta is computed against the last snapshot
- **Units:** bits per second (bps); divide by 1,000,000 for Mbps
- **Granularity:** Per-port, per-direction (RX and TX reported separately)
- **Poll interval:** 5 seconds (`POLL_INTERVAL = 5`)

All results are written to `bandwidth_log.csv` in real time with format:

```
timestamp,datapath_id,port_no,rx_bps,tx_bps,rx_packets,tx_packets
```

---

## Setup & Installation

### Prerequisites

| Software | Version | Purpose |
|----------|---------|---------|
| Ubuntu | 20.04 or 22.04 | Host OS (VM recommended) |
| Python | 3.8+ | Controller and topology scripts |
| Mininet | Latest | Network emulation |
| Open vSwitch (OVS) | Latest | Virtual switch implementation |
| Ryu Framework | 4.34+ | SDN controller framework |
| iperf | 2.x | Bandwidth measurement |
| Wireshark *(optional)* | Latest | Packet capture and inspection |

### Step-by-Step Installation

**Step 1: Update system packages**
```bash
sudo apt update && sudo apt upgrade -y
```

**Step 2: Install Mininet, OVS, and iperf**
```bash
sudo apt install mininet openvswitch-switch iperf wireshark -y
```

**Step 3: Install Ryu SDN Framework**
```bash
pip3 install ryu
```

**Step 4: Verify installations**
```bash
mn --version         # Should print Mininet version
ryu-manager --version  # Should print Ryu version
ovs-vsctl --version  # Should print OVS version
```

**Step 5: Clean any leftover Mininet state (run before each experiment)**
```bash
sudo mn -c
```

---

## Running the Project

> ⚠️ **Important:** Always start the Ryu controller **before** launching a Mininet topology. Open two separate terminal windows.

### Terminal 1 – Start the Ryu Controller

```bash
ryu-manager bandwidth_controller.py --observe-links
```

You should see:
```
╔══════════════════════════════════════════╗
║  Bandwidth Controller Started            ║
║  Polling interval: 5s                   ║
╚══════════════════════════════════════════╝
```

The controller will listen on port **6633** and begin logging once switches connect.

---

### Terminal 2 – Launch a Topology

**Linear Topology** (2 hosts, 2 switches in series):
```bash
sudo python3 topologies.py --topo linear --bw 10
```

**Star Topology** (4 hosts, 1 central switch):
```bash
sudo python3 topologies.py --topo star --bw 10
```

**Tree Topology** (4 hosts, 3 switches in hierarchy):
```bash
sudo python3 topologies.py --topo tree --bw 10
```

**Optional arguments:**

| Argument | Default | Description |
|----------|---------|-------------|
| `--topo` | `linear` | Topology type: `linear`, `star`, or `tree` |
| `--bw` | `10` | Link bandwidth cap in Mbps |
| `--controller-ip` | `127.0.0.1` | IP address of the Ryu controller |
| `--controller-port` | `6633` | Port of the Ryu controller |

---

## Test Scenarios

The topology script automatically runs these tests after startup. They can also be run manually from the Mininet CLI.

### Scenario 1 – Connectivity Verification (pingall)

```bash
mininet> pingall
```

**Purpose:** Confirm all hosts can reach each other with 0% packet loss.

**What happens internally:** First ping triggers `packet_in` → controller learns MACs → installs flow rules. Second ping is forwarded directly by the switch (no controller involvement).

**Expected:** `*** Results: 0% dropped (N/N received)`

---

### Scenario 2 – Single-Flow Bandwidth (iperf)

```bash
mininet> h1 iperf -s &
mininet> h2 iperf -c 10.0.1.1 -t 10
```

**Purpose:** Measure maximum achievable throughput on a single TCP flow.

**Expected:** Throughput close to the configured link cap (~9.x Mbps for a 10 Mbps cap). The gap from 10 Mbps is due to TCP overhead, flow setup time, and protocol headers.

---

### Scenario 3 – Parallel Flows / Bandwidth Contention (Star topology)

```bash
mininet> h1 iperf -s -D
mininet> h3 iperf -s -D
mininet> h2 iperf -c 10.0.1.1 -t 10 &
mininet> h4 iperf -c 10.0.1.3 -t 10
```

**Purpose:** Two simultaneous iperf flows compete for the shared switch bandwidth.

**Expected (Star topology):** Each flow receives approximately 50% of the link bandwidth (~4.7 Mbps each), with the total sum ≤ 10 Mbps. This demonstrates **bandwidth contention** on a shared switch.

---

### Scenario 4 – Intra vs Inter Subtree (Tree topology)

```bash
# Intra-subtree (h1 → h2, same aggregation switch s2):
mininet> h1 iperf -s -D
mininet> h2 iperf -c 10.0.1.1 -t 10

# Inter-subtree (h1 → h3, crosses core switch s1):
mininet> h3 iperf -s -D
mininet> h1 iperf -c 10.0.2.1 -t 10
```

**Expected:** Both achieve ~9.5 Mbps since the core link is provisioned at 2× bandwidth. Latency for inter-subtree is slightly higher (~11ms RTT vs ~10ms).

---

### Scenario 5 – Flow Table Inspection

```bash
mininet> sh ovs-ofctl dump-flows s1
```

**Purpose:** Verify that flow rules are correctly installed after MAC learning.

**Expected output example:**
```
cookie=0x0, duration=12.3s, table=0, n_packets=28, n_bytes=2352,
  priority=1,in_port=1,dl_src=00:00:00:00:00:01,dl_dst=00:00:00:00:00:02
  actions=output:2
```

---

## Expected Output

### Controller Terminal (after iperf test)

```
10:23:01 [INFO] ─────────────────────────────────────────────────────────────────
10:23:01 [INFO]   Switch 0000000000000001  │  Port Statistics
10:23:01 [INFO]   Port   │ RX (bps)        │ TX (bps)        │ RX Pkts   │ TX Pkts
10:23:01 [INFO]   1      │ 9834201.6       │ 132.0           │ 7823      │ 38
10:23:01 [INFO]   2      │ 131.2           │ 9834190.1       │ 38        │ 7823
10:23:01 [INFO] ─────────────────────────────────────────────────────────────────
```

- Port 1 is receiving high traffic (h1 sending) → high RX bps
- Port 2 is transmitting that traffic to h2 → matching high TX bps
- The near-symmetry of RX on port 1 and TX on port 2 confirms single-flow forwarding

### bandwidth_log.csv (auto-generated)

```csv
timestamp,datapath_id,port_no,rx_bps,tx_bps,rx_packets,tx_packets
10:23:01,0000000000000001,1,9834201.60,132.00,7823,38
10:23:01,0000000000000001,2,131.20,9834190.10,38,7823
10:23:06,0000000000000001,1,9901045.20,140.80,9234,41
```

A new row is appended every 5 seconds (one row per active port per switch).

---

## Performance Analysis & Results

| Metric | Linear | Star (1 flow) | Star (2 flows) | Tree (intra-subtree) | Tree (inter-subtree) |
|--------|--------|--------------|----------------|---------------------|---------------------|
| **Throughput** | ~9.5 Mbps | ~9.5 Mbps | ~4.7 Mbps each | ~9.5 Mbps | ~9.5 Mbps |
| **Latency (RTT)** | ~12 ms | ~4 ms | ~4 ms | ~10 ms | ~11 ms |
| **Bottleneck** | Series links | Switch fabric | Shared uplink | Edge link | Core link |
| **Packet Loss** | 0% | 0% | 0% | 0% | 0% |

### Key Findings

**Linear Topology:** Latency accumulates across series links (5ms + 2ms + 5ms = 12ms RTT). Throughput is limited by the lowest-capacity link in the chain — here all links are equal at 10 Mbps, so full throughput is achieved.

**Star Topology:** Demonstrates the most important SDN insight — when two flows compete for the same switch simultaneously, the available bandwidth is split. Each flow gets ~50% rather than the full 10 Mbps. The switch becomes the bottleneck, not the links.

**Tree Topology:** The higher-bandwidth core link (provisioned at 2× = 20 Mbps) prevents inter-subtree traffic from bottlenecking at the core, yielding comparable throughput to direct connections. Intra-subtree traffic (within the same aggregation domain) achieves optimal performance without ever traversing the core.

---

## Repository Structure

```
├── bandwidth_controller.py   # Ryu SDN controller
│                             #   - MAC learning switch
│                             #   - Port stats polling (every 5s)
│                             #   - Bandwidth calculator (Δbytes/Δtime)
│                             #   - CSV logger
│
├── topologies.py             # Mininet topology definitions + test runner
│                             #   - LinearTopo, StarTopo, TreeTopo classes
│                             #   - run_iperf_test(), run_parallel_iperf()
│                             #   - run_ping_test(), show_flow_tables()
│                             #   - Argument parser for CLI usage
│
├── bandwidth_log.csv         # Auto-generated during experiment
│                             #   - One row per port per switch per poll interval
│                             #   - Columns: timestamp, dpid, port, rx_bps, tx_bps, pkts
│
└── README.md                 # This file
```

---

## Validation & Regression Tests

| Test | Command | Expected Result | Pass Condition |
|------|---------|-----------------|----------------|
| Connectivity | `pingall` | 0% packet loss | All hosts reachable |
| Single iperf (10 Mbps cap) | `iperf -c <dst> -t 10` | ≥ 9 Mbps throughput | Within 10% of cap |
| Parallel iperf (2 flows, 10 Mbps) | Two concurrent iperf clients | ~5 Mbps each | Sum ≤ cap |
| Flow table after ping | `ovs-ofctl dump-flows s1` | ≥ 1 priority=1 rule | Rule with `actions=output:X` visible |
| Stats polling | Watch controller terminal | New log line every 5s | CSV row count grows every 5s |
| Idle timeout | Wait 30s after traffic stops | Flow rule removed | `dump-flows` shows no priority=1 rules |
| Hard timeout | Keep flow active for 120s | Flow rule reinstalled | Controller receives new `packet_in` |

---

## Key Concepts

**Software-Defined Networking (SDN):** Decouples the control plane (routing decisions) from the data plane (packet forwarding). The controller has a global view of the network; switches are simple forwarding devices.

**OpenFlow 1.3:** The protocol used for communication between the Ryu controller and OVS switches. Defines message types including `PacketIn`, `FlowMod`, `PortStatsRequest`, and `PortStatsReply`.

**MAC Learning:** The process by which the controller builds a table mapping Ethernet MAC addresses to physical switch ports. Eliminates flooding for known destinations.

**Table-Miss Rule:** A default flow rule at priority 0 that matches all packets not handled by any other rule, forwarding them to the controller. Necessary for the controller to learn new MAC addresses.

**TCLink (Traffic Control Link):** A Mininet abstraction that uses Linux `tc` (traffic control) to enforce bandwidth caps, delay, and packet loss on virtual links — making emulated networks behave like real ones.

**iperf:** A standard network benchmarking tool. Run as a server (`iperf -s`) on one host and a client (`iperf -c <ip>`) on another. Reports achievable TCP throughput over a specified duration.

---

## References

1. Mininet Overview – https://mininet.org/overview/
2. Mininet Walkthrough – https://mininet.org/walkthrough/
3. Mininet GitHub – https://github.com/mininet/mininet
4. Ryu SDN Framework Documentation – https://ryu.readthedocs.io/
5. OpenFlow 1.3 Specification – https://opennetworking.org/
6. Open vSwitch Documentation – https://docs.openvswitch.org/
7. Ryu App API Reference – https://ryu.readthedocs.io/en/latest/app/ofp_handler.html

---

*Individual Project | PES University | Computer Networks UE24CS252B*

*Controller: Ryu Framework + OpenFlow 1.3 | Emulator: Mininet + Open vSwitch*
