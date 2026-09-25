#!/bin/sh
# If a proxy CA bundle is mounted (see docker-compose.yml), trust it for outbound HTTPS at runtime.
if [ -s /etc/dipper/extra-ca.pem ]; then
  cat /etc/ssl/certs/ca-certificates.crt /etc/dipper/extra-ca.pem > /tmp/dipper-ca.pem
  export SSL_CERT_FILE=/tmp/dipper-ca.pem REQUESTS_CA_BUNDLE=/tmp/dipper-ca.pem
fi
exec "$@"
