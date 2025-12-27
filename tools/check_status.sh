#!/bin/bash
# Quick status check for Chloe paper run

echo "=================================="
echo "CHLOE ALPHA - STATUS CHECK"
echo "=================================="
echo

# Load timeframe from config
TIMEFRAME=$(jq -r '.timeframe // "15m"' config/engine_config.json 2>/dev/null || echo "15m")
echo "⏱️  Timeframe: $TIMEFRAME"
echo

# Get phase from overseer if available
if [ -f "reports/research/overseer_report.json" ]; then
    PHASE=$(jq -r '.phase // "unknown"' reports/research/overseer_report.json 2>/dev/null || echo "unknown")
    echo "📋 Phase: $PHASE"
    echo
fi

# Trade count (all assets)
if [ -f "reports/trades.jsonl" ]; then
    TRADE_COUNT=$(wc -l < reports/trades.jsonl)
    echo "📊 Total trades (all assets): $TRADE_COUNT"
    
    if [ "$TRADE_COUNT" -ge 50 ]; then
        echo "   ✅ Ready for GPT tuner"
    else
        echo "   ⏳ Need $((50 - TRADE_COUNT)) more trades for tuning"
    fi
else
    echo "📊 Total trades: 0 (no trades.jsonl found)"
fi
echo

# PF local summary
if [ -f "reports/pf_local.json" ]; then
    PF=$(jq -r '.pf' reports/pf_local.json 2>/dev/null || echo "N/A")
    COUNT=$(jq -r '.count' reports/pf_local.json 2>/dev/null || echo "N/A")
    echo "💰 PF_local: $PF (window: $COUNT trades)"
    
    if [ "$PF" != "N/A" ]; then
        if (( $(echo "$PF >= 1.0" | bc -l 2>/dev/null || echo 0) )); then
            echo "   ✅ Healthy PF"
        elif (( $(echo "$PF >= 0.9" | bc -l 2>/dev/null || echo 0) )); then
            echo "   ⚠️  PF below 1.0 (triage mode)"
        else
            echo "   ❌ PF < 0.9 (needs attention)"
        fi
    fi
else
    echo "💰 PF_local: N/A (no pf_local.json found)"
fi
echo

# ETHUSDT specific info from overseer
if [ -f "reports/research/overseer_report.json" ]; then
    ETH_TRADES=$(jq -r '.assets.ETHUSDT.total_trades // 0' reports/research/overseer_report.json 2>/dev/null || echo "0")
    ETH_PF=$(jq -r '.assets.ETHUSDT.pf // "—"' reports/research/overseer_report.json 2>/dev/null || echo "—")
    ETH_COMMENT=$(jq -r '.assets.ETHUSDT.overseer_comment // "N/A"' reports/research/overseer_report.json 2>/dev/null || echo "N/A")
    
    echo "🎯 ETHUSDT:"
    echo "   Trades: $ETH_TRADES, PF: $ETH_PF"
    echo "   Status: $ETH_COMMENT"
    echo
fi

# Last trade
if [ -f "reports/trades.jsonl" ] && [ "$TRADE_COUNT" -gt 0 ]; then
    LAST_TRADE=$(tail -1 reports/trades.jsonl | jq -r '.ts // .timestamp // "N/A"' 2>/dev/null || echo "N/A")
    echo "🕐 Last trade: $LAST_TRADE"
    echo
fi

# Recent entries
if [ -f "reports/trades.jsonl" ] && [ "$TRADE_COUNT" -gt 0 ]; then
    echo "📈 Recent entries (last 3):"
    tail -20 reports/trades.jsonl | jq -r 'select(.type=="open" or .event=="OPEN") | "   \(.ts // .timestamp) | \(.direction // .dir) | conf=\(.confidence // .conf) | regime=\(.regime // "N/A")"' 2>/dev/null | tail -3
    if [ $? -ne 0 ]; then
        echo "   (Unable to parse trade format)"
    fi
    echo
fi

# Mode check
if [ -n "$MODE" ] && [ "$MODE" = "DRY_RUN" ]; then
    echo "⚠️  WARNING: MODE=DRY_RUN (paper trades won't be logged)"
elif [ -n "$CHLOE_DRY_RUN" ] && [ "$CHLOE_DRY_RUN" = "1" ]; then
    echo "⚠️  WARNING: CHLOE_DRY_RUN=1 (paper trades won't be logged)"
else
    echo "✅ Mode: PAPER (trades will be logged)"
fi
echo

echo "=================================="
echo "For detailed view: python tools/monitor_status.py"
echo "For overseer report: python -m tools.overseer_report"
echo "=================================="

