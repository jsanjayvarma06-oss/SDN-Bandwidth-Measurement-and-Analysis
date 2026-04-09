#!/usr/bin/env python3
"""
Bandwidth Measurement Topologies - Mininet Script
==================================================
Project: Orange Level - SDN Mininet Simulation
Course: Computer Networks - UE24CS252B
PES University

Description:
    Implements THREE network topologies for bandwidth comparison:

    Topology 1 – Linear (Single Path)
        h1 ─── s1 ─── s2 ─── h2
        Demonstrates: baseline point-to-point bandwidth

    Topology 2 – Star (Hub-and-Spoke)
             h1
              │
        h3 ─ s1 ─ h2
              │
             h4
        Demonstrates: shared switch bandwidth, multi-client performance

    Topology 3 – Tree (Hierarchical, 2-level)
                  s1
               /      \
             s2          s3
           / \          / \
          h1  h2       h3  h4
        Demonstrates: inter-switch bandwidth vs intra-switch bandwidth

Usage:
    # Run with Ryu controller (start controller first):
    #   ryu-manager bandwidth_controller.py
    #
    # Then run this script:
    sudo python3 topologies.py --topo [linear|star|tree] [--bw <Mbps>]

    # Or use the interactive menu (no arguments):
    sudo python3 topologies.py
"""

import sys
import argparse
import time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.cli import CLI


# ──────────────────────────────────────────────────────
# Topology Definitions
# ──────────────────────────────────────────────────────

class LinearTopo(Topo):
    """
    Linear topology: h1 ─ s1 ─ s2 ─ h2
    Two hosts connected through two switches in series.
    Tests: single-path throughput, inter-switch bandwidth.
    """
    def build(self, bw=10):
        # Switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        # Hosts
        h1 = self.addHost('h1', ip='10.0.1.1/24')
        h2 = self.addHost('h2', ip='10.0.1.2/24')
        # Links with bandwidth constraint (TCLink)
        self.addLink(h1, s1, bw=bw, delay='5ms', loss=0)
        self.addLink(s1, s2, bw=bw, delay='2ms', loss=0)
        self.addLink(s2, h2, bw=bw, delay='5ms', loss=0)


class StarTopo(Topo):
    """
    Star topology: 4 hosts connected to a single switch.
    Tests: shared bandwidth, multi-client contention.
    """
    def build(self, bw=10):
        s1 = self.addSwitch('s1')
        hosts = []
        for i in range(1, 5):
            h = self.addHost(f'h{i}', ip=f'10.0.1.{i}/24')
            hosts.append(h)
            self.addLink(h, s1, bw=bw, delay='2ms', loss=0)


class TreeTopo(Topo):
    """
    Tree topology: 2-level hierarchy (1 core + 2 aggregation + 4 hosts).
    Tests: inter-switch vs intra-switch bandwidth difference.
    """
    def build(self, bw=10):
        # Core switch
        s1 = self.addSwitch('s1')
        # Aggregation switches
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        # Hosts
        h1 = self.addHost('h1', ip='10.0.1.1/24')
        h2 = self.addHost('h2', ip='10.0.1.2/24')
        h3 = self.addHost('h3', ip='10.0.2.1/24')
        h4 = self.addHost('h4', ip='10.0.2.2/24')
        # Core-to-aggregation (higher bandwidth backbone link)
        self.addLink(s1, s2, bw=bw*2, delay='1ms', loss=0)
        self.addLink(s1, s3, bw=bw*2, delay='1ms', loss=0)
        # Aggregation-to-host
        self.addLink(s2, h1, bw=bw, delay='5ms', loss=0)
        self.addLink(s2, h2, bw=bw, delay='5ms', loss=0)
        self.addLink(s3, h3, bw=bw, delay='5ms', loss=0)
        self.addLink(s3, h4, bw=bw, delay='5ms', loss=0)


# ──────────────────────────────────────────────────────
# Test Scenarios
# ──────────────────────────────────────────────────────

def run_iperf_test(net, src_name, dst_name, duration=10, label=""):
    """
    Run iperf throughput test between src and dst.
    Returns (throughput_string, raw_output).
    """
    src = net.get(src_name)
    dst = net.get(dst_name)

    info(f"\n{'─'*55}\n")
    info(f"  iperf TEST: {src_name} → {dst_name}  [{label}]\n")
    info(f"{'─'*55}\n")

    # Start iperf server on dst
    dst.cmd('pkill iperf 2>/dev/null; iperf -s -D')
    time.sleep(0.5)

    # Run iperf client from src
    result = src.cmd(f'iperf -c {dst.IP()} -t {duration} -i 2')
    info(result)

    dst.cmd('pkill iperf 2>/dev/null')
    return result


def run_ping_test(net, src_name, dst_name, count=10):
    """Run ping latency test."""
    src = net.get(src_name)
    dst = net.get(dst_name)

    info(f"\n  ping TEST: {src_name} → {dst_name}\n")
    result = src.cmd(f'ping -c {count} {dst.IP()}')
    info(result)
    return result


