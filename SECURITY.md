# 🔐 Aurora Monitoring Stack - Security Guide

**Last Updated:** 2026-01-10  
**Status:** Security Configuration Guide

---

## Overview

This guide documents the security configurations for Aurora's monitoring stack (Prometheus + Grafana), including authentication, encryption, and access controls.

---

## Security Features Implemented

### ✅ Prometheus Security
- **Basic Authentication:** Username/password required for all access
- **Network Isolation:** Bound to localhost only (127.0.0.1:9090)
- **Non-root User:** Runs as UID 65534 (nobody)
- **Resource Limits:** CPU and memory constraints
- **Health Checks:** Automated service monitoring

### ✅ Grafana Security
- **HTTPS Enabled:** TLS encryption for all traffic
- **Strong Authentication:** Admin password required
- **Anonymous Access:** Disabled
- **User Registration:** Disabled
- **Secure Sessions:** httpOnly, secure, SameSite cookies
- **Network Isolation:** Bound to localhost only (127.0.0.1:3001)
- **Non-root User:** Runs as UID 472 (grafana)
- **Resource Limits:** CPU and memory constraints

### ✅ SSL/TLS Encryption
- Self-signed certificates for development
- Separate certs for Prometheus and Grafana
- 2048-bit RSA keys
- 365-day validity

### ✅ Docker Security
- Containers run as non-root users
- Read-only volume mounts where possible
-localhost-only port binding
- Resource limits enforced
- Health checks configured
- Isolated bridge network

---

## Credentials

### Default Credentials

**Prometheus:**
- Username: `admin`
- Password: `<YOUR_PROMETHEUS_PASSWORD>` (set in .env)
- Access: http://localhost:9090 (requires auth)

**Grafana:**
- Username: `admin`
- Password: `<YOUR_GRAFANA_PASSWORD>` (set in .env)
- Access: https://localhost:3001 (HTTPS)

> [!WARNING]
> **For production deployment, generate unique strong passwords!**

---

## Starting the Secured Stack

### 1. Generate Fresh SSL Certificates (Optional)
```bash
./scripts/generate-ssl.sh
```

### 2. Generate Prometheus Password Hash (When Docker Running)
```bash
# Generate bcrypt hash for new password
docker run --rm httpd:alpine htpasswd -nbB admin YOUR_NEW_PASSWORD

# Copy the hash (everything after 'admin:') to:
# config/prometheus/web-config.yml
```

### 3. Set Environment Variables
```bash
# Create .env file with secrets
cat > .env << EOF
GRAFANA_SECRET_KEY=$(openssl rand -base64 32)
EOF
```

### 4. Start Services
```bash
docker-compose -f docker-compose.prod.yml up -d prometheus grafana
```

### 5. Verify Security
```bash
# Check ports are localhost-only
netstat -an | grep -E ":(9090|3001)"

# Test Prometheus auth (should fail without credentials)
curl http://localhost:9090/metrics
# Response: 401 Unauthorized

# Test with credentials
curl -u admin:$PROMETHEUS_PASSWORD http://localhost:9090/metrics

# Test Grafana HTTPS
curl -k https://localhost:3001/login
```

---

## Access URLs

**Prometheus (with auth):**
```
http://localhost:9090
```

**Grafana (HTTPS):**
```
https://localhost:3001
```

> Note: You'll see a certificate warning for self-signed certs. This is normal for development.

---

## Network Security

### Port Bindings
- Prometheus: `127.0.0.1:9090` (localhost only)
- Grafana: `127.0.0.1:3001` (localhost only)

### Why Localhost-Only?
- Prevents external access without SSH tunnel or reverse proxy
- Requires attacker to have local machine access
- Compatible with production reverse proxy setup (nginx, Traefik)

### Production Deployment
For production, use reverse proxy (nginx/Traefik) with:
- Proper SSL certificates (Let's Encrypt)
- Rate limiting
- IP whitelisting
- DDoS protection

---

## File Permissions

```bash
# SSL keys (private)
chmod 600 config/ssl/*.key

# SSL certs (public)
chmod 644 config/ssl/*.crt  

# Config files (read-only in containers)
chmod 644 config/prometheus/*.yml
chmod 644 config/grafana/*.ini
```

---

## Password Rotation

### Prometheus Password
1. Generate new bcrypt hash with htpasswd
2. Update `config/prometheus/web-config.yml`
3. Restart Prometheus: `docker restart aurora-prometheus`

### Grafana Password
1. Update `docker-compose.prod.yml` (GF_SECURITY_ADMIN_PASSWORD)
2. OR change via Grafana UI after first login
3. Restart Grafana: `docker restart aurora-grafana`

---

## Security Checklist

- [ ] Changed default Prometheus password
- [ ] Changed default Grafana password
- [ ] Generated production SSL certificates (if deploying)
- [ ] Set GRAFANA_SECRET_KEY environment variable
- [ ] Verified localhost-only binding
- [ ] Configured firewall rules
- [ ] Set up reverse proxy (for production)
- [ ] Enabled audit logging
- [ ] Configured automated backups
- [ ] Tested authentication failures

---

## Troubleshooting

### "Permission Denied" Errors
Containers run as non-root users. Ensure volume directories have correct permissions:
```bash
chown -R 65534:65534 prometheus-data/
chown -R 472:472 grafana-data/
```

### Certificate Errors
Browsers will show warnings for self-signed certs. Either:
- Accept the risk (development only)
- Add cert to system trust store
- Use proper CA-signed certs (production)

### Authentication Failures
- Check password hash in web-config.yml
- Verify htpasswd format is correct
- Ensure no trailing spaces in config files

---

## Security Best Practices

1. **Never commit secrets to Git**
   - Use `.env` files (add to `.gitignore`)
   - Use secrets management (Vault, AWS Secrets Manager)

2. **Regular updates**
   - Keep Prometheus, Grafana images updated
   - Monitor security advisories

3. **Principle of least privilege**
   - Don't run as root
   - Use read-only mounts  
   - Limit resource consumption

4. **Defense in depth**
   - Authentication + encryption + network isolation
   - Multiple layers of security

5. **Monitoring and alerting**
   - Monitor failed login attempts
   - Alert on suspicious activity
   - Regular security audits

---

## Production Deployment Notes

> [!IMPORTANT]
> **For production:**
> - Use proper CA-signed certificates (Let's Encrypt)
> - Store passwords in secrets manager (Vault, AWS)
> - Enable audit logging
> - Set up log aggregation (Loki, ELK)
> - Configure automated certificate renewal
> - Implement intrusion detection
> - Set up disaster recovery
> - Regular security assessments

---

## Support

For issues or questions:
1. Check logs: `docker logs aurora-prometheus`
2. Review configurations in `config/` directory  
3. Consult official docs:
   - [Prometheus Security](https://prometheus.io/docs/guides/basic-auth/)
   - [Grafana Security](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/)
