# Security

Do not attach real proxy configurations, UUIDs, access logs, database exports,
credentials, certificates or SSH private keys to public issues or pull requests.

The statistics API must remain on loopback. Public dashboard access requires
HTTPS and authentication covering HTML, JavaScript and **every JSON snapshot**.
The generated Nginx configuration listens only on loopback and requires an
operator-created password file; it must not be changed to public cleartext HTTP.
Browser Basic authentication has no reliable application-level logout: close
the browser session or clear the site's authentication state when using a shared device.

Use a sanitized reproducer with the synthetic demo. For a suspected security
issue, use the repository's private vulnerability reporting if available, or
contact a maintainer privately before disclosing exploit details. Do not post secrets.