def run_parallel_iperf(net, pairs, duration=10, label=""):
    """
    Run multiple iperf flows simultaneously to test bandwidth contention.
    pairs: list of (src_name, dst_name)
    """
    info(f"\n{'─'*55}\n")
    info(f"  PARALLEL iperf TEST: {len(pairs)} flows  [{label}]\n")
    info(f"{'─'*55}\n")

    hosts = {}
    # Start all servers
    for _, dst_name in pairs:
        dst = net.get(dst_name)
        dst.cmd('pkill iperf 2>/dev/null; iperf -s -D')
        hosts[dst_name] = dst
    time.sleep(0.5)

    # Start all clients simultaneously using background processes
    procs = []
    for src_name, dst_name in pairs:
        src = net.get(src_name)
        dst = hosts[dst_name]
        p = src.popen(f'iperf -c {dst.IP()} -t {duration} -i {duration}')
        procs.append((src_name, dst_name, p))

    # Collect results
    for src_name, dst_name, p in procs:
        out, _ = p.communicate()
        info(f"\n  [{src_name}→{dst_name}]\n{out.decode()}")

    # Kill all servers
    for _, dst_name in pairs:
        net.get(dst_name).cmd('pkill iperf 2>/dev/null')


def show_flow_tables(net):
    """Dump flow tables from all switches."""
    info("\n╔══════════════════════════════════╗\n")
    info("║       FLOW TABLE DUMP            ║\n")
    info("╚══════════════════════════════════╝\n")
    for sw in net.switches:
        info(f"\n── Switch: {sw.name} ──\n")
        result = sw.cmd('ovs-ofctl dump-flows %s' % sw.name)
        info(result)


# ──────────────────────────────────────────────────────
# Main Runners
# ──────────────────────────────────────────────────────

def run_topology(topo_name='linear', bw=10, controller_ip='127.0.0.1', controller_port=6633):
    """
    Launch a topology, run automated tests, then open CLI.
    """
    setLogLevel('info')

    topo_map = {
        'linear': (LinearTopo, 'LINEAR TOPOLOGY: h1─s1─s2─h2'),
        'star':   (StarTopo,   'STAR TOPOLOGY: 4 hosts─s1'),
        'tree':   (TreeTopo,   'TREE TOPOLOGY: 2-level hierarchy'),
    }

    if topo_name not in topo_map:
        print(f"[ERROR] Unknown topology: {topo_name}. Choose: linear, star, tree")
        sys.exit(1)

    TopoClass, label = topo_map[topo_name]

    info(f"\n{'═'*55}\n")
    info(f"  {label}\n")
    info(f"  Link bandwidth cap: {bw} Mbps\n")
    info(f"{'═'*55}\n")

    # Build network
    topo = TopoClass(bw=bw)
    net = Mininet(
        topo=topo,
        switch=OVSKernelSwitch,
        controller=None,
        link=TCLink,
        autoSetMacs=True
    )

    # Add remote Ryu controller
    net.addController('c0',
                      controller=RemoteController,
                      ip=controller_ip,
                      port=controller_port)

    net.start()
    info("\n[INFO] Network started. Waiting for controller...\n")
    time.sleep(3)

    # ── Scenario 1: Basic connectivity ──
    info("\n[SCENARIO 1] Connectivity Test (pingall)\n")
    net.pingAll()

    # ── Scenario 2: iperf tests ──
    info("\n[SCENARIO 2] Bandwidth Tests\n")

    if topo_name == 'linear':
        run_iperf_test(net, 'h1', 'h2', duration=10, label="Single path h1→h2")
        run_ping_test(net, 'h1', 'h2', count=10)

    elif topo_name == 'star':
        # Sequential test
        run_iperf_test(net, 'h1', 'h2', duration=10, label="Sequential h1→h2")
        run_iperf_test(net, 'h1', 'h3', duration=10, label="Sequential h1→h3")
        # Parallel test: bandwidth contention
        run_parallel_iperf(net,
                           [('h1', 'h2'), ('h3', 'h4')],
                           duration=10,
                           label="Parallel flows (contention)")

    elif topo_name == 'tree':
        # Intra-subtree (same aggregation switch)
        run_iperf_test(net, 'h1', 'h2', duration=10, label="Intra-subtree h1→h2 (via s2)")
        # Inter-subtree (crosses core switch)
        run_iperf_test(net, 'h1', 'h3', duration=10, label="Inter-subtree h1→h3 (via s1)")
        run_ping_test(net, 'h1', 'h3', count=10)

    # ── Show flow tables ──
    show_flow_tables(net)

    # ── Open CLI for manual exploration ──
    info("\n[INFO] Automated tests done. Opening CLI for manual testing.\n")
    info("[INFO] Try: h1 iperf -c 10.0.1.2 -t 5\n")
    info("[INFO] Try: ovs-ofctl dump-flows s1\n")
    CLI(net)

    net.stop()
    info("\n[INFO] Network stopped.\n")


# ──────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description='SDN Bandwidth Measurement Topologies'
    )
    parser.add_argument('--topo', choices=['linear', 'star', 'tree'],
                        default='linear',
                        help='Topology to run (default: linear)')
    parser.add_argument('--bw', type=int, default=10,
                        help='Link bandwidth in Mbps (default: 10)')
    parser.add_argument('--controller-ip', default='127.0.0.1',
                        help='Ryu controller IP (default: 127.0.0.1)')
    parser.add_argument('--controller-port', type=int, default=6633,
                        help='Ryu controller port (default: 6633)')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    run_topology(
        topo_name=args.topo,
        bw=args.bw,
        controller_ip=args.controller_ip,
        controller_port=args.controller_port
    )
