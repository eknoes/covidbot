#!/usr/bin/bash
signald() {
            echo "$1" | timeout 3 nc -U /var/run/signald/signald.sock | jq 'select(.type != "version")'
}

if [ -z "$1" ]
  then
    echo "Please provide the users number as argument in international format"
    exit 1;
fi

signald "{\"account\": \"+4915792453845\", \"address\": { \"number\": \"$1\" }, \"type\": \"get_identities\", \"version\": \"v1\" }" | jq -rc '{"number": .data.address.number, "safety_number": (.data.identities[] | select(.trust_level == "UNTRUSTED") | .safety_number) } | "{\"type\": \"trust\", \"address\": {\"number\": \"\(.number)\"}, \"safety_number\": \"\(.safety_number)\", \"account\": \"+4915792453845\", \"trust_level\": \"TRUSTED_UNVERIFIED\", \"version\": \"v1\"}"' | while read trustcmd; do
  signald "$trustcmd"
done