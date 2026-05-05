#!/usr/bin/env bash
# Day 2: bring up v2 services without touching v1.
#
# v1 stays as-is:    nginx :80, FastAPI :8000, Streamlit :8501
# v2 (this script):                FastAPI :8001, Streamlit :8502
#
# Logs:    ~/claude_db_project/logs/{api,ui}.log
# PIDs:    ~/claude_db_project/run/{api,ui}.pid
#
# Usage:
#   ./run_v2.sh start     # start both services in the background
#   ./run_v2.sh stop      # stop both services
#   ./run_v2.sh status    # show what's listening + last 5 log lines each
#   ./run_v2.sh restart   # stop + start

set -euo pipefail

PROJECT_DIR="$HOME/claude_db_project"
VENV="$PROJECT_DIR/venv"
LOG_DIR="$PROJECT_DIR/logs"
PID_DIR="$PROJECT_DIR/run"

API_PORT=8001
UI_PORT=8502

mkdir -p "$LOG_DIR" "$PID_DIR"

start_one() {
    local name="$1"
    local cmd="$2"
    local log="$LOG_DIR/$name.log"
    local pidfile="$PID_DIR/$name.pid"

    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        echo "[$name] already running (pid $(cat $pidfile))"
        return
    fi

    # shellcheck disable=SC2086
    nohup bash -c "source $VENV/bin/activate && cd $PROJECT_DIR && $cmd" \
        > "$log" 2>&1 &
    echo $! > "$pidfile"
    echo "[$name] started (pid $(cat $pidfile)) -> $log"
}

stop_one() {
    local name="$1"
    local pidfile="$PID_DIR/$name.pid"
    if [[ ! -f "$pidfile" ]]; then
        echo "[$name] no pid file"
        return
    fi
    local pid; pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        sleep 1
        kill -0 "$pid" 2>/dev/null && kill -9 "$pid" || true
        echo "[$name] stopped (was pid $pid)"
    else
        echo "[$name] not running (stale pid $pid)"
    fi
    rm -f "$pidfile"
}

cmd_start() {
    start_one "api" "uvicorn api:app --host 0.0.0.0 --port $API_PORT --log-level info"
    sleep 2
    start_one "ui"  "streamlit run app_v2.py --server.port $UI_PORT --server.address 0.0.0.0 --server.headless true"
    sleep 1
    cmd_status
}

cmd_stop() {
    stop_one "ui"
    stop_one "api"
}

cmd_status() {
    echo "----- listening ports -----"
    sudo ss -tlnp 2>/dev/null | grep -E ":($API_PORT|$UI_PORT|80|8000|8501)\s" || true
    echo ""
    for name in api ui; do
        echo "----- $name (last 5 lines) -----"
        tail -n 5 "$LOG_DIR/$name.log" 2>/dev/null || echo "(no log yet)"
        echo ""
    done
    echo "v1 stays untouched. v2 endpoints:"
    echo "  http://localhost:$API_PORT/ims/health"
    echo "  http://localhost:$UI_PORT/             (Streamlit, may need SSH tunnel)"
}

case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_stop; sleep 1; cmd_start ;;
    status)  cmd_status ;;
    *)       echo "usage: $0 {start|stop|status|restart}"; exit 1 ;;
esac
