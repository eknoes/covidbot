#!/usr/bin/bash
signald() {
            echo "$1" | nc -U /var/run/signald/signald.sock | jq 'select(.type != "version")'
}

if [ -z "$1" ]
  then
    echo "Please provide the users number as argument in international format"
    exit 1;
fi

signald "{\"account\": \"+4915792453845\", \"address\": { \"number\": \"$1\" }, \"type\": \"reset_session\", \"version\": \"v1\" }"