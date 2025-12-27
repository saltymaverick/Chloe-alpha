"""
Operator Panel — CLI command reference (read-only)
"""

from __future__ import annotations

import streamlit as st


def render():
    st.title("Operator Console (Read-Only)")
    
    st.markdown(
        """
This panel documents important CLI/operator commands.

It is **read-only** to keep trading logic and control paths separate.
"""
    )
    
    st.subheader("Wallet & Mode Commands")
    st.code(
        """\
# Check wallet status
python3 -m tools.wallet_cli status

# Switch to paper mode
python3 -m tools.wallet_cli set paper

# Switch to live mode (careful)
python3 -m tools.wallet_cli set real
""",
        language="bash",
    )
    
    st.subheader("Research & SWARM")
    st.code(
        """\
# Run nightly research manually
python3 -m engine_alpha.reflect.nightly_research

# Run SWARM sentinel
python3 -m engine_alpha.swarm.swarm_sentinel

# Run SWARM audit loop once
python3 -m engine_alpha.swarm.swarm_audit_loop
""",
        language="bash",
    )
    
    st.subheader("Services")
    st.code(
        """\
# Check timers
sudo systemctl status chloe-swarm-audit.timer
sudo systemctl status chloe-nightly-research.timer

# Check live trading
sudo systemctl status chloe-live.service
""",
        language="bash",
    )
    
    st.info(
        "When you're ready, you can extend this panel to show live status of systemd units, etc."
    )


