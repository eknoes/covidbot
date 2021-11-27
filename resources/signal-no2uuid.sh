#!/usr/bin/bash
signald() {
            echo "$1" | timeout 3 nc -U /var/run/signald/signald.sock | jq 'select(.type != "version")'
}

if [ -z "$1" ]
  then
    echo "Please provide the users number as argument in international format";
    exit 1;
fi

uuid=$(signald "{\"account\": \"+4915792453845\", \"address\": { \"number\": \"$1\" }, \"type\": \"get_identities\", \"version\": \"v1\" }" | jq -rc '.data.address.uuid');

if [ -z "$uuid" ]
  then
    echo "There is no account for this phone number";
    exit 1;
fi

echo "Users UUID: $uuid"
