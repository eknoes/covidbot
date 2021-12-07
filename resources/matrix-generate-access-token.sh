#!/usr/bin/env bash

if [ $# -ne 3 ]; then
  echo "Usage: matrix-generate-access-token <userid> <password> <homeserver>"
  exit -1
fi

api_url=$(curl $3/.well-known/matrix/client | jq --raw-output '."m.homeserver".base_url')
echo "Querying $api_url"
response=$(curl -d '{"type":"m.login.password", "user":"'$1'", "password":"'$2'", "initial_device_display_name": "Covidbot Interface"}' "$api_url/_matrix/client/v3/login")

echo "ACCESS_TOKEN=$(echo $response | jq --raw-output '.access_token')
DEVICE_ID=$(echo $response | jq --raw-output '.device_id')"