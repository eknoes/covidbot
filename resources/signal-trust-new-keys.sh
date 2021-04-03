#!/bin/bash
set -euo pipefail

signald() {
            echo "$1" | nc -q0 -U ~/covid-bot/resources/signald.sock | jq 'select(.type != "version")'
}

signald '{"type": "list_accounts"}' | jq -r 'select(.type == "account_list") | .data.accounts[].username' | while read username; do
        signald "{\"type\": \"get_identities\", \"username\": \"$username\"}" | jq -rc ".data.identities[] | select(.trust_level == \"UNTRUSTED\") | \"{\\\"type\\\": \\\"trust\\\", \\\"fingerprint\\\": \\\"\(.fingerprint)\\\", \\\"recipientAddress\\\": \(.address), \\\"username\\\": \\\"$username\\\"}\"" | while read trustcmd; do
                signald "$trustcmd"
        done
done
