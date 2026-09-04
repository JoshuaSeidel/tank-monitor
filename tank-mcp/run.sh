#!/usr/bin/with-contenv bashio
set -e

export TANK_MCP_PORT="8099"
export TANK_MCP_DB="/data/tank.db"
export TANK_MCP_TOKEN_FILE="/data/api_token"

export TANK_MCP_TOKEN="$(bashio::config 'api_token')"
export TANK_MCP_DEVICE="$(bashio::config 'device')"
export TANK_MCP_DEFAULT_ECHO="$(bashio::config 'default_echo')"
export TANK_MCP_PUBLISH_MQTT="$(bashio::config 'publish_livestock_to_mqtt')"
export TANK_MCP_LOG_LEVEL="$(bashio::config 'log_level')"

# homeassistant_api: true means the Supervisor token is a valid HA bearer
# token against the core proxy, so there is no long-lived token to manage.
export TANK_MCP_HA_URL="http://supervisor/core"
export TANK_MCP_HA_TOKEN="${SUPERVISOR_TOKEN}"

if bashio::services.available "mqtt"; then
    export TANK_MCP_MQTT_HOST="$(bashio::services 'mqtt' 'host')"
    export TANK_MCP_MQTT_PORT="$(bashio::services 'mqtt' 'port')"
    export TANK_MCP_MQTT_USER="$(bashio::services 'mqtt' 'username')"
    export TANK_MCP_MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"
    bashio::log.info "MQTT broker found at ${TANK_MCP_MQTT_HOST}:${TANK_MCP_MQTT_PORT}"
else
    bashio::log.warning "No MQTT service; livestock counts will not be mirrored into Home Assistant."
fi

bashio::log.info "Starting Tank MCP for device '${TANK_MCP_DEVICE}'"
exec python3 -m tankmcp
