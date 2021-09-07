#!/bin/bash
set -euo pipefail

# SET SIGNAL_ADMIN_PHONE as environment variable

signald() {
            echo "$1" | nc -U /var/run/signald/signald.sock | jq 'select(.type != "version")'
}

signald '{"type": "list_accounts"}' | jq -r 'select(.type == "account_list") | .data.accounts[].username' | while read username; do
        signald "{\"type\": \"get_identities\", \"username\": \"$username\"}" | jq -rc ".data.identities[] | select(.trust_level == \"UNTRUSTED\") | \"{\"type\": \"trust\", \"safety_number\": \"\(.safety_number)\", \"address\": {\"number\": \"\(.address.number)\", \"account\": \"$username\", \"trust_level\": \"TRUSTED_UNVERIFIED\"}\"" | while read trustcmd; do
                signald "$trustcmd"
                signald "{\"type\": \"send\", \"version\": \"v1\", \"recipientAddress\": {\"number\": \"$SIGNAL_ADMIN_PHONE\"}, \"username\": \"$username\", \"messageBody\": \"$(echo $trustcmd | jq -r .recipientAddress.number) ($(echo $trustcmd | jq -r .recipientAddress.uuid)) new fingerprint is $(echo $trustcmd | jq -r .fingerprint)\"}"
        done
done