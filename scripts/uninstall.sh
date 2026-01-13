#!/bin/bash
#
# MeterEye Uninstallation Script
# Removes MeterEye systemd service and optionally data
#
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/ctme"
CONFIG_DIR="/etc/ctme"
DATA_DIR="/var/lib/ctme"
SERVICE_USER="ctme"
SERVICE_NAME="ctme"

echo -e "${YELLOW}=== MeterEye Uninstallation ===${NC}"
echo

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Parse arguments
REMOVE_DATA=false
REMOVE_CONFIG=false
REMOVE_ALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --remove-data)
            REMOVE_DATA=true
            shift
            ;;
        --remove-config)
            REMOVE_CONFIG=true
            shift
            ;;
        --purge|--all)
            REMOVE_ALL=true
            REMOVE_DATA=true
            REMOVE_CONFIG=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo
            echo "Options:"
            echo "  --remove-data    Remove data directory ($DATA_DIR)"
            echo "  --remove-config  Remove configuration files ($CONFIG_DIR)"
            echo "  --purge, --all   Remove everything (data + config)"
            echo "  -h, --help       Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Stop and disable service
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Stopping service..."
    systemctl stop "$SERVICE_NAME"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    echo "Disabling service..."
    systemctl disable "$SERVICE_NAME"
fi

# Remove systemd service file
if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]]; then
    echo "Removing systemd service..."
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
fi

# Remove installation directory
if [[ -d "$INSTALL_DIR" ]]; then
    echo "Removing installation directory: $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"
fi

# Optionally remove data
if [[ "$REMOVE_DATA" == true ]] && [[ -d "$DATA_DIR" ]]; then
    echo "Removing data directory: $DATA_DIR"
    rm -rf "$DATA_DIR"
fi

# Optionally remove config
if [[ "$REMOVE_CONFIG" == true ]] && [[ -d "$CONFIG_DIR" ]]; then
    echo "Removing configuration directory: $CONFIG_DIR"
    rm -rf "$CONFIG_DIR"
fi

# Optionally remove user
if [[ "$REMOVE_ALL" == true ]]; then
    if id "$SERVICE_USER" &>/dev/null; then
        echo "Removing service user: $SERVICE_USER"
        userdel "$SERVICE_USER" 2>/dev/null || true
    fi
fi

echo
echo -e "${GREEN}=== Uninstallation Complete ===${NC}"
echo

if [[ "$REMOVE_CONFIG" != true ]] && [[ -d "$CONFIG_DIR" ]]; then
    echo -e "${YELLOW}Note: Configuration files preserved at $CONFIG_DIR${NC}"
    echo "      Use --remove-config or --purge to remove them"
fi

if [[ "$REMOVE_DATA" != true ]] && [[ -d "$DATA_DIR" ]]; then
    echo -e "${YELLOW}Note: Data files preserved at $DATA_DIR${NC}"
    echo "      Use --remove-data or --purge to remove them"
fi
