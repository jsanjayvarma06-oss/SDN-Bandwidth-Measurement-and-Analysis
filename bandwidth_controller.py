"""
Bandwidth Measurement and Analysis - Ryu SDN Controller
=======================================================
Project: Orange Level - SDN Mininet Simulation
Course: Computer Networks - UE24CS252B
PES University

Description:
    This Ryu controller implements a learning switch with:
    - Packet_in event handling for flow rule installation
    - Per-port and per-flow statistics polling (every 5 seconds)
    - Bandwidth calculation from byte counters
    - Flow table management with idle/hard timeouts
    - Logging of throughput metrics for analysis
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types
from ryu.lib import hub
import time
import logging

# ─────────────────────────────────────────────
# Configure logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)


class BandwidthController(app_manager.RyuApp):
    """
    SDN Controller with Bandwidth Measurement.

    Flow Rule Logic:
        match: (in_port, eth_dst)  →  action: output to learned port
        Default table-miss: send to controller (packet_in)

    Statistics:
        - Polls OFPPortStatsRequest every POLL_INTERVAL seconds
        - Computes TX/RX bandwidth per port using delta bytes / delta time
        - Logs bandwidth to console and saves to bandwidth_log.csv
    """

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    POLL_INTERVAL = 5  # seconds between stats requests

    def __init__(self, *args, **kwargs):
        super(BandwidthController, self).__init__(*args, **kwargs)
        # MAC learning table: { datapath_id: { mac_addr: port } }
        self.mac_to_port = {}
        # Previous port stats for delta calculation: { (dp_id, port_no): (bytes, time) }
        self.prev_stats = {}
        # Datapath registry
        self.datapaths = {}
        # Start background polling thread
        self.monitor_thread = hub.spawn(self._monitor)
        # CSV log file
        self.log_file = open("bandwidth_log.csv", "w")
        self.log_file.write("timestamp,datapath_id,port_no,rx_bps,tx_bps,rx_packets,tx_packets\n")
        self.log_file.flush()
        self.logger.info("╔══════════════════════════════════════════╗")
        self.logger.info("║  Bandwidth Controller Started            ║")
        self.logger.info("║  Polling interval: %ds                   ║" % self.POLL_INTERVAL)
        self.logger.info("╚══════════════════════════════════════════╝")

    # ──────────────────────────────────────────
    # Switch Handshake: Install Table-Miss Flow
    # ──────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """Called when a switch connects. Installs default table-miss flow."""
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Table-miss: match everything, lowest priority → send to controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self._add_flow(datapath, priority=0, match=match, actions=actions)
        self.logger.info("[SWITCH %016x] Connected. Table-miss flow installed.", datapath.id)

    # ──────────────────────────────────────────
    # Datapath Registry (for monitoring)
    # ──────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
            self.logger.info("[SWITCH %016x] Registered for monitoring.", datapath.id)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)
            self.logger.info("[SWITCH %016x] Removed from monitoring.", datapath.id)

    # ──────────────────────────────────────────
    # Packet-In Handler: Learning Switch Logic
    # ──────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        """
        Handles unknown packets sent to controller.
        1. Learns src MAC → in_port mapping
        2. If dst MAC is known, installs a flow rule
        3. Otherwise, floods the packet
        """
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        # Ignore LLDP
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dst = eth.dst
        src = eth.src
        dpid = datapath.id

        # Learn MAC → port
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port
        self.logger.info("[SWITCH %016x] Learned %s on port %s", dpid, src, in_port)

        # Determine output port
        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
            self.logger.info("[SWITCH %016x] %s → %s : port %s",
                             dpid, src, dst, out_port)
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # Install flow rule if we know the destination
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self._add_flow(datapath, priority=1, match=match, actions=actions,
                           idle_timeout=30, hard_timeout=120)

        # Send packet out
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=msg.buffer_id,
                                  in_port=in_port,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)

    # ──────────────────────────────────────────
    # Helper: Add Flow Rule
    # ──────────────────────────────────────────
    def _add_flow(self, datapath, priority, match, actions,
                  idle_timeout=0, hard_timeout=0):
        """Install an OpenFlow flow rule on the switch."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

    # ──────────────────────────────────────────
    # Background Monitor Thread
    # ──────────────────────────────────────────
    def _monitor(self):
        """Polls port statistics every POLL_INTERVAL seconds."""
        while True:
            for dp in list(self.datapaths.values()):
                self._request_stats(dp)
            hub.sleep(self.POLL_INTERVAL)

    def _request_stats(self, datapath):
        """Send OFPPortStatsRequest to a datapath."""
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    # ──────────────────────────────────────────
    # Port Stats Reply Handler
    # ──────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """
        Receives port statistics and computes bandwidth.
        Bandwidth (bps) = (delta_bytes * 8) / delta_time
        """
        now = time.time()
        dpid = ev.msg.datapath.id
        body = ev.msg.body

        self.logger.info("─" * 65)
        self.logger.info("  Switch %016x  │  Port Statistics", dpid)
        self.logger.info("─" * 65)
        self.logger.info("  %-6s │ %-14s │ %-14s │ %-10s │ %-10s",
                         "Port", "RX (bps)", "TX (bps)", "RX Pkts", "TX Pkts")
        self.logger.info("─" * 65)

        for stat in sorted(body, key=lambda s: s.port_no):
            port_no = stat.port_no
            key = (dpid, port_no)
            rx_bytes = stat.rx_bytes
            tx_bytes = stat.tx_bytes
            rx_pkts  = stat.rx_packets
            tx_pkts  = stat.tx_packets

            # Calculate bandwidth using delta
            if key in self.prev_stats:
                prev_rx, prev_tx, prev_time = self.prev_stats[key]
                delta_t = now - prev_time
                if delta_t > 0:
                    rx_bps = (rx_bytes - prev_rx) * 8 / delta_t
                    tx_bps = (tx_bytes - prev_tx) * 8 / delta_t
                else:
                    rx_bps = tx_bps = 0.0
            else:
                rx_bps = tx_bps = 0.0

            self.prev_stats[key] = (rx_bytes, tx_bytes, now)

            self.logger.info("  %-6s │ %-14.1f │ %-14.1f │ %-10d │ %-10d",
                             port_no, rx_bps, tx_bps, rx_pkts, tx_pkts)

            # Log to CSV
            self.log_file.write("%s,%016x,%s,%.2f,%.2f,%d,%d\n" % (
                time.strftime("%H:%M:%S"), dpid, port_no,
                rx_bps, tx_bps, rx_pkts, tx_pkts))
            self.log_file.flush()

        self.logger.info("─" * 65)

    def close(self):
        """Cleanup on shutdown."""
        self.log_file.close()
        self.logger.info("Controller stopped. Log saved to bandwidth_log.csv")
